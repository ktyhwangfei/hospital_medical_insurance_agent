"""四链路目标验收（只读）：冻结预期 + 完整集合校验 + 探针断言（F5/F6）。

用法：
  uv run python scripts/eval/four_chain_acceptance.py --out DIR [--record DIR]
  uv run python scripts/eval/four_chain_acceptance.py --replay DIR --out DIR

- 预期来自 `src/tests/fixtures/four_chain_acceptance.py`（冻结、不从响应生成）；
- 先比对真实面板的**展示字段与费用行的完整唯一集合**（字段 key+field_code、
  行 line_id+项目名+金额），新增/遗漏/重复/交换都失败；
- 逐目标用 `assess_target` 判定（受控算式独立 Decimal 复算、来源、缺项、禁止项）；
- 探针断言真实“字段+项目名/整单+行/名称错误”问法的目标集合与结果状态；
- `--record` 保存脱敏离线回放；`--replay` 用回放复跑同一套判定（测试用）；
- 任一失败进入 problems 并退出码 1。

鉴权：读取与问答需要 `fee_decomposition:read`。使用 `FEE_DECOMPOSITION_TOKEN`
（含或不含 Bearer）或 `AUTH_JWT_SECRET` 自签令牌。只读：不写数据库、不改服务配置。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.tests.fixtures.four_chain_acceptance import ACCEPTANCE_EXPECTATIONS  # noqa: E402
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_acceptance_grading import (  # noqa: E402
    TargetRequirement,
    assess_target,
    numeric_tokens,
)

BASE = os.getenv("FOUR_CHAIN_BASE_URL",
                 "http://127.0.0.1:8109/api/v1/medical-insurance-ai-agent")
SECRET = os.getenv("AUTH_JWT_SECRET", "four-chain-remediation-20261026")
COVER_ALL_Q = "请解释这张结算单的全部费用，逐项说明所有展示金额的金额、构成和依据"


def _token() -> str:
    explicit = os.getenv("FEE_DECOMPOSITION_TOKEN")
    if explicit:
        return explicit if explicit.startswith("Bearer ") else f"Bearer {explicit}"
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": "four-chain-acceptance", "roles": ["information_department"],
               "permissions": ["fee_decomposition:read"], "exp": time.time() + 7200}
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    b = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new(SECRET.encode(), f"{h}.{b}".encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"Bearer {h}.{b}.{sig}"


class Client:
    def __init__(self) -> None:
        self.auth = _token()

    def get(self, path: str) -> dict:
        req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode())

    def ask(self, session: str, identifier: str, chain: str, question: str) -> dict:
        body = json.dumps({
            "question": question, "mode": "settlement_explain",
            "settlement_id": identifier, "decomposition_chain": chain,
            "session_id": session, "user_id": "four-chain-acceptance", "role": "cashier",
        }).encode()
        req = urllib.request.Request(
            f"{BASE}/policy-qa/stream", data=body,
            headers={"Content-Type": "application/json", "Authorization": self.auth})
        with urllib.request.urlopen(req, timeout=900) as resp:
            raw = resp.read().decode()
        events: list[tuple[str, dict]] = []
        for block in re.split(r"\r?\n\r?\n", raw):
            name = next((line[7:] for line in block.splitlines()
                         if line.startswith("event: ")), "")
            data = "\n".join(line[6:] for line in block.splitlines()
                             if line.startswith("data: "))
            if name and data:
                events.append((name, json.loads(data)))
        result = next((payload.get("result", payload) for name, payload in events
                       if name == "result"), {})
        if not any(name == "done" for name, _ in events):
            raise RuntimeError(f"SSE 缺少 done 事件：{question}")
        summary = result.get("verification_summary") or {}
        return {
            "answer": result.get("answer") or "",
            "answer_status": result.get("answer_status"),
            "calculation_checked": summary.get("calculation_checked"),
            "citations": result.get("citations") or [],
        }


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _has_value(answer: str, value) -> bool:
    number = _decimal(value)
    return number is not None and number in set(numeric_tokens(answer))


def _amount_text(value) -> str:
    number = _decimal(value)
    return f"{number:f}" if number is not None else str(value)


# ── 集合校验（F6）────────────────────────────────────────────────

def panel_problems(case: str, panel: dict, expectation: dict) -> list[str]:
    """实际展示字段与费用行的完整唯一集合必须与冻结预期一致。"""
    problems: list[str] = []
    template = (panel.get("settlement_facts") or {}).get("display_template") or {}
    actual_fields = [(tf.get("key"), tf.get("field_code"))
                     for tf in template.get("fields", []) if tf.get("section") != "basic"]
    expected_fields = [(entry["key"].split(".", 1)[1], entry.get("field_code"))
                       for entry in expectation["fields"]]
    if Counter(actual_fields) != Counter(expected_fields):
        missing = sorted(map(str, (Counter(expected_fields) - Counter(actual_fields)).elements()))
        extra = sorted(map(str, (Counter(actual_fields) - Counter(expected_fields)).elements()))
        problems.append(f"{case}: 展示字段集合不一致 missing={missing} extra={extra}")
    if len(actual_fields) != len(set(actual_fields)):
        problems.append(f"{case}: 展示字段存在重复项")

    items = panel.get("fee_items") or []
    actual_lines = [(item.get("line_id"), item.get("item_name"),
                     _decimal(item.get("total_fee"))) for item in items]
    expected_lines = [(entry.get("line_id"), entry.get("item_name"), _decimal(entry["amount"]))
                      for entry in expectation["lines"]]
    if len(actual_lines) != len(set(actual_lines)):
        problems.append(f"{case}: 费用行存在重复 line_id/项目身份")
    # 顺序也属于验收范围：逐行回答按展示序号绑定，交换行必须失败
    if actual_lines != expected_lines:
        actual_ids = {line[0] for line in actual_lines}
        expected_ids = {line[0] for line in expected_lines}
        problems.append(
            f"{case}: 费用行集合/顺序不一致 "
            f"missing={sorted(expected_ids - actual_ids)} extra={sorted(actual_ids - expected_ids)} "
            f"actual_order={[line[0] for line in actual_lines]}")
    return problems


# ── 探针（F6）───────────────────────────────────────────────────

def probe_questions(expectation: dict) -> dict[str, str]:
    first = expectation["lines"][0]["item_name"]
    second = expectation["lines"][1]["item_name"] if len(expectation["lines"]) > 1 else first
    return {
        "field_with_item": f"费用总金额和{first}的费用分别怎么算？",
        "cover_all_with_item": f"请解释全部费用，尤其是1. {first}",
        "line_attribute_only": f"第1行{first}的医保内金额是多少？",
        "line_and_whole_field": "第1行医保内金额以及整单医保内金额分别是多少？",
        "swapped_names": f"第1行{second}和第2行{first}各怎么算？",
        "polite_line": "请解释第1行的医保内外",
        "unknown_name": "第1行阿莫西林的医保内外怎么算？",
    }


def _field_amount(expectation: dict, template_key: str):
    entry = next((row for row in expectation["fields"]
                  if row["key"].endswith(f".{template_key}")), None)
    return entry["amount"] if entry else None


def probe_problems(case: str, probe_id: str, result: dict, expectation: dict) -> list[str]:
    answer = result.get("answer") or ""
    status = result.get("answer_status")
    checked = result.get("calculation_checked")
    first = expectation["lines"][0]
    whole_total = _field_amount(expectation, "fee_all")
    whole_in = _field_amount(expectation, "fee_in")
    problems: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(f"{case}.{probe_id}: {message}")

    if probe_id in ("swapped_names", "unknown_name"):
        require(status == "unavailable", f"错误定位应拒绝，实际 answer_status={status}")
        require(checked is not True, "错误定位不得标记 calculation_checked=true")
        return problems

    require(status in ("complete", "partial"), f"应正常回答，实际 answer_status={status}")
    require(first["item_name"] in answer, f"回答缺少第1行项目名「{first['item_name']}」")
    if probe_id in ("field_with_item", "line_and_whole_field", "polite_line"):
        require(checked is True, "目标已核对时应标记 calculation_checked=true")
    if probe_id in ("field_with_item", "cover_all_with_item"):
        require(_has_value(answer, whole_total), f"回答缺少整单费用总金额 {_amount_text(whole_total)}")
    if probe_id == "cover_all_with_item":
        present = [line["item_name"] for line in expectation["lines"]
                   if line["item_name"] and line["item_name"] in answer]
        require(len(present) >= min(2, len(expectation["lines"])),
                f"全覆盖回答只交付 {len(present)} 行明细")
    if probe_id == "line_attribute_only":
        require(_has_value(answer, first.get("in_scope")),
                f"回答缺少本行医保内金额 {first.get('in_scope')}")
        if (_decimal(whole_in) is not None and _decimal(first.get("in_scope")) is not None
                and _decimal(whole_in) != _decimal(first.get("in_scope"))):
            require(not _has_value(answer, whole_in),
                    f"单行问句不应带入整单医保内金额 {_amount_text(whole_in)}")
    if probe_id == "line_and_whole_field":
        require(_has_value(answer, first.get("in_scope")),
                f"回答缺少本行医保内金额 {first.get('in_scope')}")
        require(_has_value(answer, whole_in), f"回答缺少整单医保内金额 {_amount_text(whole_in)}")
    return problems


# ── 目标判定 ────────────────────────────────────────────────────

def _requirement(entry: dict) -> TargetRequirement:
    requirement = TargetRequirement(
        key=entry["key"], label=entry["label"], amount=entry["amount"],
        kind=entry["kind"],
        required_tokens=tuple(entry.get("required_tokens") or ()),
        required_values=tuple(entry.get("required_values") or ()),
        required_sources=tuple(entry.get("required_sources") or ()),
        forbidden_tokens=tuple(entry.get("forbidden_tokens") or ()),
        source_record=bool(entry.get("source_record")),
        gap_markers=tuple(entry.get("gap_markers") or ()))
    TargetRequirement.check(entry)
    return requirement


def grade_case(case: str, expectation: dict, recorded: dict) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    problems: list[str] = []
    answers = recorded.get("answers") or {}
    for entry in expectation["fields"] + expectation["lines"]:
        label = entry["label"]
        key = entry["key"]
        result = answers.get(key) or {}
        answer = result.get("answer") or ""
        citations = tuple(c.get("title") or "" for c in result.get("citations") or ())
        assessment = assess_target(answer, _requirement(entry), citations)
        if not assessment.delivered:
            problems.append(f"{key}: 未如实交付（{assessment.reason}）")
        rows.append(dict(case=case, key=key, label=label, amount=entry["amount"],
                         kind=entry["kind"], status=assessment.status,
                         delivered=assessment.delivered, reason=assessment.reason,
                         answer_status=result.get("answer_status"),
                         answer_head=answer.splitlines()[0][:140] if answer else ""))
    for probe_id, result in (recorded.get("probes") or {}).items():
        problems.extend(probe_problems(case, probe_id, result, expectation))
    missing_probes = set(probe_questions(expectation)) - set(recorded.get("probes") or {})
    if missing_probes:
        problems.append(f"{case}: 缺少探针结果 {sorted(missing_probes)}")
    return rows, problems


def collect_case(client: Client, case: str, expectation: dict) -> dict:
    identifier, chain = expectation["identifier"], expectation["chain"]
    session = f"accept-{case}"
    panel = client.get(f"/policy-qa/sessions/{session}/decomposition"
                       f"?settlement_id={identifier}&chain={chain}")
    answers: dict[str, dict] = {}
    for entry in expectation["fields"]:
        question = f"本单「{entry['label']}」是怎么算的？"
        answers[entry["key"]] = client.ask(session, identifier, chain, question)
    for entry in expectation["lines"]:
        display_no = entry["key"].rsplit(".", 1)[1]
        question = f"第{display_no}行{entry['item_name']}的医保内外怎么算？"
        answers[entry["key"]] = client.ask(session, identifier, chain, question)
    probes = {}
    for probe_id, question in probe_questions(expectation).items():
        probes[probe_id] = {"question": question,
                            **client.ask(session, identifier, chain, question)}
    cover = client.ask(session, identifier, chain, COVER_ALL_Q)
    return {"panel": panel, "answers": answers, "probes": probes, "cover_all": cover}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / ".scratch" / "four-chain-acceptance-latest"))
    parser.add_argument("--record", default=None, help="保存脱敏回放目录（不再另发请求）")
    parser.add_argument("--replay", default=None, help="从回放目录复跑判定（测试用）")
    args = parser.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.replay:
        recording = json.loads((Path(args.replay) / "recording.json").read_text(encoding="utf-8"))
    else:
        client = Client()
        recording = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": {}}
        for case, expectation in ACCEPTANCE_EXPECTATIONS.items():
            recorded = collect_case(client, case, expectation)
            recording["cases"][case] = recorded
            (out / f"{case}-panel.json").write_text(
                json.dumps(recorded["panel"], ensure_ascii=False, indent=2), encoding="utf-8")
        if args.record:
            target = Path(args.record)
            target.mkdir(parents=True, exist_ok=True)
            (target / "recording.json").write_text(
                json.dumps(recording, ensure_ascii=False, indent=2), encoding="utf-8")

    rows: list[dict] = []
    problems: list[str] = []
    summary: dict[str, dict] = {}
    for case, expectation in ACCEPTANCE_EXPECTATIONS.items():
        recorded = (recording.get("cases") or {}).get(case)
        if recorded is None:
            problems.append(f"{case}: 回放缺少该链路数据")
            continue
        problems.extend(panel_problems(case, recorded.get("panel") or {}, expectation))
        case_rows, case_problems = grade_case(case, expectation, recorded)
        rows.extend(case_rows)
        problems.extend(case_problems)
        summary[case] = {
            "identifier_tail": expectation["identifier"][-6:],
            "chain": expectation["chain"],
            "visible_amounts": len(expectation["fields"]),
            "line_count": len(expectation["lines"]),
            "buckets": dict(Counter(row["status"] for row in case_rows)),
            "cover_all_answer_status": (recorded.get("cover_all") or {}).get("answer_status"),
            "cover_all_calculation_checked": (recorded.get("cover_all") or {}).get(
                "calculation_checked"),
        }

    if len(rows) != 84 or len({row["key"] for row in rows}) != 84:
        problems.append(f"验收目标数应为 84 且唯一，实际 {len(rows)}/{len({r['key'] for r in rows})}")

    (out / "summary.json").write_text(
        json.dumps({"summary": summary, "problems": problems}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    lines = ["# 四链路目标验收（自动生成）", "",
             f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", "",
             "| 目标 ID | 展示字段 | 金额 | 预期类型 | 内容状态 | 如实交付 | 未交付原因 | 回答首句 |",
             "|---|---|---:|---|---|---|---|---|"]
    for row in rows:
        lines.append("| {key} | {label} | {amount} | {kind} | {status} | {delivered} | {reason} | "
                     "{answer_head} |".format(**row))
    lines += ["", "## 分链路统计", "", "```json",
              json.dumps(summary, ensure_ascii=False, indent=2), "```",
              "", "## 未通过项", "", "```json",
              json.dumps(problems, ensure_ascii=False, indent=2), "```"]
    (out / "acceptance-table.md").write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({
        "total": dict(Counter(row["status"] for row in rows)),
        "delivered": sum(1 for row in rows if row["delivered"]),
        "problems": problems,
    }, ensure_ascii=False, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
