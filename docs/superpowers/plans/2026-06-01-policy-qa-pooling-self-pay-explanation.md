# Policy QA Pooling Self Pay Explanation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通“为什么我这次统筹自付这么多？”样板链路，让系统能基于 SQL 上下文、政策分段规则、退休人员系数和业务库金额形成可追溯解释。

**Architecture:** 在现有 `src.runtime.policy_qa` 运行时链路中补结构化目标费用项、解释上下文、检索查询、分段计算和对账结果。LLM 只允许润色结构化事实；无模型或检索失败时使用模板解释并输出不确定性。

**Tech Stack:** Python 3.11+, dataclasses, FastAPI, pytest, SSE, Milvus policy_rules 集合适配器。

---

## Scope and Constraints

本计划只实现住院城镇职工退休人员“统筹自付”样板链路，不实现通用费用解释树。金额展示以业务库 `yb_zyfdxx.bdtczf` 为权威值，政策计算值只用于解释和校验。计算值与业务库金额差异超过 `0.01` 元时，必须输出“政策解释计算与结算结果存在差异，需要人工复核”。

实施时不要修改用户已有的无关工作区变更。每个任务只提交本任务改动文件。

## File Structure

- Modify: `src/runtime/policy_qa/models.py`
  - 增加 `target_fee_item`、`target_fee_label`、结构化重写结果、对账结果字段。
- Modify: `src/runtime/policy_qa/intent_detector.py`
  - 识别“统筹自付/统筹自费/统筹个人自付”为 `pooling_self_pay` 目标费用项。
- Modify: `src/runtime/policy_qa/question_rewriter.py`
  - 将检索短查询与解释上下文分离，避免将大段业务上下文塞入向量检索。
- Modify: `src/runtime/policy_qa/fee_decomposition_skill.py`
  - 增加退休人员识别、统筹分段基数说明、`0.01` 元容差对账、规则缺失 warning。
- Modify: `src/runtime/policy_qa/orchestrator.py`
  - 让目标费用项贯穿 SQL、重写、检索、分解、解释步骤；对统筹自付执行定向检索和 warning 记录。
- Modify: `src/runtime/policy_qa/explanation_generator.py`
  - 以结构化事实生成统筹自付模板解释；LLM 可用时只传入受约束 prompt。
- Modify: `src/runtime/api/policy_qa_routes.py`
  - SSE detail 中输出目标费用项、短检索查询、对账结构。
- Modify: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`
  - 增加模型、意图、重写、分段计算、对账、模板解释单元测试。
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
  - 增加无需真实 SQL/Milvus 的编排器或接口结构测试。
- Create: `src/tests/integration/flow/test_policy_qa_pooling_self_pay.py`
  - 增加端到端流程级测试，使用 fake 组件验证输出事实链。

---

### Task 1: Add structured policy QA target and reconciliation models

**Files:**
- Modify: `src/runtime/policy_qa/models.py`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: Write failing model tests**

Append these tests inside `TestPolicyQAModels` in `src/tests/unit/runtime/policy_qa/test_policy_qa.py`:

```python
    def test_intent_result_supports_target_fee_item(self):
        """统筹自付解释需要结构化目标费用项。"""
        from src.runtime.policy_qa.models import PolicyQAIntent, PolicyQAIntentResult

        result = PolicyQAIntentResult(
            intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
            settlement_id="1671213",
            need_patient_data=True,
            query_type="统筹自付解释",
            confidence=0.95,
            target_fee_item="pooling_self_pay",
            target_fee_label="统筹自付",
        )

        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_fee_label == "统筹自付"

    def test_rewritten_question_separates_search_query_and_context(self):
        """重写结果需要把检索短查询和解释上下文分开。"""
        from src.runtime.policy_qa.models import RewrittenQuestion

        rewritten = RewrittenQuestion(
            original="为什么我这次统筹自付这么多？",
            rewritten="城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例",
            search_query="城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例",
            explanation_context={
                "fund_type": "城镇职工",
                "person_type": "退休",
                "medical_type": "普通住院",
                "pooling_self_pay": 4962.67,
            },
        )

        assert "【业务上下文】" not in rewritten.search_query
        assert rewritten.explanation_context["person_type"] == "退休"
        assert rewritten.explanation_context["pooling_self_pay"] == 4962.67

    def test_segment_calculation_result_supports_reconciliation_and_warnings(self):
        """分段计算结果需要包含 0.01 元容差对账结构。"""
        from src.runtime.policy_qa.models import SegmentCalculationResult

        result = SegmentCalculationResult(
            total_pay=4962.68,
            authoritative_amount=4962.67,
            reconciliation_difference=0.01,
            reconciliation_tolerance=0.01,
            reconciliation_matched=True,
            reconciliation_message="政策解释计算与业务库金额一致",
            warnings=["按现有字段估算统筹分段基数"],
        )

        assert result.authoritative_amount == 4962.67
        assert result.reconciliation_tolerance == 0.01
        assert result.reconciliation_matched is True
        assert result.warnings == ["按现有字段估算统筹分段基数"]
```

- [ ] **Step 2: Run model tests and verify they fail**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAModels -v
```

Expected: FAIL with dataclass constructor errors for unknown fields such as `target_fee_item`, `search_query`, or `authoritative_amount`.

- [ ] **Step 3: Add model fields**

Modify `src/runtime/policy_qa/models.py`:

```python
@dataclass
class PolicyQAIntentResult:
    """意图识别结果"""
    intent: PolicyQAIntent
    settlement_id: str
    need_patient_data: bool = True
    query_type: str = ""
    confidence: float = 0.0
    target_fee_item: str | None = None
    target_fee_label: str | None = None
```

Replace `RewrittenQuestion` with:

```python
@dataclass
class RewrittenQuestion:
    """重写后的问题"""
    original: str = ""
    rewritten: str = ""
    search_query: str = ""
    explanation_context: dict[str, Any] = field(default_factory=dict)
    semantic_mappings: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
```

Replace `SegmentCalculationResult` with:

```python
@dataclass
class SegmentCalculationResult:
    """分段计算结果"""
    segments: list[SegmentInfo] = field(default_factory=list)
    total_pay: float = 0.0
    authoritative_amount: float | None = None
    reconciliation_difference: float | None = None
    reconciliation_tolerance: float = 0.01
    reconciliation_matched: bool | None = None
    reconciliation_message: str = ""
    warnings: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run model tests and verify they pass**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAModels -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/runtime/policy_qa/models.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: add policy qa target and reconciliation models"
```

---

### Task 2: Detect pooling self-pay explanation intent

**Files:**
- Modify: `src/runtime/policy_qa/intent_detector.py`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: Write failing intent tests**

Append these tests inside `TestIntentDetector` in `src/tests/unit/runtime/policy_qa/test_policy_qa.py`:

```python
    def test_detects_pooling_self_pay_target(self):
        """统筹自付问题必须命中结构化目标费用项。"""
        from src.runtime.policy_qa.intent_detector import IntentDetector
        from src.runtime.policy_qa.models import PolicyQAIntent

        detector = IntentDetector()
        result = detector._keyword_based_detection("为什么我这次统筹自付这么多？")

        assert result.intent == PolicyQAIntent.TREATMENT_DECOMPOSITION
        assert result.query_type == "统筹自付解释"
        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_fee_label == "统筹自付"
        assert result.need_patient_data is True

    def test_detects_pooling_self_pay_synonym(self):
        """统筹自费是统筹自付的口语同义表达。"""
        from src.runtime.policy_qa.intent_detector import IntentDetector

        detector = IntentDetector()
        result = detector._keyword_based_detection("统筹自费为什么这么高？")

        assert result.target_fee_item == "pooling_self_pay"
        assert result.target_fee_label == "统筹自付"
```

- [ ] **Step 2: Run intent tests and verify they fail**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestIntentDetector -v
```

Expected: FAIL because pooling self-pay target fields are not set.

- [ ] **Step 3: Update prompt and keyword fallback**

Modify `INTENT_DETECTION_PROMPT` in `src/runtime/policy_qa/intent_detector.py` so the JSON schema includes:

```python
INTENT_DETECTION_PROMPT = """你是一个医保政策问答系统的意图识别模块。

用户问题: {question}

请识别用户意图，返回JSON格式:
{{
  "intent": "意图类型",
  "need_patient_data": true/false,
  "query_type": "查询类型",
  "target_fee_item": "目标费用项或null",
  "target_fee_label": "目标费用项中文名或null",
  "confidence": 0.0-1.0
}}

意图类型说明:
- fee_decomposition: 费用分解（用户想了解费用构成）
- treatment_decomposition: 待遇分解（用户想了解待遇计算）
- deductible: 起付线（用户想了解起付线相关）
- payment_ratio: 报销比例（用户想了解报销比例）
- cap_amount: 封顶线（用户想了解封顶线）
- general: 通用问答

目标费用项说明:
- pooling_self_pay: 统筹自付、统筹自费、统筹个人自付
- null: 用户未询问具体费用项

查询类型说明:
- 统筹自付解释: 解释本次统筹自付金额为什么这么多、怎么算
- 费用分解: 了解费用构成
- 待遇分解: 了解待遇计算
- 起付线: 了解起付线规则
- 报销比例: 了解报销比例
- 封顶线: 了解封顶线规则
- 其他: 其他问题

请只返回JSON，不要有其他内容。"""
```

At the top of `_keyword_based_detection`, before generic ratio/deductible rules, add:

```python
        if any(kw in question_lower for kw in ["统筹自付", "统筹自费", "统筹个人自付"]):
            return PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="",
                need_patient_data=True,
                query_type="统筹自付解释",
                confidence=0.9,
                target_fee_item="pooling_self_pay",
                target_fee_label="统筹自付",
            )
```

In `_parse_llm_response`, pass through target fields:

```python
            return PolicyQAIntentResult(
                intent=intent,
                settlement_id="",
                need_patient_data=data.get("need_patient_data", True),
                query_type=data.get("query_type", ""),
                confidence=data.get("confidence", 0.8),
                target_fee_item=data.get("target_fee_item"),
                target_fee_label=data.get("target_fee_label"),
            )
```

- [ ] **Step 4: Run intent tests and verify they pass**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestIntentDetector -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/runtime/policy_qa/intent_detector.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: detect pooling self pay policy qa intent"
```

---

### Task 3: Rewrite pooling self-pay questions into focused search queries

**Files:**
- Modify: `src/runtime/policy_qa/question_rewriter.py`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: Write failing rewrite test**

Append this async test inside `TestQuestionRewriter` in `src/tests/unit/runtime/policy_qa/test_policy_qa.py`:

```python
    @pytest.mark.asyncio
    async def test_rewrite_pooling_self_pay_uses_short_search_query(self):
        """统筹自付重写应输出短检索查询和独立解释上下文。"""
        from src.runtime.policy_qa.models import PolicyQAIntent, SQLQueryResult
        from src.runtime.policy_qa.question_rewriter import QuestionRewriter

        sql_result = SQLQueryResult(
            yb_brdjxx={
                "fund_type": "城镇职工",
                "fund_type_raw": "城镇职工",
                "PER_TYPE": "退休",
                "PER_TYPE_raw": "退休人员",
                "yllb": "普通住院",
                "yllb_raw": "普通住院",
            },
            yb_dyxxnd={"fynd": "2025"},
            yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
            yb_zyfdxx={
                "bdfyzje": 189085.85,
                "bdybnzje": 164411.81,
                "bdtczf": 4962.67,
                "bdtczfje": 91759.51,
                "bddegwyzf": 13407.93,
                "bddegwyzfje": 53631.71,
            },
        )

        result = await QuestionRewriter().rewrite(
            "为什么我这次统筹自付这么多？",
            sql_result,
            intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
            target_fee_item="pooling_self_pay",
        )

        assert result.rewritten == result.search_query
        assert "【业务上下文】" not in result.search_query
        assert "城镇职工" in result.search_query
        assert "退休人员" in result.search_query
        assert "住院" in result.search_query
        assert "统筹" in result.search_query
        assert "自付比例" in result.search_query
        assert result.explanation_context["target_fee_item"] == "pooling_self_pay"
        assert result.explanation_context["pooling_self_pay"] == 4962.67
```

- [ ] **Step 2: Run rewrite test and verify it fails**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestQuestionRewriter -v
```

Expected: FAIL because `QuestionRewriter.rewrite` does not accept `target_fee_item` and does not populate `search_query`.

- [ ] **Step 3: Update `QuestionRewriter.rewrite` signature and target extraction**

Change the method signature in `src/runtime/policy_qa/question_rewriter.py`:

```python
    async def rewrite(
        self, question: str, sql_result: SQLQueryResult,
        intent: PolicyQAIntent | None = None,
        target_fee_item: str | None = None,
    ) -> RewrittenQuestion:
```

Add helper methods to `QuestionRewriter`:

```python
    def _is_retired(self, per_type: str, per_type_raw: str) -> bool:
        text = f"{per_type} {per_type_raw}"
        return any(keyword in text for keyword in ["退休", "退职", "2"])

    def _build_pooling_self_pay_search_query(
        self,
        *,
        fund_type: str,
        per_type: str,
        per_type_raw: str,
        yllb: str,
    ) -> str:
        parts: list[str] = []
        if fund_type:
            parts.append(fund_type)
        if self._is_retired(per_type, per_type_raw):
            parts.append("退休人员")
        elif per_type:
            parts.append(per_type)
        if "住院" in yllb:
            parts.append("住院")
        elif yllb:
            parts.append(yllb)
        parts.extend(["统筹基金", "起付线以上", "分段", "自付比例", "退休人员个人负担比例"])
        return " ".join(dict.fromkeys(parts))

    def _build_pooling_self_pay_context(
        self,
        *,
        sql_result: SQLQueryResult,
        fund_type: str,
        per_type: str,
        per_type_raw: str,
        yllb: str,
    ) -> dict[str, Any]:
        treatment = sql_result.yb_zyfdxx
        admission = sql_result.yb_dyxxzy
        return {
            "target_fee_item": "pooling_self_pay",
            "target_fee_label": "统筹自付",
            "fund_type": fund_type,
            "person_type": "退休" if self._is_retired(per_type, per_type_raw) else per_type,
            "person_type_raw": per_type_raw,
            "medical_type": yllb,
            "deductible": float(admission.get("bcqfje", 0) or 0),
            "in_scope_amount": float(admission.get("bcybnje", treatment.get("bdybnzje", 0)) or 0),
            "pooling_self_pay": float(treatment.get("bdtczf", 0) or 0),
            "pooling_payment": float(treatment.get("bdtczfje", 0) or 0),
            "major_self_pay": float(treatment.get("bddegwyzf", 0) or 0),
            "major_payment": float(treatment.get("bddegwyzfje", 0) or 0),
            "total_fee": float(treatment.get("bdfyzje", 0) or 0),
        }
```

- [ ] **Step 4: Add pooling self-pay branch in `rewrite`**

Inside `rewrite`, after extracting `fund_type`, `per_type`, `yllb`, and before generic search assembly, add:

```python
            per_type_raw = sql_result.yb_brdjxx.get("PER_TYPE_raw", "")

            if target_fee_item == "pooling_self_pay":
                search_query = self._build_pooling_self_pay_search_query(
                    fund_type=fund_type,
                    per_type=per_type,
                    per_type_raw=per_type_raw,
                    yllb=yllb,
                )
                explanation_context = self._build_pooling_self_pay_context(
                    sql_result=sql_result,
                    fund_type=fund_type,
                    per_type=per_type,
                    per_type_raw=per_type_raw,
                    yllb=yllb,
                )
                semantic_mappings.update({
                    "target_fee_item": "pooling_self_pay",
                    "fund_type": fund_type,
                    "per_type": explanation_context["person_type"],
                    "yllb": yllb,
                })
                return RewrittenQuestion(
                    original=question,
                    rewritten=search_query,
                    search_query=search_query,
                    explanation_context=explanation_context,
                    semantic_mappings=semantic_mappings,
                )
```

For the generic branch, ensure returned `RewrittenQuestion` also sets `search_query=search_query` and `explanation_context={"context_text": context_str}`.

- [ ] **Step 5: Run rewrite tests and verify they pass**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestQuestionRewriter -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add src/runtime/policy_qa/question_rewriter.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: rewrite pooling self pay queries with context"
```

---

### Task 4: Add pooling self-pay reconciliation to decomposition skill

**Files:**
- Modify: `src/runtime/policy_qa/fee_decomposition_skill.py`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: Write failing reconciliation tests**

Append these tests inside `TestFeeDecompositionSkill` in `src/tests/unit/runtime/policy_qa/test_policy_qa.py`:

```python
    def test_get_person_ratio_recognizes_retired_text(self):
        """人员系数不能只依赖数字代码，也要识别退休文本。"""
        from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill

        skill = FeeDecompositionSkill()

        assert skill._get_person_ratio({"PER_TYPE": "退休"}) == 0.6
        assert skill._get_person_ratio({"PER_TYPE": "退休人员"}) == 0.6
        assert skill._get_person_ratio({"PER_TYPE": "在职"}) == 1.0

    def test_decompose_pooling_self_pay_reconciles_with_authoritative_amount(self):
        """统筹自付以业务库金额为权威值，并保存分段解释计算值。"""
        from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
        from src.runtime.policy_qa.models import PolicyRule, SQLQueryResult

        sql_result = SQLQueryResult(
            yb_brdjxx={"PER_TYPE": "退休", "PER_TYPE_raw": "退休人员"},
            yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
            yb_zyfdxx={
                "bdfyzje": 189085.85,
                "bdybnzje": 164411.81,
                "bdtczf": 4962.67,
                "bdtczfje": 91759.51,
                "bddegwyzf": 13407.93,
                "bddegwyzfje": 53631.71,
                "bdgryf": 43694.67,
            },
        )
        rules = [
            PolicyRule(rule_id="r1", rule_type="统筹分段", amount_band="650-30000", payment_ratio="0.15", source_text="起付线以上至3万元部分，自付比例15%"),
            PolicyRule(rule_id="r2", rule_type="统筹分段", amount_band="30000-40000", payment_ratio="0.10", source_text="3万元至4万元部分，自付比例10%"),
            PolicyRule(rule_id="r3", rule_type="统筹分段", amount_band="40000-inf", payment_ratio="0.05", source_text="4万元以上部分，自付比例5%"),
        ]

        result = FeeDecompositionSkill().decompose(sql_result, rules)

        assert result.treatment.pooling_self_pay.value == 4962.67
        assert result.segments.authoritative_amount == 4962.67
        assert result.segments.reconciliation_tolerance == 0.01
        assert result.segments.reconciliation_matched is False
        assert "政策解释计算与结算结果存在差异，需要人工复核" in result.segments.reconciliation_message
        assert any("估算统筹分段基数" in warning for warning in result.segments.warnings)
```

- [ ] **Step 2: Run decomposition tests and verify they fail**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestFeeDecompositionSkill -v
```

Expected: FAIL because text retirement is not recognized and reconciliation fields are not populated.

- [ ] **Step 3: Update person ratio detection**

Modify `_get_person_ratio` in `src/runtime/policy_qa/fee_decomposition_skill.py`:

```python
    def _get_person_ratio(self, patient: dict[str, Any]) -> float:
        """
        获取人员系数。

        退休人员: 60% (即自付比例×0.6)
        在职人员: 100% (即自付比例×1.0)
        """
        per_type = str(patient.get("PER_TYPE", "") or "")
        per_type_raw = str(patient.get("PER_TYPE_raw", "") or "")
        text = f"{per_type} {per_type_raw}"
        if any(keyword in text for keyword in ["退休", "退职"]):
            return 0.6
        if per_type.strip() == "2" or per_type_raw.strip() == "2":
            return 0.6
        return 1.0
```

- [ ] **Step 4: Add pooling amount derivation helper**

Add this method to `FeeDecompositionSkill`:

```python
    def _derive_pooling_amount(self, treatment: dict[str, Any]) -> tuple[float, list[str]]:
        """推导统筹分段基数，并返回解释 warning。"""
        tcfdhybn = float(treatment.get("tcfdhybn", 0) or 0)
        if tcfdhybn > 0:
            return tcfdhybn, []

        bdybnzje = float(treatment.get("bdybnzje", 0) or 0)
        degwyzfje = float(treatment.get("bddegwyzfje", 0) or 0)
        degwyzf = float(treatment.get("bddegwyzf", 0) or 0)
        estimated = bdybnzje - degwyzfje - degwyzf
        return max(estimated, 0.0), ["按现有字段估算统筹分段基数：医保内金额 - 大额支付 - 大额自付"]
```

- [ ] **Step 5: Add reconciliation helper**

Add this method to `FeeDecompositionSkill`:

```python
    def _reconcile_pooling_self_pay(
        self,
        segment_calc: SegmentCalculationResult,
        authoritative_amount: float,
        *,
        tolerance: float = 0.01,
    ) -> SegmentCalculationResult:
        """将政策解释计算值与业务库统筹自付金额对账。"""
        calculated = round(segment_calc.total_pay, 2)
        authoritative = round(float(authoritative_amount or 0), 2)
        difference = round(calculated - authoritative, 2)

        segment_calc.total_pay = calculated
        segment_calc.authoritative_amount = authoritative
        segment_calc.reconciliation_difference = difference
        segment_calc.reconciliation_tolerance = tolerance
        segment_calc.reconciliation_matched = abs(difference) <= tolerance
        if segment_calc.reconciliation_matched:
            segment_calc.reconciliation_message = "政策解释计算与业务库金额一致"
        else:
            segment_calc.reconciliation_message = "政策解释计算与结算结果存在差异，需要人工复核"
        return segment_calc
```

- [ ] **Step 6: Use helpers in `decompose` and treatment decomposition**

In `decompose`, replace the duplicated pooling amount logic with:

```python
            pooling_amount, pooling_warnings = self._derive_pooling_amount(treatment)

            segment_calc = self._calculate_segmented(
                amount=pooling_amount,
                segments=segments,
                person_ratio=person_ratio,
                deductible=admission.get("bcqfje", 0),
            )
            segment_calc.warnings.extend(pooling_warnings)
            segment_calc = self._reconcile_pooling_self_pay(
                segment_calc,
                authoritative_amount=float(treatment.get("bdtczf", 0) or 0),
                tolerance=0.01,
            )
```

In `_decompose_treatment`, replace pooling amount logic with:

```python
        pooling_amount, _ = self._derive_pooling_amount(treatment)
```

Keep `pooling_self_pay` using authoritative business amount:

```python
        pooling_self_pay = treatment.get("bdtczf", 0)
```

Change `pooling_self_pay` calculation text to:

```python
                calculation=self._format_segment_calculation(segment_calc) if segment_calc.segments else "政策分段规则不足，无法稳定解释计算过程",
```

- [ ] **Step 7: Run decomposition tests and verify they pass**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestFeeDecompositionSkill -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```bash
git add src/runtime/policy_qa/fee_decomposition_skill.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: reconcile pooling self pay calculations"
```

---

### Task 5: Add focused policy retrieval for pooling self-pay

**Files:**
- Modify: `src/runtime/policy_qa/orchestrator.py`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: Write failing orchestrator retrieval test**

Append this async test inside `TestPolicyQAOrchestrator` in `src/tests/unit/runtime/policy_qa/test_policy_qa.py`:

```python
    @pytest.mark.asyncio
    async def test_search_policy_rules_uses_pooling_self_pay_filters(self):
        """统筹自付解释应定向检索统筹分段和退休人员规则。"""
        from src.runtime.policy_qa.models import PolicyQAIntent, SQLQueryResult
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        class FakeSearchEngine:
            def __init__(self):
                self.calls = []

            def search(self, question, top_k=10, expr=None):
                self.calls.append({"question": question, "top_k": top_k, "expr": expr})
                return [
                    {
                        "rule_id": "r1",
                        "rule_type": "统筹分段",
                        "insu_type": "城镇职工",
                        "med_type": "普通住院",
                        "psn_type": "退休",
                        "amount_band": "650-30000",
                        "payment_ratio": "0.15",
                        "source_text": "起付线以上至3万元部分，自付比例15%",
                        "score": 0.99,
                    }
                ]

        search_engine = FakeSearchEngine()
        orchestrator = PolicyQAOrchestrator(model_gateway=None, search_engine=search_engine)
        sql_result = SQLQueryResult(
            yb_brdjxx={"fund_type": "城镇职工", "PER_TYPE": "退休", "yllb": "普通住院"}
        )

        rules = await orchestrator._search_policy_rules(
            "城镇职工 退休人员 住院 统筹基金 起付线以上 分段 自付比例",
            sql_result,
            intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
            target_fee_item="pooling_self_pay",
        )

        assert len(rules) == 1
        assert rules[0].rule_type == "统筹分段"
        assert search_engine.calls
        assert "统筹分段" in search_engine.calls[0]["expr"]
        assert "城镇职工" in search_engine.calls[0]["expr"]
```

- [ ] **Step 2: Run orchestrator tests and verify they fail**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator -v
```

Expected: FAIL because `_search_policy_rules` does not accept `target_fee_item` and does not add pooling self-pay filters.

- [ ] **Step 3: Pass target fee item through orchestrator**

In `process`, change rewrite and search calls in `src/runtime/policy_qa/orchestrator.py`:

```python
            rewritten = await self._rewrite_question(
                request.question,
                sql_result,
                intent_result.intent,
                target_fee_item=intent_result.target_fee_item,
            )
```

```python
            policy_rules = await self._search_policy_rules(
                rewritten.search_query or rewritten.rewritten,
                sql_result,
                intent=intent_result.intent,
                target_fee_item=intent_result.target_fee_item,
            )
```

Update the rewrite detail:

```python
                detail={
                    "rewritten_question": rewritten.rewritten,
                    "search_query": rewritten.search_query,
                    "explanation_context": rewritten.explanation_context,
                    "warnings": rewritten.warnings,
                },
```

- [ ] **Step 4: Update method signatures**

Change `_rewrite_question` signature:

```python
    async def _rewrite_question(
        self,
        question: str,
        sql_result: SQLQueryResult,
        intent=None,
        target_fee_item: str | None = None,
    ) -> RewrittenQuestion:
```

Change the rewriter call:

```python
            result = await self.question_rewriter.rewrite(
                question,
                sql_result,
                intent=intent,
                target_fee_item=target_fee_item,
            )
```

Change `_search_policy_rules` signature:

```python
    async def _search_policy_rules(
        self,
        question: str,
        sql_result: SQLQueryResult,
        intent=None,
        target_fee_item: str | None = None,
    ) -> list[PolicyRule]:
```

- [ ] **Step 5: Add pooling self-pay filter expression branch**

Inside `_search_policy_rules`, replace rule type intent filtering block with:

```python
            if target_fee_item == "pooling_self_pay":
                expr_parts.append(
                    '(rule_type == "统筹分段" or rule_type == "支付比例" or rule_type == "退休优惠" or rule_type == "人员系数")'
                )
            elif intent:
                from src.runtime.policy_qa.models import PolicyQAIntent
                if intent == PolicyQAIntent.DEDUCTIBLE:
                    expr_parts.append('(rule_type == "起付线" or rule_type == "起付线标准")')
                elif intent == PolicyQAIntent.PAYMENT_RATIO:
                    expr_parts.append('(rule_type == "统筹分段" or rule_type == "支付比例")')
                elif intent == PolicyQAIntent.CAP_AMOUNT:
                    expr_parts.append('(rule_type == "封顶线" or rule_type == "最高支付限额")')
```

When converting `PolicyRule`, include all existing fields. No schema change is required here.

- [ ] **Step 6: Run orchestrator tests and verify they pass**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator -v
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

Run:

```bash
git add src/runtime/policy_qa/orchestrator.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: focus policy search for pooling self pay"
```

---

### Task 6: Generate deterministic pooling self-pay explanations

**Files:**
- Modify: `src/runtime/policy_qa/explanation_generator.py`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: Write failing explanation test**

Append this test inside `TestExplanationGenerator` in `src/tests/unit/runtime/policy_qa/test_policy_qa.py`:

```python
    def test_placeholder_explains_pooling_self_pay_with_reconciliation(self):
        """无 LLM 时也必须生成可追溯的统筹自付解释。"""
        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.models import (
            ExplanationContext,
            FeeDecompositionResult,
            PolicyQAIntent,
            PolicyQAIntentResult,
            SegmentCalculationResult,
            SegmentInfo,
            TreatmentDecomposition,
            TreatmentItem,
        )

        decomposition = FeeDecompositionResult(
            treatment=TreatmentDecomposition(
                pooling_self_pay=TreatmentItem(value=4962.67, source="yb_zyfdxx.bdtczf"),
                deductible=TreatmentItem(value=650.0, source="yb_dyxxzy.bcqfje"),
            ),
            segments=SegmentCalculationResult(
                total_pay=4962.68,
                authoritative_amount=4962.67,
                reconciliation_difference=0.01,
                reconciliation_tolerance=0.01,
                reconciliation_matched=True,
                reconciliation_message="政策解释计算与业务库金额一致",
                warnings=["按现有字段估算统筹分段基数：医保内金额 - 大额支付 - 大额自付"],
                segments=[
                    SegmentInfo(
                        lower=650,
                        upper=30000,
                        amount=29350,
                        base_ratio=0.15,
                        person_ratio=0.6,
                        actual_ratio=0.09,
                        pay=2641.5,
                        calculation="29,350.00 × 15% × 60% = 29,350.00 × 9% = 2,641.50",
                        policy_source="起付线以上至3万元部分，自付比例15%",
                    )
                ],
            ),
        )
        context = ExplanationContext(
            question="为什么我这次统筹自付这么多？",
            intent=PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="1671213",
                target_fee_item="pooling_self_pay",
                target_fee_label="统筹自付",
            ),
            decomposition=decomposition,
        )

        text = ExplanationGenerator()._generate_placeholder(context)

        assert "业务库已结算的统筹自付金额为 4,962.67 元" in text
        assert "yb_zyfdxx.bdtczf" in text
        assert "基础自付比例" in text
        assert "退休人员系数" in text
        assert "政策解释计算与业务库金额一致" in text
        assert "起付线以上至3万元部分，自付比例15%" in text
```

- [ ] **Step 2: Run explanation tests and verify they fail**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestExplanationGenerator -v
```

Expected: FAIL because placeholder explanation does not use the new reconciliation structure.

- [ ] **Step 3: Add pooling self-pay placeholder branch**

Add this helper to `ExplanationGenerator` in `src/runtime/policy_qa/explanation_generator.py`:

```python
    def _generate_pooling_self_pay_placeholder(self, context: ExplanationContext) -> str:
        """基于结构化事实生成统筹自付解释，不编造比例和金额。"""
        decomposition = context.decomposition
        segments = decomposition.segments
        lines: list[str] = []

        authoritative = segments.authoritative_amount
        if authoritative is None:
            authoritative = decomposition.treatment.pooling_self_pay.value

        lines.append("根据本次结算信息，为您解释统筹自付金额。")
        lines.append("")
        lines.append(f"本次业务库已结算的统筹自付金额为 {authoritative:,.2f} 元，来源为 yb_zyfdxx.bdtczf。")
        lines.append("")

        if segments.warnings:
            lines.append("【计算口径说明】")
            for warning in segments.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        if not segments.segments:
            lines.append("未检索到完整的统筹分段政策规则，无法稳定解释计算过程。")
            lines.append("不确定性：缺少统筹分段比例政策依据。")
            return "\n".join(lines)

        lines.append("【政策解释计算过程】")
        for index, seg in enumerate(segments.segments, 1):
            lines.append(f"{index}. {seg.lower:,.0f} 元至 {seg.upper:,.0f} 元：")
            lines.append(f"   - 段内金额：{seg.amount:,.2f} 元")
            lines.append(f"   - 基础自付比例：{seg.base_ratio:.0%}")
            lines.append(f"   - 退休人员系数：{seg.person_ratio:.0%}")
            lines.append(f"   - 实际自付比例：{seg.actual_ratio:.0%}")
            lines.append(f"   - 该段自付：{seg.pay:,.2f} 元")
            lines.append(f"   - 计算：{seg.calculation}")
            if seg.policy_source:
                lines.append(f"   - 政策依据：{seg.policy_source}")
        lines.append("")
        lines.append(f"政策解释计算合计为 {segments.total_pay:,.2f} 元。")
        lines.append(f"业务库金额为 {authoritative:,.2f} 元。")
        if segments.reconciliation_difference is not None:
            lines.append(f"差异为 {segments.reconciliation_difference:,.2f} 元，容差为 {segments.reconciliation_tolerance:,.2f} 元。")
        if segments.reconciliation_message:
            lines.append(segments.reconciliation_message)
        if segments.reconciliation_matched is False:
            lines.append("请由医保办或收费人员结合正式结算系统进行人工复核。")
        return "\n".join(lines)
```

At the top of `_generate_placeholder`, add:

```python
        if context.intent.target_fee_item == "pooling_self_pay":
            return self._generate_pooling_self_pay_placeholder(context)
```

- [ ] **Step 4: Run explanation tests and verify they pass**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestExplanationGenerator -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add src/runtime/policy_qa/explanation_generator.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: generate pooling self pay explanation"
```

---

### Task 7: Expose target and reconciliation details in SSE steps

**Files:**
- Modify: `src/runtime/policy_qa/orchestrator.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Test: `src/tests/integration/api/test_policy_qa_routes.py`

- [ ] **Step 1: Write failing API-level orchestrator test**

Append this test class to `src/tests/integration/api/test_policy_qa_routes.py`:

```python
class TestPolicyQAPoolingSelfPayDetails:
    """验证政策问答步骤输出统筹自付结构化信息。"""

    @pytest.mark.asyncio
    async def test_orchestrator_emits_pooling_self_pay_details(self):
        from src.runtime.policy_qa.models import PolicyQARequest, SQLQueryResult
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        class FakeSQLFetcher:
            async def fetch_all_tables(self, settlement_id):
                return SQLQueryResult(
                    yb_brdjxx={"fund_type": "城镇职工", "PER_TYPE": "退休", "PER_TYPE_raw": "退休人员", "yllb": "普通住院"},
                    yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
                    yb_zyfdxx={"bdybnzje": 164411.81, "bdtczf": 4962.67, "bdtczfje": 91759.51, "bddegwyzf": 13407.93, "bddegwyzfje": 53631.71},
                )

        class FakeSearchEngine:
            def search(self, question, top_k=10, expr=None):
                return [
                    {"rule_id": "r1", "rule_type": "统筹分段", "amount_band": "650-30000", "payment_ratio": "0.15", "source_text": "起付线以上至3万元部分，自付比例15%", "score": 0.99},
                    {"rule_id": "r2", "rule_type": "统筹分段", "amount_band": "30000-40000", "payment_ratio": "0.10", "source_text": "3万元至4万元部分，自付比例10%", "score": 0.98},
                    {"rule_id": "r3", "rule_type": "统筹分段", "amount_band": "40000-inf", "payment_ratio": "0.05", "source_text": "4万元以上部分，自付比例5%", "score": 0.97},
                ]

        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
        from src.runtime.policy_qa.question_rewriter import QuestionRewriter

        orchestrator = PolicyQAOrchestrator(
            model_gateway=None,
            sql_fetcher=FakeSQLFetcher(),
            question_rewriter=QuestionRewriter(),
            search_engine=FakeSearchEngine(),
            fee_skill=FeeDecompositionSkill(),
            explanation_generator=ExplanationGenerator(model_gateway=None),
        )

        responses = []
        async for response in orchestrator.process(PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")):
            responses.append(response)

        intent_done = next(r for r in responses if r.step == "intent" and r.status == "done")
        rewrite_done = next(r for r in responses if r.step == "rewrite" and r.status == "done")
        decomposition_done = next(r for r in responses if r.step == "decomposition" and r.status == "done")

        assert intent_done.detail["target_fee_item"] == "pooling_self_pay"
        assert "search_query" in rewrite_done.detail
        assert "统筹" in rewrite_done.detail["search_query"]
        assert decomposition_done.detail["segments"]["authoritative_amount"] == 4962.67
        assert decomposition_done.detail["segments"]["reconciliation_tolerance"] == 0.01
```

- [ ] **Step 2: Run API test and verify it fails**

Run:

```bash
python -m pytest src/tests/integration/api/test_policy_qa_routes.py::TestPolicyQAPoolingSelfPayDetails -v
```

Expected: FAIL because intent detail and decomposition serialization do not expose target/reconciliation fields.

- [ ] **Step 3: Include target fee fields in intent detail**

In `src/runtime/policy_qa/orchestrator.py`, update the intent done detail:

```python
                detail={
                    "intent": intent_result.intent.value,
                    "settlement_id": intent_result.settlement_id,
                    "confidence": intent_result.confidence,
                    "target_fee_item": intent_result.target_fee_item,
                    "target_fee_label": intent_result.target_fee_label,
                    "query_type": intent_result.query_type,
                },
```

- [ ] **Step 4: Include reconciliation fields in `_serialize_decomposition`**

In `src/runtime/policy_qa/orchestrator.py`, extend `segments` serialization:

```python
            "segments": {
                "total_pay": decomposition.segments.total_pay,
                "authoritative_amount": decomposition.segments.authoritative_amount,
                "reconciliation_difference": decomposition.segments.reconciliation_difference,
                "reconciliation_tolerance": decomposition.segments.reconciliation_tolerance,
                "reconciliation_matched": decomposition.segments.reconciliation_matched,
                "reconciliation_message": decomposition.segments.reconciliation_message,
                "warnings": decomposition.segments.warnings,
                "segments": [
                    {
                        "lower": seg.lower,
                        "upper": seg.upper,
                        "amount": seg.amount,
                        "base_ratio": seg.base_ratio,
                        "person_ratio": seg.person_ratio,
                        "actual_ratio": seg.actual_ratio,
                        "pay": seg.pay,
                        "calculation": seg.calculation,
                        "rule_id": seg.rule_id,
                        "policy_source": seg.policy_source,
                    }
                    for seg in decomposition.segments.segments
                ],
            },
```

- [ ] **Step 5: Run API detail test and verify it passes**

Run:

```bash
python -m pytest src/tests/integration/api/test_policy_qa_routes.py::TestPolicyQAPoolingSelfPayDetails -v
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

Run:

```bash
git add src/runtime/policy_qa/orchestrator.py src/runtime/api/policy_qa_routes.py src/tests/integration/api/test_policy_qa_routes.py
git commit -m "feat: expose pooling self pay qa details"
```

---

### Task 8: Add flow test for the sample question

**Files:**
- Create: `src/tests/integration/flow/test_policy_qa_pooling_self_pay.py`

- [ ] **Step 1: Write flow test**

Create `src/tests/integration/flow/test_policy_qa_pooling_self_pay.py` with:

```python
"""统筹自付解释样板链路 Flow 测试。"""

import os

import pytest

os.environ["USE_MEMORY_STORAGE"] = "1"


@pytest.mark.asyncio
async def test_pooling_self_pay_explanation_flow_contains_context_rules_and_reconciliation():
    """端到端验证样板问题能产出上下文、规则、计算和对账解释。"""
    from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
    from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
    from src.runtime.policy_qa.models import PolicyQARequest, SQLQueryResult
    from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator
    from src.runtime.policy_qa.question_rewriter import QuestionRewriter

    class FakeSQLFetcher:
        async def fetch_all_tables(self, settlement_id):
            return SQLQueryResult(
                yb_brdjxx={
                    "fund_type": "城镇职工",
                    "fund_type_raw": "城镇职工",
                    "PER_TYPE": "退休",
                    "PER_TYPE_raw": "退休人员",
                    "yllb": "普通住院",
                    "yllb_raw": "普通住院",
                },
                yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
                yb_zyfdxx={
                    "bdfyzje": 189085.85,
                    "bdybnzje": 164411.81,
                    "bdtczf": 4962.67,
                    "bdtczfje": 91759.51,
                    "bddegwyzf": 13407.93,
                    "bddegwyzfje": 53631.71,
                    "bdgryf": 43694.67,
                },
            )

    class FakeSearchEngine:
        def search(self, question, top_k=10, expr=None):
            return [
                {"rule_id": "r1", "rule_type": "统筹分段", "insu_type": "城镇职工", "med_type": "普通住院", "psn_type": "退休", "amount_band": "650-30000", "payment_ratio": "0.15", "source_text": "起付线以上至3万元部分，自付比例15%", "score": 0.99},
                {"rule_id": "r2", "rule_type": "统筹分段", "insu_type": "城镇职工", "med_type": "普通住院", "psn_type": "退休", "amount_band": "30000-40000", "payment_ratio": "0.10", "source_text": "3万元至4万元部分，自付比例10%", "score": 0.98},
                {"rule_id": "r3", "rule_type": "统筹分段", "insu_type": "城镇职工", "med_type": "普通住院", "psn_type": "退休", "amount_band": "40000-inf", "payment_ratio": "0.05", "source_text": "4万元以上部分，自付比例5%", "score": 0.97},
            ]

    orchestrator = PolicyQAOrchestrator(
        model_gateway=None,
        sql_fetcher=FakeSQLFetcher(),
        question_rewriter=QuestionRewriter(),
        search_engine=FakeSearchEngine(),
        fee_skill=FeeDecompositionSkill(),
        explanation_generator=ExplanationGenerator(model_gateway=None),
    )

    chunks: list[str] = []
    details = {}
    async for response in orchestrator.process(
        PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")
    ):
        if response.detail:
            details[response.step] = response.detail
        if response.chunk:
            chunks.append(response.chunk)

    answer = "".join(chunks)

    assert details["intent"]["target_fee_item"] == "pooling_self_pay"
    assert "城镇职工" in details["rewrite"]["search_query"]
    assert "退休人员" in details["rewrite"]["search_query"]
    assert "住院" in details["rewrite"]["search_query"]
    assert details["decomposition"]["segments"]["authoritative_amount"] == 4962.67
    assert "业务库已结算的统筹自付金额为 4,962.67 元" in answer
    assert "退休人员系数" in answer
    assert "基础自付比例" in answer
    assert "政策依据" in answer
```

- [ ] **Step 2: Run flow test and verify it passes**

Run:

```bash
python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay.py -v
```

Expected: PASS.

- [ ] **Step 3: Commit Task 8**

Run:

```bash
git add src/tests/integration/flow/test_policy_qa_pooling_self_pay.py
git commit -m "test: add pooling self pay qa flow"
```

---

### Task 9: Run required serial verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run unit tests first**

Run:

```bash
python -m pytest src/tests/unit/runtime/policy_qa -v
```

Expected: PASS. If any test fails, fix the failure and rerun the entire command before continuing.

- [ ] **Step 2: Run API tests second**

Run:

```bash
python -m pytest src/tests/integration/api/test_policy_qa_routes.py -v
```

Expected: PASS. If any test fails, fix the failure and rerun the entire command before continuing.

- [ ] **Step 3: Run Flow tests third**

Run:

```bash
python -m pytest src/tests/integration/flow -v -k "policy_qa_pooling_self_pay or pooling_self_pay"
```

Expected: PASS. If the `-k` expression selects no tests, run this exact command instead:

```bash
python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit verification note if any test-only adjustments were made**

If no files changed after verification, do not commit. If fixes were needed, run:

```bash
git status --short
git add src/runtime/policy_qa src/runtime/api/policy_qa_routes.py src/tests/unit/runtime/policy_qa src/tests/integration/api/test_policy_qa_routes.py src/tests/integration/flow/test_policy_qa_pooling_self_pay.py
git commit -m "fix: stabilize pooling self pay qa verification"
```

Expected: commit succeeds only if files changed.

---

## Self-Review Checklist

- Spec coverage: Tasks 1-8 cover target fee item, SQL context propagation, short query rewrite, focused policy retrieval, Fee Skill calculation and `0.01` reconciliation, deterministic explanation, API/SSE detail exposure, and Flow verification.
- Placeholder scan: This plan contains no placeholder markers, no vague deferred-work phrases, and each code-changing task includes concrete snippets and commands.
- Type consistency: `target_fee_item`, `target_fee_label`, `search_query`, `explanation_context`, `authoritative_amount`, `reconciliation_difference`, `reconciliation_tolerance`, `reconciliation_matched`, `reconciliation_message`, and `warnings` are introduced before use in later tasks.
