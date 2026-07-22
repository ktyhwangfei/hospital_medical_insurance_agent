# Policy QA：解耦 Skill 架构 — 设计

> 日期: 2026-06-05 | 版本: v2（加入工具接口协议层）

---

## 1. 目标

1. Policy QA 的费用解释流程改为 **自包含 Skill 包**，不依赖 Agent 项目内的业务代码
2. Skill 声明所需的工具接口（SQL 查询、政策检索、LLM 解释），Agent 端通过适配器实现
3. 计算逻辑放在 skill 目录内，Agent 只提供通用基础设施
4. Skill 可注册到 Agent 技能注册网，迁移到其他 Agent 时只需实现对应接口

---

## 2. 架构

```
┌────────────────────────────────────────────────────────────┐
│  Skill 包（自包含、可发布、跨 Agent）                         │
│  skills/policy-fee-explanation/                             │
│  ├── SKILL.md           标准声明（元信息 + 步骤 + 工具声明）  │
│  ├── config.yaml        费用路由表                            │
│  ├── tool_interfaces.py 工具接口协议（Skill 需要什么）         │
│  └── calculator.py      纯业务计算逻辑（不依赖 Agent）         │
└────────────────────────────┬───────────────────────────────┘
                             │ 工具接口契约 (Protocol)
┌────────────────────────────▼───────────────────────────────┐
│  Agent 实现（本项目提供）                                     │
│  src/runtime/policy_qa/                                     │
│  ├── tool_adapters.py   把 SQL/Milvus/LLM 适配到 skill 接口  │
│  ├── orchestrator.py    意图 → 加载 Skill → 注入适配器 → 执行 │
│  ├── sql_data_fetcher.py   SQL Server 查询（不动）           │
│  ├── policy_rules_search.py  Milvus 检索（不动）             │
│  ├── explanation_generator.py LLM 解释（不动）               │
│  └── intent_detector.py  意图识别（不动）                     │
└────────────────────────────────────────────────────────────┘
```

---

## 3. 文件结构

```
skills/policy-fee-explanation/          # ★ Skill 包（自包含、可发布）
├── SKILL.md
├── config.yaml
├── tool_interfaces.py                  # 工具接口协议
└── calculator.py                       # 纯业务计算

src/runtime/policy_qa/                  # Agent 基础设施
├── tool_adapters.py                    # ★ 新增：接口适配层
├── orchestrator.py                     # 改造：简化为 skill 驱动
├── sql_data_fetcher.py                 # 不动
├── policy_rules_search.py              # 不动
├── explanation_generator.py            # 不动
├── intent_detector.py                  # 不动
├── models.py                           # 加路由配置模型
└── dictionary_normalizer.py            # 不动
```

---

## 4. 工具接口协议 — `tool_interfaces.py`

Skill 用 Python Protocol 声明需要的工具能力，不依赖 Agent 实现：

```python
from typing import Protocol, AsyncIterator

class PatientSettlementData:
    settlement_id: str
    treatment: dict
    fee_details: list
    annual: dict
    admission: dict
    patient_info: dict

class PolicyRule:
    title: str
    clause: str
    evidence_text: str
    matched_reason: str
    rule_type: str

class SqlQueryTool(Protocol):
    async def query(self, settlement_id: str) -> PatientSettlementData: ...

class PolicySearchTool(Protocol):
    async def search(self, query: str, filters: list[str], top_k: int) -> list[PolicyRule]: ...

class LlmExplainTool(Protocol):
    async def generate_stream(self, context: dict) -> AsyncIterator[str]: ...
```

---

## 5. 费用路由表 — `config.yaml`

```yaml
fee_explanation_routes:
  pooling_self_pay:
    calculator: "FeeDecompositionCalculator"
    policy_filters: ["payment_ratio", "deductible", "cap"]
  personal_liability:
    calculator: "PersonalLiabilityCalculator"
    policy_filters: ["payment_ratio", "deductible", "cap", "out_of_scope_range"]
  deductible:
    calculator: "DeductibleExplainer"
    policy_filters: ["deductible"]
  out_of_scope:
    calculator: "OutOfScopeCalculator"
    policy_filters: ["catalog_scope"]
default_route:
  calculator: "FeeDecompositionCalculator"
  policy_filters: ["payment_ratio", "deductible", "cap"]
```

---

## 6. 计算器 — `calculator.py`

纯业务逻辑，只依赖 `tool_interfaces.py` 定义的数据结构：

```python
from .tool_interfaces import PatientSettlementData, PolicyRule

class FeeDecompositionCalculator:
    def calculate(self, sql_data: PatientSettlementData, rules: list[PolicyRule]) -> dict:
        ...  # 分段比例 × 人员系数

class PersonalLiabilityCalculator:
    def calculate(self, sql_data, rules) -> dict: ...

class DeductibleExplainer:
    def calculate(self, sql_data, rules) -> dict: ...

CALCULATOR_REGISTRY = {
    "FeeDecompositionCalculator":  FeeDecompositionCalculator,
    "PersonalLiabilityCalculator": PersonalLiabilityCalculator,
    "DeductibleExplainer":         DeductibleExplainer,
}
```

---

## 7. Agent 端适配器 — `tool_adapters.py`

把 Agent 已有基础设施适配到 skill 接口：

```python
from skills.settlement_explain_skill.tool_interfaces import (
    SqlQueryTool, PolicySearchTool, LlmExplainTool,
    PatientSettlementData, PolicyRule,
)
from src.runtime.policy_qa.sql_data_fetcher import SQLDataFetcher
from src.runtime.policy_qa.policy_rules_search import PolicyRulesSearchEngine
from src.runtime.policy_qa.explanation_generator import ExplanationGenerator

class SqlQueryAdapter(SqlQueryTool):
    def __init__(self, fetcher: SQLDataFetcher):
        self.fetcher = fetcher
    async def query(self, settlement_id: str) -> PatientSettlementData:
        result = await self.fetcher.fetch_all_tables(settlement_id)
        return PatientSettlementData(...)

class PolicySearchAdapter(PolicySearchTool):
    def __init__(self, engine: PolicyRulesSearchEngine):
        self.engine = engine
    async def search(self, query: str, filters: list[str], top_k: int) -> list[PolicyRule]:
        results = await self.engine.search(query, top_k=top_k)
        return [PolicyRule(...) for r in results if r.rule_type in filters]

class LlmExplainAdapter(LlmExplainTool):
    def __init__(self, generator: ExplanationGenerator):
        self.generator = generator
    async def generate_stream(self, context: dict) -> AsyncIterator[str]:
        async for chunk in self.generator.generate(context):
            yield chunk
```

---

## 8. 编排器 — `orchestrator.py`

简化后的流程，通过 skill 配置 + 适配器驱动：

```python
class PolicyQAOrchestrator:
    def __init__(self, skill_path: Path):
        self.skill_def = load_skill_md(skill_path / "SKILL.md")
        self.skill_config = load_yaml(skill_path / "config.yaml")
        self.calculators = load_calculators(skill_path / "calculator.py")

    async def execute(self, context, adapters: dict) -> AsyncIterator[SSEEvent]:
        # Step 1: SQL 查询 (MCP)
        yield step("query_sql_data", "running", type="MCP")
        sql_data = await adapters["sql"].query(context.encounter_id)
        yield step("query_sql_data", "done", type="MCP")

        # Step 2: 政策检索 (KNOWLEDGE)
        yield step("search_policy_rules", "running", type="KNOWLEDGE")
        route = self.skill_config["fee_explanation_routes"][context.target_fee_item]
        rules = await adapters["policy"].search(context.query, route["policy_filters"], top_k=10)
        yield step("search_policy_rules", "done", type="KNOWLEDGE")

        # Step 3: 费用计算 (SKILL) — 配置路由
        yield step("calculate_explanation", "running", type="SKILL")
        calculator = self.calculators[route["calculator"]]()
        result = calculator.calculate(sql_data, rules)
        yield step("calculate_explanation", "done", type="SKILL")

        # Step 4: LLM 解释 (MCP)
        yield step("generate_explanation", "running", type="MCP")
        async for chunk in adapters["llm"].generate_stream(result):
            yield delta(chunk)
        yield step("generate_explanation", "done", type="MCP")
```

---

## 9. 可移植性

同一个 skill 包换 Agent 环境，skill 目录零改动：

```
skills/policy-fee-explanation/          # 完全相同
    ├── SKILL.md
    ├── config.yaml
    ├── tool_interfaces.py
    └── calculator.py

new_agent/tool_adapters.py              # 实现接口即可
    ├── SqlQueryTool    → MySQL (替代 SQL Server)
    ├── PolicySearchTool → Pinecone (替代 Milvus)
    └── LlmExplainTool  → 文心一言 (替代 GPT)
```

---

## 10. 前端对照

| step_id | 类型 | 颜色 | 数据来源 |
|---------|------|------|---------|
| `query_sql_data` | MCP | 🟣 紫色 | `SqlQueryAdapter` |
| `search_policy_rules` | KNOWLEDGE | 🟡 琥珀 | `PolicySearchAdapter` |
| `calculate_explanation` | SKILL | 🟠 橙色 | `calculator.py` |
| `generate_explanation` | MCP | 🟣 紫色 | `LlmExplainAdapter` |

前端 `ThinkingChain` 已有 `MCP`/`SKILL`/`KNOWLEDGE` 类型支持，无需改。
