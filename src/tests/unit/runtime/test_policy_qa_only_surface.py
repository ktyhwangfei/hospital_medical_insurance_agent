"""Policy QA 唯一业务面的架构边界测试。"""

from pathlib import Path

from src.runtime.intent.planner import ContextPlanner


SRC_ROOT = Path(__file__).resolve().parents[3]
LEGACY_PATHS = (
    "business_scenarios",
    "runtime/scenario_executor.py",
    "runtime/orchestrator.py",
    "runtime/langgraph",
    "runtime/orchestration",
    "runtime/planning",
    "runtime/scheduling",
    "runtime/capability_nodes",
    "runtime/dependencies.py",
    "runtime/skill_registry",
    "runtime/policy_qa/orchestrator.py",
    "data_platform/storage/skill/seed.py",
)


def test_retired_business_modules_are_absent() -> None:
    existing = [
        path
        for path in LEGACY_PATHS
        if (SRC_ROOT / path).is_file()
        or ((SRC_ROOT / path).is_dir() and any((SRC_ROOT / path).rglob("*.py")))
    ]

    assert existing == []


def test_context_planner_contains_no_retired_business_intents() -> None:
    assert "settlement_exception_guidance" not in ContextPlanner.INTENT_OBJECT_MAP
    assert "pre_discharge_quality_control" not in ContextPlanner.INTENT_OBJECT_MAP
