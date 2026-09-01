"""Skill 草稿校验器（P2）。

校验门禁（设计 §8.2）：结构、领域分类、Schema、脚本安全、敏感内容。
输入指标契约校验（设计 §5.4）在 P4 扩展本校验器。

输出 ``ValidationReport``；blocking 问题阻止登记/物化。
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

from pydantic import ValidationError

from src.domain.common.actions import (
    BusinessAction,
    BusinessObject,
    VALID_ACTION_OBJECT_PAIRS,
)
from src.domain.skill.draft_models import (
    RuntimeContextCode,
    SkillDraft,
    SkillDraftSourceType,
    SkillExecutionContract,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from src.runtime.skill_management.ai_authoring.security import (
    scan_ai_generated_files,
)
from src.runtime.skill_management.skill_input_service import SkillInputService
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationProvenance,
)
from src.security.desensitization.detection import detect_sensitive_patterns

# 脚本危险调用（AST 名称匹配）
_DANGEROUS_NAMES = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
}
_DANGEROUS_ATTRS = {
    "system",
    "popen",
    "spawn",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
}
_DANGEROUS_MODULES = {"subprocess", "os.system", "shutil.rmtree"}

# 敏感内容正则
_AWS_KEY = re.compile(r"AKIA[0-9A-Z]{16}")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_ID_CARD = re.compile(r"\b\d{17}[\dXx]\b")
_DB_PASSWORD = re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+")
_CREDENTIAL_SECRET = re.compile(
    r"(?i)(?:password|passwd|pwd|api[_-]?key|secret)\s*[=:]\s*\S+"
)
_GENERATION_META_PATH = "__generation_meta__.json"
_GENERATION_META_KEYS = {
    "generation_id",
    "proposal_hash",
    "provenance",
    "citations",
    "uncertainties",
}
_GENERATION_ID = re.compile(r"^gen_[0-9a-f]{12}_[A-Za-z0-9_-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SkillDraftValidator:
    """校验草稿的结构化配置与原始文件。"""

    def __init__(self, input_service: SkillInputService | None = None) -> None:
        # 可选注入语义层输入服务，启用执行契约的 runtime_resolvable 校验。
        # 默认 None 保持纯结构校验行为，不破坏现有无依赖构造点。
        self._input_service = input_service

    def validate(self, draft: SkillDraft) -> ValidationReport:
        issues: list[ValidationIssue] = []
        issues.extend(self._validate_basic(draft))
        issues.extend(self._validate_business_mounting(draft))
        issues.extend(self._validate_schemas(draft))
        issues.extend(self._validate_execution_contract(draft))
        if draft.source_type == SkillDraftSourceType.AI_GENERATED:
            issues.extend(self._validate_ai_generated_files(draft))
        else:
            issues.extend(self._validate_raw_files_safety(draft))
        return ValidationReport(issues=issues)

    def validate_files(self, raw_files: dict[str, str]) -> ValidationReport:
        """仅校验原始文件的安全性（脚本安全 + 敏感内容），用于导入场景。"""
        issues: list[ValidationIssue] = []
        for path, content in raw_files.items():
            if not isinstance(content, str):
                continue
            issues.extend(self._check_sensitive_content(path, content))
            if path.endswith(".py"):
                issues.extend(self._check_python_safety(path, content))
        return ValidationReport(issues=issues)

    # ── 基本信息校验 ──────────────────────────────────────────────

    def _validate_basic(self, draft: SkillDraft) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        basic = draft.structured_config.get("basic", {}) or {}
        if not isinstance(basic, dict):
            issues.append(self._blocking("INVALID_BASIC", "basic 必须是对象", "basic"))
            return issues
        if not str(basic.get("skill_id", "")).strip():
            issues.append(
                self._blocking("MISSING_SKILL_ID", "缺少 skill_id", "basic.skill_id")
            )
        if not str(basic.get("skill_name", "")).strip():
            issues.append(
                self._blocking("MISSING_SKILL_NAME", "缺少 skill_name", "basic.skill_name")
            )
        return issues

    # ── 业务挂载校验 ──────────────────────────────────────────────

    def _validate_business_mounting(
        self, draft: SkillDraft
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        bm = draft.structured_config.get("business_mounting", {}) or {}
        if not isinstance(bm, dict):
            issues.append(
                self._blocking(
                    "INVALID_BUSINESS_MOUNTING", "business_mounting 必须是对象"
                )
            )
            return issues
        action = str(bm.get("business_action", "")).strip()
        obj = str(bm.get("business_object", "")).strip()
        if not action:
            issues.append(
                self._blocking("MISSING_BUSINESS_ACTION", "缺少 business_action")
            )
        elif action not in BusinessAction._value2member_map_:
            issues.append(
                self._blocking(
                    "INVALID_BUSINESS_ACTION",
                    f"非法 business_action: {action}",
                    "business_mounting.business_action",
                )
            )
        if not obj:
            issues.append(
                self._blocking("MISSING_BUSINESS_OBJECT", "缺少 business_object")
            )
        elif obj not in BusinessObject._value2member_map_:
            issues.append(
                self._blocking(
                    "INVALID_BUSINESS_OBJECT",
                    f"非法 business_object: {obj}",
                    "business_mounting.business_object",
                )
            )
        # 配对白名单（仅当两者都合法时校验）
        if action in BusinessAction._value2member_map_ and obj in BusinessObject._value2member_map_:
            pair = (BusinessAction(action), BusinessObject(obj))
            if pair not in VALID_ACTION_OBJECT_PAIRS:
                issues.append(
                    self._warning(
                        "ACTION_OBJECT_PAIR_NOT_WHITELISTED",
                        f"动作-对象配对未在白名单: {action}/{obj}（仍可登记，建议确认）",
                        "business_mounting",
                    )
                )
        return issues

    # ── Schema 校验 ───────────────────────────────────────────────

    def _validate_schemas(self, draft: SkillDraft) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        schemas = draft.structured_config.get("schemas", {}) or {}
        if not isinstance(schemas, dict):
            return []
        for key, value in schemas.items():
            if value in (None, "", {}):
                continue
            if isinstance(value, (dict, list)):
                continue  # 已是结构化对象
            if isinstance(value, str):
                try:
                    json.loads(value)
                except json.JSONDecodeError as exc:
                    issues.append(
                        self._blocking(
                            "INVALID_SCHEMA_JSON",
                            f"Schema {key} 不是合法 JSON: {exc.msg}",
                            f"schemas.{key}",
                        )
                    )
        return issues

    # ── 执行契约校验（Skill Execution Contract，设计 §54）─────────
    #
    # execution_contract 为可选；不存在则完全跳过（旧 Skill 兼容，§64）。
    # 存在时解析为 SkillExecutionContract，校验：版本/profile_id/重复/
    # context code/metric runtime_resolvable。

    _VALID_CONTEXT_CODES = frozenset(c.value for c in RuntimeContextCode)

    def _validate_execution_contract(
        self, draft: SkillDraft
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        ec = draft.structured_config.get("execution_contract")
        if ec is None:
            # 无执行契约（旧 Skill 或未配置）：跳过（§64）
            return issues
        if not isinstance(ec, dict):
            issues.append(
                self._blocking(
                    "INVALID_EXECUTION_CONTRACT",
                    "execution_contract 必须是对象",
                    "execution_contract",
                )
            )
            return issues
        try:
            contract = SkillExecutionContract.model_validate(ec)
        except ValidationError as exc:
            issues.append(
                self._blocking(
                    "INVALID_EXECUTION_CONTRACT",
                    f"execution_contract 结构非法: {exc}",
                    "execution_contract",
                )
            )
            return issues

        # §54.1 版本（model 默认 2；显式非 2 由解析拒绝，这里只兜底）
        if contract.version != 2:
            issues.append(
                self._blocking(
                    "UNSUPPORTED_CONTRACT_VERSION",
                    f"仅支持 execution_contract.version=2，实际 {contract.version}",
                    "execution_contract.version",
                )
            )

        common_metric_codes: set[str] = set()
        for metric in contract.common.metric_inputs:
            if metric.metric_code in common_metric_codes:
                issues.append(self._blocking(
                    "DUPLICATE_METRIC_INPUT",
                    f"Common 内重复指标: {metric.metric_code}",
                    f"execution_contract.common.metric_inputs.{metric.metric_code}",
                ))
                continue
            common_metric_codes.add(metric.metric_code)
            issues.extend(self._validate_metric_resolvable(
                metric.metric_code,
                "execution_contract.common.metric_inputs",
            ))
        common_context_codes = {
            c.code for c in contract.common.context_inputs
        }

        # §54.2 + §54.4 + §54.5 + §54.6 逐 Profile 校验
        seen_profile_ids: set[str] = set()
        for profile in contract.profiles:
            issues.extend(
                self._validate_profile(
                    profile,
                    seen_profile_ids,
                    common_metric_codes,
                    common_context_codes,
                )
            )
        return issues

    def _validate_profile(
        self,
        profile: Any,
        seen_profile_ids: set[str],
        common_metric_codes: set[str],
        common_context_codes: set[str],
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        pid = profile.profile_id
        path = f"execution_contract.profiles.{pid}"

        # §54.2 profile_id 唯一（kebab-case 已由模型校验，这里查重）
        if pid in seen_profile_ids:
            issues.append(
                self._blocking(
                    "PROFILE_ID_DUPLICATE",
                    f"profile_id 重复: {pid}",
                    path,
                )
            )
        seen_profile_ids.add(pid)

        # §54.4 Profile 内 metric 去重
        seen_metrics: set[str] = set()
        for m in profile.metric_inputs:
            if m.metric_code in seen_metrics:
                issues.append(
                    self._blocking(
                        "DUPLICATE_METRIC_INPUT",
                        f"Profile「{pid}」内重复指标: {m.metric_code}",
                        f"{path}.metric_inputs.{m.metric_code}",
                    )
                )
                continue
            seen_metrics.add(m.metric_code)

            # §54.5 Common 已声明的 metric，Profile 不重复声明（V1 不支持 Override）
            if m.metric_code in common_metric_codes:
                issues.append(
                    self._blocking(
                        "COMMON_METRIC_REDECLARED",
                        f"指标 {m.metric_code} 已在 common 声明，Profile「{pid}」不应重复",
                        f"{path}.metric_inputs.{m.metric_code}",
                    )
                )

            # §54.3 metric runtime_resolvable（需注入 input_service）
            issues.extend(
                self._validate_metric_resolvable(m.metric_code, f"{path}.metric_inputs")
            )

        # §54.6 context code 合法（model 已保证为枚举，这里只查 Common 重复）
        for c in profile.context_inputs:
            if c.code in common_context_codes:
                issues.append(
                    self._blocking(
                        "COMMON_CONTEXT_REDECLARED",
                        f"上下文 {c.code} 已在 common 声明，Profile「{pid}」不应重复",
                        f"{path}.context_inputs.{c.code}",
                    )
                )

        # Common.metric_inputs 也需逐个 runtime_resolvable 校验
        # （common 与 profile 共用同一去重池，但 common 内部去重另查）
        return issues

    def _validate_metric_resolvable(
        self, metric_code: str, base_path: str
    ) -> list[ValidationIssue]:
        """校验 metric_code 是否 runtime_resolvable（设计 §54.3）。

        无 input_service 时降级为 WARNING（结构层无法判定运行时可解析性，
        需在物化/发布时由注入了语义层的 Validator 复验）。
        """
        if self._input_service is None:
            return [
                self._warning(
                    "METRIC_RESOLVABILITY_NOT_CHECKED",
                    f"未注入语义层服务，无法校验 {metric_code} 的 runtime_resolvable",
                    f"{base_path}.{metric_code}",
                )
            ]
        metric = self._input_service._registry.get_metric(metric_code)  # noqa: SLF001
        if metric is None:
            return [
                self._blocking(
                    "METRIC_NOT_FOUND",
                    f"指标不存在: {metric_code}",
                    f"{base_path}.{metric_code}",
                )
            ]
        obj = self._input_service._registry.get_object(metric.object_code)  # noqa: SLF001
        cap = self._input_service.resolve_metric_capability(metric, obj)
        if not cap.runtime_resolvable:
            reason = (
                cap.unavailable_reason.value if cap.unavailable_reason else "UNKNOWN"
            )
            return [
                self._blocking(
                    "METRIC_NOT_RUNTIME_RESOLVABLE",
                    f"指标 {metric_code} 不可作为 Skill 输入（{reason}）",
                    f"{base_path}.{metric_code}",
                )
            ]
        return []

    # ── 脚本与敏感内容校验 ────────────────────────────────────────

    def _validate_raw_files_safety(
        self, draft: SkillDraft
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for path, content in draft.raw_files.items():
            if not isinstance(content, str):
                continue
            issues.extend(self._check_sensitive_content(path, content))
            if path.endswith(".py"):
                issues.extend(self._check_python_safety(path, content))
        return issues

    def _validate_ai_generated_files(self, draft: SkillDraft) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        model_files: dict[str, str] = {}
        if _GENERATION_META_PATH not in draft.raw_files:
            issues.append(
                self._blocking(
                    "AI_GENERATION_META_REQUIRED",
                    "AI 草稿必须保留生成证据元数据",
                    f"raw_files.{_GENERATION_META_PATH}",
                )
            )
        for path, content in draft.raw_files.items():
            if not path.startswith("__"):
                model_files[path] = content
                continue
            if path != _GENERATION_META_PATH:
                issues.append(
                    self._blocking(
                        "AI_RESERVED_FILE_FORBIDDEN",
                        "AI 草稿包含不允许的内部保留文件",
                        f"raw_files.{path}",
                    )
                )
                continue
            issues.extend(self._validate_generation_metadata(content))

        result = scan_ai_generated_files(model_files)
        issues.extend(
            ValidationIssue(
                code=issue.code,
                message=issue.message,
                severity=ValidationSeverity.BLOCKING,
                path=f"raw_files.{issue.path}" if issue.path else "raw_files",
            )
            for issue in result.issues
        )
        return issues

    def _validate_generation_metadata(self, content: str) -> list[ValidationIssue]:
        path = f"raw_files.{_GENERATION_META_PATH}"
        if (
            detect_sensitive_patterns(content)
            or _AWS_KEY.search(content)
            or _PRIVATE_KEY.search(content)
            or _CREDENTIAL_SECRET.search(content)
        ):
            return [
                self._blocking(
                    "AI_GENERATION_META_SENSITIVE",
                    "AI 生成内部证据包含敏感内容",
                    path,
                )
            ]
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict) or set(payload) != _GENERATION_META_KEYS:
                raise ValueError("metadata keys invalid")
            generation_id = payload["generation_id"]
            proposal_hash = payload["proposal_hash"]
            if not isinstance(generation_id, str) or not _GENERATION_ID.fullmatch(
                generation_id
            ):
                raise ValueError("generation_id invalid")
            if not isinstance(proposal_hash, str) or not _SHA256.fullmatch(
                proposal_hash
            ):
                raise ValueError("proposal_hash invalid")
            SkillAIGenerationProvenance.model_validate(payload["provenance"])
            citations = payload["citations"]
            if not isinstance(citations, list) or any(
                not isinstance(item, dict)
                or set(item) != {"source_type", "source_id", "summary"}
                or any(
                    not isinstance(item[key], str) or not item[key].strip()
                    for key in item
                )
                for item in citations
            ):
                raise ValueError("citations invalid")
            uncertainties = payload["uncertainties"]
            if not isinstance(uncertainties, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in uncertainties
            ):
                raise ValueError("uncertainties invalid")
            if not citations and not uncertainties:
                raise ValueError("traceability missing")
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, ValidationError):
            return [
                self._blocking(
                    "AI_GENERATION_META_INVALID",
                    "AI 生成内部证据不是合法的严格 JSON 对象",
                    path,
                )
            ]
        return []

    def _check_python_safety(
        self, path: str, content: str
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            issues.append(
                self._blocking(
                    "SCRIPT_SYNTAX_ERROR",
                    f"脚本语法错误: {exc.msg}",
                    f"raw_files.{path}",
                )
            )
            return issues
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_NAMES:
                    issues.append(
                        self._blocking(
                            "UNSAFE_SCRIPT_CALL",
                            f"禁止调用 {node.func.id}()",
                            f"raw_files.{path}",
                        )
                    )
                elif isinstance(node.func, ast.Attribute) and node.func.attr in _DANGEROUS_ATTRS:
                    issues.append(
                        self._blocking(
                            "UNSAFE_SCRIPT_CALL",
                            f"禁止调用 .{node.func.attr}()",
                            f"raw_files.{path}",
                        )
                    )
        # 危险模块导入
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if self._module_dangerous(alias.name):
                        issues.append(
                            self._blocking(
                                "UNSAFE_IMPORT",
                                f"禁止导入 {alias.name}",
                                f"raw_files.{path}",
                            )
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if self._module_dangerous(node.module):
                    issues.append(
                        self._blocking(
                            "UNSAFE_IMPORT",
                            f"禁止导入 {node.module}",
                            f"raw_files.{path}",
                        )
                    )
        return issues

    @staticmethod
    def _module_dangerous(module: str) -> bool:
        return any(module == m or module.startswith(m + ".") for m in _DANGEROUS_MODULES)

    def _check_sensitive_content(
        self, path: str, content: str
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        if _AWS_KEY.search(content):
            issues.append(
                self._blocking(
                    "SENSITIVE_CONTENT", "检测到疑似 AWS 密钥", f"raw_files.{path}"
                )
            )
        if _PRIVATE_KEY.search(content):
            issues.append(
                self._blocking(
                    "SENSITIVE_CONTENT", "检测到疑似私钥", f"raw_files.{path}"
                )
            )
        if _ID_CARD.search(content):
            issues.append(
                self._blocking(
                    "SENSITIVE_CONTENT", "检测到疑似身份证号", f"raw_files.{path}"
                )
            )
        if _DB_PASSWORD.search(content):
            issues.append(
                self._warning(
                    "SENSITIVE_CONTENT",
                    "检测到疑似数据库密码配置，请确认非敏感",
                    f"raw_files.{path}",
                )
            )
        return issues

    # ── 辅助 ──────────────────────────────────────────────────────

    @staticmethod
    def _blocking(code: str, message: str, path: str | None = None) -> ValidationIssue:
        return ValidationIssue(
            code=code, message=message, severity=ValidationSeverity.BLOCKING, path=path
        )

    @staticmethod
    def _warning(code: str, message: str, path: str | None = None) -> ValidationIssue:
        return ValidationIssue(
            code=code, message=message, severity=ValidationSeverity.WARNING, path=path
        )
