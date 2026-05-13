from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    content: str = ""
    scope: str = "user"
    mtime: float = 0
    
    def __post_init__(self):
        if not self.name:
            raise ValueError("Skill name is required")
        if self.description is None:
            raise ValueError("Skill description is required")
    
    @property
    def skill_dir(self) -> Path:
        return self.path.parent
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
            "scope": self.scope,
            "frontmatter": self.frontmatter,
            "mtime": self.mtime
        }
