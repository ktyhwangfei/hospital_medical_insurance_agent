from dataclasses import dataclass, field


@dataclass
class IntentEntry:
    intent_id: str
    description: str
    examples: list[str]
    priority: int
    scenario_route: str


INTENT_REGISTRY: list[IntentEntry] = [
    IntentEntry(
        intent_id='settlement_exception_guidance',
        description='医保结算失败、结算异常相关问题',
        examples=['结算失败怎么办', '医保结算报错', '结算异常'],
        priority=1,
        scenario_route='guide_settlement_exception',
    ),
    IntentEntry(
        intent_id='pre_discharge_quality_control',
        description='出院前联合质控、医保风险检查',
        examples=['出院前检查', '医保风险', '质控问题'],
        priority=2,
        scenario_route='run_pre_discharge_qc',
    ),
]


def get_intent_registry() -> list[IntentEntry]:
    return INTENT_REGISTRY


def get_intent_by_id(intent_id: str) -> IntentEntry | None:
    return next((e for e in INTENT_REGISTRY if e.intent_id == intent_id), None)
