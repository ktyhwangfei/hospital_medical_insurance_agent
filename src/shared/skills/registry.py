import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Callable

from .models import Skill
from .loader import SkillLoader, SkillParseError, SkillNotFoundError

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self, paths: List[str] = None):
        self.paths: List[Path] = []
        self.skills: Dict[str, Skill] = {}
        self._last_scan: Dict[str, float] = {}
        self._watch_callbacks: List[Callable[[Skill], None]] = []
        
        if paths:
            for path in paths:
                self.add_path(path)
    
    def add_path(self, path: str) -> None:
        expanded = Path(os.path.expanduser(path)).resolve()
        if expanded not in self.paths:
            self.paths.append(expanded)
            logger.info(f"Added skill path: {expanded}")
    
    def remove_path(self, path: str) -> None:
        expanded = Path(os.path.expanduser(path)).resolve()
        if expanded in self.paths:
            self.paths.remove(expanded)
            logger.info(f"Removed skill path: {expanded}")
    
    def discover(self) -> List[Skill]:
        discovered = []
        
        for path in self.paths:
            if not path.exists():
                logger.warning(f"Skill path does not exist: {path}")
                continue
            
            for item in path.iterdir():
                if not item.is_dir():
                    continue
                
                skill_file = item / "SKILL.md"
                if not skill_file.exists():
                    continue
                
                try:
                    skill = SkillLoader.load_from_file(skill_file)
                    
                    if skill.name in self.skills:
                        existing = self.skills[skill.name]
                        if skill.mtime > existing.mtime:
                            logger.info(f"Updated skill: {skill.name}")
                            self.skills[skill.name] = skill
                            discovered.append(skill)
                    else:
                        logger.info(f"Discovered skill: {skill.name}")
                        self.skills[skill.name] = skill
                        discovered.append(skill)
                
                except (SkillParseError, SkillNotFoundError) as e:
                    logger.error(f"Failed to load skill from {skill_file}: {e}")
                except Exception as e:
                    logger.error(f"Unexpected error loading skill from {skill_file}: {e}")
        
        self._last_scan = {name: time.time() for name in self.skills}
        return discovered
    
    def refresh(self) -> List[Skill]:
        old_skills = dict(self.skills)
        self.skills.clear()
        self.discover()
        current_names = set(self.skills.keys())
        
        removed = set(old_skills.keys()) - current_names
        for name in removed:
            logger.info(f"Removed skill: {name}")
        
        new_skills = [self.skills[name] for name in current_names if name not in old_skills]
        return new_skills
    
    def load_skill(self, name: str) -> Optional[Skill]:
        if name in self.skills:
            return self.skills[name]
        
        for path in self.paths:
            skill_file = path / name / "SKILL.md"
            if skill_file.exists():
                try:
                    skill = SkillLoader.load_from_file(skill_file)
                    self.skills[name] = skill
                    return skill
                except Exception as e:
                    logger.error(f"Failed to load skill {name}: {e}")
        
        return None
    
    def find(self, name: str) -> Optional[Skill]:
        return self.skills.get(name) or self.load_skill(name)
    
    def search(self, query: str) -> List[Skill]:
        query = query.lower()
        results = []
        
        for skill in self.skills.values():
            if (query in skill.name.lower() or 
                query in skill.description.lower() or
                any(query in str(v).lower() for v in skill.frontmatter.values())):
                results.append(skill)
        
        return results
    
    def get_by_scope(self, scope: str) -> List[Skill]:
        return [s for s in self.skills.values() if s.scope == scope]
    
    def list_skills(self) -> List[Dict]:
        return [skill.to_dict() for skill in self.skills.values()]
    
    def get_skill_names(self) -> Set[str]:
        return set(self.skills.keys())
    
    def check_new_skills(self) -> List[Skill]:
        new_skills = []
        
        for path in self.paths:
            if not path.exists():
                continue
            
            for item in path.iterdir():
                if not item.is_dir():
                    continue
                
                skill_file = item / "SKILL.md"
                if not skill_file.exists():
                    continue
                
                skill_name = item.name
                if skill_name in self.skills:
                    continue
                
                try:
                    skill = SkillLoader.load_from_file(skill_file)
                    self.skills[skill.name] = skill
                    new_skills.append(skill)
                    logger.info(f"Found new skill: {skill.name}")
                except Exception as e:
                    logger.error(f"Failed to load new skill from {skill_file}: {e}")
        
        return new_skills
    
    def on_skill_added(self, callback: Callable[[Skill], None]) -> None:
        self._watch_callbacks.append(callback)
    
    def _notify_callbacks(self, skill: Skill) -> None:
        for callback in self._watch_callbacks:
            try:
                callback(skill)
            except Exception as e:
                logger.error(f"Skill watch callback error: {e}")
    
    def watch(self, interval: int = 30) -> List[Skill]:
        new_skills = self.check_new_skills()
        for skill in new_skills:
            self._notify_callbacks(skill)
        return new_skills
    
    def clear(self) -> None:
        self.skills.clear()
        self._last_scan.clear()
        logger.info("Cleared all skills")
    
    def __len__(self) -> int:
        return len(self.skills)
    
    def __contains__(self, name: str) -> bool:
        return name in self.skills
