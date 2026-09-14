"""健康运营 P1-5 LLM 智能诊断 — issue #51。

对单条 finding 组装「payload + 定向补充证据」的证据目录（统一过
security/desensitization 脱敏），经 ModelGateway scene=asset_diagnosis
生成结构化诊断：根因 + citations + uncertainties + L1/L2/L3 分级建议。

安全硬约束：citations 只能从证据目录中选取（quote 取自目录原文，模型
不可编造）；引用为空的诊断一律落库为 insufficient_evidence——root_cause
置空、建议动作清空，不驱动任何修复动作。诊断只读，不改 finding 状态。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from src.domain.ops.models import (
    DiagnosisAction,
    DiagnosisActionLevel,
    DiagnosisCitation,
    DiagnosisStatus,
    DiagnosisUnavailableError,
    OpsDiagnosisReport,
    OpsDiagnosisResult,
    OpsFinding,
)
from src.security.desensitization.detection import redact_sensitive_text

logger = logging.getLogger(__name__)

DIAGNOSIS_SCENE = "asset_diagnosis"
DIAGNOSIS_MODEL_TYPE = "llm"

# 证据条目与模型输出各部分的长度上限（证据目录 quote 传给模型前截断）
_EVIDENCE_QUOTE_MAX = 400
_ROOT_CAUSE_MAX = 2000
_UNCERTAINTY_MAX = 300
_ACTION_DESCRIPTION_MAX = 500
_MAX_UNCERTAINTIES = 5
_MAX_ACTIONS = 5
_MAX_SUPPLEMENT_ITEMS = 5

_SYSTEM_PROMPT = (
    "你是医院医保数据资产健康运营平台的诊断助手。你只能依据用户提供的编号证据"
    "（E1、E2……）分析问题根因并给出分级建议动作，禁止引入证据之外的信息或编造数值，"
    "所有根因与建议必须挂证据编号引用。输出必须是单个 JSON 对象，不要输出任何其他文本。"
    'JSON 结构：{"root_cause": "根因分析", "citations": ["E1"], '
    '"uncertainties": ["不确定之处"], "actions": [{"level": "L1", '
    '"description": "建议动作", "citation_ids": ["E1"]}]}。'
    "citations 是支撑根因分析的证据编号列表；level 含义：L1=幂等可自动重放"
    "（如重试同步任务），L2=需人工在治理流程确认（如知识重提取、Skill 草稿修改），"
    "L3=禁止自动执行仅提示（如涉及正式结算、退费、病案修改）。"
    "证据不足以定位根因时，输出空 citations 与空 actions，并在 uncertainties "
    "说明缺少什么证据，不得硬编结论。"
)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class DiagnosisModelGateway(Protocol):
    """诊断对模型网关的最小依赖（ModelGateway.generate 已满足）。"""

    def generate(self, messages: list, model_type: str, scene: str): ...


EvidenceCollector = Callable[[OpsFinding], list[tuple[str, str]]]


def default_evidence_collector() -> EvidenceCollector:
    """定向补充证据（按检查项）：门诊同步问题附最近同步尝试记录。

    补充证据与 payload 一样只携带安全字段（状态码 / safe_message / 行数 /
    时间戳），采集失败静默跳过（诊断退化为仅基于 payload）。
    """

    def collect(finding: OpsFinding) -> list[tuple[str, str]]:
        if finding.check_id != "data_sync_failed":
            return []
        try:
            from src.data_platform.storage.postgresql.outpatient_governance_store import (
                OutpatientGovernanceStore,
            )

            attempts = OutpatientGovernanceStore().list_attempts(
                finding.asset_id, limit=_MAX_SUPPLEMENT_ITEMS,
            )
        except Exception as exc:  # 读取面故障不阻断诊断：仅记录，退化为 payload 证据
            logger.warning("诊断补充证据读取失败 finding=%s: %s", finding.finding_id, exc)
            return []
        return [
            (
                f"supplement.sync_attempts[{i}]",
                (
                    f"status={attempt.status} error_code={attempt.safe_error_code or '-'} "
                    f"message={attempt.safe_message or '-'} rows={attempt.row_count} "
                    f"started_at={attempt.started_at.isoformat()}"
                ),
            )
            for i, attempt in enumerate(attempts)
        ]

    return collect


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def build_evidence_catalog(
    finding: OpsFinding,
    supplement: list[tuple[str, str]],
) -> dict[str, DiagnosisCitation]:
    """证据目录：payload 逐字段 + 定向补充，统一脱敏后编号 E1..En。"""
    entries: list[tuple[str, str]] = [
        (f"payload.{key}", json.dumps(value, ensure_ascii=False))
        for key, value in finding.payload.items()
        if value is not None and not (
            isinstance(value, str) and not value.strip()
        )
    ]
    entries.extend(supplement)
    catalog: dict[str, DiagnosisCitation] = {}
    for index, (source, raw_quote) in enumerate(entries, start=1):
        quote = redact_sensitive_text(_truncate(str(raw_quote).strip(), _EVIDENCE_QUOTE_MAX))
        if not quote:
            continue
        catalog[f"E{index}"] = DiagnosisCitation(
            citation_id=f"E{index}",
            source=_truncate(source, 128),
            quote=quote,
        )
    return catalog


def _extract_json_object(content: str) -> dict[str, Any]:
    """从模型输出提取 JSON 对象（容忍 markdown 围栏与前后杂文本）。"""
    text = _JSON_FENCE_RE.sub("", (content or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise DiagnosisUnavailableError("模型输出中未找到 JSON 对象")
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise DiagnosisUnavailableError(f"模型输出 JSON 解析失败：{exc}") from exc
    if not isinstance(parsed, dict):
        raise DiagnosisUnavailableError("模型输出不是 JSON 对象")
    return parsed


class OpsDiagnosisService:
    """LLM 智能诊断：证据目录 → ModelGateway → 校验落库（citations 硬约束）。"""

    def __init__(
        self,
        storage,
        gateway_factory: Callable[[], DiagnosisModelGateway],
        evidence_collector: EvidenceCollector | None = None,
    ) -> None:
        self._storage = storage
        self._gateway_factory = gateway_factory
        self._collect_evidence = evidence_collector or default_evidence_collector()

    def diagnose_finding(self, finding_id: str, *, actor: str) -> OpsDiagnosisResult:
        """对单条 finding 生成诊断报告并覆盖落库（不动状态与 revision）。"""
        finding = self._storage.get_finding(finding_id)
        catalog = build_evidence_catalog(finding, self._collect_evidence(finding))
        response = self._invoke_model(finding, catalog)
        report = build_report(
            finding_id,
            (getattr(response, "content", "") or "").strip(),
            catalog,
            actor=actor,
            model_name=getattr(response, "model_name", None),
        )
        updated = self._storage.save_diagnosis(
            finding_id, report.model_dump(mode="json"),
        )
        return OpsDiagnosisResult(finding=updated, report=report)

    def _invoke_model(
        self,
        finding: OpsFinding,
        catalog: dict[str, DiagnosisCitation],
    ):
        from src.model_service.models import Message

        evidence_lines = [
            "- 检查项：%s（%s 资产 %s，严重度 %s，累计发现 %d 次）"
            % (
                finding.check_id, finding.asset_type.value, finding.asset_id,
                finding.severity.value, finding.occurrence_count,
            )
        ]
        evidence_lines += [
            f"- {item.citation_id} [{item.source}]：{item.quote}"
            for item in catalog.values()
        ]
        evidence_lines.append("请依据以上证据输出诊断 JSON。")
        try:
            response = self._gateway_factory().generate(
                [
                    Message(role="system", content=_SYSTEM_PROMPT),
                    Message(role="user", content="\n".join(evidence_lines)),
                ],
                model_type=DIAGNOSIS_MODEL_TYPE,
                scene=DIAGNOSIS_SCENE,
            )
        except DiagnosisUnavailableError:
            raise
        except Exception as exc:  # 模型未配置/调用失败：不可用，不落库
            raise DiagnosisUnavailableError(f"模型调用失败：{type(exc).__name__}") from exc
        return response


def build_report(
    finding_id: str,
    model_content: str,
    catalog: dict[str, DiagnosisCitation],
    *,
    actor: str,
    model_name: str | None = None,
) -> OpsDiagnosisReport:
    """把模型输出校验为诊断报告：引用只认目录、无引用落 insufficient_evidence。"""
    parsed = _extract_json_object(model_content)    # 引用只能从证据目录选取（模型只可挑选、不可编造），按首次出现顺序去重
    selected: list[DiagnosisCitation] = []
    seen: set[str] = set()
    raw_ids = parsed.get("citations", [])
    for citation_id in raw_ids if isinstance(raw_ids, list) else []:
        if not isinstance(citation_id, str):
            continue
        item = catalog.get(citation_id.strip())
        if item is not None and item.citation_id not in seen:
            seen.add(item.citation_id)
            selected.append(item)

    raw_uncertainties = parsed.get("uncertainties", [])
    uncertainties = [
        _truncate(str(item).strip(), _UNCERTAINTY_MAX)
        for item in (raw_uncertainties if isinstance(raw_uncertainties, list) else [])
        if str(item).strip()
    ][:_MAX_UNCERTAINTIES]

    # 硬约束：无引用 → insufficient_evidence，不落根因、不留任何建议动作
    if not selected:
        return OpsDiagnosisReport(
            finding_id=finding_id,
            status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
            root_cause=None,
            citations=[],
            uncertainties=uncertainties + ["模型未给出可验证的证据引用，诊断不成立"],
            actions=[],
            model_route=_model_route(model_name),
            generated_by=actor,
            generated_at=datetime.now(timezone.utc),
        )

    valid_levels = {level.value for level in DiagnosisActionLevel}
    actions: list[DiagnosisAction] = []
    raw_actions = parsed.get("actions", [])
    for raw in raw_actions if isinstance(raw_actions, list) else []:
        if not isinstance(raw, dict):
            continue
        level = raw.get("level")
        description = str(raw.get("description", "")).strip()
        raw_action_ids = raw.get("citation_ids", [])
        action_ids = [
            cid for cid in (raw_action_ids if isinstance(raw_action_ids, list) else [])
            if isinstance(cid, str) and cid.strip() in seen
        ]
        if level not in valid_levels or not description or not action_ids:
            continue  # 级别未知 / 无描述 / 建议未挂任何有效引用 → 丢弃
        actions.append(DiagnosisAction(
            level=DiagnosisActionLevel(level),
            description=_truncate(description, _ACTION_DESCRIPTION_MAX),
            citation_ids=action_ids,
        ))
        if len(actions) >= _MAX_ACTIONS:
            break

    root_cause = str(parsed.get("root_cause", "")).strip()
    return OpsDiagnosisReport(
        finding_id=finding_id,
        status=DiagnosisStatus.COMPLETE,
        root_cause=_truncate(root_cause, _ROOT_CAUSE_MAX) or None,
        citations=selected,
        uncertainties=uncertainties,
        actions=actions,
        model_route=_model_route(model_name),
        generated_by=actor,
        generated_at=datetime.now(timezone.utc),
    )


def _model_route(model_name: str | None) -> dict[str, Any]:
    """报告审计字段：本次诊断使用的路由（scene/model_type + 实际模型名）。"""
    route: dict[str, Any] = {
        "scene": DIAGNOSIS_SCENE,
        "model_type": DIAGNOSIS_MODEL_TYPE,
    }
    if model_name:
        route["model_name"] = model_name
    return route
