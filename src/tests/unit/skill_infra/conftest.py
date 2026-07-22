"""
conftest — skill_infra 单元测试共享 fixtures.

提供：
1. importable_skills_dir: 创建可被 import 的 temp skills/ 包结构
2. reset_global_loader: 重置全局 _loader 单例
3. fresh_loader: 重置单例 + 返回真实技能 dir 的 Loader
"""

import sys
from pathlib import Path

import pytest
import yaml

import src.skill_infra.skill_loader as sl_mod

# ---------------------------------------------------------------------------
# 辅助常量
# ---------------------------------------------------------------------------

MINIMAL_ASSEMBLER = """
def load():
    class _TestAssembler:
        def execute(self, *args, **kwargs):
            return {"status": "ok"}
        def build_policy_queries(self, *args, **kwargs):
            return []
    return _TestAssembler()
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_global_loader():
    """重置全局 SkillLoader 单例状态（测试前后各一次）。"""
    saved = sl_mod._loader
    sl_mod._loader = None
    yield
    sl_mod._loader = saved


@pytest.fixture
def fresh_loader(reset_global_loader):
    """返回一个使用默认 SKILLS_DIR 的 SkillLoader（已 discover）。

    同时将 _loader 设为全局单例，使 route_question 等函数可用。
    """
    loader = sl_mod.SkillLoader()
    loader.discover()
    sl_mod._loader = loader
    return loader


# ---------------------------------------------------------------------------
# importable_skills_dir — 创建可被 importlib 加载的 temp skills 包
#
# SkillLoader._load_skill() 使用 importlib.import_module("skills.{name}.assembler")
# 所以 temp skills 必须放在一个 importable 的 skills package 里。
# 此 fixture 负责：
#   1. 在 tmpdir 下创建 skills/__init__.py 包
#   2. 临时将 tmpdir 加入 sys.path（在最前面，shadow 真实 skills）
#   3. 从 sys.modules 移除已加载的真实 skills 模块
#   4. 测试结束后恢复 sys.path 和 sys.modules
# ---------------------------------------------------------------------------

@pytest.fixture
def importable_skills_dir(tmpdir):
    """
    创建 importable 的临时 skills 包目录。

    Yields 一个工厂函数 create_skill()，用法：
        create_skill("my_skill", intents=["kw1"], exclusions=["exc1"])
    """

    # ── 1. 创建 skills 包结构 ──
    skills_pkg = Path(tmpdir) / "skills"
    skills_pkg.mkdir()
    (skills_pkg / "__init__.py").write_text("")

    created_skills: list[str] = []

    def create_skill(
        skill_id: str,
        skill_name: str | None = None,
        intents: list[str] | None = None,
        exclusions: list[str] | None = None,
        extra_manifest: dict | None = None,
    ) -> Path:
        """在临时 skills 包中创建一个 skill。"""
        if skill_name is None:
            skill_name = f"测试{skill_id}"
        if intents is None:
            intents = ["统筹自付", "起付线", "大额自付"]
        if exclusions is None:
            exclusions = []

        skill_dir = skills_pkg / skill_id
        skill_dir.mkdir()

        manifest = {
            "skill_id": skill_id,
            "skill_name": skill_name,
            "version": "1.0.0",
            "supported_intents": intents,
            "excluded_intents": exclusions,
        }
        if extra_manifest:
            manifest.update(extra_manifest)

        (skill_dir / "skill_manifest.yaml").write_text(
            yaml.dump(manifest, allow_unicode=True), encoding="utf-8"
        )
        (skill_dir / "assembler.py").write_text(MINIMAL_ASSEMBLER)
        created_skills.append(skill_id)
        return skill_dir

    # ── 2. 备份当前状态 ──
    original_path = sys.path.copy()

    saved_modules: dict[str, object] = {}
    for mod_name in list(sys.modules.keys()):
        if mod_name == "skills" or mod_name.startswith("skills."):
            saved_modules[mod_name] = sys.modules.pop(mod_name)

    # ── 3. 将 tmpdir 插入 sys.path 最前面 ──
    sys.path.insert(0, str(tmpdir))

    yield skills_pkg, create_skill

    # ── 4. 清理 ──
    # 移除所有临时 skills 模块
    for mod_name in list(sys.modules.keys()):
        if mod_name == "skills" or mod_name.startswith("skills."):
            # 只移除这次创建的
            del sys.modules[mod_name]

    # 恢复原来的 path
    sys.path = original_path

    # 恢复原来的模块
    sys.modules.update(saved_modules)

    # 重置全局 loader
    sl_mod._loader = None
