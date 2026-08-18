from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field, ValidationError
from src.model_service.governance_runtime import render_governed_prompt

from .deepseek_llm_client import DeepSeekLLMClient


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# 1. 项目路径与文件配置
# ============================================================

def find_project_root(
    start: Path,
    markers=("pyproject.toml", ".git", "requirements.txt"),
) -> Path:
    current = start.resolve()

    while current != current.parent:
        for marker in markers:
            if (current / marker).exists():
                return current
        current = current.parent

    raise RuntimeError("未找到项目根目录")


PROJECT_ROOT = find_project_root(Path(__file__))

INPUT_FILE = PROJECT_ROOT / "raw" / "policy_nodes1.xlsx"

OUTPUT_EXCEL = PROJECT_ROOT / "raw" / "policy_facts1.xlsx"
OUTPUT_JSONL = PROJECT_ROOT / "raw" / "policy_facts1.jsonl"


REQUIRED_COLUMNS = [
    "node_id",
    "parent_id",
    "level",
    "marker",
    "path_text",
    "current_text",
    "full_context_text",
    "has_children",
    "is_rule_candidate",
    "chunk_type",
    "content_size",
    "policy_index",
    "policy_title",
    "rule_score",
    "candidate_level",
    "candidate_types",
    "matched_keywords",
    "matched_patterns",
    "negative_keywords",
]


# ============================================================
# 2. 基础工具
# ============================================================

def safe_str(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()

def extract_policy_meta(row: pd.Series) -> dict[str, str]:
    meta = {}

    for col in row.index:
        if col.startswith("meta_"):
            meta[col.replace("meta_", "", 1)] = safe_str(row[col])

    return meta


def is_true(value: Any) -> bool:
    if pd.isna(value):
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value == 1

    return str(value).strip().lower() in [
        "true",
        "1",
        "yes",
        "y",
        "是",
    ]


def dumps_json(value: Any) -> str | None:
    if value is None:
        return None

    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps(
            {
                "dump_error": repr(e),
                "raw_type": str(type(value)),
                "raw_value": str(value),
            },
            ensure_ascii=False,
            indent=2,
        )


def validate_columns(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]

    if missing:
        raise ValueError(
            "Excel 字段不符合 policy_rule_candidates Schema。\n"
            f"缺失字段: {missing}\n"
            f"当前字段: {list(df.columns)}"
        )


def gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def build_prompt_text(
    *,
    current_text: str,
    full_context_text: str,
) -> str:
    if full_context_text and full_context_text != current_text:
        return (
            "【当前条款】\n"
            f"{current_text}\n\n"
            "【上下文】\n"
            f"{full_context_text}"
        )

    return current_text


# ============================================================
# 3. PolicyFact 模型
# ============================================================

class RuleCandidateResult(BaseModel):
    is_rule_candidate: bool
    rule_candidate_score: float = 0.0
    candidate_type: list[str] = Field(default_factory=list)
    candidate_reason: list[str] = Field(default_factory=list)
    non_candidate_reason: list[str] = Field(default_factory=list)


class PolicyFact(BaseModel):
    fact_id: str

    fact_type: Literal[
        "deductible",
        "payment_ratio",
        "cap",
        "formula",
        "condition",
        "inclusion",
        "exclusion",
    ]

    subject: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)

    value: Any | None = None
    value_map: dict[str, Any] | None = None
    formula: dict[str, Any] | None = None

    evidence_text: str

    derived: bool = False
    inferred: bool = False
    derivation_basis: str | None = None
    uncertainty_reason: str | None = None


class PolicyFactExtractionResult(BaseModel):
    is_rule_candidate: bool
    rule_candidate_score: float = 0.0
    candidate_type: list[str] = Field(default_factory=list)
    candidate_reason: list[str] = Field(default_factory=list)
    non_candidate_reason: list[str] = Field(default_factory=list)

    facts: list[PolicyFact] = Field(default_factory=list)


class CanonicalDSL(BaseModel):
    rule_id: str

    rule_type: Literal[
        "deductible_rule",
        "ratio_rule",
        "cap_rule",
        "formula_rule",
    ]

    subject: dict[str, Any]
    conditions: list[dict[str, Any]]

    action: dict[str, Any]

    evidence_text: str
    source_fact_id: str

    derived: bool = False
    inferred: bool = False


# ============================================================
# 4. Prompt
# ============================================================

SYSTEM_PROMPT = """
你是医保政策结构化抽取专家。

你只能做三件事：
1. 判断当前条款是否适合进入可执行规则链路；
2. 抽取政策事实 PolicyFact；
3. 给出原文证据 evidence_text。

你禁止直接生成最终 DSL。
你禁止自行扩展政策含义。
你禁止把推导内容当作原文事实。

重要约束：
- 如果内容是管理要求、原则性描述、鼓励性表述、制度建设，不应进入 DSL。
- 如果内容没有明确数值、明确条件、明确动作、明确结果，不应进入 DSL。
- derived=true 或 inferred=true 的事实默认不进入正式 DSL。
- 例如“个人自付比例 = 1 - 基金支付比例”属于推导，不是原文事实。
- 例如“第二次住院起付线 = 首次起付线 × 50%”如果原文未明确，也属于推导。

第一阶段只支持以下 fact_type：
- deductible：起付线
- payment_ratio：支付比例
- cap：封顶线、年度限额
- formula：原文明确公式
- condition：条件
- inclusion：纳入
- exclusion：排除

必须返回严格 JSON，不要输出 Markdown。
"""

USER_PROMPT_TEMPLATE = """
请从以下医保政策条款中抽取 PolicyFact。

【node_id】
{node_id}

【政策标题】
{policy_title}

【政策结构化字段】
{policy_meta_json}

【条款路径】
{path_text}

【政策文本】
{text}

请返回严格 JSON，不要输出 Markdown。

返回结构：

{{
  "is_rule_candidate": true,
  "rule_candidate_score": 0.0,
  "candidate_type": [
    "deductible_rule",
    "ratio_rule",
    "cap_rule"
  ],
  "candidate_reason": [],
  "non_candidate_reason": [],
  "facts": []
}}

字段要求：

1. candidate_type 只能使用：
   - deductible_rule
   - ratio_rule
   - cap_rule
   - formula_rule

2. fact_type 只能使用：
   - deductible
   - payment_ratio
   - cap
   - formula
   - condition
   - inclusion
   - exclusion

3. 支付比例必须这样表示：
   {{
     "value": {{
       "ratio": 0.8
     }}
   }}
   不要使用 rate，不要使用 unit: "%”。

4. “学生儿童”必须表示为：
   {{
     "population": "student_child"
   }}
   不要拆成 child。

5. 如果原文明确写了：
   - 按首次住院起付标准的50%确定
   - 按某金额/比例/基数计算
   - 以某标准乘以某比例
   - 按公式计算

   应抽取为 fact_type="formula"，并且 derived=false，inferred=false。

   示例：

   {{
     "fact_id": "fact_formula_1",
     "fact_type": "formula",
     "subject": {{
       "population": "adult",
       "service_type": "inpatient"
     }},
     "conditions": [
       {{
         "field": "admission_order",
         "operator": ">=",
         "value": 2
       }}
     ],
     "value": null,
     "value_map": null,
     "formula": {{
       "expression": "current_deductible = first_admission_deductible * 0.5",
       "target": "current_deductible",
       "base": "first_admission_deductible",
       "operator": "*",
       "multiplier": 0.5
     }},
     "evidence_text": "第二次及以后住院的起付标准按首次住院起付标准的50%确定",
     "derived": false,
     "inferred": false,
     "derivation_basis": null,
     "uncertainty_reason": null
   }}

6. 不要把公式展开成具体金额。

   错误示例：
   - 一级及以下第二次住院 = 150 元
   - 二级第二次住院 = 400 元
   - 三级第二次住院 = 650 元

   这些属于派生计算结果，不要作为正式 PolicyFact 输出。

7. derived=true 只用于：
   - 原文没有直接写出
   - 由模型根据其他事实计算出来
   - 由模型补充出来的隐含结果

8. evidence_text 必须来自原文。
9. 不确定的事实不要强行抽取。
10. 不要生成 DSL。
"""


# ============================================================
# 5. DSL Compiler
# ============================================================

class FactCompiler:
    def compile(self, fact: PolicyFact) -> CanonicalDSL | None:
        if fact.derived or fact.inferred:
            return None

        if fact.fact_type == "deductible":
            return self.compile_deductible(fact)

        if fact.fact_type == "payment_ratio":
            return self.compile_ratio(fact)

        if fact.fact_type == "cap":
            return self.compile_cap(fact)

        if fact.fact_type == "formula":
            return self.compile_formula(fact)

        return None

    def compile_deductible(self, fact: PolicyFact) -> CanonicalDSL:
        return CanonicalDSL(
            rule_id=gen_id("rule"),
            rule_type="deductible_rule",
            subject=fact.subject,
            conditions=fact.conditions,
            action={
                "type": "set_deductible",
                "value": fact.value,
            },
            evidence_text=fact.evidence_text,
            source_fact_id=fact.fact_id,
            derived=fact.derived,
            inferred=fact.inferred,
        )

    def compile_ratio(self, fact: PolicyFact) -> CanonicalDSL:
        return CanonicalDSL(
            rule_id=gen_id("rule"),
            rule_type="ratio_rule",
            subject=fact.subject,
            conditions=fact.conditions,
            action={
                "type": "set_payment_ratio",
                "value": fact.value,
            },
            evidence_text=fact.evidence_text,
            source_fact_id=fact.fact_id,
            derived=fact.derived,
            inferred=fact.inferred,
        )

    def compile_cap(self, fact: PolicyFact) -> CanonicalDSL:
        return CanonicalDSL(
            rule_id=gen_id("rule"),
            rule_type="cap_rule",
            subject=fact.subject,
            conditions=fact.conditions,
            action={
                "type": "set_annual_cap",
                "value": fact.value,
            },
            evidence_text=fact.evidence_text,
            source_fact_id=fact.fact_id,
            derived=fact.derived,
            inferred=fact.inferred,
        )

    def compile_formula(self, fact: PolicyFact) -> CanonicalDSL:
        return CanonicalDSL(
            rule_id=gen_id("rule"),
            rule_type="formula_rule",
            subject=fact.subject,
            conditions=fact.conditions,
            action={
                "type": "calculate_by_formula",
                "formula": fact.formula,
            },
            evidence_text=fact.evidence_text,
            source_fact_id=fact.fact_id,
            derived=fact.derived,
            inferred=fact.inferred,
        )


# ============================================================
# 6. 抽取单条
# ============================================================

def build_empty_result(*, error: str) -> dict[str, Any]:
    return {
        "success": False,
        "errors": [error],
        "warnings": [],
        "raw_llm_result": None,
        "normalized_policy_fact_result": None,
        "policy_fact_result": None,
        "facts": [],
        "canonical_dsls": [],
        "fact_count": 0,
        "dsl_count": 0,
    }


def normalize_fact_ids(result: PolicyFactExtractionResult) -> PolicyFactExtractionResult:
    for i, fact in enumerate(result.facts, start=1):
        if not fact.fact_id:
            fact.fact_id = f"fact_{i}"
    return result


def normalize_policy_fact_raw_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    """
    PolicyFact 轻量规范化。
    只修结构、命名和值格式，不做复杂语义推导。
    """

    if not isinstance(raw_result, dict):
        raise ValueError(f"raw_result 不是 dict: {type(raw_result)}")

    # 1. candidate_type 统一
    candidate_type = raw_result.get("candidate_type") or []

    if isinstance(candidate_type, str):
        candidate_type = [candidate_type]

    normalized_candidate_type = []

    for item in candidate_type:
        if item == "payment_ratio_rule":
            item = "ratio_rule"
        normalized_candidate_type.append(item)

    raw_result["candidate_type"] = normalized_candidate_type

    facts = raw_result.get("facts")

    if facts is None:
        raw_result["facts"] = []
        return raw_result

    if not isinstance(facts, list):
        raw_result["facts"] = []
        raw_result.setdefault("non_candidate_reason", [])
        raw_result["non_candidate_reason"].append("facts 字段不是 list，已置为空")
        return raw_result

    for i, fact in enumerate(facts, start=1):
        if not isinstance(fact, dict):
            facts[i - 1] = {
                "fact_id": f"fact_{i}",
                "fact_type": "condition",
                "subject": {},
                "conditions": [],
                "value": None,
                "value_map": None,
                "formula": None,
                "evidence_text": str(fact),
                "derived": True,
                "inferred": True,
                "uncertainty_reason": "fact 不是 dict，已降级为非正式事实",
            }
            continue

        if not fact.get("fact_id"):
            fact["fact_id"] = f"fact_{i}"

        # 2. subject 规范化
        if fact.get("subject") is None:
            fact["subject"] = {}

        if not isinstance(fact.get("subject"), dict):
            fact["subject"] = {
                "raw_subject": fact.get("subject")
            }

        subject = fact["subject"]
        evidence_text = str(fact.get("evidence_text") or "")

        if subject.get("population") in [
            "child",
            "student",
            "students_children",
            "student_children",
        ]:
            if "学生儿童" in evidence_text or "学生、儿童" in evidence_text:
                subject["population"] = "student_child"

        # 3. conditions 规范化
        if fact.get("conditions") is None:
            fact["conditions"] = []

        if not isinstance(fact.get("conditions"), list):
            fact["conditions"] = [
                {
                    "raw_condition": fact.get("conditions")
                }
            ]

        # 4. value_map 规范化
        if fact.get("value_map") is not None and not isinstance(fact.get("value_map"), dict):
            fact["value_map"] = {
                "raw_value_map": fact.get("value_map")
            }

        # 5. payment_ratio value 规范化
        if fact.get("fact_type") == "payment_ratio":
            value = fact.get("value")

            if isinstance(value, dict):
                if "ratio" not in value and "rate" in value:
                    value["ratio"] = value.pop("rate")

                value.pop("unit", None)

                if isinstance(value.get("ratio"), (int, float)) and value["ratio"] > 1:
                    value["ratio"] = value["ratio"] / 100

            elif isinstance(value, (int, float)):
                ratio = float(value)

                if ratio > 1:
                    ratio = ratio / 100

                fact["value"] = {
                    "ratio": ratio
                }

        # 6. formula 规范化
        formula = fact.get("formula")

        if isinstance(formula, str):
            fact["formula"] = {
                "expression": formula,
                "raw": formula,
            }

            # 关键修改：
            # 原文明确出现“按……计算 / 按……确定 / 50%确定”等，说明它是原文公式，不是推导公式。
            explicit_formula_in_evidence = any(
                keyword in evidence_text
                for keyword in [
                    "按",
                    "计算",
                    "确定",
                    "50%",
                    "百分之五十",
                    "乘以",
                    "×",
                    "*",
                ]
            )

            if fact.get("fact_type") == "formula" and explicit_formula_in_evidence:
                fact["derived"] = False
                fact["inferred"] = False
                fact["derivation_basis"] = None

                if fact.get("uncertainty_reason") in [
                    "LLM 输出 formula 为字符串，已包装为结构化 formula；该公式默认按推导事实处理，不进入正式 DSL"
                ]:
                    fact["uncertainty_reason"] = None

            else:
                fact["derived"] = True
                fact["inferred"] = True

                if not fact.get("derivation_basis"):
                    fact["derivation_basis"] = formula

                if not fact.get("uncertainty_reason"):
                    fact["uncertainty_reason"] = (
                        "LLM 输出 formula 为字符串，已包装为结构化 formula；"
                        "但 evidence_text 未体现明确公式表达，默认按推导事实处理，不进入正式 DSL"
                    )

        elif formula is not None and not isinstance(formula, dict):
            fact["formula"] = {
                "raw": formula
            }

            fact["derived"] = True
            fact["inferred"] = True

            if not fact.get("uncertainty_reason"):
                fact["uncertainty_reason"] = "formula 非 dict，已包装为 raw；默认不进入正式 DSL"

        if not fact.get("evidence_text"):
            fact["evidence_text"] = ""

    return raw_result

def extract_one(
    *,
    llm: DeepSeekLLMClient,
    compiler: FactCompiler,
    node_id: str,
    policy_title: str,
    path_text: str,
    current_text: str,
    full_context_text: str,
    policy_meta: dict[str, str],
) -> dict[str, Any]:
    if not current_text:
        raise ValueError(f"{node_id}: current_text 为空")

    prompt_text = build_prompt_text(
        current_text=current_text,
        full_context_text=full_context_text,
    )

    rendered = render_governed_prompt(
        "policy.fact_extract",
        variables={
            "node_id": node_id,
            "policy_title": policy_title,
            "path_text": path_text,
            "text": prompt_text,
            "policy_meta_json": json.dumps(policy_meta, ensure_ascii=False, indent=2),
        },
        fallback_system=SYSTEM_PROMPT,
        fallback_user=USER_PROMPT_TEMPLATE,
    )

    logger.info(
        f"开始调用 DeepSeek LLM 抽取 PolicyFact，node_id={node_id}，"
        f"current_text_len={len(current_text)}，"
        f"full_context_text_len={len(full_context_text)}，"
        f"prompt_text_len={len(prompt_text)}"
    )

    llm_start = time.time()

    raw_result = llm.chat_json(
        system_prompt=rendered.rendered_system_prompt or "",
        user_prompt=rendered.rendered_user_prompt or "",
        temperature=0.1,
    )

    logger.info(
        f"DeepSeek LLM 返回，node_id={node_id}，"
        f"耗时={time.time() - llm_start:.2f}s"
    )

    logger.info(f"开始 PolicyFact Schema 校验，node_id={node_id}")

    schema_start = time.time()

    normalized_raw_result = normalize_policy_fact_raw_result(raw_result)

    fact_result = PolicyFactExtractionResult.model_validate(normalized_raw_result)
    fact_result = normalize_fact_ids(fact_result)

    logger.info(
        f"PolicyFact Schema 校验通过，node_id={node_id}，"
        f"fact_count={len(fact_result.facts)}，"
        f"耗时={time.time() - schema_start:.2f}s"
    )

    dsls: list[CanonicalDSL] = []
    warnings: list[str] = []

    for fact in fact_result.facts:
        if fact.derived or fact.inferred:
            warnings.append(
                f"{fact.fact_id}: derived/inferred fact skipped from formal DSL"
            )
            continue

        dsl = compiler.compile(fact)

        if dsl is None:
            warnings.append(
                f"{fact.fact_id}: fact_type={fact.fact_type} not compiled"
            )
            continue

        dsls.append(dsl)

    facts_json = [
        fact.model_dump(mode="json", exclude_none=True)
        for fact in fact_result.facts
    ]

    dsls_json = [
        dsl.model_dump(mode="json", exclude_none=True)
        for dsl in dsls
    ]

    return {
        "success": True,
        "errors": [],
        "warnings": warnings,
        "raw_llm_result": raw_result,
        "normalized_policy_fact_result": normalized_raw_result,
        "policy_fact_result": fact_result.model_dump(mode="json", exclude_none=True),
        "facts": facts_json,
        "canonical_dsls": dsls_json,
        "fact_count": len(facts_json),
        "dsl_count": len(dsls_json),
    }


# ============================================================
# 7. 主流程
# ============================================================

def main():
    total_start = time.time()

    logger.info("=" * 80)
    logger.info("开始 PolicyFact + Canonical DSL 抽取任务")
    logger.info("=" * 80)
    logger.info(f"项目根目录: {PROJECT_ROOT}")
    logger.info(f"输入文件: {INPUT_FILE}")
    logger.info(f"Excel输出: {OUTPUT_EXCEL}")
    logger.info(f"JSONL输出: {OUTPUT_JSONL}")

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"未找到输入文件: {INPUT_FILE}")

    logger.info("开始读取 Excel")

    read_start = time.time()
    df = pd.read_excel(INPUT_FILE)

    logger.info(
        f"Excel 读取完成，行数={len(df)}，列数={len(df.columns)}，"
        f"耗时={time.time() - read_start:.2f}s"
    )

    logger.info("开始校验 Excel 字段")
    validate_columns(df)
    logger.info("Excel 字段校验通过")

    candidate_count = df["is_rule_candidate"].apply(is_true).sum()

    logger.info(f"候选规则数量: {candidate_count} / {len(df)}")

    OUTPUT_EXCEL.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)

    logger.info("开始初始化 DeepSeekLLMClient 和 FactCompiler")

    init_start = time.time()

    llm = DeepSeekLLMClient()
    compiler = FactCompiler()

    logger.info(f"初始化完成，耗时={time.time() - init_start:.2f}s")

    output_rows = []

    logger.info("开始逐行处理候选规则")

    with OUTPUT_JSONL.open("w", encoding="utf-8") as f:
        for idx, row in df.iterrows():
            row_start = time.time()

            node_id = safe_str(row["node_id"])
            policy_title = safe_str(row["policy_title"])
            policy_meta = extract_policy_meta(row)
            path_text = safe_str(row["path_text"])
            current_text = safe_str(row["current_text"])
            full_context_text = safe_str(row["full_context_text"])
            is_candidate = is_true(row["is_rule_candidate"])

            logger.info("-" * 80)
            logger.info(
                f"[{idx + 1}/{len(df)}] 开始处理 "
                f"node_id={node_id} "
                f"is_rule_candidate={is_candidate} "
                f"current_text_len={len(current_text)} "
                f"full_context_text_len={len(full_context_text)}"
            )

            if not current_text:
                result = build_empty_result(error="empty current_text")
                status = "skipped"

            elif not is_candidate:
                result = build_empty_result(error="not rule candidate")
                status = "skipped"

            else:
                try:
                    result = extract_one(
                        llm=llm,
                        compiler=compiler,
                        node_id=node_id,
                        policy_title=policy_title,
                        path_text=path_text,
                        current_text=current_text,
                        full_context_text=full_context_text,
                        policy_meta=policy_meta,
                    )

                    status = "success" if result["success"] else "failed"

                    logger.info(
                        f"[{idx + 1}/{len(df)}] 抽取完成，"
                        f"node_id={node_id} "
                        f"fact_count={result.get('fact_count')} "
                        f"dsl_count={result.get('dsl_count')} "
                        f"warnings={len(result.get('warnings') or [])}"
                    )

                except ValidationError as e:
                    logger.exception(
                        f"[{idx + 1}/{len(df)}] PolicyFact Schema 校验失败，node_id={node_id}"
                    )
                    result = build_empty_result(error=str(e))
                    status = "failed"

                except Exception as e:
                    logger.exception(
                        f"[{idx + 1}/{len(df)}] 处理异常，node_id={node_id}"
                    )
                    result = build_empty_result(error=repr(e))
                    status = "failed"

            record = {
                "row_index": idx,
                "node_id": node_id,
                "policy_title": policy_title,
                "path_text": path_text,
                "current_text": current_text,
                "extract_status": status,
                "extract_success": result["success"],
                "extract_error": "; ".join(result["errors"]) if result["errors"] else None,
                "warnings": result["warnings"],
                "fact_count": result["fact_count"],
                "dsl_count": result["dsl_count"],
                "facts": result["facts"],
                "canonical_dsls": result["canonical_dsls"],
                "policy_fact_result": result["policy_fact_result"],
                "raw_llm_result": result["raw_llm_result"],
                "normalized_policy_fact_result": result.get("normalized_policy_fact_result"),
                "policy_meta": policy_meta,
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()

            output_rows.append(
                {
                    "extract_status": record["extract_status"],
                    "extract_success": record["extract_success"],
                    "extract_error": record["extract_error"],
                    "warnings": dumps_json(record["warnings"]),
                    "fact_count": record["fact_count"],
                    "dsl_count": record["dsl_count"],
                    "facts": dumps_json(record["facts"]),
                    "canonical_dsls": dumps_json(record["canonical_dsls"]),
                    "policy_fact_result": dumps_json(record["policy_fact_result"]),
                    "raw_llm_result": dumps_json(record["raw_llm_result"]),
                    "normalized_policy_fact_result": dumps_json(record["normalized_policy_fact_result"]),
                    "policy_meta": dumps_json(record["policy_meta"]),
                }
            )

            logger.info(
                f"[{idx + 1}/{len(df)}] 处理完成 "
                f"node_id={node_id} "
                f"status={status} "
                f"fact_count={result['fact_count']} "
                f"dsl_count={result['dsl_count']} "
                f"总耗时={time.time() - row_start:.2f}s"
            )

    logger.info("所有行处理完成，开始生成 DataFrame")

    result_df = pd.concat(
        [
            df.reset_index(drop=True),
            pd.DataFrame(output_rows),
        ],
        axis=1,
    )

    logger.info("开始写入 Excel 输出文件")

    result_df.to_excel(
        OUTPUT_EXCEL,
        index=False,
    )

    logger.info("=" * 80)
    logger.info("PolicyFact + Canonical DSL 抽取完成")
    logger.info("=" * 80)
    logger.info(f"输入文件: {INPUT_FILE}")
    logger.info(f"Excel 输出: {OUTPUT_EXCEL}")
    logger.info(f"JSONL 输出: {OUTPUT_JSONL}")
    logger.info(f"总耗时: {time.time() - total_start:.2f}s")


if __name__ == "__main__":
    main()
