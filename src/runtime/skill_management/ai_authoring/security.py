"""AI 生成 Skill 原始文件的静态安全门禁。"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping

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
        if path not in ALLOWED_AI_RAW_FILES:
            issues.append(
                _issue(
                    "AI_FILE_PATH_FORBIDDEN",
                    "AI 只能生成 assembler.py 和 prompt_template.yaml",
                    path,
                )
            )

        size = len(content.encode("utf-8"))
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
        if sensitive_types:
            issues.append(
                _issue(
                    "AI_SENSITIVE_CONTENT",
                    "AI 生成内容命中敏感信息模式: " + ", ".join(sensitive_types),
                    path,
                )
            )

        if path == "assembler.py":
            issues.extend(_scan_python(content, path))

    if total_size > MAX_AI_TOTAL_BYTES:
        issues.append(
            _issue(
                "AI_TOTAL_SIZE_EXCEEDED",
                f"AI 生成文件总量超过 {MAX_AI_TOTAL_BYTES} 字节上限",
            )
        )

    issue_tuple = tuple(issues)
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

    nodes = tuple(ast.walk(tree))
    local_functions = {node.name for node in nodes if isinstance(node, ast.FunctionDef)}
    assigned_names = {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    }
    parameter_names = {node.arg for node in nodes if isinstance(node, ast.arg)}

    protected_names = FORBIDDEN_CALLS | _ALLOWED_CALLS | _DYNAMIC_BUILTIN_NAMES
    issues: list[SkillAISecurityIssue] = []
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            issues.append(_issue("AI_IMPORT_FORBIDDEN", "AI 生成脚本禁止 import", path))
            continue

        if isinstance(node, ast.FunctionDef) and node.name in protected_names:
            issues.append(
                _issue(
                    "AI_CALL_FORBIDDEN",
                    f"AI 生成脚本禁止重定义 {node.name}",
                    path,
                )
            )

        if isinstance(node, ast.arg) and node.arg in protected_names:
            issues.append(
                _issue(
                    "AI_CALL_FORBIDDEN",
                    f"AI 生成脚本禁止参数遮蔽 {node.arg}",
                    path,
                )
            )

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
                and call_name not in local_functions
            )
            allowed_local_function = (
                call_name in local_functions
                and call_name not in assigned_names
                and call_name not in parameter_names
                and call_name not in _ALLOWED_CALLS
            )
            if not allowed_builtin and not allowed_local_function:
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


def _content_hash(raw_files: Mapping[str, str]) -> str:
    canonical = json.dumps(
        sorted(raw_files.items()),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _call_label(function: ast.expr) -> str:
    if isinstance(function, ast.Name):
        return f"{function.id}()"
    if isinstance(function, ast.Attribute):
        return f".{function.attr}()"
    return "动态函数"


def _issue(code: str, message: str, path: str | None = None) -> SkillAISecurityIssue:
    return SkillAISecurityIssue(code=code, message=message, path=path)
