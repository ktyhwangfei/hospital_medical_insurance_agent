# 语义层政策规则对象指标与值域主动新增设计

日期：2026-08-12
状态：待用户书面审阅
范围：语义层"政策规则"对象（`zcgz`）下**指标（metric）**与**值域成员（standard value）**的主动发现、提议、审核与落地。不含已有指标的变更（见 §8）。

> **本版修订（v3，2026-08-12）**：补上"主动发现缺失分类维度"这一支——新增 **S5 冲突分区维度发现**（§4.8），
> 作为 §6.1 路由的第三分支（新轴提议）。这是用户核心需求的完整形态：系统从规则塌缩冲突倒推缺失维度，
> 而非等人决定加字段。v2 的 D1/D2 兜底保留，与 S5 互补：**D1 维护已有轴，S5 发现新轴**。

## 1. 背景与需求

### 1.1 现状：完全被动

"政策规则"对象（`object_code = zcgz`）当前挂 **19 个指标**[来源: `src/semantic_layer/seed.py:274`]，包含标识符（`rule_id`/`fact_id`/`policy_id`/`clause_id`/`source_text`）、带值域的维度指标（`insu_type`/`med_type`/`hosp_lv`/`psn_type`/`setl_type`/`admission_order`）、数值指标（`payment_ratio`/`personal_payment_ratio`/`deductible_amount` 等）。

这 19 个指标的新增只有两个手动入口：

- 改 `raw/数据模型1.xlsx` 的"政策规则表" sheet → 跑 `src/semantic_layer/datamodel1_importer.py` 重灌[来源: `datamodel1_importer.py:53,186`]；
- 在 `/semantic-layer/metrics` 页面手动增删改[来源: `src/apps/portal/app/semantic-layer/metrics/page.tsx`]。

值域成员同理：`StandardValueProposal` 模型与 `semantic_value_domains` / `semantic_value_mappings` 表已存在[来源: `src/knowledge_extension/rule_explanation/semantic_alignment.py:64-71`、`src/data_platform/storage/postgresql/semantic_registry_store.py`]，但同样纯靠人工填。

**没有任何机制会主动告诉管理员"这里该加一个新指标 / 新取值了"。** 这就是"被动"。

### 1.2 问题

医院医保政策年年更新：新险种、新人群、新结算方式、新限额不断出现。纯人工维护意味着新概念从"被政策写入"到"被系统认识"再到"能被正确检索"之间存在不可接受的滞后与遗漏。**而且遗漏是静默的**——规则进了库，但值域里没有这个取值，检索过滤就直接漏掉一整批规则，无人察觉。

### 1.3 目标

把指标 / 值域的"新增"从被动的人工录入，升级为：**系统从日常运转的副产物里主动发现缺口 → 带证据提议 → 人工审核门禁 → 落地进注册表。** 提议 ≠ 自动新增，人始终是门禁。

### 1.4 成功标准

1. 政策原文出现一个现有 19 个指标都装不下的新概念时，系统在下次抽取后产出一条**带原文证据的指标提议**，而非静默丢弃。
2. 现有枚举指标冒出新取值（如 `psn_type` 出现"灵活就业人员"）时，系统产出一条**值域成员提议**，而非当成脏数据丢掉。
3. 同一概念多次触发，证据自动合并、可信度提升，不重复建提议。
4. 提议**不自动进注册表**；管理员审核通过后才写入 `semantic_metrics` / `semantic_value_domains` / `semantic_value_mappings`。
5. 新指标 / 新取值落地后，下游抽取与检索立即可用，无需另一次人工同步。
6. **即使某次抽取 LLM 未自报 unknown_concepts，指标 / 值域缺口也不会静默丢失**（由 D1 值域 diff 与 D2 零结果复查兜底，§4.5/§4.6）。
7. **缺失的分类维度（轴）由系统主动发现**：同一规则身份出现多个数值、且自由文本中反复出现的归属概念能一一分区时，系统产出新轴提议（Enum 指标 + 值域 + 证据），而非等人决定加字段（S5，§4.8）。

[来源: 用户于 2026-08-12 多轮对话确认的方向与边界]

## 2. 方案选择

### 方案 A：主动信号 intake + 路由 + 统一审核台（采用）

四类主动信号汇入一个 intake，经**一个路由判断**分叉为"指标提议"或"值域提议"，两类提议并排进入**同一个审核台**，人审通过后分别写入对应表。最大化复用已有的 `CreateMetricDraft` / `StandardValueProposal` / `SourceValueMapping` 模型与三张持久化表。

优点：被动变主动；新增指标与新增取值共用一套信号源，不重复造 intake；人始终是门禁，注册表不会自动膨胀。
代价：需在抽取端加"认领不上就提议"的钩子，前端加"待审核提议"区。

### 方案 B：只做指标提议，值域仍纯人工（不采用）

少一条分叉，但放弃了价值更高、风险更大的值域成员新增——带值域的维度指标（`insu_type`/`psn_type`/`med_type`/`hosp_lv`/`setl_type`）正是检索过滤用的，值域缺值会静默漏检，比缺指标更危险。

### 方案 C：提议自动落地、不经人审（不采用）

最快，但放弃了门禁；同义词不合并、"新取值 vs 新别名"判断错误会让指标表 / 值域表迅速劣化，且不可逆。

## 3. 总体架构

```text
   政策原文冒新概念   问答检索空回   HIS字段没解释   派生模式反复   规则塌缩冲突
        (S1)            (S2)          (S3)          (S4)         (S5)
          │               │             │             │            │
          └────────┬──────┴──────┬──────┘             │            │
                   ▼             ▼                     │            │
           ┌─────────────────────────────┐           │            │
           │     主动信号 intake（带证据）│◄──────────┘◄───────────┘
           └──────────────┬──────────────┘
                          │
              ┌───────────▼───────────┐
              │  路由：这信号是新概念， │
              │  还是已有概念的新取值？ │
              └─────┬─────────────┬────┘
          新概念    │             │   已有概念的新取值/新别名
                    ▼             ▼
            ┌────────────┐  ┌──────────────┐
            │  指标提议   │  │ 值域成员提议  │
            │（新指标，若 │  │（加标准值 +  │
            │  Enum 连带  │  │  可选源值映射）│
            │  建它的值域）│  │              │
            └──────┬─────┘  └──────┬───────┘
                   └──────┬────────┘
                          ▼
              ┌───────────────────────┐
              │   统一审核台（人审）   │  /semantic-layer 提议区
              │  指标提议 │ 值域提议   │  两个 tab 并排
              └─────────┬─┬───────────┘
                 通过 ↑  │  ↓ 驳回（归档）
              ┌────────┼─────────┐
              ▼        ▼         ▼
        semantic_   semantic_   semantic_
        metrics     value_      value_
        （加指标）  domains     mappings
                    （加标准值）（加源值映射）
```

三阶段：

1. **intake**：五类信号各带结构化证据汇入（§4）。S1 另配两段确定性兜底（§4.5/§4.6），保证信号不因 LLM 非确定性而丢失；S5 直接产出新轴提议，不经旧的分叉判断。
2. **路由**：三个分支——概念对得上现有轴的"轴"→ 新取值；对不上且是单一数值概念 → 新指标；**对不上但作为分类归属反复出现、能分区冲突规则 → 新轴**（§6）。
3. **审核与落地**：三类提议（指标 / 值域 / 新轴）并排进审核台，人审通过后写表（§7）。

## 4. 主动信号

四种信号，每条带 `trigger_source` 与结构化 `evidence`。

### 4.1 S1 · 政策抽取未知（`EXTRACTION_UNKNOWN`）

**触发**：LLM 抽取一条政策时，产出一个"归不进现有 19 个指标任何一个"的概念。
**现状**：这种"没人认领"的字段没有专门机制处理，基本被丢掉或靠人后来补。
**改造**：抽取端把它连同原文证据生成一条提议（路由后判走指标提议还是值域提议）。
**证据字段**：`原始概念串`、`doc_id`、`unit_id`、`extraction_id`、`原文片段`、`该文件内出现次数`。

> 示例：新政策反复提"大额医疗互助年度起付标准 650 元"。现有 `zcgz.deductible_amount`（起付金额）是通用的，语义上装不下"大额互助专用"。→ 指标提议 `zcgz.dazhu_deductible`。

### 4.2 S2 · 问答检索空回（`DEMAND_GAP`）

**触发**：政策问答里某类问题反复检索为空（结构化检索器已产出 `missing_required_rules`[来源: `src/runtime/policy_qa/structured_policy_retriever.py`]）。
**价值**：这是"用户在问但系统答不出"的直接需求信号，比扫表更精准。
**改造**：聚合同一缺口签名（目标字段 + insu_type/med_type/hosp_lv 组合），出现 N 次即产出提议。
**证据字段**：`缺口签名`、`命中次数`、`代表性用户问题列表`。

### 4.3 S3 · 数据源字段未绑定（`DATA_SCAN`）

**触发**：`/semantic-layer/discovery` 扫描医院 SQL Server / HIS 表，发现"高频出现 + 有业务含义 + 未绑定任何指标"的列[来源: `src/apps/portal/app/semantic-layer/discovery/page.tsx`，扫描结果中 `mapped=false` 的字段]。
**现状**：discovery 页面已能扫，但结果没导流到政策侧提议。
**改造**：扫描结果里 `non_null_rate 高 + distinct_count 可枚举 + 未绑定 metric` 的列 → 提议。
**证据字段**：`table_name`、`field_name`、`sample_values`、`non_null_rate`、`distinct_count`。

### 4.4 S4 · 派生模式复发（`DERIVATION_PATTERN`）

**触发**：同一"基础指标 + 运算模式（乘系数 / 互补 / 直接复制）"出现 ≥ 2 次（如"退休个人支付 = 在职个人支付 × 0.6"与"第二次住院起付 = 第一次 × 0.5"都是乘系数）。
**改造**：建议把该派生族提升为一个正式的 `metric_type=Derived` 指标（带结构化公式），而非每次临时算。
**证据字段**：`base_metric_code`、`operator`、`已观察到的 (条件, 系数) 列表`、`涉及的 rule_id 列表`。

> 派生指标落地时复用 `src/domain/indicator/models.py` 的 `MetricFormula(expression, dependencies, type)`。

### 4.5 确定性兜底 D1 · 值域成员 diff（`VALUE_DOMAIN_GAP`）

**触发**：构建重抽后，对规则中的枚举维度字段（`insu_type`/`med_type`/`hosp_lv`/`psn_type`/`setl_type`）做确定性比对：抽取值不在已发布值域 `standard_values` 中。

**前置（关键，防噪音）**：先过别名映射 `semantic_value_mappings`——能映射到已有标准值的，**不是新值**，跳过（或补一条源值映射，不进提议）；映射查无的才视为真新取值 → 值域成员提议。

**价值**：确定性（不依赖 LLM 自报）、低噪音（只针对枚举维度）、高价值（枚举维度正是检索过滤用的，值域缺值会静默漏检）。
**证据字段**：`domain_code`、`抽取原始值`、`doc_id`、`unit_id`、`原文片段`、`出现次数`。

> 示例：规则里 `psn_type=灵活就业人员`，已发布值域 {在职, 退休, 学生儿童}，别名映射查无 → 值域成员提议 `standard_value=灵活就业人员`。

### 4.6 确定性兜底 D2 · S1 零结果复查（`EXTRACTION_RECHECK`）

**背景（实测）**：S1 依赖 LLM 在抽取那一刻自报 unknown_concepts，实测同一段原文多次抽取结果不稳定——一次报 3 个、下一次一个不报（2026-08-12 实测：`doc_7a1fbf7480d4` 手动重抽产出 3 条提议，而构建链路那次重抽 0 条）。

**触发**：构建重抽后，某单元 LLM 返回的 `unknown_concepts` 为空。

**改造**：对空结果单元发一次**独立的专门发现 prompt**——附上已发布指标清单（metric_code + name），只让 LLM 做"原文里出现但清单里没有的数值/金额/比例概念"发现任务，不复用抽取结果，取第二次意见。

**合并**：与 S1 结果按 concept fingerprint 去重并集；同一概念被两次以上独立信号命中时，`confidence` 按多源印证提升。

**效果**：把"LLM 非确定性"变成"两次意见取并集"，实际接近稳定。
**代价**：仅当 S1 为空时多一次 LLM 调用（单单元、限次），可加频率限制。

### 4.7 实测边界：为什么不做全字段级 diff

2026-08-12 对真实抽取数据的实测[来源: `doc_7a1fbf7480d4` 08:08 构建的抽取记录]：

- 规则非空字段 14 个，其中不在 registry 的 3 个全是**元数据**（`confidence`、`entities`、`relations`）——全字段级 diff 会把元数据当指标提议 → 提议噪音洪流 → 审核疲劳 → 人工门禁变橡皮图章。
- 用户真正关心的新概念（如"大额医疗互助资金最高支付限额"）**不是独立字段**，而是藏在 `rule_value` 自由文本和 `relations` 谓词里——字段级 diff **永远看不见它们**。
- 能发现自由文本概念的两条路：LLM 自报（非确定，§4.1/§4.6 处理）或自建 NER 语义匹配（成本高、同义词误报新，等于重写 LLM 做得更好的事）。

**结论**：字段级 diff 又吵又瞎，V1 不做（写进 §11）。

### 4.8 S5 · 冲突分区维度发现（`CONFLICT_PARTITION`）

**触发**：构建重抽后，对抽取规则按身份分组，发现**同一规则身份（`rule_type`/`insu_type`/`med_type`/`psn_type`/`hosp_lv`/`setl_type` 等）下存在多个不同数值结果**——规则塌缩冲突（compiler 现有 CONFLICT 检测的同一信号）。

**分析（确定性，不依赖 LLM 自报）**：

1. 按规则身份分组，筛出"多值组"（同一身份 ≥2 个不同数值）；
2. 对每个多值组，从自由文本（`rule_value` / `source_text` / `relations` 谓词）中提取候选归属短语；
3. **共现分区**：候选短语能否把多值组一一对应分组（含短语 X 的规则恒为数值 A，含短语 Y 的恒为数值 B）——完美分区；
4. 跨组 / 跨文档重复出现的分区概念 → 候选"新轴值"，聚合成新轴。

**产出**：新轴提议 = Enum 维度指标（建议 code 如 `fund_type`，值域 = 发现的概念集）+ 证据（每个分组的规则、数值、原文短语）。

**与 S1/D2 的区别**：S1/D2 依赖 LLM 自报概念，且会把轴误当金额指标（实测产出了 `zcgz.large_medical_mutual_fund_cap` 这类伪指标）；S5 从规则数据自身的结构矛盾（冲突）倒推维度，**分类天然正确（维度而非数值），且确定性**。

**价值**：这是"主动发现缺失分类维度"的唯一可靠机制——用户要的"提炼结构化知识"（如资金类型）正是这类缺口。
**证据字段**：身份签名、冲突数值集、分区短语、每条规则的归属与数值、涉及 rule_id 列表。

> 示例：身份 {insu=城镇职工, psn=在职, rule_type=支付比例} 出现 85% / 80% 两个值，自由文本中"统筹基金"恒配 85%、"大额医疗互助资金"恒配 80% → 提议新轴 `fund_type`，值域 {统筹基金, 大额医疗互助资金, 补充医疗保险, ...}。

**路由**：S5 直接走 §6.1 第三分支（新轴提议），不经过"新指标 vs 新取值"的旧判断。

## 5. 提议模型

三类提议均**复用已有模型并最小扩展**，不新建表族。

### 5.1 指标提议（复用 `CreateMetricDraft`）

| 字段 | 来源 | 说明 |
|---|---|---|
| `metric_code` | 已有 | 建议代号，如 `zcgz.dazhu_deductible` |
| `object_code` | 已有 | 固定 `zcgz` |
| `name` | 已有 | 中文名 |
| `definition` | 已有 | 标准业务定义 |
| `metric_type` | 已有 | `Atomic` / `Derived` |
| `semantic_type` | 已有 | `Amount` / `Ratio` / `Enum` / `Date` / `Count` / `String` |
| `unit` | 已有 | 单位 |
| `value_domain` | 已有（Enum 时填） | 若新建枚举指标，连带新建值域 |
| `source_binding` | 已有 | 权威来源字段绑定 |
| **`trigger_source`** | **新增** | `EXTRACTION_UNKNOWN` / `DEMAND_GAP` / `DATA_SCAN` / `DERIVATION_PATTERN` |
| **`evidence`** | **新增** | 按 `trigger_source` 结构化的证据（§4） |
| **`confidence`** | **新增** | 按证据强度与多源印证计算 |
| **`status`** | **新增** | `proposed` / `reviewing` / `accepted` / `published` / `rejected` |

### 5.2 值域成员提议（复用 `StandardValueProposalDraft`）

| 字段 | 来源 | 说明 |
|---|---|---|
| `domain_code` | 已有 | 所属值域，如 `psn_type` |
| `standard_value` | 已有 | 建议新增的标准值，如"灵活就业人员" |
| `evidence` | 已有 | 原文证据 |
| `source_ref` | 已有 | 来源引用 |
| **`trigger_source`** | **新增** | 同上 |
| **`suggested_mappings`** | **新增（可选）** | 建议的源值映射，如 `HIS.emp_type=3 → 灵活就业人员`、`原文"灵活就业" → 灵活就业人员` |
| **`status`** | 已有 | 复用 `AlignmentStatus`（`draft` → `...`） |

> 示例：政策原文出现"灵活就业人员参照城镇职工医保执行"。`psn_type` 现有值域 {在职, 退休, 学生儿童}。→ 值域成员提议，`standard_value=灵活就业人员`，`suggested_mappings=[HIS.emp_type=3→灵活就业人员, 原文"灵活就业"→灵活就业人员]`。

### 5.3 新轴提议（复用 `CreateMetricDraft`，S5 专用）

| 字段 | 来源 | 说明 |
|---|---|---|
| `metric_code` | 已有 | 建议轴代号，如 `zcgz.fund_type` |
| `semantic_type` | 已有 | **固定 `Enum`**（轴 = 分类维度，不是数值） |
| `value_domain` | 已有 | 新建值域，初始值 = S5 发现的概念集（如 {统筹基金, 大额医疗互助资金}） |
| `indexed` | 已有 | 建议 `True`（轴是检索过滤维度） |
| `extraction_hint` | 已有 | 给 LLM 的填充说明 |
| **`axis_evidence`** | **新增** | 冲突分区证据：身份签名、冲突数值集、每条规则与归属短语的对应 |
| `trigger_source` | 新增 | `CONFLICT_PARTITION` |

> 新轴提议落地后即成为新维度字段，重抽后 LLM 按契约填充；D1 值域 diff 随后维护该轴的新取值。

## 6. 路由规则

整个设计的关键是一个分叉判断。

### 6.1 主判断（三分支）

> **信号里的概念，能对上某个现有指标的"轴"（`insu_type`/`psn_type`/`med_type`/`hosp_lv`/`setl_type` 等枚举维度）吗？**
>
> - 对得上 → **已有概念的新取值** → 走**值域成员提议**。
> - 对不上，且是单一数值概念 → **全新数值指标** → 走**指标提议**。
> - 对不上，但**作为分类归属概念反复出现、能把冲突规则一一分区**（S5）→ **缺失的轴** → 走**新轴提议**（Enum 维度指标 + 值域）。

新轴提议是第三分支，也是"主动发现缺失分类维度"的关键：它从规则塌缩冲突倒推，而不是等人工发现字段缺口。

### 6.2 辅助判断：新取值 vs 新别名

进入值域提议前再判一次：这个词是**真新取值**，还是**已有取值的新别名**？

- "灵活就业人员"在 `psn_type` 里查无 → 真新取值 → 加标准值。
- "灵活就业"（少俩字）在 `psn_type` 里查无，但语义等于已有取值 → 新别名 → 不加标准值，只加**源值映射**（`原文"灵活就业" → 既有标准值`）。

判断错会让值域表越加越臃肿。这一步可用 LLM 辅助建议，但**最终结论由审核人确认**。

### 6.3 合并规则

- 同一概念（或同一缺口签名）多次触发：**合并证据、累加可信度，不重复建提议**。
- 同义词（灵活就业人员 / 灵活就业 / 灵活就业（职工））：**合并成一个标准值 + 多条源值映射**，绝不建成多个标准值。

## 7. 审核与落地

### 7.1 统一审核台

`/semantic-layer` 下新增"待审核提议"区，三个 tab 并排：

- **指标提议** tab：列表展示 `trigger_source`、建议代号、证据摘要、可信度。
- **值域提议** tab：列表展示所属值域、建议标准值、建议映射、证据摘要。
- **新轴提议** tab：列表展示建议轴代号、值域候选、冲突分区证据（哪些规则冲突、哪个短语区分了哪些数值）。

权限沿用语义层管理员边界；输出经现有脱敏机制处理。

### 7.2 状态机

```text
proposed → reviewing → accepted → published
                │           │
                └─→ rejected └─→ （归档，记录驳回原因）
```

- `proposed`：系统刚产出。
- `reviewing`：管理员打开查看即进入。
- `accepted`：已确认 `metric_code`/`indicator 分类`/`indexed`/`value_domain` 等关键字段。
- `published`：写入注册表，成为下游可消费的正式成员。
- `rejected`：归档，保留证据以备复审。

### 7.3 落地动作（通过时）

| 提议类型 | 落地 |
|---|---|
| 指标提议（Atomic / 非 Enum） | 写入 `semantic_metrics`，`status=published` |
| 指标提议（Enum） | 写入 `semantic_metrics` + 新建对应 `semantic_value_domains` 记录 |
| 指标提议（Derived） | 写入 `semantic_metrics`（`metric_type=Derived`）+ `MetricFormula` |
| **新轴提议** | 写入 `semantic_metrics`（`semantic_type=Enum`、`indexed=True`）+ 新建值域 + `extraction_hint`；重抽后 LLM 按轴填充 |
| 值域成员提议 | 向 `semantic_value_domains.standard_values` 追加标准值 + 写入 `suggested_mappings` 对应的 `semantic_value_mappings` |

**下游可用性契约**：指标 `published` 后，它成为政策知识抽取时**可以填写的合法字段**；值域成员 `published` 后，它成为对应枚举指标**可以标准化的合法取值**。无需任何额外人工同步。

## 8. 变更控制（明确不走提议流）

**修改一个已有指标（改定义 / 单位 / 值类型 / 值域绑定）不属于本设计的提议流。** 理由：主动机器擅长发现"缺"，不擅长发现"已有东西错了"；变更的信号源（校验失败、人审发现错答案、抽取不一致）是另一类，塞进同一 intake 会搅浑分叉。

变更走**受治理的编辑**：`/semantic-layer/metrics` 页面编辑 + `version` / `schema_version` / `status` 字段，改一次升一次版本。

**唯一需补的是一条变更控制硬规则**（给现有编辑路径加门禁，不新建流程）：

> 修改 `semantic_type`（如 `Amount`↔`Ratio`）或 `indexed` 标志时，**必须强制升 `schema_version` + 标记受影响的已有规则需要重新抽取/校验**。这两类是伤筋动骨的属性，改了会让存量值与检索行为失配。

将来的"抽取质量 / 不一致"信号通道建好后，其中一小撮信号会归结为"这指标定义太模糊 → 编辑定义"，到那一天再搭那座桥。**V1 不建。**

## 9. 持久化与复用

全部复用现有表，仅给提议 intake 加最小字段：

| 已有资产 | 复用方式 |
|---|---|
| `semantic_metrics` 表 | 指标提议通过后写入 |
| `semantic_value_domains` 表 | 值域提议通过后追加标准值；新 Enum 指标连带新建 |
| `semantic_value_mappings` 表 | 写入源值映射 |
| `CreateMetricDraft` / `StandardValueProposalDraft` / `SourceValueMappingDraft` | 提议模型，加 `trigger_source` / `evidence` / `confidence` / `status` |
| `/semantic-layer/discovery` 扫描器 | S3 信号源 |
| `structured_policy_retriever.missing_required_rules` | S2 信号源 |

[来源: `src/data_platform/storage/postgresql/semantic_registry_store.py`、`src/knowledge_extension/rule_explanation/semantic_alignment.py`]

## 10. 测试策略

本改动横跨抽取端、语义层存储、治理权限、API 核心契约与 Portal。实施审查按 `TEST-VERIFICATION-MATRIX.md` 的最高风险规则升级为 **R4**：人工先行设计 + T1 单元 + T2a API + T2b Flow + 对应回归与兼容性说明；因新增数据库查询模式和前端页面路径，另执行 T3 Locust 与 T4 Playwright。

### T1 单元测试

- 路由判断：新概念 → 指标提议；已有概念新取值 → 值域提议；已有概念新别名 → 仅源值映射。
- 合并规则：同概念多次触发合并证据、不重复建；同义词合并为一个标准值。
- 状态机：`proposed → ... → published` 各态转移与非法转移拦截。
- 指标提议落地：Enum 类型连带建值域；Derived 类型带 `MetricFormula`。
- 值域提议落地：追加标准值 + 写源值映射。

### T2a API 测试

- 提议列表（指标 / 值域两个 tab）。
- 审核通过 → 注册表写入且下游可读。
- 审核驳回 → 归档、不写注册表。
- 未授权访问拦截。

### Portal 验证

- Vitest：提议区两个 tab、证据展开、通过 / 驳回操作、状态流转。
- TypeScript `tsc --noEmit`。
- Playwright：提议页加载、证据审阅、接受并发布的浏览器流程。
- Locust：带审核身份的提议列表查询，验证新增持久化读路径的响应时间与错误率。

## 11. 明确不做（V1）

- **变更已有指标**走编辑路径，不进提议流（§8）。
- **提议自动落地**：永远人审门禁。
- **抽取质量 / 不一致**信号通道：V1 不建，留作将来通往"定义编辑"的桥。
- **新建独立管理门户**：复用 `/semantic-layer`。
- **全字段级 diff**：实测会把元数据（`confidence`/`entities`/`relations`）误报为指标，且真概念藏在自由文本里 diff 不可见（见 §4.7）。
- S2 / S3 / S4 信号若首版来不及，至少 **D1 + S1/D2 + S5** 必须先上（见 §12）。

## 12. 实施边界与落地顺序

### 最小可验证用户故事

> 政策管理员打开 `/semantic-layer` 提议区，看到系统从最近一次政策抽取中自动产出的"大额互助起付标准"指标提议（带原文证据）、`psn_type` 下"灵活就业人员"的值域提议，以及**因规则塌缩冲突自动推出的新轴提议 `fund_type`（值域含 {统筹基金, 大额医疗互助资金, 补充医疗保险}，带分区证据）**；点击"通过"后分别成为正式指标 / 正式取值 / 正式维度；下一次抽取即可按新契约填充。**即使某次抽取 LLM 没自报 unknown_concepts，值域 diff（D1）与零结果复查（D2）仍保证缺口不会静默丢失；缺失维度由冲突分区（S5）主动发现，而非等人决定加字段。**

该故事完成前不扩展 S2/S3/S4。

### 落地顺序（确定性优先，最便宜的先做）

| 步 | 动作 | 验证 |
|---|---|---|
| **D1** | 值域成员 diff：枚举维度抽取值 vs 已发布值域（先过别名映射）→ 值域提议 | 造一个 `psn_type=灵活就业人员` 不在值域 → 出一条值域提议；造一个同义词 → 只补映射、不建新值 |
| **S1+D2** | 抽取钩子（已有 intake）+ unknown_concepts 空时专门发现复查；路由分叉到指标 / 值域两类提议；审核台两个 tab；通过后落地 | 同一段原文连抽两次：一次自报、一次空 → 复查兜底，两次都出指标提议 |
| **S5** | 冲突分区维度发现：规则身份分组 → 多值组 → 自由文本短语共现分区 → 新轴提议（Enum 指标 + 值域） | 用"大额医疗互助"文档：支付比例身份出现 85%/80% → 推出一键建议新轴 `fund_type`，值域含 {统筹基金, 大额医疗互助资金} |
| **S2** | 接 `DEMAND_GAP`：聚合 `missing_required_rules` → 提议 | 造一个反复检索空回的缺口 → 出提议 |
| **S3** | discovery 扫描结果导流 → `DATA_SCAN` 提议 | 扫到 unmapped 高频列 → 出提议 |
| **S4** | `DERIVATION_PATTERN`：派生族复发 → Derived 指标提议 | 造两条同 base 的派生 → 出一条 Derived 指标提议 |

D1、S1/D2、S5 是必做项：D1 确定性、低噪音、最快见效，维护已有轴；S1/D2 覆盖数值指标新增的主链路；**S5 是用户核心需求的完整形态——主动发现缺失维度（轴）**。S2/S3/S4 是增量信号源，按需求排队。

---

附：与 Issue #15 政策规则编译管线设计（`2026-08-11-policy-rule-compiler-trace-design.md`）的关系——本设计产出 `published` 的指标与值域成员，是政策知识抽取与检索的合法契约；编译管线若消费指标身份，应只认 `published` 状态的 `metric_code`。两份设计独立推进，本设计不依赖编译管线落地。
