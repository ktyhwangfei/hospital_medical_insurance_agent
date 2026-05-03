from dataclasses import dataclass


@dataclass(frozen=True)
class Citation:
    source_type: str
    source_id: str
    summary: str
