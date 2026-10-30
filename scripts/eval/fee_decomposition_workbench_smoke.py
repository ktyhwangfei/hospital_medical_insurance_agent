"""费用分解工作台 API 活库冒烟（Issue #78 四链路页面可用化 Phase 4）。

直连本工作区后端（默认 http://127.0.0.1:8109），用回放 CSV 中的真实样本号逐链路打
POST /fee-decomposition/decompose，并与回放 CSV 结论比对：
- 职工门诊 / 居民门诊：execution_status + reconciliation_status + uncertainty 码集合；
- 职工门特（djh=567）：逐字段 (check_status, observed, calculated) 全量比对；
- 居民门特（djh=688）：execution/reconciliation + 差异字段名集合比对。

鉴权 token 由本脚本用 AUTH_JWT_SECRET 现签（密钥只进进程内存，不打印不落盘）。
用法：uv run python scripts/eval/fee_decomposition_workbench_smoke.py [--base-url URL] [--id-card 身份证号]
（--id-card 用于验证按人定位链路：resolve-person 列出候选后对每条链路的第一个候选做分解；
身份证号仅进程内使用，不打印原文、不落盘。）
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent

SAMPLES = [
    # (链路, identifier, 回放 CSV, 主键列)
    ("职工门诊", "011100030X240409000004", EVAL_DIR / "issue78_fee_decomposition_batch_result.csv", "trade_no"),
    ("居民门诊", "011100030X240408000002", EVAL_DIR / "issue80_resident_batch_result.csv", "trade_no"),
    ("职工门特", "567", EVAL_DIR / "issue79_special_mz_batch_result.csv", "djh"),
    ("居民门特", "688", EVAL_DIR / "issue81_resident_special_batch_result.csv", "djh"),
]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_token() -> str:
    """与 start-servers.ps1 同款 HS256 dev token（fee_decomposition:read，1h）。"""
    secret = os.environ["AUTH_JWT_SECRET"].encode("utf-8")
    header = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = _b64url(json.dumps({
        "sub": "smoke-fee-decomposition",
        "roles": ["information_department"],
        "permissions": ["fee_decomposition:read"],
        "exp": int(time.time()) + 3600,
    }, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(secret, f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decompose(base_url: str, token: str, identifier: str, chain: str = "auto") -> dict:
    req = urllib.request.Request(
        f"{base_url}/api/v1/medical-insurance-ai-agent/fee-decomposition/decompose",
        data=json.dumps({"identifier": identifier, "chain": chain}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def resolve_person(base_url: str, token: str, id_card: str) -> dict:
    req = urllib.request.Request(
        f"{base_url}/api/v1/medical-insurance-ai-agent/fee-decomposition/resolve-person",
        data=json.dumps({"id_card": id_card}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _load_csv_rows(path: Path, key_col: str, key: str) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if (row.get(key_col) or "") == key]


def compare(chain: str, identifier: str, api: dict, rows: list[dict]) -> list[str]:
    """返回不一致项列表（空 = 与回放一致）。"""
    problems: list[str] = []
    if not rows:
        return [f"回放 CSV 未找到 {identifier}"]
    if chain in ("职工门诊", "居民门诊", "居民门特"):
        expected_codes = set(filter(None, (rows[0].get("uncertainty_codes") or "").split("; ")))
        actual_codes = {u["code"] for u in api.get("uncertainties", [])}
        if expected_codes != actual_codes:
            problems.append(f"uncertainty 码集合不一致: 回放={sorted(expected_codes)} API={sorted(actual_codes)}")
        expected_recon = rows[0].get("reconciliation_status")
        if expected_recon and expected_recon != api.get("reconciliation_status"):
            problems.append(f"reconciliation_status: 回放={expected_recon} API={api.get('reconciliation_status')}")
        if chain == "居民门特":
            # 差异字段名集合比对（账面/算得数值以逐字段对账 CSV 为准，此处比字段维度）
            mismatched_text = rows[0].get("mismatched_fields") or ""
            expected_fields = {part.split("(")[0] for part in mismatched_text.split("; ") if part}
            actual_fields = {f["field_code"] for f in api.get("fields", []) if f["check_status"] == "mismatched"}
            if expected_fields != actual_fields:
                problems.append(f"差异字段集合: 回放={sorted(expected_fields)} API={sorted(actual_fields)}")
    else:  # 职工门特：逐字段全量比对
        field_rows = [r for r in rows if r.get("row_type") == "field"]
        api_fields = {f["field_code"]: f for f in api.get("fields", [])}
        if len(field_rows) != len(api_fields):
            problems.append(f"字段数: 回放={len(field_rows)} API={len(api_fields)}")
        for row in field_rows:
            api_field = api_fields.get(row["field_code"])
            if api_field is None:
                problems.append(f"API 缺字段 {row['field_code']}")
                continue
            for csv_col, api_key in (("check_status", "check_status"), ("observed_amount", "observed_amount"), ("calculated_amount", "calculated_amount")):
                expected = (row.get(csv_col) or "").strip()
                actual = api_field.get(api_key) or ""
                if csv_col != "check_status":
                    # 金额小数位口径不同（回放 4 位 vs 公开契约 2 位），按数值比
                    try:
                        if abs(float(expected) - float(actual)) > 0.005:
                            problems.append(f"{row['field_code']}.{api_key}: 回放={expected} API={actual}")
                    except ValueError:
                        if expected != actual:
                            problems.append(f"{row['field_code']}.{api_key}: 回放={expected!r} API={actual!r}")
                elif expected != actual:
                    problems.append(f"{row['field_code']}.check_status: 回放={expected} API={actual}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8109")
    parser.add_argument("--id-card", default=None, help="按人定位验证用身份证号（仅进程内使用）")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    token = mint_token()

    failed = 0
    for chain, identifier, csv_path, key_col in SAMPLES:
        try:
            api = decompose(args.base_url, token, identifier)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {chain} {identifier}: 请求异常 {exc}")
            failed += 1
            continue
        problems = compare(chain, identifier, api, _load_csv_rows(csv_path, key_col, identifier))
        meta = api.get("meta", {})
        status_line = (
            f"{api.get('execution_status')}/{api.get('reconciliation_status')} "
            f"profile={meta.get('profile')} algo={api.get('algorithm_version')} "
            f"fields={len(api.get('fields', []))} uncertainties={len(api.get('uncertainties', []))}"
        )
        if problems:
            failed += 1
            print(f"[FAIL] {chain} {identifier}: {status_line}")
            for problem in problems:
                print(f"       - {problem}")
        else:
            print(f"[OK]   {chain} {identifier}: {status_line}（与回放一致）")

    if args.id_card:
        # 按人定位链路：resolve-person 列候选（不打印身份证原文），再对每条链路的
        # 第一个候选做分解，验证「身份证 → 候选 → 分解」端到端连通。
        try:
            resolved = resolve_person(args.base_url, token, args.id_card)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] 按人定位: 请求异常 {exc}")
            failed += 1
            resolved = None
        if resolved is not None:
            candidates = resolved.get("candidates", [])
            print(
                f"[INFO] 按人定位: match_status={resolved.get('match_status')} "
                f"truncated={resolved.get('truncated')} candidates={len(candidates)}"
            )
            for cand in candidates[:10]:
                print(
                    f"       - {cand.get('chain_label')}/{cand.get('profile_label')} "
                    f"{cand.get('identifier')} {cand.get('service_date')} 总额={cand.get('total_amount')}"
                )
            if not candidates and resolved.get("match_status") != "no_match":
                failed += 1
                print("[FAIL] 按人定位: 非 no_match 但无候选")
            seen_chains: set[str] = set()
            for cand in candidates:
                if cand["chain"] in seen_chains:
                    continue
                seen_chains.add(cand["chain"])
                try:
                    api = decompose(args.base_url, token, cand["identifier"], cand["chain"])
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    print(f"[FAIL] 候选分解 {cand.get('chain_label')} {cand['identifier']}: {exc}")
                    continue
                print(
                    f"[OK]   候选分解 {cand.get('chain_label')} {cand['identifier']}: "
                    f"{api.get('execution_status')}/{api.get('reconciliation_status')} "
                    f"profile={api.get('meta', {}).get('profile')} fields={len(api.get('fields', []))}"
                )

    print("SMOKE", "PASS" if failed == 0 else f"FAIL({failed})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
