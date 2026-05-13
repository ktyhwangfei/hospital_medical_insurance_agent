---
name: ultrawork-skill-manager
description: "Manage skills in a filesystem-based registry. Skills are stored as Markdown files with YAML frontmatter. Adding a skill is as simple as creating a folder with a SKILL.md file."
---

# Ultrawork Skill Manager

## Overview

Filesystem-based skill registry that treats skills as Markdown documents with YAML frontmatter. No database, no complex registration — just folders and files.

**Core principle:** A skill is a folder containing `SKILL.md` with YAML frontmatter metadata.

## Skill Format

### File Structure

```
skills/                          # Skill root directory
├── skill-name/                  # Skill folder (kebab-case)
│   ├── SKILL.md                 # Required: Skill definition with frontmatter
│   └── ...                      # Optional: Additional resources
└── another-skill/
    ├── SKILL.md
    └── templates/
        └── template.html
```

### SKILL.md Format

```markdown
---
name: skill-name                 # Unique identifier (kebab-case)
description: "When to use this skill"  # Trigger description for agent
scope: user                      # Optional: user | project | builtin
---

# Skill Title

## Overview

Skill content in Markdown...

## When to Use

Decision criteria...

## The Pattern

Implementation details...
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique skill identifier (kebab-case) |
| `description` | Yes | When/how to use this skill |
| `scope` | No | `user` (default), `project`, or `builtin` |
| `version` | No | Semantic version string |
| `author` | No | Author identifier |

## API

### Skill Discovery

```python
from src.shared.skills import SkillRegistry

# Initialize registry with search paths
registry = SkillRegistry([
    "~/.ulw/skills",           # User skills
    "./skills",                 # Project skills
    "~/.config/opencode/skills" # System skills
])

# Scan all paths for skills
registry.discover()

# List all available skills
skills = registry.list_skills()
# [{"name": "writing-plans", "description": "...", "path": "..."}]
```

### Skill Loading

```python
# Load a specific skill
skill = registry.load_skill("writing-plans")
# Returns: Skill object with metadata + content

# Access skill data
print(skill.name)           # "writing-plans"
print(skill.description)    # "Use when you have a spec..."
print(skill.content)        # Full markdown content (without frontmatter)
print(skill.frontmatter)    # Dict of YAML frontmatter
```

### Dynamic Addition

```python
# Method 1: Watch mode (auto-detect new skills)
registry.watch(interval=30)  # Scan every 30 seconds

# Method 2: Manual refresh
registry.refresh()  # Re-scan all paths

# Method 3: Add skill path dynamically
registry.add_path("/path/to/new/skills")
registry.discover()  # Discover skills in new path
```

### Skill Resolution

```python
# Find skill by name (searches all scopes)
skill = registry.find("writing-plans")

# Find by partial match
skills = registry.search("plan")

# Get skills by scope
user_skills = registry.get_by_scope("user")
project_skills = registry.get_by_scope("project")
```

## Directory Watching

The registry supports filesystem watching for automatic skill detection:

```python
# Enable watching
registry.enable_watching()

# Check for new skills
new_skills = registry.check_new_skills()

# Event-based (if watchdog available)
registry.watch_async(callback=on_skill_added)
```

## Implementation Details

### Skill Class

```python
@dataclass
class Skill:
    name: str
    description: str
    path: Path
    frontmatter: Dict[str, Any]
    content: str
    scope: str = "user"
    mtime: float = 0
```

### Registry Class

```python
class SkillRegistry:
    def __init__(self, paths: List[str] = None):
        self.paths = paths or []
        self.skills: Dict[str, Skill] = {}
        self._watcher = None
    
    def discover(self) -> List[Skill]:
        """Scan all paths and load valid skills."""
        
    def load_skill(self, name: str) -> Optional[Skill]:
        """Load skill by name."""
        
    def refresh(self) -> List[Skill]:
        """Re-scan and return newly discovered skills."""
```

## Adding a New Skill

### Step 1: Create Skill Directory

```bash
mkdir -p skills/my-new-skill
touch skills/my-new-skill/SKILL.md
```

### Step 2: Write SKILL.md

```markdown
---
name: my-new-skill
description: "Use when you need to perform X operation"
---

# My New Skill

## Overview

What this skill does...

## When to Use

Trigger conditions...

## How to Use

Implementation steps...
```

### Step 3: Discover

```python
registry.refresh()  # New skill automatically available
```

## Conventions

- **Naming:** Use kebab-case for skill names and directories
- **Descriptions:** Start with "Use when..." or action verb
- **Scopes:** 
  - `user`: Personal skills in `~/.ulw/skills/`
  - `project`: Project-specific skills in `./skills/`
  - `builtin`: System skills in `~/.config/opencode/skills/`
- **No duplicates:** Same name in multiple paths — last one wins
- **Hot reload:** Modify SKILL.md and refresh to update

## Error Handling

- Missing `SKILL.md` → Skip directory with warning
- Invalid frontmatter → Log error, skip skill
- Duplicate names → Override with latest path (warn)
- Missing required fields → Skip with error message

## Example: Complete Workflow

```python
from src.shared.skills import SkillRegistry

# 1. Initialize
registry = SkillRegistry([
    "~/.ulw/skills",
    "./skills"
])

# 2. Discover all skills
registry.discover()
print(f"Loaded {len(registry.skills)} skills")

# 3. Use a skill
skill = registry.find("writing-plans")
if skill:
    print(f"Using skill: {skill.description}")
    # Follow skill instructions...

# 4. Add new skill dynamically
# (User creates new folder with SKILL.md)
new_skills = registry.refresh()
print(f"Discovered {len(new_skills)} new skills")
```
