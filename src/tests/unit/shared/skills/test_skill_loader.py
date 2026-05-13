import os
import tempfile
from pathlib import Path

import pytest

from src.shared.skills import SkillLoader
from src.shared.skills.loader import SkillParseError


class TestSkillLoaderEdgeCases:
    def test_skill_with_complex_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: complex-skill
description: "A complex skill with special chars"
scope: project
version: "2.1.0"
author: "Test Author"
tags:
  - tag1
  - tag2
metadata:
  key: value
  nested:
    child: data
---

# Complex Skill

Content with **markdown** and `code`.

## Section

More content.
""")
            
            skill = SkillLoader.load_from_file(skill_file)
            assert skill.name == "complex-skill"
            assert skill.frontmatter["tags"] == ["tag1", "tag2"]
            assert skill.frontmatter["metadata"]["nested"]["child"] == "data"
    
    def test_skill_with_code_blocks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: code-skill
description: "Skill with code"
---

# Code Skill

```python
def hello():
    return "world"
```

Some text.

```yaml
key: value
```
""")
            
            skill = SkillLoader.load_from_file(skill_file)
            assert "```python" in skill.content
            assert "```yaml" in skill.content
    
    def test_skill_with_horizontal_rules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: rule-skill
description: "Skill with rules"
---

# Rule Skill

Section 1

---

Section 2

---

Section 3
""")
            
            skill = SkillLoader.load_from_file(skill_file)
            assert "---" in skill.content
            assert skill.content.count("---") == 2
    
    def test_empty_description(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: empty-desc
description: ""
---

# Empty
""")
            
            with pytest.raises(SkillParseError):
                SkillLoader.load_from_file(skill_file)
    
    def test_unicode_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: unicode-skill
description: "Unicode: 中文测试 🎉"
---

# Unicode Skill

中文内容

Emoji: 🚀 💻
""", encoding="utf-8")
            
            skill = SkillLoader.load_from_file(skill_file)
            assert skill.description == "Unicode: 中文测试 🎉"
            assert "中文内容" in skill.content
    
    def test_frontmatter_with_different_types(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = Path(tmpdir) / "SKILL.md"
            skill_file.write_text("""---
name: typed-skill
description: "Typed skill"
enabled: true
count: 42
ratio: 3.14
items:
  - one
  - two
config:
  nested: value
---

# Typed
""")
            
            skill = SkillLoader.load_from_file(skill_file)
            assert skill.frontmatter["enabled"] is True
            assert skill.frontmatter["count"] == 42
            assert skill.frontmatter["ratio"] == 3.14
            assert skill.frontmatter["items"] == ["one", "two"]
