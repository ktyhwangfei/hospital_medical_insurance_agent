from dataclasses import dataclass


@dataclass
class ClosureTask:
    task_id: str
    task_type: str
    status: str
    responsible_role: str
    description: str
