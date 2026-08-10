"""AI 生成 Skill 原始文件的静态安全门禁。"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.security.desensitization.detection import detect_sensitive_patterns


ALLOWED_AI_RAW_FILES = frozenset({"assembler.py", "prompt_template.yaml"})
FORBIDDEN_CALLS = frozenset(
    {
        "compile",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
        "__import__",
    }
)

# 与现有 Skill 复制的单文件上限一致；AI 仅允许两个小型文本文件。
MAX_AI_FILE_BYTES = 256 * 1024
MAX_AI_TOTAL_BYTES = 384 * 1024

_ALLOWED_CALLS = frozenset(
    {
        "bool",
        "dict",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "round",
        "str",
        "sum",
        "tuple",
    }
)
_DYNAMIC_BUILTIN_NAMES = frozenset({"__builtins__", "builtins"})
_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|passwd|pwd|api[_-]?key|secret)\s*[=:]\s*\S+"),
)
_ALLOWED_AST_NODES = (
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.Expr,
    ast.If,
    ast.IfExp,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Dict,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.Compare,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.And,
    ast.Or,
    ast.Not,
    ast.UAdd,
    ast.USub,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
)


class SkillAISecurityIssue(BaseModel):
    """AI 文件的单项稳定安全问题。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    path: str | None = Field(default=None, max_length=512)


class SkillAISecurityResult(BaseModel):
    """AI 文件集合的不可变扫描结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    passed: bool
    issues: tuple[SkillAISecurityIssue, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _validate_summary(self) -> "SkillAISecurityResult":
        if self.passed != (not self.issues):
            raise ValueError("passed 必须与 issues 是否为空一致")
        return self


def scan_ai_generated_files(raw_files: Mapping[str, str]) -> SkillAISecurityResult:
    """扫描 AI 直接生成的文件，全程不写盘、不导入、不执行。"""

    issues: list[SkillAISecurityIssue] = []
    total_size = 0

    for path, content in raw_files.items():
        try:
            path.encode("utf-8")
            encoded_content = content.encode("utf-8")
        except UnicodeEncodeError:
            issues.append(
                _issue(
                    "AI_TEXT_ENCODING_INVALID",
                    "AI 生成文件路径或内容不是有效 UTF-8 文本",
                )
            )
            continue

        if path not in ALLOWED_AI_RAW_FILES:
            issues.append(
                _issue(
                    "AI_FILE_PATH_FORBIDDEN",
                    "AI 只能生成 assembler.py 和 prompt_template.yaml",
                    path,
                )
            )

        size = len(encoded_content)
        total_size += size
        if size > MAX_AI_FILE_BYTES:
            issues.append(
                _issue(
                    "AI_FILE_TOO_LARGE",
                    f"AI 生成文件超过 {MAX_AI_FILE_BYTES} 字节上限",
                    path,
                )
            )

        sensitive_types = detect_sensitive_patterns(content)
        contains_secret = any(pattern.search(content) for pattern in _SECRET_PATTERNS)
        if sensitive_types or contains_secret:
            matched_types = [*sensitive_types]
            if contains_secret:
                matched_types.append("credential_secret")
            issues.append(
                _issue(
                    "AI_SENSITIVE_CONTENT",
                    "AI 生成内容命中敏感信息模式: " + ", ".join(matched_types),
                    path,
                )
            )

        if path == "assembler.py":
            issues.extend(_scan_python(content, path))
        elif path == "prompt_template.yaml":
            issues.extend(_scan_prompt_yaml(content, path))

    if total_size > MAX_AI_TOTAL_BYTES:
        issues.append(
            _issue(
                "AI_TOTAL_SIZE_EXCEEDED",
                f"AI 生成文件总量超过 {MAX_AI_TOTAL_BYTES} 字节上限",
            )
        )

    issue_tuple = _deduplicate_issues(issues)
    return SkillAISecurityResult(
        passed=not issue_tuple,
        issues=issue_tuple,
        content_hash=_content_hash(raw_files),
    )


def _scan_python(content: str, path: str) -> list[SkillAISecurityIssue]:
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return [
            _issue(
                "AI_PYTHON_SYNTAX_ERROR",
                f"AI 生成脚本语法错误: {exc.msg}",
                path,
            )
        ]

    protected_names = FORBIDDEN_CALLS | _ALLOWED_CALLS | _DYNAMIC_BUILTIN_NAMES
    issues: list[SkillAISecurityIssue] = []

    top_level_functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef)
    ]
    function_names = {node.name for node in top_level_functions}
    module_bound_names = {
        name
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for name in _assignment_names(node)
    }
    callable_helpers = function_names - module_bound_names - protected_names

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            issues.append(_issue("AI_IMPORT_FORBIDDEN", "AI 生成脚本禁止 import", path))
            continue

        if isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                issues.append(
                    _issue(
                        "AI_AST_NODE_FORBIDDEN",
                        "AI 生成脚本禁止函数装饰器",
                        path,
                    )
                )
            if node.name in protected_names:
                issues.append(
                    _issue(
                        "AI_CALL_FORBIDDEN",
                        f"AI 生成脚本禁止重定义 {node.name}",
                        path,
                    )
                )
            issues.extend(
                _scan_top_level_function(
                    node,
                    path=path,
                    callable_helpers=callable_helpers,
                    protected_names=protected_names,
                )
            )
            continue

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target_names = _assignment_names(node)
            value = node.value
            has_forbidden_reference = value is not None and any(
                isinstance(child, ast.Name)
                and child.id in FORBIDDEN_CALLS | _DYNAMIC_BUILTIN_NAMES
                for child in ast.walk(value)
            )
            if (
                target_names & (protected_names | function_names)
                or has_forbidden_reference
            ):
                issues.append(
                    _issue(
                        "AI_CALL_FORBIDDEN",
                        "AI 生成脚本禁止重绑定调用能力",
                        path,
                    )
                )
            elif value is not None and not _is_static_expression(value):
                issues.append(
                    _issue(
                        "AI_AST_NODE_FORBIDDEN",
                        "AI 生成脚本禁止模块顶层执行表达式",
                        path,
                    )
                )
            continue

        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue

        if isinstance(node, ast.Expr) and _contains_forbidden_module_call(node.value):
            issues.append(
                _issue(
                    "AI_CALL_FORBIDDEN",
                    "AI 生成脚本禁止模块顶层危险调用",
                    path,
                )
            )
            continue

        issues.append(
            _issue(
                "AI_AST_NODE_FORBIDDEN",
                "AI 生成脚本模块顶层只允许静态定义",
                path,
            )
        )

    return issues


def _scan_top_level_function(
    function: ast.FunctionDef,
    *,
    path: str,
    callable_helpers: set[str],
    protected_names: frozenset[str],
) -> list[SkillAISecurityIssue]:
    nodes = tuple(_walk_function_scope(function))
    parameter_names = {
        node.arg for node in ast.walk(function.args) if isinstance(node, ast.arg)
    }
    assigned_names = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    issues: list[SkillAISecurityIssue] = []

    for default in (*function.args.defaults, *function.args.kw_defaults):
        if default is not None and not _is_static_expression(default):
            issues.append(
                _issue(
                    "AI_AST_NODE_FORBIDDEN",
                    "AI 生成脚本禁止可执行的默认参数",
                    path,
                )
            )

    for parameter_name in parameter_names & protected_names:
        issues.append(
            _issue(
                "AI_CALL_FORBIDDEN",
                f"AI 生成脚本禁止参数遮蔽 {parameter_name}",
                path,
            )
        )

    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            issues.append(
                _issue(
                    "AI_AST_NODE_FORBIDDEN",
                    "AI 生成脚本禁止嵌套函数",
                    path,
                )
            )
            continue

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            issues.append(_issue("AI_IMPORT_FORBIDDEN", "AI 生成脚本禁止 import", path))
            continue

        if isinstance(node, ast.Name):
            if node.id in FORBIDDEN_CALLS | _DYNAMIC_BUILTIN_NAMES:
                issues.append(
                    _issue(
                        "AI_CALL_FORBIDDEN",
                        f"AI 生成脚本禁止引用 {node.id}",
                        path,
                    )
                )
            elif isinstance(node.ctx, ast.Store) and node.id in _ALLOWED_CALLS:
                issues.append(
                    _issue(
                        "AI_CALL_FORBIDDEN",
                        f"AI 生成脚本禁止重绑定 {node.id}",
                        path,
                    )
                )

        if isinstance(node, ast.Call):
            call_name = node.func.id if isinstance(node.func, ast.Name) else None
            allowed_builtin = (
                call_name in _ALLOWED_CALLS
                and call_name not in assigned_names
                and call_name not in parameter_names
            )
            allowed_helper = (
                call_name in callable_helpers
                and call_name not in assigned_names
                and call_name not in parameter_names
            )
            if not allowed_builtin and not allowed_helper:
                issues.append(
                    _issue(
                        "AI_CALL_FORBIDDEN",
                        f"AI 生成脚本禁止调用 {_call_label(node.func)}",
                        path,
                    )
                )
            continue

        if isinstance(node, ast.Attribute):
            issues.append(
                _issue(
                    "AI_ATTRIBUTE_FORBIDDEN",
                    "AI 生成脚本禁止属性访问和反射",
                    path,
                )
            )
            continue

        if not isinstance(node, _ALLOWED_AST_NODES):
            issues.append(
                _issue(
                    "AI_AST_NODE_FORBIDDEN",
                    f"AI 生成脚本禁止 {type(node).__name__} 语法",
                    path,
                )
            )

    return issues


def _walk_function_scope(function: ast.FunctionDef):
    for statement in function.body:
        yield from _walk_without_nested_bodies(statement)


def _walk_without_nested_bodies(node: ast.AST):
    yield node
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        return
    for child in ast.iter_child_nodes(node):
        yield from _walk_without_nested_bodies(child)


def _assignment_names(node: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {
        child.id
        for target in targets
        for child in ast.walk(target)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }


def _is_static_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_static_expression(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is None or _is_static_expression(key) for key in node.keys
        ) and all(_is_static_expression(value) for value in node.values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_static_expression(node.operand)
    return False


def _contains_forbidden_module_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if not isinstance(child.func, ast.Name) or child.func.id in FORBIDDEN_CALLS:
            return True
    return False


def _scan_prompt_yaml(content: str, path: str) -> list[SkillAISecurityIssue]:
    try:
        yaml.safe_load(content)
    except yaml.YAMLError:
        return [_issue("AI_YAML_INVALID", "AI 生成提示词 YAML 无效", path)]
    return []


def _deduplicate_issues(
    issues: list[SkillAISecurityIssue],
) -> tuple[SkillAISecurityIssue, ...]:
    unique: list[SkillAISecurityIssue] = []
    seen: set[tuple[str, str | None]] = set()
    for issue in issues:
        key = (issue.code, issue.path)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return tuple(unique)


def _content_hash(raw_files: Mapping[str, str]) -> str:
    canonical = json.dumps(
        sorted(raw_files.items()),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _call_label(function: ast.expr) -> str:
    if isinstance(function, ast.Name):
        return f"{function.id}()"
    if isinstance(function, ast.Attribute):
        return f".{function.attr}()"
    return "动态函数"


def _issue(code: str, message: str, path: str | None = None) -> SkillAISecurityIssue:
    return SkillAISecurityIssue(code=code, message=message, path=path)
