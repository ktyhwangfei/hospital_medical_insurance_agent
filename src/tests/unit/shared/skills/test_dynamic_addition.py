import os
import tempfile
from pathlib import Path

import pytest

from src.shared.skills import SkillRegistry


class TestSkillRegistryDynamicAddition:
    def test_dynamic_addition_by_creating_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = SkillRegistry([tmpdir])
            registry.discover()
            assert len(registry) == 0
            
            new_skill_dir = Path(tmpdir) / "dynamic-skill"
            new_skill_dir.mkdir()
            (new_skill_dir / "SKILL.md").write_text("""---
name: dynamic-skill
description: "Dynamically added"
---

# Dynamic
""")
            
            new_skills = registry.check_new_skills()
            assert len(new_skills) == 1
            assert new_skills[0].name == "dynamic-skill"
            assert len(registry) == 1
    
    def test_dynamic_addition_multiple(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            for i in range(3):
                skill_dir = Path(tmpdir) / f"batch-skill-{i}"
                skill_dir.mkdir()
                (skill_dir / "SKILL.md").write_text(f"""---
name: batch-skill-{i}
description: "Batch skill {i}"
---
""")
            
            new_skills = registry.check_new_skills()
            assert len(new_skills) == 3
    
    def test_dynamic_addition_with_refresh(self):
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
            assert len(registry) == 1
            
            new_dir = Path(tmpdir) / "added-later"
            new_dir.mkdir()
            (new_dir / "SKILL.md").write_text("""---
name: added-later
description: "Added later"
---
""")
            
            refreshed = registry.refresh()
            assert len(refreshed) == 1
            assert refreshed[0].name == "added-later"
            assert len(registry) == 2
    
    def test_watch_method(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = SkillRegistry([tmpdir])
            registry.discover()
            
            callbacks_received = []
            
            def on_add(skill):
                callbacks_received.append(skill.name)
            
            registry.on_skill_added(on_add)
            
            skill_dir = Path(tmpdir) / "watched-skill"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text("""---
name: watched-skill
description: "Watched"
---
""")
            
            registry.watch()
            
            assert "watched-skill" in callbacks_received
    
    def test_add_path_dynamically(self):
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
            
            registry = SkillRegistry([tmpdir1])
            registry.discover()
            assert len(registry) == 1
            
            registry.add_path(tmpdir2)
            registry.discover()
            assert len(registry) == 2
    
    def test_remove_path(self):
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
            registry.discover()
            assert len(registry) == 2
            
            registry.remove_path(tmpdir1)
            registry.refresh()
            assert len(registry) == 1
            assert "skill-2" in registry
    
    def test_simulate_filesystem_workflow(self):
        with tempfile.TemporaryDirectory() as skills_dir:
            os.makedirs(os.path.join(skills_dir, "writing-plans"))
            with open(os.path.join(skills_dir, "writing-plans", "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("""---
name: writing-plans
description: "Use when you have a spec or requirements for a multi-step task, before touching code"
---

# Writing Plans

## Overview

Write comprehensive implementation plans...
""")
            
            os.makedirs(os.path.join(skills_dir, "brainstorming"))
            with open(os.path.join(skills_dir, "brainstorming", "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("""---
name: brainstorming
description: "You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior"
---

# Brainstorming

## Overview

Help turn ideas into fully formed designs...
""")
            
            registry = SkillRegistry([skills_dir])
            discovered = registry.discover()
            
            assert len(discovered) == 2
            
            writing = registry.find("writing-plans")
            assert writing is not None
            assert "multi-step task" in writing.description
            
            brain = registry.find("brainstorming")
            assert brain is not None
            assert "creative work" in brain.description
            
            os.makedirs(os.path.join(skills_dir, "new-dynamic-skill"))
            with open(os.path.join(skills_dir, "new-dynamic-skill", "SKILL.md"), "w", encoding="utf-8") as f:
                f.write("""---
name: new-dynamic-skill
description: "A dynamically added skill"
---

# New Dynamic Skill

This was added after initial discovery.
""")
            
            new_skills = registry.check_new_skills()
            assert len(new_skills) == 1
            assert new_skills[0].name == "new-dynamic-skill"
            assert len(registry) == 3
