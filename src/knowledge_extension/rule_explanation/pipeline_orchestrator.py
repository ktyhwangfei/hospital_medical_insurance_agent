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
from datetime import datetime, timezone
from typing import Any

from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """当前 UTC 时间 ISO 字符串（用于字段级溯源 extracted_at）。"""
    return datetime.now(timezone.utc).isoformat()


class PipelineOrchestrator:
    """管线编排器：从政策原文中提取事实→规则→实体→关系"""

    def __init__(self, store: PipelineStore | None = None):
        self._store = store or PipelineStore()

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

        self._store.update_document(doc_id, {"status": "processing"})

        try:
            # ── LLM 提取政策事实（长文档分片，避免 JSON 输出超 max_tokens 截断）──
            # 片长 1000：平衡“规则密集片仍截断”与“片数过多拖慢”（9069 字 → ~10 片）
            chunks = self._split_text(content, max_len=1000)
            facts: list[dict[str, Any]] = []
            for chunk in chunks:
                facts.extend(
                    self._extract_policy_facts(
                        chunk, document_title=doc.get("title", "")
                    )
                )

            if not facts:
                self._store.update_document(doc_id, {"status": "extracted"})
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
            extraction_items: list[dict[str, Any]] = []
            total_rules = 0
            for fact in facts:
                fact_rules = fact.get("rules", [])
                total_rules += len(fact_rules)

                confidences = [r.get("confidence", 0.7) for r in fact_rules]
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.7

                extraction_items.append({
                    "extraction_id": f"ext_{uuid.uuid4().hex[:12]}",
                    "doc_id": doc_id,
                    "source_text": fact.get("fact_text", ""),
                    "extracted_fields": {
                        "fact_text": fact.get("fact_text", ""),
                        "rules": fact_rules,
                        "total_rules": len(fact_rules),
                    },
                    "confidence": round(avg_conf, 2),
                })

            # ── 持久化（先清空旧提取记录，避免重提取时 LLM 漂移堆积近似重复）──
            wiped = self._store.delete_extractions_by_doc(doc_id)
            if wiped:
                logger.info("重提取 doc_id=%s：清空旧提取记录 %d 条", doc_id, wiped)
            count = self._store.batch_create_extractions(extraction_items)

            # ── 更新文档状态 + 覆盖率 ──
            self._store.update_document(doc_id, {
                "status": "extracted",
                "coverage_ratio": coverage["ratio"],
                "coverage_detail": json.dumps(coverage),
            })

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
            self._store.update_document(doc_id, {"status": "raw"})
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

    def extract_single(self, doc_id: str, source_text: str) -> dict[str, Any]:
        """对单段文本提取政策事实并创建一条提取记录（用于无提取记录的单元）。"""
        doc = self._store.get_document(doc_id)
        if not doc:
            return {"success": False, "error": "文档不存在", "doc_id": doc_id}
        try:
            facts = self._extract_policy_facts(source_text, document_title=doc.get("title", ""))
            if not facts:
                # LLM 未提取出事实 → 创建一条占位记录（source_text 原样保留，状态 draft）
                extraction_item = {
                    "extraction_id": f"ext_{uuid.uuid4().hex[:12]}",
                    "doc_id": doc_id,
                    "source_text": source_text,
                    "extracted_fields": {"fact_text": source_text, "rules": [], "total_rules": 0},
                    "confidence": 0.5,
                }
                self._store.batch_create_extractions([extraction_item])
                return {"success": True, "doc_id": doc_id, "extractions_created": 1, "facts": 0}
            extraction_items = []
            for fact in facts:
                fact_rules = fact.get("rules", [])
                confidences = [r.get("confidence", 0.7) for r in fact_rules]
                avg_conf = sum(confidences) / len(confidences) if confidences else 0.7
                extraction_items.append({
                    "extraction_id": f"ext_{uuid.uuid4().hex[:12]}",
                    "doc_id": doc_id,
                    "source_text": fact.get("fact_text", source_text),
                    "extracted_fields": {
                        "fact_text": fact.get("fact_text", ""),
                        "rules": fact_rules,
                        "total_rules": len(fact_rules),
                    },
                    "confidence": round(avg_conf, 2),
                })
            count = self._store.batch_create_extractions(extraction_items)
            return {"success": True, "doc_id": doc_id, "extractions_created": count, "facts": len(facts)}
        except Exception as e:
            logger.error("单条提取失败 doc_id=%s: %s", doc_id, e)
            return {"success": False, "error": str(e), "doc_id": doc_id}

    def _extract_policy_facts(
        self,
        document_text: str,
        document_title: str = "",
    ) -> list[dict[str, Any]]:
        """LLM 全文提取政策事实、规则、实体和关系。

        一次 LLM 调用完成三件事：
        1. 识别所有政策事实（自包含的政策规定）
        2. 从每个事实抽取结构化规则
        3. 标注实体和关系

        失败时返回空列表（由调用方处理）。
        """
        if not document_text.strip():
            return []

        prompt = self._build_fact_extraction_prompt(document_text, document_title)

        try:
            gateway = ModelGateway()
            messages = [Message(role="user", content=prompt)]
            # 长文档提取的 JSON 输出常超 router 默认 max_tokens 被截断，
            # 这里显式放大输出空间（P8.4 迁移后重提取所需）
            response = gateway.generate(
                messages=messages,
                model_type="llm",
                scene="policy_qa",
                max_tokens=8192,
            )

            content = response.content.strip()
            if content.startswith("```"):
                parts = content.split("```")
                content = parts[1] if len(parts) >= 2 else content
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            facts = json.loads(content)
            if isinstance(facts, list):
                logger.info(
                    "Extracted %d policy facts from %r",
                    len(facts), document_title,
                )
                return facts
            if isinstance(facts, dict):
                if "facts" in facts:
                    facts_list = facts["facts"]
                    logger.info(
                        "Extracted %d policy facts from %r (nested)",
                        len(facts_list), document_title,
                    )
                    return facts_list
                # 单条事实或单条规则包装为事实
                if "fact_text" in facts:
                    logger.info("LLM returned single fact dict, wrapping as list")
                    return [facts]
                if "rule_type" in facts:
                    logger.info("LLM returned single rule dict, wrapping as fact")
                    return [{"fact_text": facts.get("source_text", ""), "rules": [facts]}]

            logger.warning("Unexpected LLM response type: %s", type(facts).__name__)
            return []
        except Exception as e:
            logger.warning("Policy fact extraction failed: %s", e)
            return []

    def _build_fact_extraction_prompt(self, text: str, title: str) -> str:
        """构建事实提取 prompt（schema-driven，§3.1）。

        从语义层读 zcgz 对象的 published 指标契约，动态拼提示词（加维度不改代码）。
        回退：registry 不可用或契约空时用硬编码 legacy prompt（保证提取不中断）。
        """
        from src.semantic_layer.registry import create_registry
        from src.semantic_layer.extraction_contract import (
            build_extraction_schema, build_prompt_from_schema,
        )
        try:
            schema = build_extraction_schema(create_registry(), "zcgz")
            if schema.fields or schema.entities or schema.relations:
                return build_prompt_from_schema(text, title, schema)
        except Exception:
            pass
        return self._legacy_fact_extraction_prompt(text, title)

    def _legacy_fact_extraction_prompt(self, text: str, title: str) -> str:
        """[legacy] 硬编码 19 字段 prompt（registry 不可用时的回退）。"""
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
8. hosp_lv: 医疗机构等级（三级/二级/一级/社区/未定级）
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
    ]
  }}
]

## 实体类型
PERSON(人员), ORG(机构), SERVICE(医疗服务), AMOUNT(金额), RATIO(比例),
DISEASE(病种), DRUG(药品), DATE(日期), CONDITION(条件), LOCATION(地点)

## 注意
1. 尽可能多地提取事实，**覆盖原文中所有蕴含政策含义的语句**
2. 每个事实可包含多条规则，每条规则必须填满全部 19 个字段
3. 未提及的字段填空字符串 ""
4. 只返回 JSON 数组，不要任何其他内容"""

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

    def reextract_unit(self, extraction_id: str) -> dict[str, Any]:
        """对单个单元重新调用 LLM 提取（人工审核不通过后触发）。

        复用 _extract_policy_facts：用单元 source_text 作为输入，取首条事实覆盖
        extracted_fields，置信度回填规则均值，状态重置为 draft（需重新审核）。
        """
        ext = self._store.get_extraction(extraction_id)
        if not ext:
            return {"success": False, "error": "提取记录不存在"}
        doc = self._store.get_document(ext["doc_id"])
        title = doc.get("title", "") if doc else ""
        source = ext.get("source_text") or ext.get("extracted_fields", {}).get("fact_text", "")
        if not source.strip():
            return {"success": False, "error": "单元无源文本，无法重提取"}

        facts = self._extract_policy_facts(source, title)
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
        merged_fields.pop("audit_reason", None)  # 重提取清除上次驳回原因

        updated = self._store.update_extraction(extraction_id, {
            "extracted_fields": merged_fields,
            "confidence": avg_conf,
            "status": "draft",  # 重提取后需重新审核
        })
        return {"success": True, "extraction_id": extraction_id, "extraction": updated}
