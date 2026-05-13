# Learnings

## 2026-05-08 Session Start
- All domain models use Pydantic BaseModel (not dataclass) except Patient which uses frozen dataclass
- StrEnum pattern for all enums (import from enum, not StrEnum from fastapi or similar)
- Storage pattern: Protocol in ports.py, InMemoryXxxStorage in in_memory.py, factory.py for backend selection
- InMemoryStorage uses model_copy(deep=True) for get/list operations (defensive copy)
- MCP storage factory pattern: settings.persistence_backend switch, postgres/kingbase/in_memory
- Planning models: PlanStep + ExecutionPlan pattern, StepType enum, RiskLevel enum
- Orchestration: if/elif dispatch in execute_plan() by plan.scenario string
- Existing roles: cashier, medical_office, information_department, medical_record_staff, clinician
- SCENARIO_ALLOWED_ROLES uses raw string keys matching Role enum values
- tests use conftest.py with build_client() returning TestClient(create_app())
- Every directory needs __init__.py (can be empty)
