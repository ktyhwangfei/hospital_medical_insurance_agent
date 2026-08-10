"""AI 生成 Skill 原始文件安全门禁测试。"""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from src.runtime.skill_management.ai_authoring.security import (
    MAX_AI_FILE_BYTES,
    MAX_AI_TOTAL_BYTES,
    SkillAISecurityResult,
    scan_ai_generated_files,
)


@pytest.mark.parametrize(
    "path, content, expected_code",
    [
        ("../escape.py", "value = 1", "AI_FILE_PATH_FORBIDDEN"),
        ("assembler.py", "import socket", "AI_IMPORT_FORBIDDEN"),
        ("assembler.py", "open('secret.txt').read()", "AI_CALL_FORBIDDEN"),
        (
            "assembler.py",
            "__import__('os').system('whoami')",
            "AI_CALL_FORBIDDEN",
        ),
        ("payload.bin", "not-python", "AI_FILE_PATH_FORBIDDEN"),
    ],
)
def test_scan_ai_files_rejects_unsafe_content(
    path: str,
    content: str,
    expected_code: str,
) -> None:
    result = scan_ai_generated_files({path: content})
    assert expected_code in {issue.code for issue in result.issues}


def test_scan_ai_files_accepts_minimal_assembler_and_prompt() -> None:
    result = scan_ai_generated_files(
        {
            "assembler.py": "def load(config):\n    return config\n",
            "prompt_template.yaml": "system: explain with citations\n",
        }
    )

    assert result.passed is True
    assert result.issues == ()
    assert re.fullmatch(r"[0-9a-f]{64}", result.content_hash)


@pytest.mark.parametrize("path", ["/tmp/assembler.py", r"C:\tmp\assembler.py"])
def test_scan_ai_files_rejects_absolute_paths(path: str) -> None:
    result = scan_ai_generated_files({path: "value = 1"})
    assert "AI_FILE_PATH_FORBIDDEN" in {issue.code for issue in result.issues}


def test_scan_ai_files_measures_single_file_limit_in_utf8_bytes() -> None:
    encoded_width = len("医".encode("utf-8"))
    at_limit = "医" * (MAX_AI_FILE_BYTES // encoded_width) + "x" * (
        MAX_AI_FILE_BYTES % encoded_width
    )
    accepted = scan_ai_generated_files({"prompt_template.yaml": at_limit})
    rejected = scan_ai_generated_files({"prompt_template.yaml": at_limit + "医"})

    assert "AI_FILE_TOO_LARGE" not in {issue.code for issue in accepted.issues}
    assert "AI_FILE_TOO_LARGE" in {issue.code for issue in rejected.issues}


def test_scan_ai_files_rejects_total_size_over_limit() -> None:
    assembler_size = MAX_AI_TOTAL_BYTES - MAX_AI_FILE_BYTES + 1
    assembler = "#" + ("x" * (assembler_size - 1))
    prompt = "x" * MAX_AI_FILE_BYTES

    result = scan_ai_generated_files(
        {"assembler.py": assembler, "prompt_template.yaml": prompt}
    )

    assert "AI_TOTAL_SIZE_EXCEEDED" in {issue.code for issue in result.issues}


def test_scan_ai_files_rejects_python_syntax_errors() -> None:
    result = scan_ai_generated_files({"assembler.py": "def load(:\n    pass\n"})
    assert "AI_PYTHON_SYNTAX_ERROR" in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    "content",
    [
        "system: patient phone 13800138000",
        "system: patient id 110101199003071234",
    ],
)
def test_scan_ai_files_reuses_sensitive_pattern_detection(content: str) -> None:
    result = scan_ai_generated_files({"prompt_template.yaml": content})
    assert "AI_SENSITIVE_CONTENT" in {issue.code for issue in result.issues}


def test_scan_ai_files_accepts_allowed_data_shaping_nodes_and_calls() -> None:
    assembler = """\
def load(config):
    values = [config["value"], 1]
    if len(values) > 1:
        result = {"values": values, "enabled": True}
    else:
        result = {"values": [], "enabled": False}
    return result
"""
    result = scan_ai_generated_files({"assembler.py": assembler})
    assert result.passed is True


def test_scan_ai_files_rejects_attribute_calls() -> None:
    result = scan_ai_generated_files(
        {"assembler.py": "def load(config):\n    return config.get('value')\n"}
    )
    assert "AI_CALL_FORBIDDEN" in {issue.code for issue in result.issues}


@pytest.mark.parametrize("dangerous_name", ["eval", "open"])
def test_scan_ai_files_rejects_dangerous_call_aliases(
    dangerous_name: str,
) -> None:
    assembler = f"""\
len = {dangerous_name}
def load(config):
    return len(config)
"""
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert "AI_CALL_FORBIDDEN" in {issue.code for issue in result.issues}
    assert result.passed is False


def test_scan_ai_files_rejects_allowed_call_name_parameter_shadowing() -> None:
    assembler = """\
def load(len):
    return len([])
"""
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert "AI_CALL_FORBIDDEN" in {issue.code for issue in result.issues}


def test_scan_ai_files_rejects_dynamic_builtins_access() -> None:
    result = scan_ai_generated_files(
        {"assembler.py": ("def load(config):\n    return __builtins__['open']\n")}
    )

    assert "AI_CALL_FORBIDDEN" in {issue.code for issue in result.issues}


def test_scan_ai_files_accepts_safe_local_function_calls() -> None:
    assembler = """\
def normalize(value):
    if value:
        return str(value)
    return ""

def load(config):
    value = config["value"]
    return normalize(value)
"""
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert result.passed is True


def test_scan_ai_files_rejects_nested_function_shadowing() -> None:
    assembler = """\
def outer():
    def breakpoint():
        return None
    return breakpoint

def load(config):
    return breakpoint()
"""
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert [issue.code for issue in result.issues] == [
        "AI_AST_NODE_FORBIDDEN",
        "AI_CALL_FORBIDDEN",
    ]


def test_scan_ai_files_rejects_decorators_without_resolving_them() -> None:
    assembler = """\
@breakpoint
def load(config):
    return config
"""
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert [issue.code for issue in result.issues] == ["AI_AST_NODE_FORBIDDEN"]


@pytest.mark.parametrize(
    "assembler",
    [
        ("def load(config) -> __import__('os').system('whoami'):\n    return config\n"),
        ("def load(config: open('pwned.txt', 'w')):\n    return config\n"),
        "value: __import__('os').system('whoami') = 1\n",
        "__builtins__['open'] = None\n",
    ],
)
def test_scan_ai_files_rejects_definition_time_execution_and_unsafe_targets(
    assembler: str,
) -> None:
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert [issue.code for issue in result.issues] == ["AI_AST_NODE_FORBIDDEN"]


@pytest.mark.parametrize(
    "assembler",
    [
        (
            "def load[T: __import__('os').system('whoami')](config):\n"
            "    return config\n"
        ),
        "def load[T](config):\n    return config\n",
    ],
)
def test_scan_ai_files_rejects_function_type_parameters(assembler: str) -> None:
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert [issue.code for issue in result.issues] == ["AI_AST_NODE_FORBIDDEN"]


def test_scan_ai_files_keeps_simple_name_and_destructuring_assignments() -> None:
    assembler = """\
def load(config):
    value = config["value"]
    left, right = [value, 1]
    return {"left": left, "right": right}
"""
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert result.passed is True


def test_scan_ai_files_rejects_module_level_calls() -> None:
    result = scan_ai_generated_files(
        {"assembler.py": "value = len([])\ndef load(config):\n    return config\n"}
    )

    assert [issue.code for issue in result.issues] == ["AI_AST_NODE_FORBIDDEN"]


def test_cross_scope_assignment_does_not_shadow_safe_top_level_helper() -> None:
    assembler = """\
def normalize(value):
    return str(value)

def unrelated(value):
    normalize = value
    return normalize

def load(config):
    return normalize(config["value"])
"""
    result = scan_ai_generated_files({"assembler.py": assembler})

    assert result.passed is True


def test_scan_ai_files_rejects_non_whitelisted_ast_nodes() -> None:
    result = scan_ai_generated_files(
        {"assembler.py": "handler = lambda value: value\n"}
    )
    assert "AI_AST_NODE_FORBIDDEN" in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    "raw_files",
    [
        {"\ud800": "safe"},
        {"prompt_template.yaml": "\ud800"},
    ],
)
def test_scan_ai_files_returns_stable_issue_for_unencodable_text(
    raw_files: dict[str, str],
) -> None:
    result = scan_ai_generated_files(raw_files)
    repeated = scan_ai_generated_files(raw_files)

    assert [issue.code for issue in result.issues] == ["AI_TEXT_ENCODING_INVALID"]
    assert re.fullmatch(r"[0-9a-f]{64}", result.content_hash)
    assert repeated.content_hash == result.content_hash


@pytest.mark.parametrize(
    "content",
    [
        "system: [unterminated\n",
        "!!python/object/apply:os.system ['whoami']\n",
    ],
)
def test_scan_ai_files_rejects_invalid_or_unsafe_prompt_yaml(content: str) -> None:
    result = scan_ai_generated_files({"prompt_template.yaml": content})

    assert [issue.code for issue in result.issues] == ["AI_YAML_INVALID"]


def test_scan_ai_files_accepts_safe_prompt_yaml() -> None:
    result = scan_ai_generated_files(
        {
            "prompt_template.yaml": (
                "system: explain with citations\n"
                "messages:\n"
                "  - role: user\n"
                "    content: explain this item\n"
            )
        }
    )

    assert result.issues == ()


def test_scan_ai_files_maps_deep_yaml_resource_failure_to_stable_issue() -> None:
    deeply_nested_yaml = "value: " + ("[" * 500) + "0" + ("]" * 500)

    result = scan_ai_generated_files({"prompt_template.yaml": deeply_nested_yaml})

    assert [issue.code for issue in result.issues] == ["AI_YAML_INVALID"]


def test_scan_ai_files_enforces_yaml_node_limit() -> None:
    too_many_nodes = "items:\n" + ("  - 0\n" * 4097)

    result = scan_ai_generated_files({"prompt_template.yaml": too_many_nodes})

    assert [issue.code for issue in result.issues] == ["AI_YAML_INVALID"]


def test_yaml_resource_failure_does_not_poison_next_scan() -> None:
    deeply_nested_yaml = "value: " + ("[" * 500) + "0" + ("]" * 500)
    failed = scan_ai_generated_files({"prompt_template.yaml": deeply_nested_yaml})
    recovered = scan_ai_generated_files(
        {"prompt_template.yaml": "system: explain with citations\n"}
    )

    assert [issue.code for issue in failed.issues] == ["AI_YAML_INVALID"]
    assert recovered.issues == ()


def test_scan_ai_files_reports_direct_open_once() -> None:
    result = scan_ai_generated_files(
        {"assembler.py": "def load(config):\n    return open('secret.txt')\n"}
    )

    assert [issue.code for issue in result.issues] == ["AI_CALL_FORBIDDEN"]


def test_scan_ai_files_reports_secret_once() -> None:
    result = scan_ai_generated_files(
        {"prompt_template.yaml": "api_key: AKIAIOSFODNN7EXAMPLE\n"}
    )

    assert [issue.code for issue in result.issues] == ["AI_SENSITIVE_CONTENT"]


def test_security_result_is_strict_and_frozen() -> None:
    result = scan_ai_generated_files({"prompt_template.yaml": "system: safe"})

    with pytest.raises(ValidationError):
        result.passed = False  # type: ignore[misc]
    with pytest.raises(ValidationError):
        SkillAISecurityResult(
            passed=True,
            issues=(),
            content_hash=result.content_hash,
            unexpected=True,
        )

    rejected = scan_ai_generated_files({"payload.bin": "unsafe"})
    with pytest.raises(ValidationError):
        rejected.issues[0].code = "CHANGED"  # type: ignore[misc]


def test_content_hash_is_independent_of_mapping_order() -> None:
    files = {
        "assembler.py": "def load(config):\n    return config\n",
        "prompt_template.yaml": "system: safe\n",
    }
    reversed_files = dict(reversed(tuple(files.items())))

    assert (
        scan_ai_generated_files(files).content_hash
        == scan_ai_generated_files(reversed_files).content_hash
    )
