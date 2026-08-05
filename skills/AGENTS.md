# skills/ — Skill 驱动架构

## 概述

自包含的医保业务能力包。每个子目录是一个独立 skill，通过 YAML 配置 + Python assembler
实现声明式业务逻辑。由 `src/skill_infra/skill_loader.py` 动态发现和加载。

## 设计原则

- **产品层不写死业务逻辑**：统筹自付比例、退休人员 60%、政策查询计划等全部由 skill YAML 配置定义
- **Business Action 分类**：每个 Skill 必须声明 `business_action` 和 `business_object`（参见 `src/domain/common/actions.py`），归属于平台七类业务动作之一
- **Skill 自包含**：每个 skill 目录包含 SKILL.md（规范）、schemas/（数据契约）、templates/（解释模板）、scripts/（执行脚本）、tests/（测试用例）
- **MCP 驱动**：skill 不自行实现 MCP，通过 `agents/openai.yaml` 声明依赖已有 MCP
- **动态加载**：新增 skill 只需创建目录 + skill_manifest.yaml + assembler.py，无需修改产品代码

## 结构

```
skills/
├── AGENTS.md
├── __init__.py
└── settlement_explain_skill/         # 医保费用解释 Skill v2.0
    ├── SKILL.md                    #   YAML front matter + 13步执行流程
    ├── skill_manifest.yaml         #   SkillLoader 发现配置（业务动作、关键词、MCP 依赖）
    ├── assembler.py                #   轻量调度器（~120行，委托给 Strategy）
    ├── agents/openai.yaml          #   MCP 依赖声明
    ├── schemas/                    #   JSON Schema（input/output/trace_event/evidence）
    ├── templates/                  #   解释模板（answer/cannot_answer/partial_answer）
    ├── scripts/                    #   上下文标准化、输出校验、链路事件
    ├── references/                 #   领域术语、查询模式、字段映射、质量标准
    ├── tests/                      #   验收测试用例
    └── strategies/                 #   ★ Strategy Pattern — 费用项策略包
        ├── base.py                 #     BaseFeeStrategy 抽象类（6个抽象方法）
        ├── registry.py             #     STRATEGY_REGISTRY（延迟导入 + 实例缓存）
        ├── pooling_self_pay/       #     统筹自付策略
        │   ├── strategy.py         #       PoolingSelfPayStrategy
        │   ├── definition.yaml     #       "统筹段内按政策比例由个人承担的金额"
        │   ├── answer_template.yaml
        │   └── policy_queries.yaml #       85/90/95 + 退休60%
        ├── deductible/             #     起付线策略
        │   ├── strategy.py         #       DeductibleStrategy
        │   ├── definition.yaml     #       "医保开始报销前需先由个人承担的固定金额"
        │   ├── answer_template.yaml
        │   └── policy_queries.yaml #       起付线标准 + 二次减半
        └── large_amount_self_pay/  #     大额自付策略（框架）
            ├── strategy.py
            └── definition.yaml
```

## 如何新增 Skill

1. 创建 `skills/<skill_id>/` 目录
2. 创建 `skill_manifest.yaml`（含 `skill_id`, `business_action`, `business_object`, `supported_intents`, `excluded_intents`）
   - `business_action` 必须是 `BusinessAction` 七类之一（如 `explain`, `query`, `guide`）
   - `business_object` 必须是 `BusinessObject` 枚举值（如 `settlement`, `benefit`, `policy`）
   - Action-Object 组合必须在 `src/domain/common/actions.py` 的 `VALID_ACTION_OBJECT_PAIRS` 白名单中
3. 创建 `assembler.py`（含 `load()` 函数返回 assembler 实例，带 `execute()` 方法）
4. SkillLoader 下次 `discover()` 时自动发现

**产品代码无需修改**。

**命名约定**：`{BusinessObject}{BusinessAction}Skill`（如 `SettlementExplainSkill`、`BenefitQuerySkill`）。

## 当前已注册 Skill

| Skill ID | 业务动作 | 业务对象 | 触发方式 |
|----------|---------|---------|----------|
| `settlement_explain_skill` | `explain` | `settlement` | 关键词快筛（25 个核心词）+ LLM 语义消歧（hybrid 模式） |

### 路由机制

技能路由采用 **关键词快筛 + LLM 语义消歧** 的混合模式（`SKILL_ROUTING_MODE=hybrid`，默认）：

1. **关键词快筛**：用 `skill_manifest.yaml` 的 `supported_intents`（精简至 ~25 个用户核心词）做子字符串匹配，置信度 ≥ 0.3 直接路由（<5ms，零 LLM 成本）
2. **LLM 消歧**：关键词未命中或低置信度时，调用 LLM 做语义判断（~300ms）
3. **降级保障**：LLM 不可用时退回关键词结果

环境变量控制：
- `SKILL_ROUTING_MODE=keyword` — 纯关键词匹配（零 LLM）
- `SKILL_ROUTING_MODE=llm` — 纯 LLM 语义路由
- `SKILL_ROUTING_MODE=hybrid` — 混合模式（默认）

### 关键词清单

`supported_intents` 只保留用户对医保人员会「说出口」的词（~25 个），内部字段名由 LLM 语义理解兜底：

```
费用类: 统筹自付、起付线、门槛费、报销比例、大额自付、封顶线、自费、
        个人总支付、医保内、医保外、报销、统筹支付、大病保险、个人负担
人群类: 职工医保、居民医保、退休、在职
场景类: 为什么这么多、怎么算的、能报多少、花了多少
高频:   结算、费用
```

### Business Action 分类

每个 Skill 通过 `skill_manifest.yaml` 的 `business_action` 和 `business_object` 字段
声明其业务归属。这两个字段共同唯一确定一个 Skill。

平台定义七类 Business Action（定义在 `src/domain/common/actions.py`）：

| Action | 中文 | 核心问题 |
|--------|------|---------|
| `explain` | 解释 | 为什么 |
| `query` | 查询 | 是什么 |
| `guide` | 导办 | 怎么办 |
| `verify` | 核验 | 对不对 |
| `compare` | 对比 | 有什么不同 |
| `evaluate` | 评估 | 如果这样会怎样 |
| `analyze` | 分析 | 有什么规律 |

**原则**：
- 新增业务优先新增 Skill，不新增 Action
- 每个 Skill 必须属于一个 Primary Action
- Evaluate 与 Explain 严格区分：解释过去，评估未来

## 约束

- skill 之间互相独立，不直接依赖
- skill 不写 UI 渲染逻辑
- 解释文案由 strategy YAML 配置定义，不在 Python 代码中硬编码
- 政策查询计划由各 strategy 的 `policy_queries.yaml` 独立定义
- assembler.py 是调度器（~120行），不包含解释逻辑——所有逻辑下沉到 Strategy
- 每个 Strategy 拥有独立的 definition、template、policy_queries、warnings、completeness
