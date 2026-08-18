"""Skill 执行契约领域模型单元测试（设计 §4-§53）。

覆盖：
- ContextInputSpec / MetricInputSpec 字段与枚举约束
- ExecutionProfileSpec 的 profile_id kebab-case 校验
- SkillExecutionContract 版本与结构
- MetricRuntimeCapability 运行时可解析能力模型
- 模型冻结（frozen）保证
- JSON 序列化往返（structured_config 兼容）
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.domain.skill.draft_models import (
    CommonInputSpec,
    ContextInputSpec,
    ExecutionProfileSpec,
    MetricInputSpec,
    MetricResolutionType,
    MetricRuntimeCapability,
    MetricUnavailableReason,
    RuntimeContextCode,
    SkillExecutionContract,
)


# ── ContextInputSpec ──────────────────────────────────────────────


def test_context_input_spec_defaults() -> None:
    spec = ContextInputSpec(code=RuntimeContextCode.SETTLEMENT_ID)
    assert spec.code == RuntimeContextCode.SETTLEMENT_ID
    assert spec.required is True
    assert spec.alias == ""
    assert spec.purpose == ""


def test_context_input_spec_accepts_string_code() -> None:
    # 字符串自动转枚举（Pydantic StrEnum 行为）
    spec = ContextInputSpec(code="question", purpose="用户原始问题")
    assert spec.code == RuntimeContextCode.QUESTION
    assert spec.purpose == "用户原始问题"


def test_context_input_spec_rejects_invalid_code() -> None:
    with pytest.raises(ValidationError):
        ContextInputSpec(code="not_a_known_context")  # type: ignore[arg-type]


def test_context_input_spec_frozen() -> None:
    spec = ContextInputSpec(code=RuntimeContextCode.VISIT_ID)
    with pytest.raises(ValidationError):
        spec.code = RuntimeContextCode.PERSON_ID  # type: ignore[misc]


# ── MetricInputSpec ───────────────────────────────────────────────


def test_metric_input_spec_defaults() -> None:
    spec = MetricInputSpec(metric_code="zcgz.deductible_amount")
    assert spec.required is True
    assert spec.alias == ""


def test_metric_input_spec_rejects_empty_code() -> None:
    with pytest.raises(ValidationError):
        MetricInputSpec(metric_code="")


# ── ExecutionProfileSpec · profile_id kebab-case ─────────────────


def test_profile_id_accepts_kebab_case() -> None:
    profile = ExecutionProfileSpec(
        profile_id="deductible-explanation",
        name="起付线解释",
    )
    assert profile.profile_id == "deductible-explanation"


def test_profile_id_accepts_single_segment() -> None:
    profile = ExecutionProfileSpec(profile_id="default", name="默认场景")
    assert profile.profile_id == "default"


@pytest.mark.parametrize(
    "bad_id",
    [
        "",  # 空
        "Deductible-Explanation",  # 大写
        "deductible explanation",  # 空格
        "deductible_explanation",  # 下划线（非 kebab-case）
        "起付线解释",  # 中文
        "-leading",  # 前导连字符
        "trailing-",  # 结尾连字符
    ],
)
def test_profile_id_rejects_non_kebab_case(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        ExecutionProfileSpec(profile_id=bad_id, name="x")


def test_profile_defaults_empty_collections() -> None:
    profile = ExecutionProfileSpec(profile_id="p", name="场景")
    assert profile.routing_hints == []
    assert profile.context_inputs == []
    assert profile.metric_inputs == []
    assert profile.purpose == ""


def test_profile_with_inputs() -> None:
    profile = ExecutionProfileSpec(
        profile_id="copayment-explanation",
        name="统筹自付解释",
        purpose="解释统筹自付金额形成原因",
        routing_hints=["统筹自付", "为什么自付这么多"],
        context_inputs=[ContextInputSpec(code=RuntimeContextCode.SETTLEMENT_ID)],
        metric_inputs=[
            MetricInputSpec(metric_code="zyfdxx.bdtczf", alias="统筹自付金额"),
        ],
    )
    assert profile.routing_hints == ["统筹自付", "为什么自付这么多"]
    assert profile.metric_inputs[0].alias == "统筹自付金额"


# ── SkillExecutionContract ────────────────────────────────────────


def test_contract_defaults_version_two() -> None:
    # 设计 §66：execution_contract.version 默认 2
    contract = SkillExecutionContract()
    assert contract.version == 2
    assert contract.profiles == []
    assert contract.common == CommonInputSpec()


def test_contract_full_structure_matches_design_example() -> None:
    # 对齐设计 §18 示例结构
    contract = SkillExecutionContract(
        version=2,
        common=CommonInputSpec(
            context_inputs=[
                ContextInputSpec(
                    code=RuntimeContextCode.SETTLEMENT_ID,
                    alias="结算标识",
                    purpose="定位本次医保结算",
                )
            ],
            metric_inputs=[
                MetricInputSpec(
                    metric_code="Settlement.person_type",
                    alias="人员类别",
                    purpose="确定待遇适用人群",
                )
            ],
        ),
        profiles=[
            ExecutionProfileSpec(
                profile_id="deductible-explanation",
                name="起付线解释",
                purpose="解释本次起付金额及来源",
                routing_hints=["起付线", "门槛费"],
                metric_inputs=[
                    MetricInputSpec(metric_code="zcgz.deductible_amount"),
                    MetricInputSpec(metric_code="zydyxx.bcqfje"),
                ],
            ),
            ExecutionProfileSpec(
                profile_id="copayment-explanation",
                name="统筹自付解释",
                metric_inputs=[MetricInputSpec(metric_code="zyfdxx.bdtczf")],
            ),
        ],
    )
    assert contract.version == 2
    assert len(contract.profiles) == 2
    assert contract.common.metric_inputs[0].metric_code == "Settlement.person_type"


def test_contract_serializes_to_structured_config_json() -> None:
    # 验证可作为 structured_config.execution_contract 的 JSON 结构
    contract = SkillExecutionContract(
        common=CommonInputSpec(
            context_inputs=[ContextInputSpec(code=RuntimeContextCode.QUESTION)],
        ),
        profiles=[
            ExecutionProfileSpec(profile_id="p-a", name="A"),
        ],
    )
    dumped = contract.model_dump(mode="json")
    # 往返：从 JSON dict 重建（模拟从 structured_config 读取）
    restored = SkillExecutionContract.model_validate(dumped)
    assert restored == contract


def test_contract_frozen() -> None:
    contract = SkillExecutionContract()
    with pytest.raises(ValidationError):
        contract.version = 3  # type: ignore[misc]


# ── MetricRuntimeCapability ───────────────────────────────────────


def test_capability_resolvable_source_field() -> None:
    cap = MetricRuntimeCapability(
        metric_code="Settlement.deductible_amount",
        status="published",
        runtime_resolvable=True,
        resolution_type=MetricResolutionType.SOURCE_FIELD,
        unavailable_reason=None,
    )
    assert cap.runtime_resolvable is True
    assert cap.resolution_type == MetricResolutionType.SOURCE_FIELD
    assert cap.unavailable_reason is None


def test_capability_not_resolvable_with_reason() -> None:
    cap = MetricRuntimeCapability(
        metric_code="Policy.external_rule",
        status="published",
        runtime_resolvable=False,
        resolution_type=None,
        unavailable_reason=MetricUnavailableReason.NO_RUNTIME_RESOLVER,
    )
    assert cap.runtime_resolvable is False
    assert cap.unavailable_reason == MetricUnavailableReason.NO_RUNTIME_RESOLVER


def test_capability_accepts_string_enums() -> None:
    cap = MetricRuntimeCapability(
        metric_code="x.y",
        status="draft",
        runtime_resolvable=False,
        resolution_type=None,
        unavailable_reason="NOT_PUBLISHED",
    )
    assert cap.unavailable_reason == MetricUnavailableReason.NOT_PUBLISHED


def test_runtime_context_code_values() -> None:
    # 设计 §19 V1 固定枚举
    expected = {
        "question",
        "settlement_id",
        "person_id",
        "visit_id",
        "hospital_id",
    }
    assert {c.value for c in RuntimeContextCode} == expected


def test_resolution_type_has_reserved_values() -> None:
    # 设计 §15：V1 仅前两者实现，但模型预留扩展
    values = {r.value for r in MetricResolutionType}
    assert "SOURCE_FIELD" in values
    assert "DEFAULT_VALUE" in values
    assert "SQL_EXPRESSION" in values  # 预留
