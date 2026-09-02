"""Skill 包生成器（P2）。

根据结构化草稿生成标准 Skill 包文件树（内存中，不落盘）。
供模板向导第四步"生成预览"和 P5 物化器使用。

生成的包结构对齐 ``skills/settlement_explain_skill/``：
SKILL.md / skill_manifest.yaml / config.yaml / schemas/* / templates/*。
"""

from __future__ import annotations

from typing import Any

import yaml

from src.domain.skill.draft_models import SkillDraft


class SkillPackage:
    """生成的 Skill 包：文件路径 → 内容。"""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = dict(files)

    @property
    def file_paths(self) -> list[str]:
        return sorted(self.files.keys())

    def manifest(self) -> dict[str, Any]:
        content = self.files.get("skill_manifest.yaml", "")
        return yaml.safe_load(content) or {} if content else {}


class SkillPackageGenerator:
    """从草稿结构化配置生成标准 Skill 包。"""

    def generate(self, draft: SkillDraft) -> SkillPackage:
        cfg = draft.structured_config
        basic = cfg.get("basic", {}) or {}
        bm = cfg.get("business_mounting", {}) or {}
        schemas = cfg.get("schemas", {}) or {}

        files: dict[str, str] = {}
        files["SKILL.md"] = self._render_skill_md(draft, basic)
        files["skill_manifest.yaml"] = self._render_manifest(draft, basic, bm)
        files["config.yaml"] = self._render_config(basic, bm)

        input_schema = schemas.get("input")
        output_schema = schemas.get("output")
        if input_schema is not None:
            files["schemas/input.schema.json"] = self._dump_schema(input_schema)
        if output_schema is not None:
            files["schemas/output.schema.json"] = self._dump_schema(output_schema)

        # 合并草稿携带的原始文件（导入/源码编辑产物），保留用户自定义内容
        for path, content in draft.raw_files.items():
            if not path.startswith("__"):
                files[path] = content

        return SkillPackage(files)

    # ── 文件渲染 ──────────────────────────────────────────────────

    def _render_skill_md(
        self, draft: SkillDraft, basic: dict[str, Any]
    ) -> str:
        name = str(basic.get("skill_name", draft.skill_id))
        description = str(basic.get("description", "")).strip()
        lines = [f"# {name}", ""]
        if description:
            lines.extend([description, ""])
        lines.extend(
            [
                "## 输入",
                "",
                "本 Skill 通过语义层声明所需输入指标，具体指标见 `skill_manifest.yaml`。",
                "",
                "## 输出",
                "",
                "见 `schemas/output.schema.json`。",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_manifest(
        self,
        draft: SkillDraft,
        basic: dict[str, Any],
        bm: dict[str, Any],
    ) -> str:
        manifest: dict[str, Any] = {
            "skill_id": draft.skill_id,
            "skill_name": str(basic.get("skill_name", draft.skill_name)),
            "version": "1.0.0",
            "business_action": str(bm.get("business_action", "")),
            "business_object": str(bm.get("business_object", "")),
            "supported_intents": list(bm.get("include_keywords", []) or []),
            "excluded_intents": list(bm.get("excluded_intents", []) or []),
            "needed_objects": [],  # P4 输入指标契约填充
            "required_mcp": [],
            "optional_mcp": [],
        }
        if basic.get("description"):
            manifest["description"] = str(basic["description"])
        if basic.get("owner"):
            manifest["owner"] = str(basic["owner"])
        execution_contract = draft.structured_config.get("execution_contract")
        if isinstance(execution_contract, dict):
            manifest["execution_contract"] = execution_contract
        return yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False)

    def _render_config(
        self, basic: dict[str, Any], bm: dict[str, Any]
    ) -> str:
        config = {
            "skill_id": basic.get("skill_id"),
            "display": {"mode": "single"},
        }
        return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)

    def _dump_schema(self, schema: Any) -> str:
        if isinstance(schema, str):
            # 已是 JSON 字符串，规范化重排
            import json

            try:
                return json.dumps(json.loads(schema), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                return schema
        import json

        return json.dumps(schema, ensure_ascii=False, indent=2)
