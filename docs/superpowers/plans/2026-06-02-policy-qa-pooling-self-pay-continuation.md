# 统筹自付解释链路补齐 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐政策问答中“为什么我这次统筹自付这么多？”样板链路的 API 输出契约、边界提示和验证闭环。

**Architecture:** 在现有 `policy_qa` 运行时链路内做最小增强，不重构通用解释树。以结构化 `target_fee_item` 驱动短检索查询、分段计算、业务库金额对账和模板解释，API SSE 事件暴露目标费用项、短检索查询、分段对账结构与解释不确定性。

**Tech Stack:** Python 3.13、FastAPI、pytest、dataclass、现有 `src.model_service.gateway.ModelGateway`、现有 `src.runtime.policy_qa` 模块。

---

## 当前恢复状态

- `.planning/` 不存在，无法从 GSD 状态恢复；本计划基于当前工作区打开文件、设计文档和测试结果恢复任务。
- 已运行 `python -m pytest src/tests/unit/runtime/policy_qa -v --tb=short`，当前 32 个单元测试全部通过。
- 当前实现已具备：
  - `PolicyQAIntentResult.target_fee_item` 与 `target_fee_label`。
  - “统筹自付/统筹自费”关键词识别。
  - 统筹自付短检索查询与结构化解释上下文。
  - 分段计算、业务库金额对账、模板占位解释。
  - 统筹自付检索规则类型过滤。

## 文件结构与职责

- Modify: `src/runtime/policy_qa/models.py`
  - 扩展 `PolicyQAResponse` 细节结构不改类签名；必要时只补注释，不新增复杂模型，避免扩大范围。
- Modify: `src/runtime/policy_qa/orchestrator.py`
  - 在 SSE step detail 中补齐验收要求字段：意图目标费用项、检索降级 warnings、分解对账结构。
  - 将当前 `print` 调试输出逐步收敛为 `logger` 或保留最小必要输出；本计划优先不做大规模日志重构。
- Modify: `src/runtime/policy_qa/explanation_generator.py`
  - 在统筹自付模板解释中加入患者上下文、业务库权威金额说明、政策依据缺失时的不确定性声明。
  - 避免 LLM 自行补金额和比例：无模型网关时继续模板生成；有模型网关时 prompt 明确“只能润色结构化事实”。
- Modify: `src/runtime/api/policy_qa_routes.py`
  - 流式 API 保持响应格式不变，只确保事件 detail 透出新增结构化字段。
  - 测试端点如需增加契约字段，保持向后兼容。
- Modify: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`
  - 增加目标费用项 detail、分解序列化 reconciliation、缺规则不确定性、患者上下文解释的单元测试。
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
  - 增加 SSE 契约测试，重点断言返回 step 中包含目标费用项、短检索查询、分解对账结构、解释文本关键内容。
- Create or Modify: `src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py`
  - 建立端到端轻量 Flow 测试，使用假组件或直接编排器验证统筹自付样板链路输出。

---

### Task 1: 补齐意图与重写步骤的 SSE detail 契约

**Files:**
- Modify: `src/runtime/policy_qa/orchestrator.py:85-131`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: 写失败测试，断言意图完成事件包含目标费用项**

在 `TestPolicyQAOrchestrator` 内追加：

```python
    @pytest.mark.asyncio
    async def test_process_intent_detail_includes_target_fee_item(self):
        """统筹自付问题的意图 SSE detail 必须暴露结构化目标费用项。"""
        from src.runtime.policy_qa.models import PolicyQARequest
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        orchestrator = PolicyQAOrchestrator(model_gateway=None)
        events = []

        async for event in orchestrator.process(
            PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")
        ):
            events.append(event)
            if event.step == "intent" and event.status == "done":
                break

        intent_done = events[-1]
        assert intent_done.detail["intent"] == "treatment_decomposition"
        assert intent_done.detail["query_type"] == "统筹自付解释"
        assert intent_done.detail["target_fee_item"] == "pooling_self_pay"
        assert intent_done.detail["target_fee_label"] == "统筹自付"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator::test_process_intent_detail_includes_target_fee_item -v`

Expected: FAIL，失败原因是 `target_fee_item` 或 `query_type` 不在 `intent_done.detail`。

- [ ] **Step 3: 最小实现**

修改 `src/runtime/policy_qa/orchestrator.py` 中 intent done detail：

```python
                detail={
                    "intent": intent_result.intent.value,
                    "settlement_id": intent_result.settlement_id,
                    "confidence": intent_result.confidence,
                    "query_type": intent_result.query_type,
                    "target_fee_item": intent_result.target_fee_item,
                    "target_fee_label": intent_result.target_fee_label,
                },
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator::test_process_intent_detail_includes_target_fee_item -v`

Expected: PASS。

- [ ] **Step 5: 写失败测试，断言重写完成事件短检索查询与解释上下文分离**

在 `TestPolicyQAOrchestrator` 内追加：

```python
    @pytest.mark.asyncio
    async def test_process_rewrite_detail_exposes_short_query_and_context(self):
        """重写 SSE detail 必须同时暴露短检索查询和结构化解释上下文。"""
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
                    yb_dyxxnd={"fynd": "2025"},
                    yb_dyxxzy={"bcqfje": 650.0, "bcybnje": 164411.81},
                    yb_zyfdxx={"bdtczf": 4962.67, "bdtczfje": 91759.51},
                )

        orchestrator = PolicyQAOrchestrator(
            model_gateway=None,
            sql_fetcher=FakeSQLFetcher(),
            question_rewriter=QuestionRewriter(),
        )

        rewrite_done = None
        async for event in orchestrator.process(
            PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")
        ):
            if event.step == "rewrite" and event.status == "done":
                rewrite_done = event
                break

        assert rewrite_done is not None
        assert rewrite_done.detail["search_query"] == rewrite_done.detail["rewritten_question"]
        assert "【业务上下文】" not in rewrite_done.detail["search_query"]
        assert rewrite_done.detail["explanation_context"]["target_fee_item"] == "pooling_self_pay"
        assert rewrite_done.detail["semantic_mappings"]["统筹自付"] == "pooling_self_pay"
```

- [ ] **Step 6: 运行测试确认失败**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator::test_process_rewrite_detail_exposes_short_query_and_context -v`

Expected: FAIL，失败原因是 `semantic_mappings` 不在 rewrite detail。

- [ ] **Step 7: 最小实现**

修改 `src/runtime/policy_qa/orchestrator.py` 中 rewrite done detail：

```python
                detail={
                    "rewritten_question": rewritten.rewritten,
                    "search_query": rewritten.search_query,
                    "explanation_context": rewritten.explanation_context,
                    "semantic_mappings": rewritten.semantic_mappings,
                    "warnings": rewritten.warnings,
                },
```

- [ ] **Step 8: 运行局部测试**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator -v`

Expected: `TestPolicyQAOrchestrator` 全部 PASS。

- [ ] **Step 9: Commit**

```bash
git add src/runtime/policy_qa/orchestrator.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: expose policy qa target fee details"
```

---

### Task 2: 分解结果序列化补齐对账结构与 warnings

**Files:**
- Modify: `src/runtime/policy_qa/orchestrator.py:497-546`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: 写失败测试**

在 `TestPolicyQAOrchestrator` 内追加：

```python
    def test_serialize_decomposition_includes_reconciliation_and_warnings(self):
        """分解 detail 必须输出统筹自付对账结构和数据口径提示。"""
        from src.runtime.policy_qa.models import (
            FeeDecompositionResult,
            SegmentCalculationResult,
            SegmentInfo,
        )
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator

        decomposition = FeeDecompositionResult(
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
                        rule_id="r1",
                        policy_source="起付线以上至3万元部分，自付比例15%",
                    )
                ],
            )
        )

        detail = PolicyQAOrchestrator(model_gateway=None)._serialize_decomposition(decomposition)

        assert detail["segments"]["warnings"] == ["按现有字段估算统筹分段基数：医保内金额 - 大额支付 - 大额自付"]
        assert detail["segments"]["reconciliation"]["authoritative_amount"] == 4962.67
        assert detail["segments"]["reconciliation"]["calculated_amount"] == 4962.68
        assert detail["segments"]["reconciliation"]["difference"] == 0.01
        assert detail["segments"]["reconciliation"]["tolerance"] == 0.01
        assert detail["segments"]["reconciliation"]["matched"] is True
        assert detail["segments"]["reconciliation"]["message"] == "政策解释计算与业务库金额一致"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator::test_serialize_decomposition_includes_reconciliation_and_warnings -v`

Expected: FAIL，失败原因是 `warnings` 或 `reconciliation` 缺失。

- [ ] **Step 3: 最小实现**

修改 `src/runtime/policy_qa/orchestrator.py` 的 `_serialize_decomposition` 中 `segments` 字典：

```python
            "segments": {
                "total_pay": decomposition.segments.total_pay,
                "warnings": decomposition.segments.warnings,
                "reconciliation": {
                    "authoritative_amount": decomposition.segments.authoritative_amount,
                    "calculated_amount": decomposition.segments.total_pay,
                    "difference": decomposition.segments.reconciliation_difference,
                    "tolerance": decomposition.segments.reconciliation_tolerance,
                    "matched": decomposition.segments.reconciliation_matched,
                    "message": decomposition.segments.reconciliation_message,
                },
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

- [ ] **Step 4: 运行局部测试**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestPolicyQAOrchestrator::test_serialize_decomposition_includes_reconciliation_and_warnings -v`

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/runtime/policy_qa/orchestrator.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: expose policy qa reconciliation details"
```

---

### Task 3: 强化统筹自付模板解释的上下文、依据与不确定性

**Files:**
- Modify: `src/runtime/policy_qa/explanation_generator.py:438-499`
- Test: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: 写失败测试，断言解释包含患者上下文和权威金额声明**

在 `TestExplanationGenerator` 内追加：

```python
    def test_pooling_self_pay_placeholder_includes_patient_context_and_authoritative_statement(self):
        """统筹自付解释必须说明患者上下文和业务库金额权威性。"""
        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.models import (
            ExplanationContext,
            FeeDecompositionResult,
            PolicyQAIntent,
            PolicyQAIntentResult,
            RewrittenQuestion,
            SegmentCalculationResult,
            TreatmentDecomposition,
            TreatmentItem,
        )

        context = ExplanationContext(
            question="为什么我这次统筹自付这么多？",
            intent=PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="1671213",
                target_fee_item="pooling_self_pay",
                target_fee_label="统筹自付",
            ),
            rewritten_question=RewrittenQuestion(
                explanation_context={
                    "fund_type": "城镇职工",
                    "medical_type": "普通住院",
                    "person_type": "退休",
                    "year": "2025",
                }
            ),
            decomposition=FeeDecompositionResult(
                treatment=TreatmentDecomposition(
                    pooling_self_pay=TreatmentItem(value=4962.67, source="yb_zyfdxx.bdtczf"),
                ),
                segments=SegmentCalculationResult(
                    total_pay=4962.67,
                    authoritative_amount=4962.67,
                    reconciliation_matched=True,
                    reconciliation_message="政策解释计算与业务库金额一致",
                ),
            ),
        )

        text = ExplanationGenerator()._generate_placeholder(context)

        assert "城镇职工" in text
        assert "普通住院" in text
        assert "退休" in text
        assert "业务库金额为本次结算的权威金额" in text
        assert "yb_zyfdxx.bdtczf" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestExplanationGenerator::test_pooling_self_pay_placeholder_includes_patient_context_and_authoritative_statement -v`

Expected: FAIL，失败原因是缺少患者上下文或权威金额声明。

- [ ] **Step 3: 最小实现：在模板解释开头加入上下文**

修改 `_generate_pooling_self_pay_placeholder` 开头：

```python
        explanation_context = context.rewritten_question.explanation_context or {}
        patient_context_parts = []
        if explanation_context.get("fund_type"):
            patient_context_parts.append(str(explanation_context["fund_type"]))
        if explanation_context.get("medical_type"):
            patient_context_parts.append(str(explanation_context["medical_type"]))
        if explanation_context.get("person_type"):
            patient_context_parts.append(str(explanation_context["person_type"]))
        if explanation_context.get("year"):
            patient_context_parts.append(f"{explanation_context['year']}年度")

        lines = [
            "根据本次结算业务库和已检索到的统筹分段规则，为您解释“统筹自付”金额：",
            "",
        ]
        if patient_context_parts:
            lines.extend([
                "【患者与结算上下文】",
                f"- 本次上下文：{'、'.join(patient_context_parts)}。",
                "",
            ])
        lines.extend([
            "【业务库结算金额】",
            f"- 业务库已结算的统筹自付金额为 {pooling_self_pay.value:,.2f} 元。",
            "- 业务库金额为本次结算的权威金额，政策解释计算值仅用于解释和复核。",
        ])
```

- [ ] **Step 4: 写失败测试，断言缺少分段规则时输出不确定性与政策依据缺失**

在 `TestExplanationGenerator` 内追加：

```python
    def test_pooling_self_pay_placeholder_declares_uncertainty_without_segments(self):
        """缺少统筹分段规则时不能编造比例，必须输出不确定性声明。"""
        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.models import (
            ExplanationContext,
            FeeDecompositionResult,
            PolicyQAIntent,
            PolicyQAIntentResult,
            SegmentCalculationResult,
            TreatmentDecomposition,
            TreatmentItem,
        )

        context = ExplanationContext(
            question="为什么我这次统筹自付这么多？",
            intent=PolicyQAIntentResult(
                intent=PolicyQAIntent.TREATMENT_DECOMPOSITION,
                settlement_id="1671213",
                target_fee_item="pooling_self_pay",
            ),
            decomposition=FeeDecompositionResult(
                treatment=TreatmentDecomposition(
                    pooling_self_pay=TreatmentItem(value=4962.67, source="yb_zyfdxx.bdtczf"),
                ),
                segments=SegmentCalculationResult(total_pay=0.0),
            ),
        )

        text = ExplanationGenerator()._generate_placeholder(context)

        assert "未检索到完整的统筹分段政策规则" in text
        assert "不确定性：缺少统筹分段比例政策依据" in text
        assert "无法稳定解释计算过程" in text
```

- [ ] **Step 5: 运行测试确认当前状态**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestExplanationGenerator::test_pooling_self_pay_placeholder_declares_uncertainty_without_segments -v`

Expected: 可能已 PASS；如果 FAIL，按 Step 6 修复。

- [ ] **Step 6: 最小修复不确定性文案**

确保无分段规则分支为：

```python
        if not segments.segments:
            lines.append("【统筹分段计算】")
            lines.append("未检索到完整的统筹分段政策规则，无法稳定解释计算过程。")
            lines.append("不确定性：缺少统筹分段比例政策依据。")
            return "\n".join(lines)
```

- [ ] **Step 7: 运行解释生成器单元测试**

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py::TestExplanationGenerator -v`

Expected: `TestExplanationGenerator` 全部 PASS。

- [ ] **Step 8: Commit**

```bash
git add src/runtime/policy_qa/explanation_generator.py src/tests/unit/runtime/policy_qa/test_policy_qa.py
git commit -m "feat: strengthen pooling self pay explanation"
```

---

### Task 4: API SSE 契约测试覆盖目标费用项、短查询、对账结构

**Files:**
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
- Modify only if needed: `src/runtime/api/policy_qa_routes.py:61-184`

- [ ] **Step 1: 写 API SSE 契约测试**

在 `TestPolicyQAStreamEndpoint` 内追加：

```python
    def test_stream_endpoint_exposes_pooling_self_pay_contract(self, client):
        """统筹自付问题的 SSE 事件必须暴露目标费用项、短查询和分解结构。"""
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={
                "question": "为什么我这次统筹自付这么多？",
                "settlement_id": "1671213",
            },
        )

        assert response.status_code == 200
        body = response.text
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert "pooling_self_pay" in body
        assert "统筹自付" in body
        assert "search_query" in body
        assert "【业务上下文】" not in body.split("search_query", 1)[1].split("explanation_context", 1)[0]
        assert "reconciliation" in body
```

- [ ] **Step 2: 运行 API 测试确认失败或通过**

Run: `python -m pytest src/tests/integration/api/test_policy_qa_routes.py::TestPolicyQAStreamEndpoint::test_stream_endpoint_exposes_pooling_self_pay_contract -v`

Expected: 如果当前 API 初始化能跑通，新增契约应 PASS；若 FAIL，失败点应指向缺少 `pooling_self_pay`、`search_query` 或 `reconciliation`。

- [ ] **Step 3: 如 API body 缺少新增字段，修复事件输出**

`src/runtime/api/policy_qa_routes.py` 当前会把 `response.detail` 原样放入 `event_data["detail"]`，通常不需要改。若测试显示 detail 被丢失，确保以下逻辑存在：

```python
            if response.detail:
                event_data["detail"] = response.detail
```

- [ ] **Step 4: 运行完整 policy_qa API 测试**

Run: `python -m pytest src/tests/integration/api/test_policy_qa_routes.py -v`

Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/tests/integration/api/test_policy_qa_routes.py src/runtime/api/policy_qa_routes.py
git commit -m "test: cover policy qa pooling self pay sse contract"
```

---

### Task 5: Flow 测试覆盖统筹自付样板链路

**Files:**
- Create: `src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py`

- [ ] **Step 1: 创建 Flow 测试文件**

写入完整测试：

```python
"""政策问答统筹自付样板链路 Flow 测试。"""

import pytest


@pytest.mark.asyncio
async def test_policy_qa_pooling_self_pay_flow_outputs_explainable_chain():
    """输入统筹自付问题后，输出必须包含上下文、分段比例、权威金额和复核结论。"""
    from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
    from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
    from src.runtime.policy_qa.models import PolicyQARequest, PolicyRule, SQLQueryResult
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
                yb_dyxxnd={"fynd": "2025"},
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
                PolicyRule(
                    rule_id="r1",
                    rule_type="统筹分段",
                    amount_band="650-30000",
                    payment_ratio="0.15",
                    source_text="起付线以上至3万元部分，自付比例15%",
                    score=0.99,
                ).__dict__,
                PolicyRule(
                    rule_id="r2",
                    rule_type="统筹分段",
                    amount_band="30000-40000",
                    payment_ratio="0.10",
                    source_text="3万元至4万元部分，自付比例10%",
                    score=0.98,
                ).__dict__,
                PolicyRule(
                    rule_id="r3",
                    rule_type="统筹分段",
                    amount_band="40000-inf",
                    payment_ratio="0.05",
                    source_text="4万元以上部分，自付比例5%",
                    score=0.97,
                ).__dict__,
            ]

    orchestrator = PolicyQAOrchestrator(
        model_gateway=None,
        sql_fetcher=FakeSQLFetcher(),
        question_rewriter=QuestionRewriter(),
        search_engine=FakeSearchEngine(),
        fee_skill=FeeDecompositionSkill(),
        explanation_generator=ExplanationGenerator(model_gateway=None),
    )

    events = []
    async for event in orchestrator.process(
        PolicyQARequest(question="为什么我这次统筹自付这么多？", settlement_id="1671213")
    ):
        events.append(event)

    intent_done = next(event for event in events if event.step == "intent" and event.status == "done")
    rewrite_done = next(event for event in events if event.step == "rewrite" and event.status == "done")
    decomposition_done = next(event for event in events if event.step == "decomposition" and event.status == "done")
    explanation_text = "".join(event.chunk for event in events if event.step == "explain" and event.status == "streaming")

    assert intent_done.detail["target_fee_item"] == "pooling_self_pay"
    assert "城镇职工" in rewrite_done.detail["search_query"]
    assert "退休人员" in rewrite_done.detail["search_query"]
    assert "住院" in rewrite_done.detail["search_query"]
    assert decomposition_done.detail["segments"]["segments"]
    assert decomposition_done.detail["segments"]["reconciliation"]["authoritative_amount"] == 4962.67
    assert "城镇职工" in explanation_text
    assert "普通住院" in explanation_text
    assert "退休" in explanation_text
    assert "4,962.67" in explanation_text
    assert "基础自付比例" in explanation_text
    assert "退休人员系数" in explanation_text
    assert "业务库金额为本次结算的权威金额" in explanation_text
    assert "政策依据" in explanation_text
```

- [ ] **Step 2: 运行 Flow 测试确认状态**

Run: `python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py -v`

Expected: PASS。若 FAIL，按失败断言回到 Task 1-3 的相关实现补齐。

- [ ] **Step 3: Commit**

```bash
git add src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py
git commit -m "test: add policy qa pooling self pay flow"
```

---

### Task 6: 按项目硬性顺序验证

**Files:**
- No code changes unless verification fails.

- [ ] **Step 1: 单元测试**

Run: `python -m pytest src/tests/unit/runtime/policy_qa -v`

Expected: 全部 PASS。若失败，修复后重新运行整个 `src/tests/unit/runtime/policy_qa`。

- [ ] **Step 2: API 测试**

Run: `python -m pytest src/tests/integration/api/test_policy_qa_routes.py -v`

Expected: 全部 PASS。仅在 Step 1 PASS 后执行；若失败，修复后重新运行整个 `src/tests/integration/api/test_policy_qa_routes.py`。

- [ ] **Step 3: Flow 测试**

Run: `python -m pytest src/tests/integration/flow -v -k "policy_qa or pooling_self_pay"`

Expected: 全部匹配用例 PASS。仅在 Step 2 PASS 后执行；若失败，修复后重新运行该 Flow 命令。

- [ ] **Step 4: 最终检查工作区变更**

Run: `git status --short`

Expected: 只包含本计划相关文件改动；不得误改无关模块。

---

## 自查结果

- Spec coverage:
  - 目标费用项：Task 1 覆盖。
  - 短检索查询与结构化解释上下文：Task 1 覆盖。
  - 业务库权威金额与分段计算对账：Task 2、Task 3 覆盖。
  - 政策依据或不确定性声明：Task 3、Task 5 覆盖。
  - API SSE 验收字段：Task 4 覆盖。
  - Flow 验收：Task 5 覆盖。
  - 验证顺序：Task 6 覆盖。
- Placeholder scan: 未使用 TBD、TODO、implement later 或“类似 Task N”。
- Type consistency:
  - `target_fee_item`、`target_fee_label`、`search_query`、`explanation_context`、`semantic_mappings` 与当前 dataclass 字段一致。
  - `reconciliation` 子字段均来自 `SegmentCalculationResult` 现有字段。
  - Flow 测试假组件使用现有 `PolicyQAOrchestrator.process` 接口。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-02-policy-qa-pooling-self-pay-continuation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

