import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from .models import Skill

logger = logging.getLogger(__name__)


class SkillParseError(Exception):
    pass


class SkillNotFoundError(Exception):
    pass


class SkillLoader:
    REQUIRED_FIELDS = {"name", "description"}
    
    @classmethod
    def load_from_file(cls, path: Path) -> Skill:
        if not path.exists():
            raise SkillNotFoundError(f"Skill file not found: {path}")
        
        if not path.name == "SKILL.md":
            raise SkillParseError(f"Invalid skill file name: {path.name}, expected SKILL.md")
        
        content = path.read_text(encoding="utf-8")
        return cls.parse(content, path)
    
    @classmethod
    def parse(cls, content: str, path: Path) -> Skill:
        if not content.strip():
            raise SkillParseError("Empty skill file")
        
        frontmatter, body = cls._extract_frontmatter(content)
        
        missing = cls.REQUIRED_FIELDS - set(frontmatter.keys())
        if missing:
            raise SkillParseError(f"Missing required fields: {missing}")
        
        skill = Skill(
            name=frontmatter["name"],
            description=frontmatter["description"],
            path=path,
            frontmatter=frontmatter,
            content=body.strip(),
            scope=frontmatter.get("scope", "user"),
            mtime=path.stat().st_mtime if path.exists() else 0
        )
        
        return skill
    
    @classmethod
    def _extract_frontmatter(cls, content: str) -> tuple:
        if not content.startswith("---"):
            return {}, content
        
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content
        
        try:
            frontmatter = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as e:
            raise SkillParseError(f"Invalid YAML frontmatter: {e}")
        
        if not frontmatter.get("description"):
            raise SkillParseError("Skill description cannot be empty")
        
        body = parts[2]
        return frontmatter, body
