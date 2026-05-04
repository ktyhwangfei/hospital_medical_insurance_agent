from dataclasses import dataclass, field


@dataclass
class WorkflowInstance:
    workflow_id: str
    status: str
    steps: list[str] = field(default_factory=list)
    knowledge_events: list[dict] = field(default_factory=list)
    knowledge_degradation_reasons: list[str] = field(default_factory=list)
