"""
政策知识管线编排器

串联现有提取模块：full text → LLM facts → rules + entities + relations
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from contextlib import AbstractContextManager, nullcontext
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    ExtractionOverride,
)
from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.semantic_alignment import (
        SemanticAlignmentService,
    )

logger = logging.getLogger(__name__)

_BASE_POLICY_FIELD_CODES = frozenset({
    "rule_id", "fact_id", "policy_id", "clause_id", "source_text",
    "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
    "payment_ratio", "deductible_amount", "cap_amount", "time_period",
    "admission_order", "amount_band", "priority", "rule_type", "rule_value",
})


LEGACY_FACT_EXTRACTION_PROMPT_TEMPLATE = """你是一个医保政策分析专家。请从以下政策文本中提取所有"政策事实"，并从每个事实中提取结构化的"政策规则"。

## 定义
- **政策事实**：一条完整的、可独立理解的政策规定。尽量覆盖原文中所有实质内容。
- **政策规则**：从事实中抽取的完全结构化规则（一条事实可包含多条规则），每条规则包含 19 个必填字段（原文未提及则填空字符串""）。
- **实体**：规则中涉及的主体（人员、机构、金额、比例等）/ **关系**：实体间的三元组。

## 19 个必填字段
rule_id / fact_id / policy_id / clause_id / source_text / insu_type / med_type / hosp_lv / psn_type / setl_type / payment_ratio / deductible_amount / cap_amount / time_period / admission_order / amount_band / priority / rule_type / rule_value

## 政策文件
{title}

## 原文
{text}

## 输出格式
返回 JSON 数组：
[
  {{
    "fact_text": "完整的事实描述",
    "rules": [{{
      "rule_id": "", "fact_id": "", "policy_id": "", "clause_id": "",
      "source_text": "原文精确片段", "insu_type": "镇职工基本医疗保险", "med_type": "住院",
      "hosp_lv": "三级", "psn_type": "退休人员", "setl_type": "按项目",
      "payment_ratio": "85%", "deductible_amount": "1300元", "cap_amount": "",
      "time_period": "年度", "admission_order": "首次", "amount_band": "1300-30000",
      "priority": "高", "rule_type": "支付比例", "rule_value": "...",
      "confidence": 0.92,
      "entities": [],
      "relations": []
    }}]
  }}
]

## 注意
1. 尽可能多地提取事实，覆盖原文中所有蕴含政策含义的语句
2. 每条规则填满全部 19 个字段，未提及填空字符串""
3. 只返回 JSON 数组，不要任何其他内容"""


class PolicyFactExtractionError(RuntimeError):
    """政策事实提取失败（模型不可用/输出不合法/截断不可恢复）。"""


class _TruncatedOutputError(RuntimeError):
    """内部信号：LLM 输出被 max_tokens 截断（finish_reason=length）。"""


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串（用于字段级溯源 extracted_at）。"""
    return datetime.now(timezone.utc).isoformat()


def _backfill_schema_fields(
    facts: list[dict[str, Any]], field_codes: list[str]
) -> list[dict[str, Any]]:
    """按提取契约回填缺失字段，并将复合人群拆成原子规则。"""
    if not field_codes:
        return facts
    for fact in facts:
        expanded: list[Any] = []
        for rule in fact.get("rules") or []:
            if isinstance(rule, dict):
                for code in field_codes:
                    rule.setdefault(code, "")
                populations = [
                    item.strip()
                    for item in re.split(r"[,，、]", str(rule.get("psn_type") or ""))
                    if item.strip()
                ]
                if len(populations) > 1:
                    base_id = str(rule.get("rule_id") or "rule").strip() or "rule"
                    expanded.extend(
                        {**rule, "rule_id": f"{base_id}_psn_{index}", "psn_type": population}
                        for index, population in enumerate(populations, 1)
                    )
                    continue
            expanded.append(rule)
        fact["rules"] = expanded
    return facts


class PipelineOrchestrator:
    """管线编排器：从政策原文中提取事实→规则→实体→关系"""

    def __init__(
        self,
        store: PipelineStore | None = None,
        alignment_service: "SemanticAlignmentService | None" = None,
    ):
        self._store = store or PipelineStore()
        self._alignment_service = alignment_service

    @property
    def store(self) -> PipelineStore:
        return self._store

    # ═══════════════ Extraction ═══════════════

    def run_extraction(self, doc_id: str) -> dict[str, Any]:
        """
        对指定政策原文执行全文事实提取：
        1. 获取原文 → 2. LLM 提取政策事实（含规则/实体/关系）
        3. 逐事实持久化 → 4. 计算覆盖率 → 5. 更新文档状态
        """
        doc = self._store.get_document(doc_id)
        if not doc:
            return {"success": False, "error": "文档不存在", "doc_id": doc_id}

        content = doc.get("content_text", "")
        if not content.strip():
            return {"success": False, "error": "文档内容为空", "doc_id": doc_id}

        run_token = uuid.uuid4().hex
        if not self._claim_extraction_run(doc_id, run_token):
            return {"success": False, "error": "无法声明提取任务", "doc_id": doc_id}

        try:
            # ── LLM 提取政策事实（长文档分片，避免 JSON 输出超 max_tokens 截断）──
            # 片长 1000：平衡“规则密集片仍截断”与“片数过多拖慢”（9069 字 → ~10 片）
            chunks = self._split_text(content, max_len=1000)
            facts: list[dict[str, Any]] = []
            for chunk in chunks:
                chunk_facts = self._extract_policy_facts_adaptive(
                    chunk, document_title=doc.get("title", "")
                )
                for fact in chunk_facts:
                    grounded_fact = dict(fact)
                    # 内部来源由编排器覆盖，模型无法伪造；持久化契约不会写入该字段。
                    grounded_fact["_source_context"] = chunk
                    facts.append(grounded_fact)

            if not facts:
                count = self._reconcile_extractions(doc_id, [], run_token=run_token)
                if count is None:
                    return self._stale_run_result(doc_id)
                with self._commit_extraction_run(doc_id, run_token) as current:
                    if not current or not self._finish_extraction_run(
                        doc_id, run_token, {"status": "extracted"}
                    ):
                        return self._stale_run_result(doc_id)
                self._intake_conflict_partitions(doc_id, [], mark_missing_stale=True)
                return {
                    "success": True,
                    "doc_id": doc_id,
                    "total_facts": 0,
                    "total_rules": 0,
                    "extractions_created": 0,
                    "coverage": {"ratio": 0, "covered_chars": 0, "total_chars": 0},
                }

            # ── 计算覆盖率 ──
            coverage = self._calculate_coverage(content, facts)

            # ── 每个事实 → 一条提取记录 ──
            from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
                _is_main_text_path,
                _path_text_parts,
                match_leaves,
                parse_kept_leaves,
            )

            _root, _by_id, _all_leaves, kept_leaves = parse_kept_leaves(
                content,
                doc.get("title", ""),
            )
            extraction_items: list[dict[str, Any]] = []
            grounding_texts: list[str] = []
            total_rules = 0
            for fact in facts:
                fact_rules = fact.get("rules", [])
                total_rules += len(fact_rules)
                matched_units = match_leaves(fact.get("fact_text", ""), kept_leaves)
                # 多匹配时优先正文段（修改决定 vs 正文重复），避免 unit_id 留空
                # （迭代 19 反思：重复单元导致全部 extraction 无归属）
                if len(matched_units) > 1:
                    _main = [
                        uid for uid in matched_units
                        if _is_main_text_path(
                            _path_text_parts(_by_id.get(uid), _by_id)
                        )
                    ]
                    if _main:
                        matched_units = _main[:1]
                unit_id = matched_units[0] if len(matched_units) == 1 else ""
                fact_text = str(fact.get("fact_text") or "")
                raw_context = str(fact.get("_source_context") or "")
                unit_node = _by_id.get(unit_id) if unit_id else None
                unit_text = str(getattr(unit_node, "text", "") or "")
                if fact_text and fact_text in raw_context:
                    grounding_text = fact_text
                elif unit_text and unit_text in raw_context:
                    grounding_text = unit_text
                else:
                    grounding_text = raw_context

                confidences = [r.get("confidence", 0.7) for r in fact_rules]
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.7

                extraction_items.append({
                    "extraction_id": self._stable_extraction_id(
                        doc_id, unit_id, fact.get("fact_text", "")
                    ),
                    "doc_id": doc_id,
                    "unit_id": unit_id,
                    "source_text": fact.get("fact_text", ""),
                    "extracted_fields": {
                        "fact_text": fact.get("fact_text", ""),
                        "rules": fact_rules,
                        "total_rules": len(fact_rules),
                    },
                    "confidence": round(avg_conf, 2),
                })
                grounding_texts.append(grounding_text)

            # ── 单事务 upsert 当前结果并归档差集，历史证据引用始终可查 ──
            count = self._reconcile_extractions(
                doc_id, extraction_items, run_token=run_token
            )
            if count is None:
                return self._stale_run_result(doc_id)
            with self._commit_extraction_run(doc_id, run_token) as current:
                if not current:
                    return self._stale_run_result(doc_id)
                for fact, item, grounding_text in zip(
                    facts, extraction_items, grounding_texts
                ):
                    self._intake_unknown_concepts(
                        fact,
                        doc_id=doc_id,
                        unit_id=item["unit_id"],
                        extraction_id=item["extraction_id"],
                        document_text=grounding_text,
                        run_token=run_token,
                    )
                if not self._finish_extraction_run(
                    doc_id,
                    run_token,
                    {
                        "status": "extracted",
                        "coverage_ratio": coverage["ratio"],
                        "coverage_detail": coverage,
                    },
                ):
                    return self._stale_run_result(doc_id)

            self._intake_conflict_partitions(
                doc_id, extraction_items, mark_missing_stale=True
            )
            return {
                "success": True,
                "doc_id": doc_id,
                "total_facts": len(facts),
                "total_rules": total_rules,
                "extractions_created": count,
                "coverage": coverage,
            }
        except Exception as e:
            logger.error("提取失败 doc_id=%s: %s", doc_id, e)
            self._finish_extraction_run(doc_id, run_token, {"status": "raw"})
            return {"success": False, "error": str(e), "doc_id": doc_id}

    # ═══════════════ Policy Fact Extraction (LLM) ═══════════════

    def _split_text(self, text: str, max_len: int = 1500) -> list[str]:
        """按段落切分长文档，每片不超过 max_len（段落粒度，不破坏句子）。

        长文档全文提取的 JSON 输出会超 max_tokens 被截断，分片后逐片提取可避免。
        """
        if len(text) <= max_len:
            return [text]
        chunks: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for para in text.split("\n"):
            plen = len(para)
            if cur and cur_len + plen > max_len:
                chunks.append("\n".join(cur))
                cur, cur_len = [], 0
            cur.append(para)
            cur_len += plen
        if cur:
            chunks.append("\n".join(cur))
        return chunks

    def extract_single(
        self,
        doc_id: str,
        source_text: str,
        unit_id: str = "",
        reset_status: str = "draft",
    ) -> dict[str, Any]:
        """对单段文本提取政策事实并创建一条提取记录（用于无提取记录的单元）。"""
        doc = self._store.get_document(doc_id)
        if not doc:
            return {"success": False, "error": "文档不存在", "doc_id": doc_id}
        try:
            facts = self._extract_policy_facts(source_text, document_title=doc.get("title", ""))
            if not facts:
                return {
                    "success": False,
                    "error": "LLM 未返回可构建的政策事实",
                    "doc_id": doc_id,
                    "unit_id": unit_id,
                }
            total_rules = sum(
                len(fact.get("rules", []) or []) for fact in facts
            )
            if total_rules == 0:
                return {
                    "success": False,
                    "error": "LLM 未返回可构建的政策规则",
                    "doc_id": doc_id,
                    "unit_id": unit_id,
                }
            extraction_items = []
            for fact in facts:
                fact_rules = fact.get("rules", [])
                confidences = [r.get("confidence", 0.7) for r in fact_rules]
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.7
                extraction_items.append({
                    "extraction_id": self._stable_extraction_id(
                        doc_id, unit_id, fact.get("fact_text", source_text)
                    ),
                    "doc_id": doc_id,
                    "unit_id": unit_id,
                    "source_text": fact.get("fact_text", source_text),
                    "extracted_fields": {
                        "fact_text": fact.get("fact_text", ""),
                        "rules": fact_rules,
                        "total_rules": len(fact_rules),
                    },
                    "confidence": round(avg_conf, 2),
                })
            count = self._store.batch_create_extractions(extraction_items)
            for fact, item in zip(facts, extraction_items):
                self._intake_unknown_concepts(
                    fact,
                    doc_id=doc_id,
                    unit_id=item["unit_id"],
                    extraction_id=item["extraction_id"],
                    document_text=source_text,
                )
            if reset_status != "draft":
                for item in extraction_items:
                    self._store.update_extraction(
                        item["extraction_id"], {"status": reset_status}
                    )
            # REBUILD 语义：单元级替换——归档该单元差集（保留外键，
            # list_extractions 默认过滤 archived），避免重抽无限累积。
            if unit_id:
                list_extractions = getattr(self._store, "list_extractions", None)
                if callable(list_extractions):
                    kept = {item["extraction_id"] for item in extraction_items}
                    stale = [
                        e
                        for e in list_extractions(
                            page=1, page_size=1000, doc_id=doc_id
                        ).get("items", [])
                        if e.get("unit_id") == unit_id
                        and e["extraction_id"] not in kept
                    ]
                    for stale_item in stale:
                        self._store.update_extraction(
                            stale_item["extraction_id"], {"status": "archived"}
                        )
            self._intake_conflict_partitions(
                doc_id, extraction_items, mark_missing_stale=False
            )
            return {
                "success": True,
                "doc_id": doc_id,
                "unit_id": unit_id,
                "extractions_created": count,
                "extraction_ids": [
                    item["extraction_id"] for item in extraction_items
                ],
                "facts": len(facts),
                "total_rules": total_rules,
            }
        except Exception as e:
            logger.error("单条提取失败 doc_id=%s: %s", doc_id, e)
            return {"success": False, "error": str(e), "doc_id": doc_id}

    def _extract_policy_facts_adaptive(
        self,
        chunk: str,
        document_title: str,
        *,
        min_chunk: int = 200,
        override: ExtractionOverride | None = None,
    ) -> list[dict[str, Any]]:
        """截断自适应提取：输出被 max_tokens 截断时把片对半细分，两半分别提取。

        密集表格页段落少密度高，固定 1000 字分片仍可能超出输出上限；
        检测 finish_reason=length 后按段落/字符对半细分（两半都提，不丢后半），
        直到 min_chunk。事实顺序按原文顺序拼接。
        """
        try:
            return self._extract_policy_facts(
                chunk, document_title, override=override,
                _raise_on_truncation=True,
            )
        except _TruncatedOutputError:
            if len(chunk) <= min_chunk:
                raise PolicyFactExtractionError(
                    "政策事实提取失败：分片已达下限仍被截断"
                )
            half = len(chunk) // 2
            split_at = chunk.rfind("\n", 0, half)
            if split_at < len(chunk) // 4:
                split_at = half
            head, tail = chunk[:split_at].strip(), chunk[split_at:].strip()
            logger.info(
                "提取输出被截断，细分重试 chunk=%d -> %d+%d",
                len(chunk), len(head), len(tail),
            )
            facts: list[dict[str, Any]] = []
            for part in (head, tail):
                if part:
                    facts.extend(self._extract_policy_facts_adaptive(
                        part, document_title, min_chunk=min_chunk, override=override,
                    ))
            return facts

    def _extract_policy_facts(
        self,
        document_text: str,
        document_title: str = "",
        override: ExtractionOverride | None = None,
        _raise_on_truncation: bool = False,
    ) -> list[dict[str, Any]]:
        """LLM 全文提取政策事实、规则、实体和关系。

        一次 LLM 调用完成三件事：
        1. 识别所有政策事实（自包含的政策规定）
        2. 从每个事实抽取结构化规则
        3. 标注实体和关系

        ``override`` 非空时按其覆盖提示词模式 / 模型 / max_tokens（迭代 18）。
        失败时返回空列表（由调用方处理）。
        """
        if not document_text.strip():
            return []

        prompt = self._build_fact_extraction_prompt(document_text, document_title, override)
        # schema 模式下按契约回填缺失字段键（LLM 常省略，实测只回 4/24 字段）
        mode = override.prompt_mode if override and override.prompt_mode else "schema"
        field_codes = self._schema_field_codes() if mode == "schema" else []

        try:
            gateway = ModelGateway()
            messages = [Message(role="user", content=prompt)]
            # 长文档提取的 JSON 输出常超 router 默认 max_tokens 被截断，
            # 这里显式放大输出空间（P8.4 迁移后重提取所需）。
            # override.max_tokens 可覆盖默认 8192（迭代 18）。
            max_tokens = override.max_tokens if override and override.max_tokens else 8192
            generate_kwargs: dict[str, Any] = {
                "messages": messages,
                "model_type": "llm",
                "scene": "policy_fact_extraction",
                "max_tokens": max_tokens,
            }
            if override and override.model_name:
                # 审核时显式换大模型：仅在用户指定时才传入，避免干扰默认路由
                generate_kwargs["model_override"] = override.model_name
            response = gateway.generate(**generate_kwargs)
            if _raise_on_truncation and getattr(response, "finish_reason", None) == "length":
                raise _TruncatedOutputError(str(len(response.content)))

            content = response.content.strip()
            if content.startswith("```"):
                parts = content.split("```")
                content = parts[1] if len(parts) >= 2 else content
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            facts = json.loads(content)
            if isinstance(facts, list):
                if not all(isinstance(item, dict) for item in facts):
                    raise ValueError("facts 数组元素必须是对象")
                logger.info(
                    "Extracted %d policy facts from %r",
                    len(facts), document_title,
                )
                return _backfill_schema_fields(facts, field_codes)
            if isinstance(facts, dict):
                if "facts" in facts:
                    facts_list = facts["facts"]
                    if not isinstance(facts_list, list) or not all(
                        isinstance(item, dict) for item in facts_list
                    ):
                        raise ValueError("facts 字段必须是对象数组")
                    logger.info(
                        "Extracted %d policy facts from %r (nested)",
                        len(facts_list), document_title,
                    )
                    return _backfill_schema_fields(facts_list, field_codes)
                # 单条事实或单条规则包装为事实
                if "fact_text" in facts:
                    logger.info("LLM returned single fact dict, wrapping as list")
                    return _backfill_schema_fields([facts], field_codes)
                if "rule_type" in facts:
                    logger.info("LLM returned single rule dict, wrapping as fact")
                    return _backfill_schema_fields(
                        [{"fact_text": facts.get("source_text", ""), "rules": [facts]}],
                        field_codes,
                    )

            raise ValueError(f"Unexpected LLM response type: {type(facts).__name__}")
        except _TruncatedOutputError:
            raise  # 截断信号交给自适应层细分重试，不在这里包装
        except Exception as e:
            logger.warning("Policy fact extraction failed: %s", e)
            raise PolicyFactExtractionError("政策事实提取失败") from e

    def _schema_field_codes(self) -> list[str]:
        """提取契约字段短码（schema 模式回填缺失字段用；失败返回空）。"""
        try:
            from src.semantic_layer.registry import create_registry
            from src.semantic_layer.extraction_contract import build_extraction_schema
            return [
                f.code
                for f in build_extraction_schema(create_registry(), "zcgz").fields
            ]
        except Exception:
            return []

    def _build_fact_extraction_prompt(
        self,
        text: str,
        title: str,
        override: ExtractionOverride | None = None,
    ) -> str:
        """构建事实提取 prompt（schema-driven，§3.1）。

        提示词模式（迭代 18）：
        - ``custom``：用 ``override.custom_prompt``，替换 ``{title}``/``{text}`` 占位符，
          不自动注入指标（由用户自行包含）。
        - ``schema``（默认）：从语义层读 zcgz 对象的 published 指标契约，动态拼提示词
          （加维度不改代码）。registry 不可用或契约空时用硬编码 legacy prompt。
        - ``legacy``：跳过 schema 契约，直接用硬编码 19 字段 prompt。
        """
        mode = override.prompt_mode if override and override.prompt_mode else "schema"

        if mode == "custom" and override and override.custom_prompt:
            return (
                override.custom_prompt
                .replace("{title}", title)
                .replace("{text}", text)
            )

        if mode == "schema":
            from src.semantic_layer.registry import create_registry
            from src.semantic_layer.extraction_contract import (
                build_extraction_schema, build_prompt_from_schema,
            )
            try:
                schema = build_extraction_schema(create_registry(), "zcgz")
                field_codes = {field.code for field in schema.fields}
                if _BASE_POLICY_FIELD_CODES <= field_codes:
                    return build_prompt_from_schema(text, title, schema)
            except Exception:
                pass

        return self._legacy_fact_extraction_prompt(text, title)

    def _legacy_fact_extraction_prompt(self, text: str, title: str) -> str:
        """[legacy] 硬编码 19 字段 prompt（registry 不可用时的回退）。"""
        from src.semantic_layer.extraction_contract import (
            EXTRACTION_QUALITY_GUIDANCE,
            UNKNOWN_CONCEPT_GUIDANCE,
        )

        return f"""你是一个医保政策分析专家。请从以下政策文本中提取所有"政策事实"，并从每个事实中提取结构化的"政策规则"。

## 定义
- **政策事实**：一条完整的、可独立理解的政策规定。尽量覆盖原文中所有实质内容。
- **政策规则**：从事实中抽取的完全结构化规则（一条事实可包含多条规则）。
  每条规则必须包含以下全部 19 个字段（原文未提及则填空字符串""）。
- **实体**：规则中涉及的主体（人员、机构、金额、比例等），标注 highlight 为原文中的精确文本。
- **关系**：实体之间的语义关系，用三元组 (主体, 关系, 客体) 表示。

## 19 个必填字段说明（来自数据模型1-政策规则表）
1. rule_id: 规则唯一标识（留空，系统生成）
2. fact_id: 来源事实标识（留空）
3. policy_id: 政策文件标识（留空）
4. clause_id: 条款标识（留空）
5. source_text: 原始政策文本片段（填入原文精确内容，用于溯源）
6. insu_type: 险种类别（城镇职工基本医疗保险/城乡居民基本医疗保险/大病保险/工伤保险/生育保险）
7. med_type: 医疗类别（住院/门诊/门特/急诊/购药）
8. hosp_lv: 医疗机构等级（三级/二级/一级及以下/社区卫生服务中心/社区卫生服务站/基层医疗机构/未定级）
9. psn_type: 人群标签（在职职工/退休人员/城乡居民/学生儿童/灵活就业/困难人群）— 可嵌套多个值
10. setl_type: 结算方式（按项目/DRG/DIP/按病种/按人头/按床日）
11. payment_ratio: 支付比例（如"85%"）
12. deductible_amount: 起付金额（如"1300元"）
13. cap_amount: 封顶金额（如"30万元"）
14. time_period: 时间周期（年度/季度/月度/单次）
15. admission_order: 住院次数（首次/二次及以上/不限）
16. amount_band: 金额分段（如"30000-40000"）
17. priority: 规则优先级（高/中/低）
18. rule_type: 规则类型（起付线/支付比例/封顶线/排除规则/适用范围/通用规则）— 可嵌套
19. rule_value: 规则值 — 可嵌套，描述规则的具体计算逻辑或条件

## 政策文件
{title}

## 原文
{text}

## 输出格式
返回 JSON 数组：
[
  {{
    "fact_text": "完整的事实描述（含上下文，可独立理解）",
    "rules": [
      {{
        "rule_id": "",
        "fact_id": "",
        "policy_id": "",
        "clause_id": "",
        "source_text": "原文精确片段",
        "insu_type": "城镇职工基本医疗保险",
        "med_type": "住院",
        "hosp_lv": "三级",
        "psn_type": "退休人员",
        "setl_type": "按项目",
        "payment_ratio": "85%",
        "deductible_amount": "1300元",
        "cap_amount": "",
        "time_period": "年度",
        "admission_order": "首次",
        "amount_band": "1300-30000",
        "priority": "高",
        "rule_type": "支付比例",
        "rule_value": "起付标准以上至3万元部分，统筹基金支付85%",
        "confidence": 0.92,
        "entities": [
          {{"name": "参保人员", "type": "PERSON", "highlight": "参保人员"}},
          {{"name": "1300元", "type": "AMOUNT", "highlight": "1300元"}}
        ],
        "relations": [
          {{"subject": "参保人员", "predicate": "起付标准", "object": "1300元"}}
        ]
      }}
    ],
    "unknown_concepts": []
  }}
]

## 实体类型
PERSON(人员), ORG(机构), SERVICE(医疗服务), AMOUNT(金额), RATIO(比例),
DISEASE(病种), DRUG(药品), DATE(日期), CONDITION(条件), LOCATION(地点)

## 注意
1. 尽可能多地提取事实，**覆盖原文中所有蕴含政策含义的语句**
2. 每个事实可包含多条规则，每条规则必须填满全部 19 个字段
3. 未提及的字段填空字符串 ""
4. 只返回 JSON 数组，不要任何其他内容

{EXTRACTION_QUALITY_GUIDANCE}
{UNKNOWN_CONCEPT_GUIDANCE}"""

    def _intake_unknown_concepts(
        self,
        fact: dict[str, Any],
        *,
        doc_id: str,
        unit_id: str,
        extraction_id: str,
        document_text: str,
        run_token: str | None = None,
    ) -> None:
        """把 LLM 未知概念转为带原文证据的 S1 信号；失败不阻断主提取。"""
        unknowns = fact.get("unknown_concepts")
        if not isinstance(unknowns, list):
            return
        for item in unknowns:
            try:
                if run_token and not self._is_extraction_run_current(doc_id, run_token):
                    logger.info(
                        "全文提取运行已过期，停止未知概念入队 doc_id=%s extraction_id=%s",
                        doc_id,
                        extraction_id,
                    )
                    return
                if not isinstance(item, dict):
                    raise ValueError("unknown_concepts 项必须是对象")
                concept = str(item.get("concept") or "").strip()
                if not concept:
                    raise ValueError("未知概念串不能为空")
                excerpt = self._verified_excerpt(document_text, concept)
                if excerpt is None:
                    logger.warning(
                        "未知概念证据未在输入原文定位，已跳过 doc_id=%s unit_id=%s extraction_id=%s",
                        doc_id,
                        unit_id,
                        extraction_id,
                    )
                    continue
                occurrence_count = document_text.count(concept)

                from src.knowledge_extension.rule_explanation.semantic_alignment import (
                    DiscoveryEvidence,
                    DiscoverySignal,
                    TriggerSource,
                    get_semantic_alignment_service,
                )

                alignment_service = (
                    self._alignment_service or get_semantic_alignment_service()
                )
                signal_fields = {
                    key: item[key]
                    for key in (
                        "object_code", "metric_code", "metric_name", "definition",
                        "metric_type", "semantic_type", "unit", "value_domain",
                        "metric_kind", "indexed", "extraction_hint", "schema_version",
                        "axis_metric_code", "domain_code", "alias_target", "confidence",
                    )
                    if item.get(key) is not None
                }
                concept_identity = hashlib.sha256(
                    " ".join(concept.casefold().split()).encode("utf-8")
                ).hexdigest()[:16]
                # 政策解读类纯文本可能没有编号条款，仍以文档级稳定单元保留证据。
                evidence_unit_id = unit_id or f"document:{doc_id}"
                alignment_service.intake_signal(DiscoverySignal(
                    trigger_source=TriggerSource.EXTRACTION_UNKNOWN,
                    concept=concept,
                    evidence=DiscoveryEvidence(
                        source_ref=(
                            f"policy-extraction:{doc_id}:{evidence_unit_id}:{concept_identity}"
                        ),
                        doc_id=doc_id,
                        unit_id=evidence_unit_id,
                        extraction_id=extraction_id,
                        excerpt=excerpt,
                        occurrence_count=occurrence_count,
                    ),
                    **signal_fields,
                ))
            except Exception:
                logger.exception(
                    "未知概念提议入队失败 doc_id=%s unit_id=%s extraction_id=%s",
                    doc_id,
                    unit_id,
                    extraction_id,
                )

    def run_conflict_partition_discovery(self, doc_id: str) -> dict[str, Any]:
        """聚合视角运行 S5：以文档为单位读取当前全部提取记录做冲突分区诊断。

        对齐 2026-08-14 S5 设计 §十二「抽取快照完成统一阶段」：塌缩常跨
        单元/跨 rule_type（如统筹 85% vs 大额 80% 分属不同单元），单 fact
        快照内不可见，需聚合后诊断。幂等：同快照内容产出同 fingerprint。
        """
        list_extractions = getattr(self._store, "list_extractions", None)
        if not callable(list_extractions):
            return {"success": False, "error": "存储不支持提取记录列举", "doc_id": doc_id}
        result = list_extractions(page=1, page_size=1000, doc_id=doc_id)
        items = result.get("items", []) if isinstance(result, dict) else []
        self._intake_conflict_partitions(doc_id, items, mark_missing_stale=True)
        return {"success": True, "doc_id": doc_id, "extractions": len(items)}

    def _intake_conflict_partitions(
        self,
        doc_id: str,
        extraction_items: list[dict[str, Any]],
        *,
        mark_missing_stale: bool,
    ) -> None:
        """基于已持久化的同一快照运行 S5；失败不影响主抽取结果。"""
        try:
            from src.knowledge_extension.rule_explanation.conflict_partition_discovery import (
                ExtractionEntity,
                ExtractionRelation,
                ExtractionRule,
                discover_conflict_partitions,
            )
            from src.knowledge_extension.rule_explanation.semantic_alignment import (
                get_semantic_alignment_service,
            )

            snapshot_payload = [
                {
                    "extraction_id": item.get("extraction_id"),
                    "unit_id": item.get("unit_id"),
                    "rules": (item.get("extracted_fields") or {}).get("rules", []),
                }
                for item in sorted(
                    extraction_items, key=lambda value: str(value.get("extraction_id") or "")
                )
            ]
            snapshot_id = "snapshot_" + hashlib.sha256(json.dumps(
                snapshot_payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")).hexdigest()[:24]
            rules: list[ExtractionRule] = []
            for item in extraction_items:
                fields = item.get("extracted_fields") or {}
                for index, raw in enumerate(fields.get("rules") or []):
                    if not isinstance(raw, dict):
                        continue
                    raw_rule_type = self._plain_value(raw.get("rule_type"))
                    rule_type = str(raw_rule_type or "").strip()
                    value, unit = self._conflict_rule_value(raw, rule_type)
                    if value in (None, ""):
                        continue
                    rule_id = str(raw.get("rule_id") or "").strip() or (
                        f"{item.get('extraction_id') or 'extraction'}_r{index + 1}"
                    )
                    entities = []
                    raw_entities = self._plain_value(raw.get("entities"))
                    for entity_index, entity in enumerate(
                        raw_entities if isinstance(raw_entities, list) else []
                    ):
                        if not isinstance(entity, dict) or not str(entity.get("name") or "").strip():
                            continue
                        entities.append(ExtractionEntity(
                            entity_id=str(entity.get("entity_id") or "").strip()
                            or f"{rule_id}_e{entity_index + 1}",
                            name=str(entity["name"]).strip(),
                            entity_type=str(entity.get("entity_type") or entity.get("type") or ""),
                            highlight=entity.get("highlight"),
                            binding_scope=entity.get("binding_scope") or "rule",
                        ))
                    relations = []
                    raw_relations = self._plain_value(raw.get("relations"))
                    for relation in raw_relations if isinstance(raw_relations, list) else []:
                        if not isinstance(relation, dict):
                            continue
                        subject = str(relation.get("subject") or "").strip()
                        predicate = str(relation.get("predicate") or "").strip()
                        object_value = str(
                            relation.get("object_value") or relation.get("object") or ""
                        ).strip()
                        if subject and predicate and object_value:
                            relations.append(ExtractionRelation(
                                subject=subject,
                                predicate=predicate,
                                object_value=object_value,
                                rule_id=rule_id,
                                binding_scope=relation.get("binding_scope") or "rule",
                            ))
                    try:
                        rules.append(ExtractionRule(
                            rule_id=rule_id,
                            document_id=doc_id,
                            snapshot_id=snapshot_id,
                            extraction_contract_version=str(
                                fields.get("schema_version") or raw.get("schema_version") or "unknown"
                            ),
                            rule_type=rule_type,
                            rule_value=value,
                            rule_unit=unit,
                            insu_type=self._optional_text(raw.get("insu_type")),
                            med_type=self._optional_text(raw.get("med_type")),
                            psn_type=self._optional_text(raw.get("psn_type")),
                            hosp_lv=self._optional_text(raw.get("hosp_lv")),
                            setl_type=self._optional_text(raw.get("setl_type")),
                            effective_start=self._plain_value(raw.get("effective_start")) or None,
                            effective_end=self._plain_value(raw.get("effective_end")) or None,
                            region_code=self._optional_text(raw.get("region_code")),
                            entities=entities,
                            relations=relations,
                            source_clause_id=str(
                                raw.get("clause_id") or item.get("unit_id") or rule_id
                            ),
                            evidence_text=str(
                                raw.get("source_text") or item.get("source_text") or ""
                            ),
                        ))
                    except ValueError:
                        logger.warning(
                            "S5 跳过无效规则 doc_id=%s rule_id=%s", doc_id, rule_id
                        )
            report = discover_conflict_partitions(rules)
            service = self._alignment_service or get_semantic_alignment_service()
            intake = getattr(service, "intake_conflict_report", None)
            if callable(intake):
                intake(
                    report,
                    document_id=doc_id,
                    snapshot_id=snapshot_id,
                    mark_missing_stale=mark_missing_stale,
                )
        except Exception:
            logger.exception("S5 冲突分区诊断失败 doc_id=%s", doc_id)

    @staticmethod
    def _plain_value(value: Any) -> Any:
        return value.get("value") if isinstance(value, dict) and "value" in value else value

    @classmethod
    def _optional_text(cls, value: Any) -> str | None:
        text = str(cls._plain_value(value) or "").strip()
        return text or None

    @classmethod
    def _conflict_rule_value(
        cls, raw: dict[str, Any], rule_type: str
    ) -> tuple[Any, str | None]:
        if "比例" in rule_type or "ratio" in rule_type.casefold():
            keys, unit = ("payment_ratio", "personal_payment_ratio"), "%"
        elif "起付" in rule_type or "deductible" in rule_type.casefold():
            keys, unit = ("deductible_amount",), "元"
        elif any(token in rule_type for token in ("封顶", "限额")) or "cap" in rule_type.casefold():
            keys, unit = ("cap_amount",), "元"
        else:
            keys, unit = (), cls._optional_text(raw.get("rule_unit"))
        for key in (*keys, "rule_value"):
            value = cls._plain_value(raw.get(key))
            if value not in (None, ""):
                return value, unit
        return None, unit

    @staticmethod
    def _verified_excerpt(document_text: str, concept: str) -> str | None:
        """仅从原始概念的实际位置截取证据，禁止无关 excerpt 绕过。"""
        position = document_text.find(concept)
        if position >= 0:
            return document_text[max(0, position - 100):position + len(concept) + 100]
        return None

    @staticmethod
    def _stable_extraction_id(doc_id: str, unit_id: str, source_text: str) -> str:
        """相同文档、单元和事实重跑复用 ID，使提议证据不会指向已删记录。"""
        identity = "\0".join((doc_id, unit_id, source_text))
        return f"ext_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}"

    def _reconcile_extractions(
        self,
        doc_id: str,
        extraction_items: list[dict[str, Any]],
        run_token: str | None = None,
    ) -> int | None:
        """生产存储单事务对账；极简 fake 沿用批量创建接口。"""
        reconcile = getattr(self._store, "reconcile_extractions", None)
        if callable(reconcile):
            if run_token is not None:
                return reconcile(doc_id, extraction_items, run_token=run_token)
            return reconcile(doc_id, extraction_items)
        if run_token and not self._is_extraction_run_current(doc_id, run_token):
            return None
        return self._store.batch_create_extractions(extraction_items)

    def _claim_extraction_run(self, doc_id: str, run_token: str) -> bool:
        claim = getattr(self._store, "claim_extraction_run", None)
        if callable(claim):
            return bool(claim(doc_id, run_token))
        self._store.update_document(doc_id, {
            "status": "processing",
            "extraction_run_token": run_token,
        })
        return True

    def _is_extraction_run_current(self, doc_id: str, run_token: str) -> bool:
        check = getattr(self._store, "is_extraction_run_current", None)
        if callable(check):
            return bool(check(doc_id, run_token))
        doc = self._store.get_document(doc_id)
        stored_token = doc.get("extraction_run_token") if doc else None
        return bool(doc and (stored_token is None or stored_token == run_token))

    def _finish_extraction_run(
        self, doc_id: str, run_token: str, data: dict[str, Any]
    ) -> bool:
        finish = getattr(self._store, "finish_extraction_run", None)
        if callable(finish):
            return bool(finish(doc_id, run_token, data))
        if not self._is_extraction_run_current(doc_id, run_token):
            return False
        self._store.update_document(doc_id, data)
        return True

    def _commit_extraction_run(
        self, doc_id: str, run_token: str
    ) -> AbstractContextManager[bool]:
        commit = getattr(self._store, "commit_extraction_run", None)
        if callable(commit):
            return commit(doc_id, run_token)
        return nullcontext(self._is_extraction_run_current(doc_id, run_token))

    @staticmethod
    def _stale_run_result(doc_id: str) -> dict[str, Any]:
        return {
            "success": False,
            "error": "提取任务已被更新运行取代",
            "doc_id": doc_id,
        }

    # ═══════════════ Coverage ═══════════════

    @staticmethod
    def _calculate_coverage(document_text: str, document_title: str = "") -> dict[str, Any]:
        """结构单元产出率 = kept_units / all_units。

        覆盖率语义：政策原文经结构拆分后，去重保留的叶子单元占全部叶子的比例。
        - 单元 = 文档结构叶子（条/项/目），由 Python 确定性拆分得到。
        - 网页抓取的导航/搜索样板噪声在 parse 阶段已被剔除，不计入分母。
        - 因此一篇正常提取的政策文档覆盖率通常接近 100%（提取单元无遗漏）。

        [变更] 旧实现按 LLM 提取的 fact_text 在原文中逐字/k-gram 匹配字符位置，
        既受 LLM 改写影响、又被文档噪声稀释，数值偏低且语义模糊，已废弃。
        """
        try:
            from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import parse_kept_leaves
            _root, _by_id, all_leaves, kept = parse_kept_leaves(document_text or "", document_title or "")
        except Exception:
            logger.exception("parse_kept_leaves failed in coverage calc")
            return {"ratio": 0, "kept_units": 0, "total_units": 0}
        total = len(all_leaves)
        kept_n = len(kept)
        ratio = round(min(kept_n / total, 1.0), 2) if total else 0
        return {"ratio": ratio, "kept_units": kept_n, "total_units": total}

    # ═══════════════ Regex Fallback ═══════════════

    def _fill_fields_by_pattern(self, text: str, fields: dict[str, str]) -> None:
        """简单正则匹配填充字段（LLM 失败时的降级方案）"""
        # 支付比例：85%、支付85%
        m = re.search(r"支付\s*(\d+)\s*%|(\d+)\s*%\s*支付", text)
        if m:
            fields["payment_ratio"] = m.group(1) or m.group(2)

        # 起付金额：起付标准为300元、起付线800元
        m = re.search(r"起付[标准线].*?(\d+)\s*元", text)
        if m:
            fields["deductible_amount"] = m.group(1)

        # 封顶金额：最高支付限额30万元
        m = re.search(r"最高.*?(\d+)\s*万?元", text)
        if m:
            val = m.group(1)
            if "万" in m.group(0):
                val = str(int(val) * 10000)
            fields["cap_amount"] = val

        # 医院等级
        for keyword, val in [("三级", "三级医院"), ("二级", "二级医院"), ("一级", "一级医院"), ("社区", "社区医院")]:
            if keyword in text:
                fields["hosp_lv"] = val
                break

        # 住院次数
        m = re.search(r"第\s*([一二三四五六七八九十百千]+)\s*次", text)
        if m:
            num_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5"}
            fields["admission_order"] = num_map.get(m.group(1), "1")

    # ═══════════════ Publish to new collections (P3) ═══════════════

    def publish_to_new_collections(self, extraction_id: str) -> dict[str, Any]:
        """将审核通过的提取结果发布到新 collection（policy_facts + policy_rules_v2）。

        与 publish_extraction（写旧 policy_rules）并存，互不影响（隔离，P10 才切换）。
        """
        ext = self._store.get_extraction(extraction_id)
        if not ext:
            return {"success": False, "error": "提取记录不存在"}
        if ext["status"] != "reviewed":
            return {"success": False, "error": "只有已审核的提取记录才能入库"}

        fields = ext["extracted_fields"]
        if isinstance(fields, str):
            fields = json.loads(fields)
        fact_text = fields.get("fact_text", "") or ext.get("source_text", "")
        rules = fields.get("rules", [])
        doc_id = ext["doc_id"]
        extracted_at = _now_iso()

        try:
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
                create_policy_facts_collection, upsert_facts,
            )
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
                create_policy_rules_v2_collection, upsert_rules,
            )
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_ingestion import (
                build_ingest_records,
            )
            from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
                get_embedding_provider,
            )
        except ImportError as e:
            return {"success": False, "error": f"依赖缺失: {e}"}

        try:
            provider = get_embedding_provider()
            facts_col = create_policy_facts_collection()
            rules_col = create_policy_rules_v2_collection()

            fact_records, rule_entities = build_ingest_records(
                [{"fact_text": fact_text, "rules": rules}],
                doc_id=doc_id, provider=provider, extracted_at=extracted_at,
            )
            upsert_facts(facts_col, fact_records)
            upsert_rules(rules_col, rule_entities)

            rule_ids = [e["rule_id"] for e in rule_entities]
            for rid in rule_ids:
                self._store.create_lineage(rid, extraction_id, doc_id)
            self._store.update_extraction(extraction_id, {"status": "published"})

            return {
                "success": True,
                "extraction_id": extraction_id,
                "fact_id": fact_records[0]["fact_id"] if fact_records else "",
                "rule_ids": rule_ids,
                "published_count": len(rule_ids),
                "target": "policy_facts + policy_rules_v2",
            }
        except Exception as e:
            logger.error("发布到新 collection 失败 ext=%s: %s", extraction_id, e)
            return {"success": False, "error": str(e), "extraction_id": extraction_id}

    # ═══════════════ Single-unit Re-extraction (LLM) ═══════════════

    def reextract_unit(
        self,
        extraction_id: str,
        override: ExtractionOverride | None = None,
        reset_status: str = "draft",
    ) -> dict[str, Any]:
        """对单个单元重新调用 LLM 提取（人工审核不通过后触发）。

        复用 _extract_policy_facts：用单元 source_text 作为输入，取首条事实覆盖
        extracted_fields，置信度回填规则均值，状态重置为 ``reset_status``。

        - ``reset_status="draft"``（默认，体系 A 单元审核）：重提取后需重新走单元审核。
        - ``reset_status="reviewed"``（体系 B 变更集重提取）：保持单元在工作台可见，
          新内容进入 PENDING_REVIEW 变更集接受审核（变更集状态即"需重新审核"信号）。

        ``override`` 非空时按其覆盖提示词模式 / 模型（迭代 18），并将覆盖配置
        写入 ``last_override`` 审计字段（来源可追溯）。
        """
        ext = self._store.get_extraction(extraction_id)
        if not ext:
            return {"success": False, "error": "提取记录不存在"}
        doc = self._store.get_document(ext["doc_id"])
        title = doc.get("title", "") if doc else ""
        source = ext.get("source_text") or ext.get("extracted_fields", {}).get("fact_text", "")
        if not source.strip():
            return {"success": False, "error": "单元无源文本，无法重提取"}

        try:
            facts = self._extract_policy_facts(source, title, override=override)
        except PolicyFactExtractionError as exc:
            return {"success": False, "error": str(exc), "extraction_id": extraction_id}
        if not facts:
            return {"success": False, "error": "LLM 未返回结果（请检查 MODEL_API_KEY 与模型配置）"}

        fact = facts[0]
        rules = fact.get("rules", []) or []
        confs = [float(r.get("confidence", 0.7) or 0.7) for r in rules]
        avg_conf = round(sum(confs) / len(confs), 2) if confs else 0.7

        merged_fields = {**(ext.get("extracted_fields") or {})}
        merged_fields["fact_text"] = fact.get("fact_text", source)
        merged_fields["rules"] = rules
        merged_fields["total_rules"] = len(rules)
        merged_fields.pop("unknown_concepts", None)
        merged_fields.pop("audit_reason", None)  # 重提取清除上次驳回原因

        update = {
            "extracted_fields": merged_fields,
            "confidence": avg_conf,
            "status": reset_status,  # 体系 A=draft / 体系 B=reviewed（保持可见）
        }
        override_dump = override.model_dump() if override else None
        if override_dump is not None:
            # 审计字段：记录本次重提取用的提示词 / 模型覆盖（来源可追溯）
            update["last_override"] = override_dump

        updated = self._store.update_extraction(extraction_id, update)
        for extracted_fact in facts:
            self._intake_unknown_concepts(
                extracted_fact,
                doc_id=ext["doc_id"],
                unit_id=ext.get("unit_id", ""),
                extraction_id=extraction_id,
                document_text=source,
            )
        self._intake_conflict_partitions(
            ext["doc_id"],
            [{
                **ext,
                "source_text": source,
                "extracted_fields": merged_fields,
            }],
            mark_missing_stale=False,
        )
        return {
            "success": True,
            "extraction_id": extraction_id,
            "extraction": updated,
            "override_applied": override_dump,
        }
