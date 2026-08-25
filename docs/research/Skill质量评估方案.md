# Skill 质量评估方案

> 日期: 2026-07-31 | 版本: 1.0
> 基于: `docs/research/测试模块研究-现状调研报告.md`

---

## 一、评估维度与可量化指标

### 1.1 功能正确性（Functional Correctness）【权重 30%】

| 子维度 | 可量化指标 | 测量方式 |
|--------|-----------|---------|
| Strategy 执行不崩溃 | 6 种 Strategy execute() 成功率 = 100% | 执行所有 strategy，无异常 |
| 7 抽象方法全覆盖 | 6×7=42 方法调用成功率 = 100% | 枚举调用 |
| 输出结构完整性 | `StrategyResult` 7 字段非空率 ≥ 90% | 检查 definition/patient_answer 等 |
| 金额数值正确 | 输出金额 = 输入 ctx 金额（精确匹配） | 正则提取金额对比 |
| fee_item 识别正确 | target_fee_item / target_field 映射正确率 = 100% | vs expected mapping |

### 1.2 输出一致性（Output Stability）【权重 15%】

| 子维度 | 可量化指标 | 测量方式 |
|--------|-----------|---------|
| 同输入同输出 | 同一 (ctx, evidence) 多次执行，关键信息相似度 ≥ 95% | 提取关键字段（金额、政策）做相似度对比 |
| 无模板泄漏 | forbidden_output 命中数 = 0（if t. / undefined / NaN 等） | 正则模式匹配 forbidden_output 清单 |
| JSON 可序列化 | 输出可 json.dumps 且无循环引用 | 实际序列化 |

### 1.3 边界与异常（Robustness）【权重 20%】

| 子维度 | 可量化指标 | 测量方式 |
|--------|-----------|---------|
| 零证据降级 | no_policy_matched → completeness.level != "full_policy_matched" | 断言降级正确 |
| 缺失字段处理 | ctx 缺字段时无 AttributeError/KeyError | 逐一删除字段重跑 |
| 未知 fee_item | get_strategy("unknown") → fallback 到 pooling_self_pay | 断言 fallback |
| 空证据列表 | evidence=[] → warnings 非空 + completeness 降级 | 断言降级信号 |
| 极端值 | 金额=0 / 金额=None / 金额=负数的行为 | 各自断言输出合理性 |
| 超长 ctx | ctx 含 100+ 字段时无崩溃 | 构造大 ctx |

### 1.4 可复用性（Reusability）【权重 15%】

| 子维度 | 可量化指标 | 测量方式 |
|--------|-----------|---------|
| 新增 Strategy 成本 | 从创建目录到首测通过 ≤ 3 文件 + ≤ 50 行代码 | 实际执行新增 mock strategy |
| BaseFeeStrategy 契约 | 所有子类正确实现 7 个抽象方法（无 NotImplementedError） | hasattr + callable 检查 |
| Registry 可发现 | list_strategies() 覆盖所有已注册 strategy | 断言数量 = 预期 |

### 1.5 与能力矩阵匹配度（Capability Alignment）【权重 10%】

| 子维度 | 可量化指标 | 测量方式 |
|--------|-----------|---------|
| manifest 声明有效 | `is_valid_action_object(action, object)` = True | actions.py 函数 |
| 关键词覆盖 | supported_intents 命中预期用户问题的比例 | 采样 50 个典型问题 |
| 路由准确率 | SkillRouter 对 50 个标注问题的路由正确率 | 构造 ground truth |
| MCP 依赖对齐 | required_mcp 列表中的 MCP 确实被 assembler 使用 | 静态分析 imports |

### 1.6 性能（Performance）【权重 10%】

| 子维度 | 可量化指标 | 测量方式 |
|--------|-----------|---------|
| Strategy 执行延迟 | P50 < 50ms, P95 < 200ms（无 LLM 调用） | timeit 采样 100 次 |
| 关键词路由延迟 | < 5ms | unified_router keyword 模式 |
| Assembler 加载时间 | `get_assembler()` 首次调用 < 100ms | timeit |

---

## 二、落地到测试模块的方式

### 2.1 测试层级分配

| 评估维度 | 建议层级 | 目录 |
|---------|:--:|------|
| 功能正确性 | T1 单元 + T2b Flow | `src/tests/unit/skills/` + `src/tests/integration/flow/` |
| 输出一致性 | T1 单元 | `src/tests/unit/skills/` |
| 边界与异常 | T1 单元 | `src/tests/unit/skills/` |
| 可复用性 | T1 单元 | `src/tests/unit/skills/` |
| 能力矩阵匹配度 | T1 单元 + T2b Flow | `src/tests/unit/skills/` + `src/tests/integration/flow/` |
| 性能 | T3 性能 | `src/tests/performance/scenarios/` |

### 2.2 建议目录结构

```
src/tests/unit/skills/                      ← 新建
├── __init__.py
├── conftest.py                             ← fixtures: settlement_context, mock_evidence
├── test_skill_functional.py                ← §1.1 功能正确性
│   ├── TestAllStrategiesExecute            ← 6 种 execute() 冒烟
│   ├── TestStrategyOutputIntegrity         ← StrategyResult 字段完整性
│   ├── TestAmountAccuracy                  ← 金额精确匹配
│   └── TestFeeItemMapping                  ← target_fee_item 映射
├── test_skill_consistency.py               ← §1.2 输出一致性
│   ├── TestIdempotency                     ← 同输入同输出
│   └── TestNoTemplateLeaks                 ← forbidden_output 检查
├── test_skill_robustness.py               ← §1.3 边界与异常
│   ├── TestNoEvidence                      ← 零证据降级
│   ├── TestMissingFields                   ← 缺失字段
│   ├── TestUnknownFeeItem                  ← 未知 fee_item fallback
│   ├── TestEmptyEvidence                   ← 空证据
│   └── TestExtremeValues                   ← 极端值
├── test_skill_reusability.py              ← §1.4 可复用性
│   ├── TestBaseFeeStrategyContract         ← 抽象方法契约
│   └── TestNewStrategyCost                 ← 新增 strategy 成本
├── test_skill_capability_alignment.py     ← §1.5 能力矩阵
│   ├── TestManifestActionObjectValid       ← manifest 白名单校验
│   ├── TestKeywordCoverage                 ← 关键词覆盖率
│   └── TestMCPDependencyReflection         ← MCP 依赖一致性
└── test_skill_performance.py              ← §1.6 性能基准
    ├── TestStrategyLatency                  ← P50/P95 延迟
    └── TestKeywordRoutingLatency            ← 路由延迟
```

### 2.3 关键用例模板

#### 功能正确性

```python
# test_skill_functional.py
import pytest
from skills.settlement_explain_skill.strategies.registry import get_strategy, list_strategies
from skills.settlement_explain_skill.schemas.output_schema import validate_output

class TestAllStrategiesExecute:
    """每个 strategy 的 execute() 冒烟 + 输出结构完整性。"""

    @pytest.mark.parametrize("fee_item", [
        "pooling_self_pay", "deductible", "large_amount_self_pay",
        "pooling_payment", "personal_total_pay", "out_of_scope",
    ])
    def test_execute_does_not_crash(self, fee_item, settlement_ctx, mock_evidence):
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_ctx, mock_evidence, "policy_matched")
        assert result.patient_answer  # 核心输出非空

    @pytest.mark.parametrize("fee_item,expected_field", [
        ("pooling_self_pay", "basic_pooling_self_pay"),
        ("deductible", "deductible"),
        # ...
    ])
    def test_target_field_mapping(self, fee_item, expected_field):
        strategy = get_strategy(fee_item)
        assert strategy.fee_field == expected_field
```

#### 输出一致性

```python
# test_skill_consistency.py
from skill_manifest import FORBIDDEN_OUTPUT_PATTERNS

class TestIdempotency:
    def test_same_input_same_output(self, settlement_ctx, mock_evidence):
        strategy = get_strategy("pooling_self_pay")
        r1 = strategy.execute(settlement_ctx, mock_evidence, "policy_matched")
        r2 = strategy.execute(settlement_ctx, mock_evidence, "policy_matched")
        # 关键信息相同（金额 + 结论性文本）
        assert r1.target_fee_item == r2.target_fee_item
        # 用 difflib 比较 patient_answer 相似度
        import difflib
        ratio = difflib.SequenceMatcher(None, r1.patient_answer, r2.patient_answer).ratio()
        assert ratio >= 0.90  # 高相似度（允许模板变量差异）

class TestNoTemplateLeaks:
    FORBIDDEN = ["if t.", "undefined", "null", "NaN", "embedding_text", "Milvus score"]

    @pytest.mark.parametrize("strategy_name", list_strategies())
    def test_output_no_forbidden_tokens(self, strategy_name, settlement_ctx, mock_evidence):
        strategy = get_strategy(strategy_name)
        result = strategy.execute(settlement_ctx, mock_evidence, "policy_matched")
        combined = result.patient_answer + result.office_answer
        for token in self.FORBIDDEN:
            assert token not in combined, f"{strategy_name} 泄漏模板代码: {token}"
```

#### 能力矩阵匹配度

```python
# test_skill_capability_alignment.py
from src.domain.common.actions import BusinessAction, BusinessObject, is_valid_action_object
from src.skill_infra.skill_loader import get_loader

class TestManifestActionObjectValid:
    def test_settlement_explain_skill_declaration(self):
        loader = get_loader()
        skill = loader.get("settlement_explain_skill")
        action = BusinessAction(skill.business_action)
        obj = BusinessObject(skill.business_object)
        assert is_valid_action_object(action, obj), \
            f"manifest 声明 ({action}, {obj}) 不在能力矩阵白名单中"

    def test_all_loaded_skills_valid(self):
        loader = get_loader()
        for skill_id in loader.list_ids():
            skill = loader.get(skill_id)
            action = BusinessAction(skill.business_action)
            obj = BusinessObject(skill.business_object)
            assert is_valid_action_object(action, obj)
```

---

## 三、与现有测试的关系

### 3.1 不破坏现有代码

- `skills/settlement_explain_skill/tests/` 下的现有测试保持不变
- 新增 `src/tests/unit/skills/` 与现有 `src/tests/unit/shared/skills/`（SkillLoader 测试）是互补关系，不重叠
- 新增测试用 `src.tests.unit.skills.conftest.py` 提供共享 fixtures，避免重复

### 3.2 与现有 Flow 测试的协作

现有 `src/tests/integration/flow/` 中有：
- `test_skill_intent_matching.py` — 关键词匹配
- `test_skill_mention.py` — @-mention 执行
- `test_full_mvp_contract.py` — MVP 全链路

新增的 T2b 测试可以扩展现有 flow 测试，在现有结算异常导办流程中增加 Skill 输出质量断言。

---

## 四、实施优先级

| 优先级 | 文件 | 理由 |
|:--:|------|------|
| P0 | `test_skill_functional.py` | 基础正确性，立刻可写 |
| P0 | `test_skill_capability_alignment.py` | manifest 白名单校验，防误配 |
| P1 | `test_skill_robustness.py` | 边界覆盖 |
| P1 | `test_skill_consistency.py` | 输出质量门禁 |
| P2 | `test_skill_reusability.py` | 新 strategy 脚手架完备性 |
| P3 | `test_skill_performance.py` | 需要基准环境 |

---

## 五、风险等级

按照 `docs/governance/TEST-VERIFICATION-MATRIX.md` 的附录：

| 改动场景 | 风险等级 | 必须执行 |
|---------|:--:|------|
| 新增 skill（含新增测试目录 `unit/skills/`） | R1 | T1（本方案全部单元测试） |
| 修改 skill 内部 logic | R1 | T1 |
| 修改 `src/skill_infra/`（路由加载） | R3 | T1 + T2b |
