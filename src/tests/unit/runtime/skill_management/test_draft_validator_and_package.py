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

    def test_manifest_preserves_description_and_execution_contract(self):
        contract = {
            "version": 2,
            "common": {
                "context_inputs": [],
                "metric_inputs": [{"metric_code": "settlement.total_amount"}],
            },
            "profiles": [
                {
                    "profile_id": "deductible-explanation",
                    "name": "起付线解释",
                    "metric_inputs": [{"metric_code": "settlement.deductible"}],
                }
            ],
        }
        cfg = {
            "basic": {
                "skill_id": "my_skill",
                "skill_name": "My Skill",
                "description": "解释医保结算费用构成",
            },
            "business_mounting": {
                "business_action": "explain",
                "business_object": "settlement",
            },
            "execution_contract": contract,
        }

        manifest = self.generator.generate(
            _draft(structured_config=cfg)
        ).manifest()

        assert manifest["description"] == "解释医保结算费用构成"
        assert manifest["execution_contract"] == contract

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
        raw = {
            "SKILL.md": "# edited skill",
            "templates/custom.md": "# custom",
            "references/note.md": "note",
        }
        package = self.generator.generate(_draft(raw_files=raw))
        assert package.files["SKILL.md"] == "# edited skill"
        assert "templates/custom.md" in package.file_paths
        assert "references/note.md" in package.file_paths

    def test_skill_md_contains_description(self):
        cfg = {
            "basic": {"skill_id": "s1", "skill_name": "My Skill", "description": "这是说明"},
            "business_mounting": {"business_action": "explain", "business_object": "settlement"},
        }
        package = self.generator.generate(_draft(structured_config=cfg))
        assert "这是说明" in package.files["SKILL.md"]


# ── 执行契约校验（Skill Execution Contract，设计 §54）─────────────

from types import SimpleNamespace  # noqa: E402

from src.runtime.skill_management.skill_input_service import (  # noqa: E402
    SkillInputService,
)


def _ec_metric(code="zydyxx.bcqfje", **kw):
    """构造一个 runtime_resolvable 的执行契约 metric input。"""
    node = {"metric_code": code}
    node.update(kw)
    return node


def _fake_registry_for_contract():
    """复刻 test_skill_input_service 的 FakeRegistry 子集。"""
    def _metric(code, *, status="published", adapter="InsuranceInterfacePort",
                field="t.col", default=None):
        return SimpleNamespace(
            metric_code=code, object_code="zydyxx", name=code, definition="d",
            status=status, source_adapter_port=adapter, source_field=field,
            default_value=default, importance="core", quality_score=0.9,
            usage_count=1, unit=None, semantic_type="Amount",
        )

    class _Reg:
        def __init__(self):
            self._metrics = {
                "zydyxx.bcqfje": _metric("zydyxx.bcqfje"),
                "zydyxx.constant": _metric("zydyxx.constant", adapter=None, field=None, default="X"),
                "zydyxx.draft": _metric("zydyxx.draft", status="draft"),
                "zydyxx.noimpl": _metric("zydyxx.noimpl", adapter=None, field=None, default=None),
            }
            self._objects = {"zydyxx": SimpleNamespace(
                object_code="zydyxx", domain_code="settle", name="住院待遇",
                definition="d", status="published", current_version="1",
            )}

        def get_metric(self, code):
            return self._metrics.get(code)

        def get_object(self, code):
            return self._objects.get(code)

    return _Reg()


def _contract_cfg(**ec_overrides) -> dict:
    """构造含 execution_contract 的 structured_config。"""
    ec = {
        "version": 2,
        "common": {
            "context_inputs": [
                {"code": "settlement_id", "alias": "结算标识", "purpose": "定位结算"},
            ],
            "metric_inputs": [],
        },
        "profiles": [
            {
                "profile_id": "deductible-explanation",
                "name": "起付线解释",
                "purpose": "解释起付金额",
                "routing_hints": ["起付线", "门槛费"],
                "context_inputs": [],
                "metric_inputs": [
                    {"metric_code": "zydyxx.bcqfje", "required": True},
                ],
            }
        ],
    }
    ec.update(ec_overrides)
    return {
        "basic": {"skill_id": "my_skill", "skill_name": "My Skill"},
        "business_mounting": {
            "business_action": "explain", "business_object": "settlement",
            "include_keywords": [], "excluded_intents": [],
        },
        "inputs": [],
        "schemas": {},
        "execution_contract": ec,
    }


class TestExecutionContractValidation:
    """执行契约校验门禁（§54.1-54.6）。"""

    def setup_method(self):
        self.validator_plain = SkillDraftValidator()
        self.validator = SkillDraftValidator(
            SkillInputService(_fake_registry_for_contract())
        )

    def test_no_execution_contract_skips(self):
        # §64 无 execution_contract 时完全跳过（旧 Skill 兼容）
        report = self.validator.validate(_draft())
        assert "INVALID_EXECUTION_CONTRACT" not in _codes(report)
        assert report.blocking_ok

    def test_valid_contract_passes(self):
        report = self.validator.validate(_draft(structured_config=_contract_cfg()))
        ec_codes = [c for c in _codes(report) if "METRIC" in c or "PROFILE" in c
                    or "CONTRACT" in c or "REDECLARED" in c or "DUPLICATE_METRIC" in c]
        assert ec_codes == []
        assert report.blocking_ok

    def test_unsupported_version_blocking(self):
        # §54.1 非支持版本
        cfg = _contract_cfg(version=1)
        report = self.validator.validate(_draft(structured_config=cfg))
        # version=1 会触发 UNSUPPORTED_CONTRACT_VERSION（或解析失败）
        assert not report.blocking_ok

    def test_invalid_contract_structure_blocking(self):
        cfg = _contract_cfg()
        cfg["execution_contract"] = {"version": 2, "profiles": "not_a_list"}
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "INVALID_EXECUTION_CONTRACT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_profile_id_duplicate_blocking(self):
        cfg = _contract_cfg(
            profiles=[
                {"profile_id": "dup", "name": "A", "metric_inputs": []},
                {"profile_id": "dup", "name": "B", "metric_inputs": []},
            ],
            common={"context_inputs": [], "metric_inputs": []},
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "PROFILE_ID_DUPLICATE" in _codes(report, ValidationSeverity.BLOCKING)

    def test_profile_id_invalid_kebab_case_blocking(self):
        # profile_id 非 kebab-case → 模型解析失败 → INVALID_EXECUTION_CONTRACT
        cfg = _contract_cfg(
            profiles=[{"profile_id": "Bad_Case", "name": "A", "metric_inputs": []}],
            common={"context_inputs": [], "metric_inputs": []},
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "INVALID_EXECUTION_CONTRACT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_duplicate_metric_in_profile_blocking(self):
        cfg = _contract_cfg(
            profiles=[
                {
                    "profile_id": "p1", "name": "A", "metric_inputs": [
                        {"metric_code": "zydyxx.bcqfje"},
                        {"metric_code": "zydyxx.bcqfje"},
                    ],
                }
            ],
            common={"context_inputs": [], "metric_inputs": []},
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "DUPLICATE_METRIC_INPUT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_common_metric_redeclared_in_profile_blocking(self):
        # §54.5 Common 已声明的 metric，Profile 不重复声明
        cfg = _contract_cfg(
            common={"context_inputs": [], "metric_inputs": [
                {"metric_code": "zydyxx.bcqfje"},
            ]},
            profiles=[
                {"profile_id": "p1", "name": "A", "metric_inputs": [
                    {"metric_code": "zydyxx.bcqfje"},
                ]},
            ],
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "COMMON_METRIC_REDECLARED" in _codes(report, ValidationSeverity.BLOCKING)

    def test_common_metrics_use_the_same_uniqueness_and_runtime_gate(self):
        cfg = _contract_cfg(
            common={"context_inputs": [], "metric_inputs": [
                {"metric_code": "zydyxx.draft"},
                {"metric_code": "zydyxx.draft"},
            ]},
            profiles=[],
        )

        report = self.validator.validate(_draft(structured_config=cfg))

        assert "DUPLICATE_METRIC_INPUT" in _codes(report, ValidationSeverity.BLOCKING)
        assert "METRIC_NOT_RUNTIME_RESOLVABLE" in _codes(
            report, ValidationSeverity.BLOCKING,
        )

    def test_metric_not_resolvable_blocking(self):
        # §54.3 draft 指标不可解析
        cfg = _contract_cfg(
            profiles=[
                {"profile_id": "p1", "name": "A", "metric_inputs": [
                    {"metric_code": "zydyxx.draft"},
                ]},
            ],
            common={"context_inputs": [], "metric_inputs": []},
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "METRIC_NOT_RUNTIME_RESOLVABLE" in _codes(report, ValidationSeverity.BLOCKING)

    def test_metric_not_found_blocking(self):
        cfg = _contract_cfg(
            profiles=[
                {"profile_id": "p1", "name": "A", "metric_inputs": [
                    {"metric_code": "missing.x"},
                ]},
            ],
            common={"context_inputs": [], "metric_inputs": []},
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "METRIC_NOT_FOUND" in _codes(report, ValidationSeverity.BLOCKING)

    def test_invalid_context_code_blocking(self):
        # context code 不在枚举 → 模型解析失败 → INVALID_EXECUTION_CONTRACT
        cfg = _contract_cfg(
            common={"context_inputs": [
                {"code": "totally_unknown_context"},
            ], "metric_inputs": []},
            profiles=[],
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "INVALID_EXECUTION_CONTRACT" in _codes(report, ValidationSeverity.BLOCKING)

    def test_common_context_redeclared_in_profile_blocking(self):
        cfg = _contract_cfg(
            common={"context_inputs": [
                {"code": "settlement_id"},
            ], "metric_inputs": []},
            profiles=[
                {"profile_id": "p1", "name": "A", "metric_inputs": [], "context_inputs": [
                    {"code": "settlement_id"},
                ]},
            ],
        )
        report = self.validator.validate(_draft(structured_config=cfg))
        assert "COMMON_CONTEXT_REDECLARED" in _codes(report, ValidationSeverity.BLOCKING)

    def test_plain_validator_without_service_warns_not_blocks(self):
        # 无 input_service 时降级 WARNING，不阻塞
        report = self.validator_plain.validate(_draft(structured_config=_contract_cfg()))
        assert report.blocking_ok  # 无阻塞
        assert "METRIC_RESOLVABILITY_NOT_CHECKED" in _codes(report, ValidationSeverity.WARNING)
