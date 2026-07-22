"""
manifest_generator.py — 从语义层指标定义自动生成 Skill Manifest 关键字

功能:
1. 读取 IndicatorRegistry 获取所有指标定义和字典
2. 从指标名称、语义标签、字典标准值/同义词提取关键词
3. 合并到现有 skill_manifest.yaml 的 supported_intents 中
4. 保留手动维护的关键词，只增不减

用法:
    from src.semantic_layer.manifest_generator import ManifestKeywordGenerator

    gen = ManifestKeywordGenerator()
    gen.update_skill_manifest("skills/settlement_explain_skill")

流程:
    新增指标或字典时 → 运行 generator → 自动补充路由关键词
    → 减少手动维护 supported_intents 的工作量
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from src.semantic_layer.registry import get_registry

logger = logging.getLogger(__name__)


class ManifestKeywordGenerator:
    """
    从语义层指标定义和字典自动生成 Skill Manifest 关键字。

    桥接 semantic_layer → skill routing 的关键词链路：
      指标定义（名称 + 语义标签） → 关键词候选
      字典条目（标准值 + 同义词） → 关键词候选
      → 与现有 supported_intents 合并 → 去重排序 → 写入 manifest
    """

    def __init__(self) -> None:
        self._registry = get_registry()

    # ============================================================
    # 公共方法
    # ============================================================

    def generate_keywords_for_skill(self, skill_id: str = "") -> list[str]:
        """为指定技能生成关键词列表。

        从语义层全部指标和字典中提取关键词候选：
        a) 指标名称（IndicatorDefinition.name）
        b) 语义标签（IndicatorDefinition.semantic_tags）
        c) 字典标准值（DictionaryEntry.standard_value）
        d) 字典同义词（DictionaryEntry.synonyms）

        Args:
            skill_id: 技能 ID（当前为扩展预留，未来可按 skill 过滤）

        Returns:
            去重排序后的关键词列表
        """
        keywords: set[str] = set()

        # a) 从指标名称提取
        for ind in self._registry.list_all():
            name = ind.name.strip()
            if name:
                keywords.add(name)

        # b) 从语义标签提取
        for ind in self._registry.list_all():
            for tag in ind.semantic_tags:
                tag = tag.strip()
                if tag:
                    keywords.add(tag)

        # c) 从字典标准值提取
        categories = self._registry.list_dictionary_categories()
        for cat_info in categories:
            entries = self._registry.get_dictionary(cat_info["category"])
            for entry in entries:
                val = entry.standard_value.strip()
                if val:
                    keywords.add(val)

        # d) 从字典同义词提取
        for cat_info in categories:
            entries = self._registry.get_dictionary(cat_info["category"])
            for entry in entries:
                for syn in entry.synonyms:
                    syn = syn.strip()
                    if syn:
                        keywords.add(syn)

        return sorted(keywords, key=lambda x: (len(x), x))

    def merge_with_existing(
        self,
        existing_keywords: list[str],
        generated_keywords: list[str],
    ) -> list[str]:
        """合并现有关键词和自动生成的关键词。

        规则:
        1. 保留所有现有关键词（手动维护的精度高于自动生成）
        2. 添加自动生成的新关键词（补齐遗漏）
        3. 去重并按长度+字典序排序（短词在前，便于路由优先匹配）

        Args:
            existing_keywords: 现有 supported_intents（手动维护）
            generated_keywords: 自动生成的关键词候选

        Returns:
            合并后的关键词列表
        """
        merged: set[str] = set()
        for kw in existing_keywords:
            kw = kw.strip()
            if kw:
                merged.add(kw)
        for kw in generated_keywords:
            kw = kw.strip()
            if kw:
                merged.add(kw)
        return sorted(merged, key=lambda x: (len(x), x))

    def update_skill_manifest(self, skill_dir: str) -> None:
        """更新指定 skill 的 manifest 文件。

        流程:
        1. 读取 skill_manifest.yaml 获取 skill_id 和现有 supported_intents
        2. 从语义层生成关键词候选
        3. 合并现有关键词和生成关键词
        4. 仅替换 supported_intents 段（保留文件注释和其他字段）

        Args:
            skill_dir: skill 目录路径（如 "skills/settlement_explain_skill"）

        Raises:
            FileNotFoundError: manifest 文件不存在
            ValueError: manifest 中缺少 supported_intents 字段
        """
        manifest_path = Path(skill_dir) / "skill_manifest.yaml"
        if not manifest_path.exists():
            raise FileNotFoundError(
                f"Skill manifest not found: {manifest_path}"
            )

        # 1. 从 YAML 解析元数据
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

        skill_id = manifest.get("skill_id", "")
        existing: list[str] = list(manifest.get("supported_intents", []))

        if "supported_intents" not in manifest:
            raise ValueError(
                f"Manifest missing 'supported_intents': {manifest_path}"
            )

        # 2. 生成并合并关键词
        generated = self.generate_keywords_for_skill(skill_id)
        merged = self.merge_with_existing(existing, generated)

        # 仅当有变化时才重写文件
        if merged == existing:
            logger.info(
                "[ManifestGenerator] No new keywords for %s (skipped)", skill_id
            )
            return

        # 3. 以文本方式替换 supported_intents 段（保留注释和文件结构）
        self._replace_supported_intents(manifest_path, merged)

        added_count = len(set(merged)) - len(set(existing))
        logger.info(
            "[ManifestGenerator] Updated %s: %d existing + %d new = %d keywords",
            skill_id,
            len(existing),
            added_count,
            len(merged),
        )

    # ============================================================
    # 内部方法 — YAML 文本级操作
    # ============================================================

    @staticmethod
    def _find_section_boundaries(
        lines: list[str], key: str
    ) -> tuple[int, int]:
        """在 YAML 行列表中找到指定顶级键的起止行索引。

        Args:
            lines: YAML 文件的逐行列表（保留换行符）
            key: 目标顶级键名

        Returns:
            (start_line, end_line) — 包含目标键的行和下一个顶级键的行

        Raises:
            ValueError: 未找到目标键
        """
        start: Optional[int] = None
        end = len(lines)

        for i, line in enumerate(lines):
            raw = line.rstrip("\n").rstrip("\r")
            if not raw:
                continue
            indent = len(line) - len(line.lstrip())
            stripped = raw.strip()

            # 找到目标键所在行
            if stripped == key or stripped.startswith(key + ":"):
                start = i
                continue

            # 找到下一个缩进为 0 的非注释行作为结束边界
            if start is not None and indent == 0 and not stripped.startswith("#"):
                end = i
                break

        if start is None:
            raise ValueError(f"Key '{key}' not found in YAML")

        return start, end

    @classmethod
    def _replace_supported_intents(
        cls, manifest_path: Path, keywords: list[str]
    ) -> None:
        """以文本方式安全替换 supported_intents 段的值。

        使用文本操作而非 yaml.dump 全量重写，目的是保留:
        - 文件头注释
        - 其他字段的注释
        - YAML 字段顺序和格式风格

        Args:
            manifest_path: manifest 文件路径
            keywords: 替换后的完整关键词列表
        """
        raw = manifest_path.read_text(encoding="utf-8")
        lines = raw.splitlines(keepends=True)

        # 定位 supported_intents 段
        start, end = cls._find_section_boundaries(lines, "supported_intents")

        # 生成新的 YAML 列表（缩进 2 空格）
        new_list_lines: list[str] = []
        if keywords:
            for kw in keywords:
                new_list_lines.append(f"  - {kw}\n")
        else:
            new_list_lines.append("  []\n")

        # 组装新文件
        new_lines = lines[: start + 1] + new_list_lines + lines[end:]

        manifest_path.write_text("".join(new_lines), encoding="utf-8")
