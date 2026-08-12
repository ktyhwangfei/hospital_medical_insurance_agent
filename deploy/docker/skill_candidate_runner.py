"""Minimal stdin/stdout runner used only inside the candidate Docker sandbox."""

from __future__ import annotations

import json
import inspect
import runpy
import sys
from typing import Any


def _evaluate(case_type: str, output: Any, assertions: dict[str, Any]) -> bool:
    if case_type == "calculation":
        value = output.get("value") if isinstance(output, dict) else output
        expected = float(assertions["expected_value"])
        tolerance = float(assertions.get("tolerance", 0.0))
        return (
            isinstance(value, (int, float))
            and abs(float(value) - expected) <= tolerance
        )
    serialized = json.dumps(output, ensure_ascii=False, sort_keys=True)
    if case_type == "policy_content":
        return all(
            value in serialized for value in assertions.get("must_include", [])
        ) and not any(value in serialized for value in assertions.get("forbidden", []))
    if case_type == "citation":
        return all(
            value in serialized for value in assertions.get("required_source_ids", [])
        )
    if case_type == "answer_quality":
        return all(
            value in serialized for value in assertions.get("must_include", [])
        ) and not any(
            value in serialized for value in assertions.get("must_not_include", [])
        )
    if case_type == "safety":
        expected_state = assertions.get("expected_state")
        state = output.get("state") if isinstance(output, dict) else None
        return state == expected_state
    return False


def main() -> int:
    request = json.loads(sys.stdin.read())
    namespace = runpy.run_path("/candidate/assembler.py")
    assemble = namespace.get("assemble")
    if callable(assemble):
        output = assemble(request["input"])
    else:
        load = namespace.get("load")
        if not callable(load):
            raise ValueError("assembler.py must define assemble(data) or load(config)")
        load_parameters = inspect.signature(load).parameters
        loaded = load(request["input"]) if load_parameters else load()
        execute = getattr(loaded, "execute", None)
        output = execute(request["input"]) if callable(execute) else loaded
    passed = _evaluate(request["case_type"], output, request["assertions"])
    print(
        json.dumps(
            {
                "case_id": request["case_id"],
                "status": "passed" if passed else "failed",
                "passed": passed,
                "output": output if isinstance(output, dict) else {"value": output},
                "blocked_reason": None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
