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

from src.domain.common.actions import (
    BusinessAction,
    BusinessObject,
    VALID_ACTION_OBJECT_PAIRS,
)
from src.domain.skill.draft_models import (
    SkillDraft,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)

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


class SkillDraftValidator:
    """校验草稿的结构化配置与原始文件。"""

    def validate(self, draft: SkillDraft) -> ValidationReport:
        issues: list[ValidationIssue] = []
        issues.extend(self._validate_basic(draft))
        issues.extend(self._validate_business_mounting(draft))
        issues.extend(self._validate_schemas(draft))
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
