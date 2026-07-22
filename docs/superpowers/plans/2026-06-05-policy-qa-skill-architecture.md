# Policy QA 解耦 Skill 架构 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Policy QA 费用解释流程从硬编码流水线改为自包含 Skill 包 + 工具接口适配层架构。

**Architecture:** 三层解耦 — Skill 包声明工具接口协议（Protocol），Agent 端通过适配器实现接口，skill 内 calculator.py 纯业务计算不依赖 Agent。编排器读 SKILL.md + config.yaml 驱动执行。

**Tech Stack:** Python 3.12, Protocol, PyYAML, Pydantic, FastAPI SSE, React/TypeScript (前端不改)

---

### Task 1: 创建 Skill 包目录结构

**Files:**
- Create: `skills/policy-fee-explanation/SKILL.md`
- Create: `skills/policy-fee-explanation/__init__.py`
- Create: `skills/policy-fee-explanation/config.yaml`
- Create: `skills/policy-fee-explanation/tool_interfaces.py`
- Create: `skills/policy-fee-explanation/calculator.py`

- [ ] **Step 1: 创建目录**

```bash
New-Item -ItemType Directory -Path "D:\project\hospital_medical_insurance_agent\skills\policy-fee-explanation" -Force
```

- [ ] **Step 2: 创建 `__init__.py`（空文件）**

```python
# skills/policy-fee-explanation/__init__.py
```

- [ ] **Step 3: 写入 SKILL.md**

```markdown
---
name: policy-fee-explanation
description: "解释医保费用构成，回答统筹自付、个人应付、起付线、报销比例、药品自付、医保外费用等'为什么这笔钱是这个数'类问题"
scope: project
version: "1.0.0"
tools:
  - query_sql_settlement_data     # MCP: SQL Server 查结算数据
  - search_policy_rules           # MCP: Milvus 检索政策规则
  - calculate_fee_explanation     # SKILL: 费用计算（config.yaml 路由）
  - generate_policy_explanation   # MCP: LLM 生成解释
steps:
  - id: query_sql_data
    tool: query_sql_settlement_data
    depends_on: []
    type: MCP
    label: 查询结算数据
  - id: search_policy_rules
    tool: search_policy_rules
    depends_on: [query_sql_data]
    type: KNOWLEDGE
    label: 检索政策规则
  - id: calculate_explanation
    tool: calculate_fee_explanation
    depends_on: [query_sql_data, search_policy_rules]
    type: SKILL
    label: 费用计算
  - id: generate_explanation
    tool: generate_policy_explanation
    depends_on: [query_sql_data, search_policy_rules, calculate_explanation]
    type: MCP
    label: 生成解释
config_file: config.yaml
---

# 医保费用解释 Skill

## 概述

根据意图识别确定的目标费用项（target_fee_item），自动查询结算数据、检索对应政策规则、计算费用构成、生成双视角解释。

## 适用场景

- 统筹自付为什么这么高
- 个人应付怎么计算
- 起付线是多少
- 甲类药为什么还要自付
- 医保外费用（特需等）为什么这么多
- 报销比例相关问题

## 执行流程

1. SQL 查询：从 SQL Server 获取患者结算数据（待遇分解、费用明细、年度累计、住院信息、患者登记）
2. 政策检索：按 target_fee_item 定向检索 Milvus 政策规则库
3. 费用计算：config.yaml 路由到对应计算器，执行分段计算
4. LLM 解释：流式生成患者视角 + 院端视角两份解释
```

- [ ] **Step 4: 写入 config.yaml**

```yaml
# 费用解释路由表
# key = target_fee_item，新增费用项只需加一条记录
fee_explanation_routes:
  pooling_self_pay:
    calculator: "FeeDecompositionCalculator"
    policy_filters: ["payment_ratio", "deductible", "cap"]
    description: "统筹自付解释"

  personal_liability:
    calculator: "PersonalLiabilityCalculator"
    policy_filters: ["payment_ratio", "deductible", "cap", "out_of_scope_range"]
    description: "个人应付解释"

  deductible:
    calculator: "DeductibleExplainer"
    policy_filters: ["deductible"]
    description: "起付线解释"

  out_of_scope:
    calculator: "OutOfScopeCalculator"
    policy_filters: ["catalog_scope"]
    description: "医保外费用解释"

default_route:
  calculator: "FeeDecompositionCalculator"
  policy_filters: ["payment_ratio", "deductible", "cap"]
  description: "通用费用解释"
```

- [ ] **Step 5: Commit**

```bash
git add skills/policy-fee-explanation/
git commit -m "feat: create policy-fee-explanation skill package scaffold"
```

---

### Task 2: 定义工具接口协议

**Files:**
- Create: `skills/policy-fee-explanation/tool_interfaces.py`（写入内容）

- [ ] **Step 1: 写入 tool_interfaces.py**

```python
"""工具接口协议 — Skill 声明它需要什么能力，Agent 端负责实现。

本文件定义纯接口契约，不依赖任何 Agent 项目内的具体实现。
换一个 Agent 环境时，只要实现了这些 Protocol，calculator.py 就能跑。
"""

from dataclasses import dataclass, field
from typing import Protocol, AsyncIterator


# ── 标准化数据结构 ──────────────────────────────────────────────

@dataclass
class PatientSettlementData:
    """标准化患者结算数据 — 所有 Agent 必须返回此结构"""
    settlement_id: str = ""
    treatment: dict = field(default_factory=dict)
    fee_details: list = field(default_factory=list)
    annual: dict = field(default_factory=dict)
    admission: dict = field(default_factory=dict)
    patient_info: dict = field(default_factory=dict)


@dataclass
class PolicyRule:
    """标准化政策规则"""
    title: str = ""
    clause: str = ""
    evidence_text: str = ""
    matched_reason: str = ""
    rule_type: str = ""
    score: float = 0.0


# ── 工具接口 ────────────────────────────────────────────────────

class SqlQueryTool(Protocol):
    """SQL 数据查询接口"""

    async def query(self, settlement_id: str) -> PatientSettlementData:
        """根据结算ID查询患者结算相关数据"""
        ...


class PolicySearchTool(Protocol):
    """政策规则检索接口"""

    async def search(
        self, query: str, filters: list[str], top_k: int
    ) -> list[PolicyRule]:
        """搜索政策规则，按 filters 过滤规则类型"""
        ...


class LlmExplainTool(Protocol):
    """LLM 解释生成接口"""

    async def generate_stream(self, context: dict) -> AsyncIterator[str]:
        """流式生成解释文本"""
        ...
```

- [ ] **Step 2: Commit**

```bash
git add skills/policy-fee-explanation/tool_interfaces.py
git commit -m "feat(skill): define tool interface protocols for policy-fee-explanation"
```

---

### Task 3: 编写计算器（从现有 FeeDecompositionSkill 重构）

**Files:**
- Read: `src/runtime/policy_qa/fee_decomposition_skill.py`（理解现有逻辑）
- Create: `skills/policy-fee-explanation/calculator.py`

- [ ] **Step 1: 理解现有计算逻辑**

读取 `src/runtime/policy_qa/fee_decomposition_skill.py` 的 `FeeDecompositionSkill.decompose()` 方法，它接收 `SQLQueryResult` 和 `list[PolicyRule]`，返回 `FeeDecompositionResult`。

核心逻辑：
- 解析 SQL 结果中的待遇数据（统筹内金额、起付线等）
- 根据政策规则计算分段自付比例（基础比例 × 人员系数）
- 分段计算自付金额并汇总
- 生成溯源证据

- [ ] **Step 2: 写入 calculator.py**

```python
"""费用计算器 — 纯业务逻辑，只依赖 tool_interfaces.py。

每个计算器负责一种 target_fee_item 的计算逻辑。
新增费用项时在此文件添加计算器类，并在底部 CALCULATOR_REGISTRY 注册。
"""

from .tool_interfaces import PatientSettlementData, PolicyRule


# ── 统筹自付分段计算 ────────────────────────────────────────────

class FeeDecompositionCalculator:
    """统筹自付 = Σ(各分段金额 × 各分段自付比例)"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        patient_info = sql_data.patient_info or {}

        # 1. 提取关键参数
        total_fee = treatment.get("total_fee", 0)
        in_scope = treatment.get("in_scope", 0)
        deductible = treatment.get("deductible", 0)
        pooling_self_pay_authoritative = treatment.get("pooling_self_pay", 0)

        # 2. 确定人员类型和对应的系数
        person_type = patient_info.get("person_type", "在职")
        is_retired = "退休" in str(person_type)
        fund_type = patient_info.get("fund_type", "城镇职工")

        # 3. 构建分段规则（从政策规则中提取）
        segments = self._build_segments(in_scope, deductible, fund_type, is_retired, policy_rules)

        # 4. 分段计算
        total_calculated = 0.0
        for seg in segments:
            seg["person_ratio"] = self._get_person_ratio(fund_type, is_retired)
            seg["actual_ratio"] = seg["base_ratio"] * seg["person_ratio"]
            seg["pay"] = seg["amount"] * seg["actual_ratio"]
            total_calculated += seg["pay"]

        # 5. 与权威金额对账
        reconciliation = {
            "authoritative_amount": pooling_self_pay_authoritative,
            "calculated_amount": round(total_calculated, 2),
            "difference": round(pooling_self_pay_authoritative - total_calculated, 2),
            "matched": abs(pooling_self_pay_authoritative - total_calculated) < 0.01,
        }

        return {
            "treatment": {
                "total_fee": total_fee,
                "in_scope": in_scope,
                "deductible": deductible,
                "pooling_self_pay": pooling_self_pay_authoritative,
                "personal_liability": treatment.get("personal_liability", 0),
            },
            "segments": segments,
            "reconciliation": reconciliation,
            "evidence_count": len(policy_rules),
        }

    def _build_segments(self, in_scope, deductible, fund_type, is_retired, rules):
        """从政策规则中构建分段信息"""
        segments = []
        # 起付线以下段（如果有）
        if deductible > 0:
            segments.append({
                "lower": 0, "upper": deductible,
                "amount": min(deductible, in_scope),
                "base_ratio": 0.0,
                "rule_id": "deductible_rule",
                "policy_source": "起付线规则",
                "calculation": f"起付线以下: {min(deductible, in_scope):.2f} × 0% = 0",
            })

        remaining = max(0, in_scope - deductible)

        # 从规则中提取分段比例
        band_rules = [r for r in rules if r.rule_type == "payment_ratio"]
        for rule in band_rules:
            band = self._parse_band(rule.evidence_text)
            if band and band["lower"] <= remaining:
                seg_amount = min(band["upper"] - band["lower"], remaining)
                if seg_amount > 0:
                    segments.append({
                        "lower": band["lower"],
                        "upper": band["upper"],
                        "amount": seg_amount,
                        "base_ratio": band["ratio"],
                        "rule_id": rule.clause,
                        "policy_source": rule.title or rule.clause,
                        "calculation": f"{seg_amount:.2f} × {band['ratio']*100}% × 待定",
                    })
                remaining -= seg_amount
            if remaining <= 0:
                break

        return segments

    def _parse_band(self, text: str) -> dict | None:
        """从政策条文解析分段信息，如 '3万-4万: 10%' → {lower: 30000, upper: 40000, ratio: 0.10}"""
        import re
        band_match = re.search(r'(\d+)\s*[-~万到至]+\s*(\d+)\s*[万:：]*\s*(\d+)%?', text)
        if band_match:
            lower_val = float(band_match.group(1))
            upper_val = float(band_match.group(2))
            ratio_val = float(band_match.group(3))
            # 如果数值较小（<100），可能是以"万"为单位
            if lower_val < 100:
                lower_val *= 10000
            if upper_val < 100:
                upper_val *= 10000
            if ratio_val > 1:
                ratio_val /= 100
            return {"lower": lower_val, "upper": upper_val, "ratio": ratio_val}
        return None

    def _get_person_ratio(self, fund_type: str, is_retired: bool) -> float:
        """获取人员系数 — 退休人员 60%，在职人员 100%"""
        return 0.6 if is_retired else 1.0


# ── 个人应付计算 ────────────────────────────────────────

class PersonalLiabilityCalculator:
    """个人应付 = 统筹自付 + 大额自付 + 医保外"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        total_fee = treatment.get("total_fee", 0)
        pooling_self_pay = treatment.get("pooling_self_pay", 0)
        major_self_pay = treatment.get("major_self_pay", 0)
        out_of_scope = treatment.get("out_of_scope", 0)
        personal_liability = treatment.get("personal_liability", 0)

        return {
            "treatment": {
                "total_fee": total_fee,
                "pooling_self_pay": pooling_self_pay,
                "major_self_pay": major_self_pay,
                "out_of_scope": out_of_scope,
                "personal_liability": personal_liability,
            },
            "components": [
                {"label": "统筹自付", "amount": pooling_self_pay, "source": "统筹基金分段计算"},
                {"label": "大额自付", "amount": major_self_pay, "source": "大额医疗费用补助"},
                {"label": "医保外", "amount": out_of_scope, "source": "不在医保目录内的费用"},
            ],
            "evidence_count": len(policy_rules),
        }


# ── 起付线解释 ──────────────────────────────────────────

class DeductibleExplainer:
    """解释当前结算的起付线规则"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        patient_info = sql_data.patient_info or {}
        deductible = treatment.get("deductible", 0)

        deductible_rules = [r for r in policy_rules if r.rule_type == "deductible"]

        return {
            "treatment": {
                "deductible": deductible,
                "fund_type": patient_info.get("fund_type", ""),
                "person_type": patient_info.get("person_type", ""),
                "medical_type": patient_info.get("medical_type", ""),
            },
            "rules": [
                {"clause": r.clause, "evidence": r.evidence_text}
                for r in deductible_rules
            ],
            "evidence_count": len(deductible_rules),
        }


# ── 医保外费用解释 ──────────────────────────────────────

class OutOfScopeCalculator:
    """解释医保外费用构成"""

    def calculate(
        self,
        sql_data: PatientSettlementData,
        policy_rules: list[PolicyRule],
    ) -> dict:
        treatment = sql_data.treatment or {}
        fee_details = sql_data.fee_details or []
        out_of_scope = treatment.get("out_of_scope", 0)

        # 分类医保外费用
        categories: dict[str, float] = {}
        for fee in fee_details:
            if fee.get("reimbursement_category") == "丙类":
                cat = fee.get("category", "其他")
                categories[cat] = categories.get(cat, 0) + fee.get("amount", 0)

        return {
            "treatment": {
                "out_of_scope": out_of_scope,
                "total_fee": treatment.get("total_fee", 0),
            },
            "categories": [
                {"name": name, "amount": amount}
                for name, amount in sorted(categories.items(), key=lambda x: -x[1])
            ],
            "evidence_count": len(policy_rules),
        }


# ── 计算器注册表 ─────────────────────────────────────────

CALCULATOR_REGISTRY = {
    "FeeDecompositionCalculator":  FeeDecompositionCalculator,
    "PersonalLiabilityCalculator": PersonalLiabilityCalculator,
    "DeductibleExplainer":         DeductibleExplainer,
    "OutOfScopeCalculator":        OutOfScopeCalculator,
}
```

- [ ] **Step 3: Commit**

```bash
git add skills/policy-fee-explanation/calculator.py
git commit -m "feat(skill): implement fee explanation calculators with config-driven routing"
```

---

### Task 4: 编写 Agent 端工具适配器

**Files:**
- Create: `src/runtime/policy_qa/tool_adapters.py`
- Read: `src/runtime/policy_qa/sql_data_fetcher.py`（参考现有接口）
- Read: `src/runtime/policy_qa/policy_rules_search.py`（参考现有接口）
- Read: `src/runtime/policy_qa/explanation_generator.py`（参考现有接口）

- [ ] **Step 1: 写入 tool_adapters.py**

```python
"""工具适配器 — 把 Agent 已有的基础设施适配到 skill 声明的工具接口。

每个适配器实现 skill 包 tool_interfaces.py 中定义的 Protocol。
skill 计算器只依赖接口，不依赖此处的具体实现。
"""

import sys
from pathlib import Path

# 确保 skills 目录在 Python path 中
_skill_dir = Path(__file__).parent.parent.parent / "skills"
if str(_skill_dir) not in sys.path:
    sys.path.insert(0, str(_skill_dir))

from skills.settlement_explain_skill.tool_interfaces import (
    SqlQueryTool,
    PolicySearchTool,
    LlmExplainTool,
    PatientSettlementData,
    PolicyRule,
)

from src.runtime.policy_qa.sql_data_fetcher import SQLDataFetcher
from src.runtime.policy_qa.policy_rules_search import PolicyRulesSearchEngine
from src.runtime.policy_qa.explanation_generator import ExplanationGenerator


class SqlQueryAdapter(SqlQueryTool):
    """把 SQLDataFetcher 适配到 SqlQueryTool 接口"""

    def __init__(self, fetcher: SQLDataFetcher | None = None):
        self._fetcher = fetcher

    async def query(self, settlement_id: str) -> PatientSettlementData:
        if self._fetcher is None:
            self._fetcher = SQLDataFetcher()

        result = await self._fetcher.fetch_all_tables(settlement_id)

        # 标准化输出
        return PatientSettlementData(
            settlement_id=settlement_id,
            treatment=result.yb_zyfdxx or {},
            fee_details=result.yb_zyfymx or [],
            annual={
                "year": (result.yb_dyxxnd or {}).get("year", ""),
                "accumulated": (result.yb_dyxxnd or {}).get("accumulated", 0),
            },
            admission=result.yb_dyxxzy or {},
            patient_info={
                "fund_type": (result.yb_brdjxx or {}).get("fund_type", ""),
                "person_type": (result.yb_brdjxx or {}).get("person_type", ""),
                "medical_type": (result.yb_brdjxx or {}).get("medical_type", ""),
            },
        )


class PolicySearchAdapter(PolicySearchTool):
    """把 PolicyRulesSearchEngine 适配到 PolicySearchTool 接口"""

    def __init__(self, engine: PolicyRulesSearchEngine | None = None):
        self._engine = engine

    async def search(
        self, query: str, filters: list[str], top_k: int
    ) -> list[PolicyRule]:
        if self._engine is None:
            from src.config.production import MILVUS_HOST, MILVUS_PORT
            self._engine = PolicyRulesSearchEngine(
                host=MILVUS_HOST, port=MILVUS_PORT, embedding_kind="hash"
            )

        results = await self._engine.search_async(query, top_k=top_k)

        # 按 policy_filters 过滤 + 标准化输出
        filtered = []
        for r in results:
            if not filters or r.rule_type in filters:
                filtered.append(PolicyRule(
                    title=r.title or "",
                    clause=r.clause or r.clause_id or "",
                    evidence_text=r.evidence_text or r.source_text or "",
                    matched_reason=r.matched_reason or "",
                    rule_type=r.rule_type or "",
                    score=getattr(r, "score", 0.0),
                ))
        return filtered


class LlmExplainAdapter(LlmExplainTool):
    """把 ExplanationGenerator 适配到 LlmExplainTool 接口"""

    def __init__(self, generator: ExplanationGenerator | None = None):
        self._generator = generator

    async def generate_stream(self, context: dict) -> AsyncIterator[str]:
        if self._generator is None:
            from src.model_service.gateway import ModelGateway
            model = ModelGateway()
            self._generator = ExplanationGenerator(model_gateway=model)

        async for chunk in self._generator.generate_stream(context):
            yield chunk
```

- [ ] **Step 2: 检查 policy_rules_search.py 是否有异步搜索方法**

```bash
Select-String -Path "src\runtime\policy_qa\policy_rules_search.py" -Pattern "async def search|def search"
```

如果 `PolicyRulesSearchEngine` 没有 `search_async` 方法，将适配器中的调用改为同步包装：

```python
import asyncio

async def search(self, query, filters, top_k):
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None, lambda: self._engine.search(query, top_k=top_k)
    )
    ...
```

- [ ] **Step 3: Commit**

```bash
git add src/runtime/policy_qa/tool_adapters.py
git commit -m "feat: add tool adapters bridging Agent infra to skill interfaces"
```

---

### Task 5: 简化编排器

**Files:**
- Modify: `src/runtime/policy_qa/orchestrator.py`

- [ ] **Step 1: 在 orchestrator.py 顶部添加 skill 加载逻辑**

```python
import sys
import yaml
from pathlib import Path

# 加载 skill 包
_skill_path = Path(__file__).parent.parent.parent / "skills" / "policy-fee-explanation"
if str(_skill_path.parent) not in sys.path:
    sys.path.insert(0, str(_skill_path.parent))

def _load_skill_config() -> dict:
    with open(_skill_path / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _load_calculators() -> dict:
    from skills.settlement_explain_skill.calculator import CALCULATOR_REGISTRY
    return CALCULATOR_REGISTRY
```

- [ ] **Step 2: 修改 `PolicyQAOrchestrator.__init__`**

在 `__init__` 中加载 skill 配置和计算器注册表，不再依赖硬编码的步骤列表：

```python
def __init__(self, model_gateway, sql_fetcher=None, question_rewriter=None,
             search_engine=None, fee_skill=None, explanation_generator=None):
    self.model_gateway = model_gateway
    self.sql_fetcher = sql_fetcher
    self.question_rewriter = question_rewriter
    self.search_engine = search_engine
    self.fee_skill = fee_skill
    self.explanation_generator = explanation_generator
    self.intent_detector = IntentDetector(model_gateway=model_gateway)

    # ★ 新增：加载 skill 配置
    self.skill_config = _load_skill_config()
    self.calculators = _load_calculators()
    # ★ 新增：初始化适配器
    from src.runtime.policy_qa.tool_adapters import (
        SqlQueryAdapter, PolicySearchAdapter, LlmExplainAdapter
    )
    self.adapters = {
        "sql": SqlQueryAdapter(sql_fetcher),
        "policy": PolicySearchAdapter(search_engine),
        "llm": LlmExplainAdapter(explanation_generator),
    }
```

- [ ] **Step 3: 修改 `process()` 方法**

将硬编码的 6 步流水线替换为 adapter 驱动的 4 步 + 配置路由：

```python
async def process(self, request: PolicyQARequest) -> AsyncGenerator[PolicyQAResponse, None]:
    context = ExplanationContext(question=request.question)

    try:
        # Step 0: 意图识别
        yield PolicyQAResponse(step="intent", status="running", public_message="正在识别问题意图")
        intent_result = await self._detect_intent(request)
        context.intent = intent_result
        yield PolicyQAResponse(
            step="intent", status="done",
            detail={...},
            public_detail={"summary": f"识别为「{intent_result.query_type}」问题", "confidence": intent_result.confidence},
            public_message=f"检测到「{intent_result.query_type}」问题",
        )

        target = intent_result.target_fee_item or "default"

        # Step 1: SQL 查询 (MCP)
        yield PolicyQAResponse(step="query_sql_data", status="running", public_message="正在查询患者结算数据")
        sql_data = await self.adapters["sql"].query(intent_result.settlement_id)
        context.sql_data = sql_data
        yield PolicyQAResponse(
            step="query_sql_data", status="done",
            public_message="已获取结算数据与费用明细",
            public_detail={"summary": "已查询患者结算数据与费用明细"},
        )

        # Step 2: 政策检索 (KNOWLEDGE)
        yield PolicyQAResponse(step="search_policy_rules", status="running", public_message="正在检索相关政策规则")
        route = self.skill_config["fee_explanation_routes"].get(
            target, self.skill_config["default_route"]
        )
        policy_rules = await self.adapters["policy"].search(
            intent_result.query_type or request.question,
            filters=route["policy_filters"],
            top_k=10,
        )
        context.policy_rules = policy_rules
        context.rag_miss = len(policy_rules) == 0
        yield PolicyQAResponse(
            step="search_policy_rules", status="done",
            public_message=f"检索到 {len(policy_rules)} 条政策规则",
            public_detail={"summary": f"已检索到 {len(policy_rules)} 条相关政策规则", "rules_count": len(policy_rules), "rag_miss": len(policy_rules) == 0},
        )

        # Step 3: 费用计算 (SKILL) — 配置路由
        yield PolicyQAResponse(step="calculate_explanation", status="running", public_message="正在计算费用分解")
        calculator_cls = self.calculators.get(route["calculator"])
        if calculator_cls is None:
            raise ValueError(f"未知计算器: {route['calculator']}")
        calculator = calculator_cls()
        calc_result = calculator.calculate(sql_data, policy_rules)
        context.calc_result = calc_result
        yield PolicyQAResponse(
            step="calculate_explanation", status="done",
            public_message=f"费用计算完成",
            public_detail={"summary": "费用分解计算完成", "evidence_count": calc_result.get("evidence_count", 0)},
            detail=calc_result,
        )

        # Step 4: LLM 解释 (MCP, 流式)
        yield PolicyQAResponse(step="generate_explanation", status="running", public_message="正在生成自然语言解释")
        full_response = ""
        explain_context = {
            "query_type": intent_result.query_type,
            "target_fee_item": target,
            "sql_data": sql_data,
            "policy_rules": policy_rules,
            "calc_result": calc_result,
        }
        async for chunk in self.adapters["llm"].generate_stream(explain_context):
            full_response += chunk
            yield PolicyQAResponse(step="generate_explanation", status="streaming", chunk=chunk, public_message=chunk)

        yield PolicyQAResponse(
            step="generate_explanation", status="done",
            public_message="解释生成完成",
            patient_view=full_response,
            office_view=full_response,
        )

    except Exception as e:
        logger.exception("PolicyQA processing failed")
        yield PolicyQAResponse(step="error", status="error", error=str(e))
```

- [ ] **Step 4: 删除不再需要的私有方法**

以下方法不再需要（已被 adapter 替代），可以删除或标记为 deprecated：
- `_fetch_sql_data` → 由 `SqlQueryAdapter` 替代
- `_rewrite_question` → 如果其他场景仍需要则保留
- `_search_policy_rules` → 由 `PolicySearchAdapter` 替代
- `_calculate_decomposition` → 由 `CALCULATOR_REGISTRY` 替代
- `_generate_explanation` → 由 `LlmExplainAdapter` 替代

**注意**：如果其他调用方（如 settlement 场景）仍依赖这些方法，不要删除，只在本类的 `process()` 中不再调用。

- [ ] **Step 5: Commit**

```bash
git add src/runtime/policy_qa/orchestrator.py
git commit -m "refactor: simplify PolicyQAOrchestrator to adapter-driven skill execution"
```

---

### Task 6: 运行后端测试

**Files:**
- 验证: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`

- [ ] **Step 1: 运行 Policy QA 单元测试**

```bash
python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py -v --tb=short
```

预期：37/37 通过（如果 orchestrator 改动影响了测试断言，需要更新测试用例中的步骤名预期值）

- [ ] **Step 2: 运行 Policy QA API 测试**

```bash
python -m pytest src/tests/integration/api/test_policy_qa_routes.py -v --tb=short
```

预期：所有 test_stream_endpoint_* 测试通过

- [ ] **Step 3: 如果有测试失败，修复后重新运行**

根据失败信息调整测试断言或修复代码逻辑。

---

### Task 7: 前端 STEP_CONFIGS 适配

**Files:**
- Modify: `src/apps/portal/src/components/thinking-chain.tsx`

- [ ] **Step 1: 更新 STEP_CONFIGS**

确保新增的步骤 ID 在 `STEP_CONFIGS` 中有对应条目。在 `thinking-chain.tsx` 中添加：

```typescript
// ── Policy QA Skill 步骤（新架构）──
query_sql_data: {
    icon: '🔌',
    name: '数据查询',
    type: 'MCP',
    color: '#a855f7',
    ...
},
search_policy_rules: {
    icon: '📚',
    name: '政策检索',
    type: 'KNOWLEDGE',
    color: '#eab308',
    ...
},
calculate_explanation: {
    icon: '🧮',
    name: '费用计算',
    type: 'SKILL',
    color: '#f97316',
    ...
},
generate_explanation: {
    icon: '💬',
    name: '生成解释',
    type: 'MCP',
    color: '#a855f7',
    ...
},
```

**注意**：保留旧的 `sql_query`、`search`、`decomposition`、`explain` 条目用于向后兼容（旧的 policy_qa_routes.py 直连 SSE 端点仍用这些步骤名）。

- [ ] **Step 2: 更新 policy-qa-chat.tsx 的 STEP_DISPLAY_NAMES**

在 `src/apps/portal/src/components/policy-qa-chat.tsx` 中：

```typescript
const STEP_DISPLAY_NAMES: Record<string, string> = {
    intent: '识别问题意图',
    query_sql_data: '查询结算数据',
    search_policy_rules: '检索政策依据',
    calculate_explanation: '费用计算',
    generate_explanation: '生成解释',
    // 向后兼容
    sql_query: '查询结算数据',
    search: '检索政策依据',
    decomposition: '费用计算',
    explain: '生成解释',
}
```

- [ ] **Step 3: 运行前端测试**

```bash
cd src/apps/portal && npx vitest run --config vitest.config.ts
```

预期：19/19 通过

- [ ] **Step 4: Commit**

```bash
git add src/apps/portal/src/components/thinking-chain.tsx src/apps/portal/src/components/policy-qa-chat.tsx
git commit -m "feat: update frontend step configs for new skill architecture step names"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 启动后端**

```bash
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
```

- [ ] **Step 2: curl 测试 SSE 流式**

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/policy-qa/stream \
  -H "Content-Type: application/json" \
  -d '{"question":"统筹自付为什么这么高","settlement_id":"1671213","session_id":"e2e-test"}'
```

预期输出中应包含：
- `event: step` + `"step": "intent"` + `"status": "running"` / `"done"`
- `event: step` + `"step": "query_sql_data"` + `"status": "running"` / `"done"`
- `event: step` + `"step": "search_policy_rules"` + `"status": "running"` / `"done"`
- `event: step` + `"step": "calculate_explanation"` + `"status": "running"` / `"done"`
- `event: step` + `"step": "generate_explanation"` + `"status": "running"` / `"streaming"` / `"done"`
- `event: done`

- [ ] **Step 3: 启动前端验证 UI**

```bash
cd src/apps/portal && npm run dev
```

打开 `http://localhost:3000/policy-qa`，输入结算ID `1671213`，输入问题 "统筹自付为什么这么高"，验证：

- 思维链标题显示 "🧠 AI 思维链 · 实时推理过程"
- 步骤依次出现：🎯意图识别 → 🔌数据查询(MCP) → 📚政策检索(KNOWLEDGE) → 🧮费用计算(SKILL) → 💬生成解释(MCP)
- 每步有正确的语义色和类型徽章
- 步骤状态从 running → done 正常过渡
- 最终生成双视角解释
