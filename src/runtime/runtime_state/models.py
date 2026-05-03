from dataclasses import dataclass, field


@dataclass
class WorkflowInstance:
    workflow_id: str
    status: str
    steps: list[str] = field(default_factory=list)