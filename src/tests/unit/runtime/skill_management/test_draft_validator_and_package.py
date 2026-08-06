"""SkillDraftValidator 与 SkillPackageGenerator 单元测试（P2）。"""

from __future__ import annotations

import pytest

from src.domain.skill.draft_models import (
    SkillDraft,
    SkillDraftSourceType,
    ValidationSeverity,
)
from src.runtime.skill_management.draft_validator import SkillDraftValidator
from src.runtime.skill_management.package_generator import SkillPackageGenerator


def _draft(
    *,
    structured_config: dict | None = None,
    raw_files: dict | None = None,
) -> SkillDraft:
    cfg = structured_config or {
        "basic": {"skill_id": "my_skill", "skill_name": "My Skill"},
        "business_mounting": {
            "business_action": "explain",
            "business_object": "settlement",
            "include_keywords": [],
            "excluded_intents": [],
        },
        "inputs": [],
        "schemas": {},
    }
    return SkillDraft(
        draft_id="d1",
        skill_id="my_skill",
        skill_name="My Skill",
        source_type=SkillDraftSourceType.TEMPLATE,
        structured_config=cfg,
        raw_files=raw_files or {},
        created_by="u",
    )


def _codes(report, severity=None):
    return [
        i.code
        for i in report.issues
        if severity is None or i.severity == severity
    ]


# ── 校验器 ────────────────────────────────────────────────────────


class TestSkillDraftValidator:
    def setup_method(self):
        self.validator = SkillDraftValidator()

    def test_valid_draft_passes(self):
        report = self.validator.validate(_draft())
        assert report.blocking_ok
        assert report.has_blocking is False

    def test_missing_skill_id_blocking(self):
        cfg = {
            "basic": {"skill_name": "X"},
            "business_mounting": {"business_action": "explain", "business_object": "settlement"},
        }
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "MISSING_SKILL_ID" in _codes(report, ValidationSeverity.BLOCKING)

    def test_invalid_business_action_blocking(self):
        cfg = {
            "basic": {"skill_id": "s1", "skill_name": "X"},
            "business_mounting": {"business_action": "bogus", "business_object": "settlement"},
        }
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "INVALID_BUSINESS_ACTION" in _codes(report, ValidationSeverity.BLOCKING)

    def test_invalid_business_object_blocking(self):
        cfg = {
            "basic": {"skill_id": "s1", "skill_name": "X"},
            "business_mounting": {"business_action": "explain", "business_object": "bogus"},
        }
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "INVALID_BUSINESS_OBJECT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_non_whitelisted_pair_is_warning(self):
        # explain + appeal 通常不在白名单
        cfg = {
            "basic": {"skill_id": "s1", "skill_name": "X"},
            "business_mounting": {"business_action": "explain", "business_object": "appeal"},
        }
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "ACTION_OBJECT_PAIR_NOT_WHITELISTED" in _codes(
            report, ValidationSeverity.WARNING
        )
        assert report.blocking_ok  # warning 不阻塞

    def test_invalid_schema_json_blocking(self):
        cfg = {
            "basic": {"skill_id": "s1", "skill_name": "X"},
            "business_mounting": {"business_action": "explain", "business_object": "settlement"},
            "schemas": {"output": "{not valid json"},
        }
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "INVALID_SCHEMA_JSON" in _codes(report, ValidationSeverity.BLOCKING)

    def test_unsafe_python_eval_blocking(self):
        raw = {"scripts/run.py": "result = eval(input())"}
        report = self.validator.validate(_draft(raw_files=raw))
        assert "UNSAFE_SCRIPT_CALL" in _codes(report, ValidationSeverity.BLOCKING)

    def test_unsafe_subprocess_import_blocking(self):
        raw = {"scripts/x.py": "import subprocess\nsubprocess.run(['ls'])"}
        report = self.validator.validate(_draft(raw_files=raw))
        assert "UNSAFE_IMPORT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_safe_python_passes(self):
        raw = {"scripts/calc.py": "def add(a, b):\n    return a + b\n"}
        report = self.validator.validate(_draft(raw_files=raw))
        assert report.blocking_ok

    def test_sensitive_aws_key_blocking(self):
        raw = {"config.yaml": "key: AKIAIOSFODNN7EXAMPLE"}
        report = self.validator.validate(_draft(raw_files=raw))
        assert "SENSITIVE_CONTENT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_sensitive_private_key_blocking(self):
        raw = {"id_rsa": "-----BEGIN RSA PRIVATE KEY-----\nxxxxx"}
        report = self.validator.validate(_draft(raw_files=raw))
        assert "SENSITIVE_CONTENT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_sensitive_id_card_blocking(self):
        raw = {"data.txt": "身份证 110101199003071234"}
        report = self.validator.validate(_draft(raw_files=raw))
        assert "SENSITIVE_CONTENT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_python_syntax_error_blocking(self):
        raw = {"scripts/bad.py": "def (:\n"}
        report = self.validator.validate(_draft(raw_files=raw))
        assert "SCRIPT_SYNTAX_ERROR" in _codes(report, ValidationSeverity.BLOCKING)


# ── 包生成器 ──────────────────────────────────────────────────────


class TestSkillPackageGenerator:
    def setup_method(self):
        self.generator = SkillPackageGenerator()

    def test_generates_core_files(self):
        package = self.generator.generate(_draft())
        paths = set(package.file_paths)
        assert "SKILL.md" in paths
        assert "skill_manifest.yaml" in paths
        assert "config.yaml" in paths

    def test_manifest_contains_business_mounting(self):
        package = self.generator.generate(_draft())
        manifest = package.manifest()
        assert manifest["skill_id"] == "my_skill"
        assert manifest["business_action"] == "explain"
        assert manifest["business_object"] == "settlement"

    def test_includes_schemas_when_configured(self):
        cfg = {
            "basic": {"skill_id": "s1", "skill_name": "X"},
            "business_mounting": {"business_action": "explain", "business_object": "settlement"},
            "schemas": {
                "input": {"type": "object"},
                "output": {"type": "object"},
            },
        }
        package = self.generator.generate(_draft(structured_config=cfg))
        assert "schemas/input.schema.json" in package.file_paths
        assert "schemas/output.schema.json" in package.file_paths

    def test_preserves_user_raw_files(self):
        raw = {"templates/custom.md": "# custom", "references/note.md": "note"}
        package = self.generator.generate(_draft(raw_files=raw))
        assert "templates/custom.md" in package.file_paths
        assert "references/note.md" in package.file_paths

    def test_skill_md_contains_description(self):
        cfg = {
            "basic": {"skill_id": "s1", "skill_name": "My Skill", "description": "这是说明"},
            "business_mounting": {"business_action": "explain", "business_object": "settlement"},
        }
        package = self.generator.generate(_draft(structured_config=cfg))
        assert "这是说明" in package.files["SKILL.md"]
