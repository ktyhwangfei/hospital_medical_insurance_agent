"""
Tests for SkillLoader — 动态扫描 skills/ 目录加载 skill 包。

测试分类：
  ① 发现与加载（discover）
  ② get / get_all
  ③ manifest 字段解析
  ④ 生命周期（rediscover / unload）
  ⑤ 全局单例（get_loader / refresh_loader）
  ⑥ 边界 & 异常

注意：需要 import 的 temp skill 必须使用 importable_skills_dir fixture。
不需要 import 的纯文件扫描场景可直接用 tmpdir。
"""

from pathlib import Path

import pytest
import yaml

from src.skill_infra.skill_loader import SkillLoader, LoadedSkill, get_loader, refresh_loader


# ═══════════════════════════════════════════════════════════════════
# ① 发现与加载（discover）
# ═══════════════════════════════════════════════════════════════════

class TestSkillLoaderDiscovery:
    """discover() 从 skills/ 目录正确扫描并加载 skill。"""

    def test_discover_finds_real_skill(self):
        """能发现真实的 settlement_explain_skill skill。"""
        loader = SkillLoader()
        skills = loader.discover()
        assert "settlement_explain_skill" in skills

    def test_draft_outpatient_pre_refund_skill_is_not_discovered(self):
        loader = SkillLoader()
        loader.discover()

        assert loader.get("outpatient_pre_refund_analysis_skill") is None

    def test_discover_returns_dict_of_loaded_skill(self):
        """返回 dict[str, LoadedSkill] 类型。"""
        loader = SkillLoader()
        skills = loader.discover()
        skill = skills.get("settlement_explain_skill")
        assert isinstance(skill, LoadedSkill)

    def test_discover_returns_non_empty_real_skills(self):
        """真实 skills 目录至少包含一个技能。"""
        loader = SkillLoader()
        skills = loader.discover()
        assert len(skills) >= 1

    def test_discover_skips_dir_without_manifest(self, tmpdir):
        """跳过没有 skill_manifest.yaml 的目录。"""
        (Path(tmpdir) / "no_manifest").mkdir()
        loader = SkillLoader(str(tmpdir))
        skills = loader.discover()
        assert len(skills) == 0

    def test_discover_skips_dir_without_assembler(self, tmpdir):
        """跳过没有 assembler.py 的目录。"""
        skill_dir = Path(tmpdir) / "no_assembler"
        skill_dir.mkdir()
        (skill_dir / "skill_manifest.yaml").write_text(
            yaml.dump({"skill_id": "no_assembler", "skill_name": "test"}), encoding="utf-8"
        )
        loader = SkillLoader(str(tmpdir))
        skills = loader.discover()
        assert len(skills) == 0

    def test_discover_skips_hidden_dirs(self, importable_skills_dir):
        """跳过以 _ 或 . 开头的目录。"""
        skills_pkg, create_skill = importable_skills_dir
        for prefix in ("_private", ".hidden"):
            d = skills_pkg / prefix
            d.mkdir()
            (d / "skill_manifest.yaml").write_text("dummy", encoding="utf-8")
            (d / "assembler.py").write_text("dummy", encoding="utf-8")

        create_skill("visible_skill", intents=["test"])

        loader = SkillLoader(str(skills_pkg))
        skills = loader.discover()
        assert len(skills) == 1
        assert "visible_skill" in skills

    def test_discover_skips_regular_files(self, tmpdir):
        """跳过 skills 目录下的普通文件（仅处理子目录）。"""
        (Path(tmpdir) / "notes.txt").write_text("hello", encoding="utf-8")
        loader = SkillLoader(str(tmpdir))
        skills = loader.discover()
        assert len(skills) == 0

    def test_discover_handles_nonexistent_dir(self):
        """不存在的目录返回空字典。"""
        loader = SkillLoader("/nonexistent/path_for_test_12345")
        skills = loader.discover()
        assert skills == {}

    def test_discover_loads_multiple_skills(self, importable_skills_dir):
        """能同时加载多个有效 skill。"""
        skills_pkg, create_skill = importable_skills_dir
        for sid in ["skill_a", "skill_b", "skill_c"]:
            create_skill(sid, intents=[f"kw_{sid}"])

        loader = SkillLoader(str(skills_pkg))
        skills = loader.discover()
        assert len(skills) == 3
        for sid in ["skill_a", "skill_b", "skill_c"]:
            assert sid in skills


# ═══════════════════════════════════════════════════════════════════
# ② get / get_all
# ═══════════════════════════════════════════════════════════════════

class TestSkillLoaderGetAndGetAll:
    """get() / get_all() / registry 属性。"""

    def test_get_returns_loaded_skill(self):
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert skill is not None
        assert isinstance(skill, LoadedSkill)

    def test_get_returns_none_for_unknown(self):
        loader = SkillLoader()
        loader.discover()
        assert loader.get("nonexistent_skill_xyz") is None

    def test_get_returns_none_before_discover(self):
        """discover() 调用前 get() 返回 None。"""
        loader = SkillLoader()
        assert loader.get("settlement_explain_skill") is None

    def test_get_all_returns_all_skills(self):
        loader = SkillLoader()
        loader.discover()
        all_skills = loader.get_all()
        assert isinstance(all_skills, dict)
        assert "settlement_explain_skill" in all_skills

    def test_get_all_returns_copy(self):
        """get_all() 返回副本，修改不影响内部注册表。"""
        loader = SkillLoader()
        loader.discover()
        all_skills = loader.get_all()
        all_skills.clear()
        assert "settlement_explain_skill" in loader.get_all()

    def test_registry_property(self):
        loader = SkillLoader()
        loader.discover()
        assert isinstance(loader.registry, dict)
        assert "settlement_explain_skill" in loader.registry

    def test_registry_matches_get_all_values(self):
        """registry 与 get_all() 的值一致。"""
        loader = SkillLoader()
        loader.discover()
        assert loader.registry is loader._registry
        assert loader.registry is not loader.get_all()


# ═══════════════════════════════════════════════════════════════════
# ③ manifest 字段解析
# ═══════════════════════════════════════════════════════════════════

class TestSkillLoaderManifestFields:
    """manifest 字段被正确解析到 LoadedSkill。"""

    def test_skill_id_from_manifest(self):
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert skill.skill_id == "settlement_explain_skill"

    def test_skill_name_from_manifest(self):
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert skill.skill_name == "结算解释技能"

    def test_include_keywords_contains_expected(self):
        """包含 统筹自付、起付线、大额自付 等关键意图词。"""
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert "统筹自付" in skill.include_keywords
        assert "起付线" in skill.include_keywords
        assert "大额自付" in skill.include_keywords

    def test_include_keywords_is_list_of_strings(self):
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert isinstance(skill.include_keywords, list)
        assert all(isinstance(kw, str) for kw in skill.include_keywords)

    def test_excluded_intents_route_compare_away(self):
        """settlement_explain_skill 的 excluded_intents 含对比类关键词。

        对比问法（对比/比较/差异等）应路由到 settlement_compare_skill，
        explain skill 命中这些词时受 confidence ×0.3 惩罚。
        """
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert isinstance(skill.excluded_intents, list)
        assert set(skill.excluded_intents) == {"对比", "比较", "差异", "为什么这次", "跟上次"}

    def test_compare_skill_discovered_with_compare_action(self):
        """settlement_compare_skill 被发现，且声明 compare × settlement。"""
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_compare_skill")
        assert skill is not None
        assert skill.business_action == "compare"
        assert skill.business_object == "settlement"
        assert "对比" in skill.include_keywords

    def test_manifest_raw_data_preserved(self):
        """manifest 原始数据完整保留。"""
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert "required_mcp" in skill.manifest
        assert "settlement-data" in skill.manifest["required_mcp"]
        assert "output_schema" in skill.manifest
        assert "required_settlement_fields" in skill.manifest

    def test_assembler_has_expected_methods(self):
        """assembler 含有 execute / build_policy_queries 方法。"""
        loader = SkillLoader()
        loader.discover()
        skill = loader.get("settlement_explain_skill")
        assert hasattr(skill.assembler, "execute")
        assert hasattr(skill.assembler, "build_policy_queries")

    def test_manifest_from_importable_skill(self, importable_skills_dir):
        """importable skill 也能正确解析 manifest 字段。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill(
            "temp_skill",
            skill_name="临时技能",
            intents=["意图A", "意图B"],
            exclusions=["排除X"],
        )

        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        skill = loader.get("temp_skill")
        assert skill.skill_id == "temp_skill"
        assert skill.skill_name == "临时技能"
        assert skill.include_keywords == ["意图A", "意图B"]
        assert skill.excluded_intents == ["排除X"]

    def test_skill_id_falls_back_to_dir_name(self, importable_skills_dir):
        """manifest 中 skill_id 为空时使用目录名。"""
        skills_pkg, create_skill = importable_skills_dir
        skill_dir = skills_pkg / "fallback_skill"
        skill_dir.mkdir()
        manifest = {"skill_name": "fallback", "supported_intents": [], "excluded_intents": []}
        (skill_dir / "skill_manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
        (skill_dir / "assembler.py").write_text("def load():\n    return object()\n")

        loader = SkillLoader(str(skills_pkg))
        skills = loader.discover()
        skill = skills.get("fallback_skill")
        assert skill is not None
        assert skill.skill_id == "fallback_skill"


# ═══════════════════════════════════════════════════════════════════
# ④ 生命周期（rediscover / unload）
# ═══════════════════════════════════════════════════════════════════

class TestSkillLoaderLifecycle:
    """rediscover / unload 等生命周期方法。"""

    def test_rediscover_discovers_new_skills(self, importable_skills_dir):
        """rediscover() 发现新增的 skill。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill("skill_a", intents=["a"])

        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        assert len(loader.get_all()) == 1

        create_skill("skill_b", intents=["b"])

        skills = loader.rediscover()
        assert len(skills) == 2
        assert "skill_a" in skills
        assert "skill_b" in skills

    def test_rediscover_removes_deleted_skills(self, importable_skills_dir):
        """rediscover() 清除已删除的旧 skill。"""
        import shutil
        skills_pkg, create_skill = importable_skills_dir
        create_skill("skill_a", intents=["a"])
        create_skill("skill_b", intents=["b"])

        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        assert len(loader.get_all()) == 2

        shutil.rmtree(str(skills_pkg / "skill_a"))
        skills = loader.rediscover()
        assert len(skills) == 1
        assert "skill_b" in skills
        assert "skill_a" not in skills

    def test_unload_removes_skill(self, importable_skills_dir):
        """unload() 正确移除 skill。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill("removable", intents=["r"])

        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        assert "removable" in loader.get_all()

        result = loader.unload("removable")
        assert result is True
        assert "removable" not in loader.get_all()
        assert len(loader.get_all()) == 0

    def test_unload_returns_false_for_unknown(self):
        loader = SkillLoader()
        result = loader.unload("nonexistent_skill_xyz")
        assert result is False

    def test_discover_called_multiple_times(self, importable_skills_dir):
        """多次 discover() 重新加载最新内容。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill("first", intents=["f"])

        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        assert len(loader.get_all()) == 1

        create_skill("second", intents=["s"])

        loader.discover()
        assert len(loader.get_all()) == 2


# ═══════════════════════════════════════════════════════════════════
# ⑤ 全局单例（get_loader / refresh_loader）
# ═══════════════════════════════════════════════════════════════════

class TestSkillLoaderSingleton:
    """get_loader() / refresh_loader() 全局单例行为。"""

    def test_get_loader_returns_singleton(self, reset_global_loader):
        """连续调用返回同一个实例。"""
        loader1 = get_loader()
        loader2 = get_loader()
        assert loader1 is loader2

    def test_get_loader_discovers_skills(self, reset_global_loader):
        """单例已自动 discover。"""
        loader = get_loader()
        assert len(loader.get_all()) >= 1
        assert "settlement_explain_skill" in loader.get_all()

    def test_refresh_loader_returns_dict(self, reset_global_loader):
        """refresh_loader() 返回 dict[str, LoadedSkill]。"""
        result = refresh_loader()
        assert isinstance(result, dict)
        assert "settlement_explain_skill" in result

    def test_refresh_loader_when_loader_none(self, reset_global_loader):
        """当 _loader 为 None 时，refresh_loader() 创建新实例。"""
        import src.skill_infra.skill_loader as sl_mod
        sl_mod._loader = None
        result = refresh_loader()
        assert isinstance(result, dict)
        assert "settlement_explain_skill" in result

    def test_get_loader_singleton_has_same_skills(self, reset_global_loader):
        """单例多次访问保持一致的 skill 列表。"""
        loader1 = get_loader()
        loader2 = get_loader()
        assert loader1.get_all() == loader2.get_all()


# ═══════════════════════════════════════════════════════════════════
# ⑥ 边界 & 异常
# ═══════════════════════════════════════════════════════════════════

class TestSkillLoaderEdgeCases:
    """边界条件和异常处理。"""

    def test_load_skill_missing_directory(self, tmpdir):
        """指向空目录时 discover 返回空。"""
        empty = Path(tmpdir) / "empty"
        empty.mkdir()
        loader = SkillLoader(str(empty))
        assert loader.discover() == {}

    def test_load_skill_with_invalid_yaml(self, tmpdir):
        """YAML 格式错误时跳过该 skill。"""
        d = Path(tmpdir) / "bad_yaml"
        d.mkdir()
        (d / "skill_manifest.yaml").write_text(": : invalid yaml [[[", encoding="utf-8")
        (d / "assembler.py").write_text("def load():\n    return object()\n")
        loader = SkillLoader(str(tmpdir))
        skills = loader.discover()
        assert "bad_yaml" not in skills

    def test_load_skill_with_broken_assembler(self, importable_skills_dir):
        """assembler 导入失败时跳过该 skill 不影响其他 skill。"""
        skills_pkg, create_skill = importable_skills_dir

        broken_dir = skills_pkg / "broken"
        broken_dir.mkdir()
        (broken_dir / "skill_manifest.yaml").write_text(
            yaml.dump({"skill_id": "broken", "skill_name": "B", "supported_intents": [], "excluded_intents": []}),
            encoding="utf-8",
        )
        (broken_dir / "assembler.py").write_text("import does_not_exist_xyz\n\ndef load():\n    return object()\n")

        create_skill("good", intents=["good"])

        loader = SkillLoader(str(skills_pkg))
        skills = loader.discover()
        assert "broken" not in skills
        assert "good" in skills

    def test_loaded_skill_dataclass_defaults(self):
        """LoadedSkill 默认字段正确。"""
        skill = LoadedSkill(
            skill_id="test",
            skill_name="Test",
            assembler=object(),
        )
        assert skill.manifest == {}
        assert skill.include_keywords == []
        assert skill.excluded_intents == []

    def test_loaded_skill_custom_values(self):
        """LoadedSkill 自定义字段正确。"""
        obj = object()
        skill = LoadedSkill(
            skill_id="custom",
            skill_name="Custom",
            assembler=obj,
            manifest={"key": "val"},
            include_keywords=["kw1"],
            excluded_intents=["exc1"],
        )
        assert skill.skill_id == "custom"
        assert skill.skill_name == "Custom"
        assert skill.assembler is obj
        assert skill.manifest == {"key": "val"}
        assert skill.include_keywords == ["kw1"]
        assert skill.excluded_intents == ["exc1"]

    def test_constructor_with_custom_skills_dir(self, importable_skills_dir):
        """SkillLoader 使用自定义目录。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill("my_skill", intents=["test"])

        loader = SkillLoader(str(skills_pkg))
        loader.discover()
        assert "my_skill" in loader.get_all()


# ═══════════════════════════════════════════════════════════════════
# ⑦ needed_objects 兼容性
# ═══════════════════════════════════════════════════════════════════

class TestNeededObjectsCompatibility:
    def test_parse_needed_objects_from_manifest(self, importable_skills_dir):
        """解析 manifest 中的 needed_objects 字段。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill(
            "test_skill",
            intents=["test"],
            extra_manifest={
                "business_action": "explain",
                "business_object": "settlement",
                "needed_objects": [
                    {"object_code": "Settlement", "metrics": ["deductible", "fund_pay"], "importance": "core"},
                    {"object_code": "Institution", "metrics": ["level"], "importance": "optional"},
                ],
            },
        )

        loader = SkillLoader(skills_dir=str(skills_pkg))
        loader.discover()
        skill = loader.get("test_skill")
        assert skill is not None
        assert hasattr(skill, "needed_objects")
        assert len(skill.needed_objects) == 2
        assert skill.needed_objects[0]["object_code"] == "Settlement"
        assert skill.needed_objects[0]["metrics"] == ["deductible", "fund_pay"]

    def test_backward_compatible_no_needed_objects(self, importable_skills_dir):
        """没有 needed_objects 时默认为空列表（向后兼容）。"""
        skills_pkg, create_skill = importable_skills_dir
        create_skill(
            "old_skill",
            skill_name="Old Skill",
            intents=["test"],
            extra_manifest={
                "business_action": "explain",
                "business_object": "settlement",
                "required_settlement_fields": ["deductible"],
            },
        )

        loader = SkillLoader(skills_dir=str(skills_pkg))
        loader.discover()
        skill = loader.get("old_skill")
        assert skill is not None
        assert skill.needed_objects == []
