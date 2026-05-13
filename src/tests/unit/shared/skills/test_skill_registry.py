import os
import tempfile
from pathlib import Path

import pytest

from src.shared.skills import Skill, SkillLoader, SkillRegistry
from src.shared.skills.loader import SkillParseError, SkillNotFoundError


class TestSkillLoader:
    def test_load_valid_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: test-skill
description: "A test skill"
---

# Test Skill

This is a test skill.
""")
            
            skill = SkillLoader.load_from_file(skill_file)
            
            assert skill.name == "test-skill"
            assert skill.description == "A test skill"
            assert skill.content == "# Test Skill\n\nThis is a test skill."
            assert skill.scope == "user"
    
    def test_load_skill_with_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: project-skill
description: "A project skill"
scope: project
---

# Project Skill
""")
            
            skill = SkillLoader.load_from_file(skill_file)
            assert skill.scope == "project"
    
    def test_load_skill_with_optional_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: full-skill
description: "A full skill"
version: "1.0.0"
author: "test"
category: "test-category"
---

# Full Skill
""")
            
            skill = SkillLoader.load_from_file(skill_file)
            assert skill.frontmatter["version"] == "1.0.0"
            assert skill.frontmatter["author"] == "test"
            assert skill.frontmatter["category"] == "test-category"
    
    def test_load_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "NONEXISTENT.md"
            
            with pytest.raises(SkillNotFoundError):
                SkillLoader.load_from_file(skill_file)
    
    def test_load_invalid_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "wrong-name.md"
            skill_file.write_text("""---
name: test
description: "test"
---
""")
            
            with pytest.raises(SkillParseError):
                SkillLoader.load_from_file(skill_file)
    
    def test_load_missing_required_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: no-description
---

# No Description
""")
            
            with pytest.raises(SkillParseError):
                SkillLoader.load_from_file(skill_file)
    
    def test_load_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("")
            
            with pytest.raises(SkillParseError):
                SkillLoader.load_from_file(skill_file)
    
    def test_load_no_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("# No Frontmatter\n\nJust markdown.")
            
            with pytest.raises(SkillParseError):
                SkillLoader.load_from_file(skill_file)


class TestSkillRegistry:
    def test_empty_registry(self):
        registry = SkillRegistry()
        assert len(registry) == 0
        assert registry.list_skills() == []
    
    def test_discover_single_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "my-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: my-skill
description: "My test skill"
---

# My Skill
""")
            
            registry = SkillRegistry([tmpdir])
            discovered = registry.discover()
            
            assert len(discovered) == 1
            assert discovered[0].name == "my-skill"
            assert len(registry) == 1
    
    def test_discover_multiple_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["skill-a", "skill-b", "skill-c"]:
                skill_dir = Path(tmpdir) / name
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"""---
name: {name}
description: "Skill {name}"
---

# Skill {name}
""")
            
            registry = SkillRegistry([tmpdir])
            discovered = registry.discover()
            
            assert len(discovered) == 3
            assert set(s.name for s in discovered) == {"skill-a", "skill-b", "skill-c"}
    
    def test_discover_ignores_non_skill_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "valid-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: valid-skill
description: "Valid"
---
""")
            
            no_skill_dir = Path(tmpdir) / "not-a-skill"
            no_skill_dir.mkdir()
            
            registry = SkillRegistry([tmpdir])
            discovered = registry.discover()
            
            assert len(discovered) == 1
            assert discovered[0].name == "valid-skill"
    
    def test_find_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "findable"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: findable
description: "Find me"
---
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            found = registry.find("findable")
            assert found is not None
            assert found.name == "findable"
            
            not_found = registry.find("nonexistent")
            assert not_found is None
    
    def test_search_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_data = [
                ("planning-skill", "Use for planning tasks"),
                ("coding-skill", "Use for coding tasks"),
                ("debug-skill", "Use for debugging"),
            ]
            
            for name, desc in skills_data:
                skill_dir = Path(tmpdir) / name
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"""---
name: {name}
description: "{desc}"
---
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            results = registry.search("plan")
            assert len(results) == 1
            assert results[0].name == "planning-skill"
            
            results = registry.search("task")
            assert len(results) == 2
    
    def test_get_by_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            user_dir = Path(tmpdir) / "user-skill"
            user_dir.mkdir()
            (user_dir / "SKILL.md").write_text("""---
name: user-skill
description: "User"
scope: user
---
""")
            
            project_dir = Path(tmpdir) / "project-skill"
            project_dir.mkdir()
            (project_dir / "SKILL.md").write_text("""---
name: project-skill
description: "Project"
scope: project
---
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            user_skills = registry.get_by_scope("user")
            assert len(user_skills) == 1
            assert user_skills[0].name == "user-skill"
            
            project_skills = registry.get_by_scope("project")
            assert len(project_skills) == 1
    
    def test_refresh_finds_new_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "original"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: original
description: "Original"
---
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            assert len(registry) == 1
            
            new_dir = Path(tmpdir) / "new-skill"
            new_dir.mkdir()
            (new_dir / "SKILL.md").write_text("""---
name: new-skill
description: "New"
---
""")
            
            new_skills = registry.refresh()
            assert len(new_skills) == 1
            assert new_skills[0].name == "new-skill"
            assert len(registry) == 2
    
    def test_check_new_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "existing"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: existing
description: "Existing"
---
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            new_dir = Path(tmpdir) / "brand-new"
            new_dir.mkdir()
            (new_dir / "SKILL.md").write_text("""---
name: brand-new
description: "Brand New"
---
""")
            
            new_skills = registry.check_new_skills()
            assert len(new_skills) == 1
            assert new_skills[0].name == "brand-new"
    
    def test_multiple_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            dir1 = Path(tmpdir1) / "skill-1"
            dir1.mkdir()
            (dir1 / "SKILL.md").write_text("""---
name: skill-1
description: "Skill 1"
---
""")
            
            dir2 = Path(tmpdir2) / "skill-2"
            dir2.mkdir()
            (dir2 / "SKILL.md").write_text("""---
name: skill-2
description: "Skill 2"
---
""")
            
            registry = SkillRegistry([tmpdir1, tmpdir2])
            discovered = registry.discover()
            
            assert len(discovered) == 2
            assert set(s.name for s in discovered) == {"skill-1", "skill-2"}
    
    def test_skill_override(self):
        with tempfile.TemporaryDirectory() as tmpdir1, tempfile.TemporaryDirectory() as tmpdir2:
            dir1 = Path(tmpdir1) / "same-skill"
            dir1.mkdir()
            (dir1 / "SKILL.md").write_text("""---
name: same-skill
description: "First version"
---
""")
            
            dir2 = Path(tmpdir2) / "same-skill"
            dir2.mkdir()
            (dir2 / "SKILL.md").write_text("""---
name: same-skill
description: "Second version"
---
""")
            
            registry = SkillRegistry([tmpdir1, tmpdir2])
            registry.discover()
            
            skill = registry.find("same-skill")
            assert skill.description == "Second version"
    
    def test_clear_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "temp-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: temp-skill
description: "Temp"
---
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            assert len(registry) == 1
            
            registry.clear()
            assert len(registry) == 0
    
    def test_contains(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "member"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: member
description: "Member"
---
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            assert "member" in registry
            assert "nonmember" not in registry
    
    def test_skill_to_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = Path(tmpdir) / "dict-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: dict-skill
description: "Dict test"
version: "1.0"
---

# Content
""")
            
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            skill_dict = registry.list_skills()[0]
            assert skill_dict["name"] == "dict-skill"
            assert skill_dict["description"] == "Dict test"
            assert skill_dict["scope"] == "user"
            assert "path" in skill_dict
    
    def test_path_expansion(self):
        home = os.path.expanduser("~")
        registry = SkillRegistry(["~/.test-skills"])
        
        assert len(registry.paths) == 1
        assert str(registry.paths[0]) == os.path.join(home, ".test-skills")
    
    def test_add_remove_path(self):
        registry = SkillRegistry()
        assert len(registry.paths) == 0
        
        registry.add_path("/tmp/test")
        assert len(registry.paths) == 1
        
        registry.remove_path("/tmp/test")
        assert len(registry.paths) == 0
    
    def test_watch_callback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            called_with = []
            
            def callback(skill):
                called_with.append(skill.name)
            
            registry = SkillRegistry([tmpdir])
            registry.on_skill_added(callback)
            
            skill_dir = Path(tmpdir) / "watched"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: watched
description: "Watched"
---
""")
            
            registry.watch()
            
            assert "watched" in called_with
