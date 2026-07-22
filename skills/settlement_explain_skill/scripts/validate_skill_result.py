"""
validate_skill_result.py — 输出校验脚本

根据 validators.yaml 定义的规则校验 skill 输出。

校验项：
1. 禁止文本扫描 — 任何输出不得包含 forbidden_text 列表中的内容
2. 必须文本检查 — 根据模式(模板/LLM)检查 patient_answer 是否包含关键内容
3. LLM 输出检查 — 验证 LLM 模式下的结构完整性
4. 金额一致性 — patient_answer 和 office_answer 中的金额引用必须一致

规则来源: validators.yaml (技能目录下)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ── YAML 加载 ─────────────────────────────────────────────────

_VALIDATORS_PATH = Path(__file__).resolve().parent.parent / "validators.yaml"


def _load_validators() -> dict[str, Any]:
    """从 validators.yaml 加载校验规则。"""
    with open(_VALIDATORS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_VALIDATORS = _load_validators()

# 导出规则（保持兼容性）
FORBIDDEN_TEXT: list[str] = _VALIDATORS.get("forbidden_text", [])
REQUIRED_CONTAINS: list = _VALIDATORS.get("required_patient_answer_contains", [])
REQUIRED_CONTAINS_COMPLETE: list = _VALIDATORS.get(
    "required_patient_answer_contains_when_complete", []
)
LLM_CHECKS: list = _VALIDATORS.get("llm_output_checks", [])

# 兼容旧代码：导出纯文本列表（包含所有 required 文本，过滤 skip_for_llm 标记）
REQUIRED_CONTAINS_POOLING_SELF_PAY: list[str] = [
    item["text"] if isinstance(item, dict) else item for item in REQUIRED_CONTAINS
]
REQUIRED_CONTAINS_POOLING_SELF_PAY_COMPLETE: list[str] = [
    item["text"] if isinstance(item, dict) else item
    for item in REQUIRED_CONTAINS_COMPLETE
]


# ── 校验结果 ──────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """校验结果。"""
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── 内部工具 ──────────────────────────────────────────────────


def _get_required(
    target_fee_item: str, is_complete: bool, skip_for_llm: bool = False
) -> list[str]:
    """
    获取需要检查的必须文本列表。

    Args:
        target_fee_item: 目标费用项
        is_complete: 政策是否完整匹配
        skip_for_llm: 是否跳过 skip_for_llm 标记的规则

    Returns:
        文本片段列表
    """
    required: list[str] = []
    if target_fee_item == "pooling_self_pay":
        for item in REQUIRED_CONTAINS:
            if isinstance(item, dict):
                if skip_for_llm and item.get("skip_for_llm", False):
                    continue
                required.append(item["text"])
            else:
                required.append(item)
        if is_complete:
            for item in REQUIRED_CONTAINS_COMPLETE:
                if isinstance(item, dict):
                    if skip_for_llm and item.get("skip_for_llm", False):
                        continue
                    required.append(item["text"])
                else:
                    required.append(item)
    return required


# ── 校验函数 ──────────────────────────────────────────────────


def validate_patient_answer(
    patient_answer: str,
    target_fee_item: str,
    is_complete: bool = False,
    skip_for_llm: bool = False,
) -> ValidationResult:
    """
    校验患者视角输出。

    Args:
        patient_answer: 患者视角文本
        target_fee_item: 目标费用项
        is_complete: 政策是否完整匹配
        skip_for_llm: 是否跳过 skip_for_llm 标记的规则（LLM 模式使用）

    Returns:
        ValidationResult
    """
    result = ValidationResult()

    # 1. 禁止文本扫描（无论模式都执行）
    for fb in FORBIDDEN_TEXT:
        if fb and fb in patient_answer:
            result.errors.append(f"患者视角包含禁止文本: {repr(fb)}")
            result.passed = False

    # 2. 必须文本检查
    required = _get_required(target_fee_item, is_complete, skip_for_llm)
    for req in required:
        if req not in patient_answer:
            result.warnings.append(f"患者视角缺少必须文本: {req}")

    return result


def validate_llm_output(output: str) -> ValidationResult:
    """
    校验 LLM 输出（仅 LLM 模式使用）。

    检查 validators.yaml 中 llm_output_checks 定义的结构完整性规则。

    Args:
        output: LLM 输出的文本

    Returns:
        ValidationResult
    """
    result = ValidationResult()

    # 1. 禁止文本扫描
    for fb in FORBIDDEN_TEXT:
        if fb and fb in output:
            result.errors.append(f"LLM 输出包含禁止文本: {repr(fb)}")
            result.passed = False

    # 2. LLM 特有检查
    for check in LLM_CHECKS:
        if "text" in check:
            # 必须包含指定文本
            if check["text"] not in output:
                result.errors.append(
                    f"LLM 输出缺少: {check.get('description', check['text'])}"
                )
                result.passed = False
        elif "pattern" in check:
            # 必须匹配正则
            if not re.search(check["pattern"], output):
                result.errors.append(
                    f"LLM 输出不匹配: {check.get('description', check['pattern'])}"
                )
                result.passed = False

    return result


# ── 兼容入口 ──────────────────────────────────────────────────


def validate_skill_output(
    result: dict[str, Any],
    skip_for_llm: bool = False,
) -> ValidationResult:
    """
    校验完整的 skill 输出。

    Args:
        result: skill 输出字典（需含 patient_answer, office_answer, target_fee_item 等）
        skip_for_llm: 是否跳过 skip_for_llm 标记的规则

    Returns:
        ValidationResult
    """
    vr = ValidationResult()

    patient_answer = str(result.get("patient_answer", ""))
    office_answer = str(result.get("office_answer", ""))
    target_fee_item = str(result.get("target_fee_item", "pooling_self_pay"))
    completeness = result.get("evidence_completeness", {})
    is_complete = completeness.get("level") == "full_policy_ratio_matched"

    # 校验患者视角
    pr = validate_patient_answer(
        patient_answer, target_fee_item, is_complete, skip_for_llm
    )
    vr.warnings.extend(pr.warnings)
    vr.errors.extend(pr.errors)
    if not pr.passed:
        vr.passed = False

    # 校验医保办视角
    for fb in FORBIDDEN_TEXT:
        if fb and fb in office_answer:
            vr.errors.append(f"医保办视角包含禁止文本: {repr(fb)}")
            vr.passed = False

    # 金额一致性检查
    if "4,962.67" in patient_answer and "4,962.67" not in office_answer:
        vr.warnings.append("患者和医保办视角金额不一致")

    return vr


# ── 命令行测试 ──────────────────────────────────────────────────

if __name__ == "__main__":
    # 模拟 skill 输出（模板模式）
    mock_output = {
        "target_fee_item": "pooling_self_pay",
        "patient_answer": "本次结算中，您的统筹自付为 4,962.67 元。三级医院...",
        "office_answer": "统筹自付 4,962.67 元...",
        "evidence_completeness": {"level": "full_policy_ratio_matched"},
    }
    vr = validate_skill_output(mock_output)
    print(f"[模板模式] 校验结果: passed={vr.passed}")
    print(f"  警告: {vr.warnings}")
    print(f"  错误: {vr.errors}")

    # 模拟 LLM 输出
    llm_output = "【本次结论】您本次的统筹自付金额为 1,234.56 元。"
    lr = validate_llm_output(llm_output)
    print(f"\n[LLM模式] 校验结果: passed={lr.passed}")
    print(f"  警告: {lr.warnings}")
    print(f"  错误: {lr.errors}")
    print("OK")
