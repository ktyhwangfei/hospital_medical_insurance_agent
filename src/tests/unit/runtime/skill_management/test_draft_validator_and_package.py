"""SkillDraftValidator 与 SkillPackageGenerator 单元测试（P2）。"""

from __future__ import annotations

import json

import pytest

from src.domain.skill.draft_models import (
    SkillDraft,
    SkillDraftSourceType,
    SkillDraftStatus,
    ValidationSeverity,
)
from src.runtime.skill_management.draft_validator import SkillDraftValidator
from src.runtime.skill_management.package_generator import SkillPackageGenerator


def _draft(
    *,
    structured_config: dict | None = None,
    raw_files: dict | None = None,
    source_type: SkillDraftSourceType = SkillDraftSourceType.TEMPLATE,
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
        source_type=source_type,
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


def _generation_meta(**overrides: object) -> str:
    payload: dict[str, object] = {
        "generation_id": "gen_abcdef123456_unit",
        "proposal_hash": "a" * 64,
        "provenance": {
            "model_type": "test-model",
            "scene": "skill_authoring",
            "prompt_version": "skill-authoring-v1",
            "metric_versions": [],
            "generated_at": "2026-08-10T00:00:00Z",
            "content_hash": "b" * 64,
        },
        "citations": [
            {
                "source_type": "metric_registry",
                "source_id": "settlement.total_amount@3",
                "summary": "已发布指标快照",
            }
        ],
        "uncertainties": ["政策适用范围需人工确认"],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


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

    def test_ai_generated_draft_appends_blocking_ai_security_issues(self):
        report = self.validator.validate(
            _draft(
                raw_files={
                    "assembler.py": "import socket\n",
                    "__generation_meta__.json": _generation_meta(),
                },
                source_type=SkillDraftSourceType.AI_GENERATED,
            )
        )

        assert "AI_IMPORT_FORBIDDEN" in _codes(
            report, ValidationSeverity.BLOCKING
        )
        assert report.blocking_ok is False

    def test_ai_generated_safe_draft_passes_ai_security_gate(self):
        report = self.validator.validate(
            _draft(
                raw_files={
                    "assembler.py": "def load(config):\n    return config\n",
                    "prompt_template.yaml": "system: explain with citations\n",
                    "__generation_meta__.json": _generation_meta(),
                },
                source_type=SkillDraftSourceType.AI_GENERATED,
            )
        )

        assert report.blocking_ok

    def test_ai_generated_strict_generation_metadata_is_not_model_scanned(self):
        report = self.validator.validate(
            _draft(
                raw_files={
                    "assembler.py": "def load(config):\n    return config\n",
                    "prompt_template.yaml": "system: explain with citations\n",
                    "__generation_meta__.json": _generation_meta(),
                },
                source_type=SkillDraftSourceType.AI_GENERATED,
            )
        )

        assert report.blocking_ok
        assert "AI_FILE_PATH_FORBIDDEN" not in _codes(report)

    def test_ai_generated_draft_requires_generation_metadata(self):
        report = self.validator.validate(
            _draft(
                raw_files={
                    "assembler.py": "def load(config):\n    return config\n",
                    "prompt_template.yaml": "system: explain with citations\n",
                },
                source_type=SkillDraftSourceType.AI_GENERATED,
            )
        )

        assert "AI_GENERATION_META_REQUIRED" in _codes(
            report, ValidationSeverity.BLOCKING
        )
        assert report.blocking_ok is False

    @pytest.mark.parametrize(
        ("internal_files", "expected_code"),
        [
            ({"__unexpected__.json": "{}"}, "AI_RESERVED_FILE_FORBIDDEN"),
            ({"__generation_meta__.json": "not-json"}, "AI_GENERATION_META_INVALID"),
            ({"__generation_meta__.json": "[]"}, "AI_GENERATION_META_INVALID"),
            ({"__generation_meta__.json": "{}"}, "AI_GENERATION_META_INVALID"),
            (
                {
                    "__generation_meta__.json": _generation_meta(
                        uncertainties=["患者身份证号 110101199003071234"]
                    )
                },
                "AI_GENERATION_META_SENSITIVE",
            ),
            (
                {
                    "__generation_meta__.json": _generation_meta(
                        uncertainties=["api_key=secret-value"]
                    )
                },
                "AI_GENERATION_META_SENSITIVE",
            ),
        ],
    )
    def test_ai_generated_internal_files_are_strictly_validated(
        self,
        internal_files: dict[str, str],
        expected_code: str,
    ) -> None:
        report = self.validator.validate(
            _draft(
                raw_files={
                    "assembler.py": "def load(config):\n    return config\n",
                    "prompt_template.yaml": "system: explain with citations\n",
                    "__generation_meta__.json": _generation_meta(),
                    **internal_files,
                },
                source_type=SkillDraftSourceType.AI_GENERATED,
            )
        )

        assert expected_code in _codes(report, ValidationSeverity.BLOCKING)
        assert report.blocking_ok is False

    @pytest.mark.parametrize(
        "raw_files, expected_code",
        [
            (
                {"assembler.py": "def load(:\n    pass\n"},
                "AI_PYTHON_SYNTAX_ERROR",
            ),
            (
                {"prompt_template.yaml": "patient: 110101199003071234\n"},
                "AI_SENSITIVE_CONTENT",
            ),
            (
                {"prompt_template.yaml": "api_key: AKIAIOSFODNN7EXAMPLE\n"},
                "AI_SENSITIVE_CONTENT",
            ),
            (
                {
                    "assembler.py": (
                        "def load(config):\n    return open('secret.txt')\n"
                    )
                },
                "AI_CALL_FORBIDDEN",
            ),
        ],
    )
    def test_ai_generated_draft_uses_only_integrated_security_gate(
        self,
        raw_files: dict[str, str],
        expected_code: str,
    ) -> None:
        draft = _draft(
            raw_files={
                **raw_files,
                "__generation_meta__.json": _generation_meta(),
            },
            source_type=SkillDraftSourceType.AI_GENERATED,
        )

        report = self.validator.validate(draft)

        assert _codes(report, ValidationSeverity.BLOCKING) == [expected_code]
        assert report.blocking_ok is False
        assert draft.status == SkillDraftStatus.EDITING

    @pytest.mark.parametrize(
        "source_type",
        [
            SkillDraftSourceType.TEMPLATE,
            SkillDraftSourceType.IMPORT,
            SkillDraftSourceType.COPY,
        ],
    )
    def test_non_ai_drafts_keep_legacy_security_codes(
        self,
        source_type: SkillDraftSourceType,
    ) -> None:
        report = self.validator.validate(
            _draft(
                raw_files={"scripts/bad.py": "def load(:\n    pass\n"},
                source_type=source_type,
            )
        )

        assert _codes(report, ValidationSeverity.BLOCKING) == ["SCRIPT_SYNTAX_ERROR"]

    def test_template_draft_does_not_apply_ai_file_whitelist(self):
        report = self.validator.validate(
            _draft(raw_files={"templates/custom.md": "# custom"})
        )

        assert "AI_FILE_PATH_FORBIDDEN" not in _codes(report)
        assert report.blocking_ok


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
