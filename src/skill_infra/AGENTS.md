# src/skill_infra/ — Skill 基础设施

## 概述

Skill 驱动架构的运行时基础设施。负责从 `skills/` 目录动态发现、
加载 skill 包，并根据用户问题路由到对应 skill。

## 业务动作分类（Business Action）

Skill 基础设施的上层是 **Business Action**（业务动作分类），
定义在 `src/domain/common/actions.py`。

### 三层路由架构

```
用户问题
  │
  ├─ 1. Business Action Recognition  ← 做什么？（7 类动作之一）
  │     Explain / Query / Guide / Verify / Compare / Evaluate / Analyze
  │
  ├─ 2. Business Object Recognition ← 处理谁？（结算/待遇/政策/目录/…）
  │     Settlement / Benefit / Policy / Directory / ChronicDisease / Referral / …
  │
  └─ 3. Skill Router                ← 哪个 Skill？
        └─ 本模块负责：关键词评分 + LLM 语义消歧
```

### 七类业务动作

| Action | 中文 | 核心问题 | 面向对象 | 路由关键词示例 |
|--------|------|---------|---------|-------------|
| `explain` | 解释 | 为什么 | 患者 | "为什么"、"怎么算的" |
| `query` | 查询 | 是什么 | 患者 | "是什么"、"有多少" |
| `guide` | 导办 | 怎么办 | 患者 | "怎么办"、"去哪办" |
| `verify` | 核验 | 对不对 | 患者/医保办 | "是不是"、"有没有错" |
| `compare` | 对比 | 有什么不同 | 患者 | "为什么不一样"、"差多少" |
| `evaluate` | 评估 | 如果这样会怎样 | 患者/医保办 | "如果"、"换成"、"退掉" |
| `analyze` | 分析 | 有什么规律 | 管理者 | "最多"、"趋势"、"排名" |

**原则**：Business Action 是平台最高层分类，不允许随意扩展。新增业务优先新增 Skill。
参见：`Business Action Specification V1.0`（项目根目录下的设计规范文档）。

### Action Router 与本模块的关系

Action Router 是平台第一层路由（决定"做什么"），本模块（Skill Router）是第三层
（决定"用哪个 Skill"）。中间层（Business Object Recognition）由场景执行器
（`src/runtime/scenario_executor.py`）负责。

当前实现中，三层路由未完全分离——关键词匹配同时隐含了 Action 和 Object 的识别。
未来演进方向：规则识别（关键词→Action）→ LLM 消歧（Action+Object）→ Skill 匹配。

## 文件

| 文件 | 职责 |
|------|------|
| `../domain/common/actions.py` | ★ `BusinessAction` + `BusinessObject` 枚举定义（平台最高层业务分类） |
| `skill_loader.py` | `SkillLoader`：扫描 `SKILLS_DIR`（`skills/`），动态 `importlib.import_module` 加载 assembler |
| `skill_router.py` | `route_question()`：委托给 unified_router；`get_assembler()`：按 skill_id 获取实例 |
| `unified_router.py` | ★ 核心路由引擎：关键词评分 + LLM 语义消歧（hybrid 模式），环境变量 `SKILL_ROUTING_MODE` 控制 |

## 路由机制

### 三种模式

通过环境变量 `SKILL_ROUTING_MODE` 切换（默认 `hybrid`）：

| 模式 | 机制 | 延迟 | LLM 成本 | 适用场景 |
|------|------|------|----------|----------|
| `keyword` | 纯关键词子字符串匹配 | <5ms | $0 | 关键词覆盖率高的已知场景 |
| `llm` | 纯 LLM 语义判断 | ~300-800ms | ~$0.002/次 | 需要最大准确率，无关键词维护 |
| `hybrid` | 关键词快筛 → 低置信度时 LLM 消歧 | 5ms (90%) / 300ms (10%) | 平均 ~$0.0003/次 | **生产推荐** |

### Hybrid 模式决策流程

```
用户问题
  │
  ├─ 关键词快筛命中 + 置信度 ≥ 0.3 → 直接返回 (<5ms，零 LLM)
  │
  ├─ 关键词快筛命中 + 置信度 < 0.3 → LLM 消歧 (~300ms)
  │   ├─ LLM 有结果 → 用 LLM 的（语义 > 关键词）
  │   └─ LLM 失败 → 退回关键词结果
  │
  └─ 关键词无命中 → LLM 消歧 (~300ms)
      ├─ LLM 判断需要技能 → 返回 skill_id
      └─ LLM 判断无需技能 / LLM 失败 → 返回 None
```

### LLM 降级保障

LLM 调用通过 `ModelGateway`，scene 为 `skill_routing`。任何异常（网络错误、超时、路由表未配置、JSON 解析失败）都会静默降级，由上层退回关键词结果或返回 None。**LLM 不可用时系统照常工作。**

### 关键词精简

`skill_manifest.yaml` 的 `supported_intents` 从 130+ 个精简至 ~25 个用户核心词，只保留用户对医保人员会「说出口」的词汇。内部字段名（如 `规则ID`、`条款标识`）由 LLM 语义理解兜底。

## 约定

- 每个 skill 目录必须有 `skill_manifest.yaml`（含 `skill_id`, `business_action`, `business_object`, `supported_intents`）
  - `business_action` 必须是 `BusinessAction` 七类枚举值之一（如 `explain`）
  - `business_object` 必须是 `BusinessObject` 枚举值之一（如 `settlement`）
  - Action-Object 组合必须在 `VALID_ACTION_OBJECT_PAIRS` 白名单中
- 每个 skill 目录必须有 `assembler.py`（含 `load()` 返回 assembler 实例）
- `SkillLoader.discover()` 自动跳过头文件/隐藏目录
- 全局单例 `get_loader()` 缓存已加载 skill

## SkillLoader 接口

```python
from src.skill_infra.skill_loader import get_loader

loader = get_loader()                        # 全局单例，自动 discover()
skill = loader.get("settlement_explain_skill")  # LoadedSkill 对象
assembler = skill.assembler                  # 带 execute() 的 assembler 实例
```

## SkillRouter 接口

```python
from src.skill_infra.skill_router import route_question, get_assembler

skill_id = route_question("我的统筹自付为什么这么多")
# → "settlement_explain_skill"

assembler = get_assembler(skill_id)
result = assembler.execute(...)
```

## LoadedSkill 数据结构

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_id` | str | 唯一标识 |
| `skill_name` | str | 中文名称 |
| `assembler` | object | assembler 实例（含 `execute()` + `build_policy_queries()`） |
| `manifest` | dict | 完整的 skill_manifest.yaml 原始字典 |
| `business_action` | str | BusinessAction 枚举值（如 `"explain"`），来自 manifest |
| `business_object` | str | BusinessObject 枚举值（如 `"settlement"`），来自 manifest |
| `include_keywords` | list[str] | 触发关键词（来自 manifest.supported_intents） |
| `excluded_intents` | list[str] | 排除关键词（来自 manifest.excluded_intents） |

## Skill 内部架构：Strategy Pattern

当一个 Skill 需要处理多个子场景（如费用解释需处理统筹自付/起付线/大额自付），
Skill 内部使用 **Strategy Pattern** 而非拆分成多个 Skill。

```
skills/settlement_explain_skill/
├── assembler.py                ← 轻量调度器（~120行，委托给 Strategy）
└── strategies/
    ├── base.py                 ← BaseFeeStrategy 抽象类
    │                             6个抽象方法：build_definition / build_policy_queries
    │                             / build_answer / build_calculation_trace
    │                             / build_warnings / build_completeness
    ├── registry.py             ← STRATEGY_REGISTRY（延迟导入 + 实例缓存）
    ├── pooling_self_pay/       ← 统筹自付策略
    │   ├── strategy.py         ←   PoolingSelfPayStrategy（含 _extract_segment_ratios）
    │   ├── definition.yaml     ←   "统筹段内按政策比例由个人承担的金额"
    │   ├── answer_template.yaml  ← 6段单一答案模板（结论/是什么钱/政策依据/比例影响/金额关系/总结）
    │   └── policy_queries.yaml ←   85/90/95 分段 + 退休60% 折算
    ├── deductible/             ← 起付线策略
    │   ├── strategy.py         ←   DeductibleStrategy
    │   ├── definition.yaml     ←   "医保开始报销前需先由个人承担的固定金额"
    │   ├── answer_template.yaml
    │   └── policy_queries.yaml ←   起付线标准 + 二次住院减半
    └── large_amount_self_pay/  ← 大额自付策略（框架）
        ├── strategy.py
        └── definition.yaml
```

**关键原则**：每个 Strategy 拥有完全独立的定义、模板、查询计划、警告、完整性判断。
问"起付线"返回起付线定义，问"统筹自付"返回统筹自付定义——两者互不干扰。

**什么时候拆 Skill**：能力边界完全不同时（fee-explanation vs fraud-detection）

**什么时候用 Strategy**：同一领域内的子能力差异（统筹自付 vs 起付线）

### 新增费用项只需 3 步

1. 创建 `strategies/<fee_item>/` 目录 + `strategy.py`（继承 BaseFeeStrategy）+ YAML 配置
2. 在 `strategies/registry.py` 注册 factory 函数
3. 无需修改 assembler.py、SkillLoader、SkillRouter、产品代码

### Assembler 调度流程

```
endpoint → assembler.execute(ctx, evidence, status, target_fee_item)
             │
             ├─ get_strategy(target_fee_item)  ← 从 registry 获取
             │
             └─ strategy.execute(ctx, evidence, status)
                  ├─ build_definition()       ← 独立定义
                  ├─ build_answer()           ← 独立单一答案模板
                  ├─ build_policy_queries()   ← 独立查询计划
                  ├─ build_calculation_trace()← 独立计算链路
                  ├─ build_warnings()         ← 独立警告
                  └─ build_completeness()     ← 独立完整性判断
```
