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
            # ── LLM 全文提取政策事实 ──
            facts = self._extract_policy_facts(
                content,
                document_title=doc.get("title", ""),
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

            # ── 持久化 ──
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

    # ═══════════════ Publish ═══════════════

    def publish_extraction(self, extraction_id: str) -> dict[str, Any]:
        """将审核通过的提取结果（含所有规则）发布到 Milvus policy_rules"""
        ext = self._store.get_extraction(extraction_id)
        if not ext:
            return {"success": False, "error": "提取记录不存在"}

        if ext["status"] != "reviewed":
            return {"success": False, "error": "只有已审核的提取记录才能入库"}

        try:
            from pymilvus import Collection, connections
            from src.config.production import MILVUS_HOST, MILVUS_PORT
        except ImportError:
            return {"success": False, "error": "pymilvus 未安装"}

        fields = ext["extracted_fields"]
        if isinstance(fields, str):
            fields = json.loads(fields)

        rules = fields.get("rules", [])
        fact_text = ext.get("source_text", "")
        published_rule_ids: list[str] = []

        try:
            connections.connect(host=MILVUS_HOST, port=str(MILVUS_PORT), timeout=5)
            col = Collection("policy_rules")
        except Exception as e:
            return {"success": False, "error": f"Milvus 连接失败: {e}"}

        for rule in rules:
            rule_id = f"rule_{uuid.uuid4().hex[:12]}"
            row = {
                "rule_id": rule_id,
                "fact_id": f"fact_{uuid.uuid4().hex[:12]}",
                "policy_id": "",
                "clause_id": "",
                "source_text": fact_text,
                "insu_type": rule.get("insu_type", ""),
                "med_type": rule.get("med_type", ""),
                "hosp_lv": rule.get("hosp_lv", ""),
                "psn_type": rule.get("psn_type", ""),
                "setl_type": rule.get("setl_type", ""),
                "payment_ratio": rule.get("payment_ratio", ""),
                "deductible_amount": rule.get("deductible_amount", ""),
                "cap_amount": rule.get("cap_amount", ""),
                "time_period": rule.get("time_period", ""),
                "admission_order": rule.get("admission_order", ""),
                "amount_band": rule.get("amount_band", ""),
                "priority": rule.get("priority", ""),
                "rule_type": rule.get("rule_type", ""),
                "rule_value": rule.get("rule_value", ""),
                "doc_id": ext["doc_id"],
            }
            try:
                col.insert([row])
                published_rule_ids.append(rule_id)
            except Exception as e:
                logger.warning("Milvus 写入单条规则失败: %s", e)

        if published_rule_ids:
            col.flush()
            for rid in published_rule_ids:
                self._store.create_lineage(rid, extraction_id, ext["doc_id"])

        self._store.update_extraction(extraction_id, {"status": "published"})

        return {
            "success": True,
            "rule_ids": published_rule_ids,
            "extraction_id": extraction_id,
            "published_count": len(published_rule_ids),
        }

    # ═══════════════ Policy Fact Extraction (LLM) ═══════════════

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
            response = gateway.generate(
                messages=messages,
                model_type="llm",
                scene="policy_qa",
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
    def _calculate_coverage(document_text: str, facts: list[dict]) -> dict[str, Any]:
        """计算政策事实对原文的覆盖率。

        通过匹配每个 fact_text 在原文中的出现位置来估算覆盖率。
        """
        normalized_doc = re.sub(r"\s+", "", document_text)
        total_chars = len(normalized_doc)
        if total_chars == 0:
            return {"ratio": 0, "covered_chars": 0, "total_chars": 0}

        # 计算每个事实覆盖的字符数（通过原文匹配）
        covered_positions: set[int] = set()
        for fact in facts:
            fact_text = fact.get("fact_text", "")
            normalized_fact = re.sub(r"\s+", "", fact_text)
            if normalized_fact and len(normalized_fact) >= 3:
                # 在原文中查找事实文本的位置
                idx = normalized_doc.find(normalized_fact)
                if idx >= 0:
                    for pos in range(idx, idx + len(normalized_fact)):
                        covered_positions.add(pos)

        covered_chars = len(covered_positions)
        ratio = round(min(covered_chars / total_chars, 1.0), 2)

        return {
            "ratio": ratio,
            "covered_chars": covered_chars,
            "total_chars": total_chars,
        }

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
