# 医保费用解释树手工验证模块设计

## 背景

当前 `src/knowledge_extension/rule_explanation/policy_retrieval/test_contextual_qa.py` 已能通过真实 SQL Server 与政策检索链路做上下文增强问答验证。新需求是在 `src/knowledge_extension/rule_explanation/policy_retrieval` 下，基于最新 `config/business_sql.yaml` 和外部《医保费用解释树设计文档 V1》，补充一个可连接真实 SQL Server 的医保费用解释树手工验证能力。

本次不接入 LLM、Milvus、前端或 API，只先把“费用解释树 JSON”生成稳定，让后续自然语言解释只作为翻译层。

## 目标

1. 新增可复用生产模块 `claim_explain_tree.py`，负责医保费用解释树构建。
2. 保留 `test_claim_explain_tree.py` 作为手工验证脚本，负责初始化真实 SQL Server 客户端、传入样例参数并打印结果。
3. 解释树必须体现“先目录规则层，再待遇分解层”。
4. 待遇分段比例、阈值、大额支付比例等规则参数不能写死在核心计算中，必须由调用方传入。
5. 结果必须可审计、可追溯，保留 SQL 字段来源、公式、金额、原因编码和告警。

## 非目标

- 不做 pytest 自动化测试类。
- 不改造 `ContextualPolicyQA` 问答链路。
- 不新增后端 API。
- 不接入 LLM 生成患者版解释。
- 不在核心模块内写死北京退休职工三级医院的比例和阈值。

## 文件与职责

### `src/knowledge_extension/rule_explanation/policy_retrieval/claim_explain_tree.py`

新增生产模块，包含：

- `BenefitSegmentRule`：单个基本统筹分段规则，包含名称、起始阈值、结束阈值、统筹支付比例。
- `BenefitRuleConfig`：待遇分解配置，包含基本统筹分段列表、大额支付比例、年度统筹封顶金额、当前结算前已统筹支付金额等可选参数。
- `ExplainTreeResult`：构建结果，包含 `settlement_id`、`tree`、`warnings`。
- `ClaimExplainTreeBuilder`：核心构建类，负责查询 SQL、汇总目录规则层、计算待遇分解层并输出树结构。
- 金额工具函数：统一使用 `Decimal` 和两位小数四舍五入，避免浮点误差。

### `src/knowledge_extension/rule_explanation/policy_retrieval/test_claim_explain_tree.py`

重写为手工验证脚本，职责仅包括：

- 读取 `config/business_sql.yaml`。
- 初始化 `SqlServerBusinessDataClient`。
- 构造样例 `BenefitRuleConfig`。
- 调用 `ClaimExplainTreeBuilder.build_tree()`。
- 用 `pprint(asdict(result))` 打印结果。

## 数据流

```text
test_claim_explain_tree.py
  → SqlServerBusinessDataClient(sql_config_path=config/business_sql.yaml)
  → ClaimExplainTreeBuilder(client, rule_config)
  → settlement_context 查询待遇分解字段
  → fee_catalog_context 查询医保外明细与归因
  → 目录规则层汇总
  → 待遇分解层计算
  → 医保费用解释树 JSON
```

## SQL 查询约定

使用 `config/business_sql.yaml` 中已有查询：

- `settlement_context`：读取结算上下文，参数名仍按 YAML 中 `params` 使用 `sfz`，但当前 SQL 实际条件是 `WHERE a.djh = ?`，因此脚本传入的是登记号/结算号。
- `fee_catalog_context`：读取医保外费用明细及 `ybwje_reason`。

核心模块不新增 SQL 文本，只通过 `SqlTemplateStore` 读取配置。

## 目录规则层逻辑

基于 `fee_catalog_context` 返回的医保外明细，按 `ybwje_reason` 分组汇总：

| 原因编码 | 展示节点名 |
|---|---|
| `01_特需项目` | 特需项目费用 |
| `02_丙类全自费` | 目录等级为丙类的费用 |
| `03_按自付比例` | 自付比例产生的费用 |
| `04_按住院限价A_zyxj` | 住院限价差额 |
| `05_按MEDIC_L限价` | 医保支付标准差额 |
| `99_其他未归因` | 其他未归因费用 |

说明：展示节点名采用设计文档中更严谨的说法；原始 `ybwje_reason` 保留为 `reason_code`，便于追溯 SQL 结果。

输出字段包括：

- `amount`：该原因下医保外金额汇总。
- `item_count`：明细数量。
- `zje`、`ybnje`、`ybwje`：总金额、医保内金额、医保外金额汇总。
- `reason_code`：SQL 原始归因编码。

若没有医保外明细，仍输出“医保外费用归因”节点，金额为 `0`，并追加告警说明当前查询未返回医保外项目。

## 待遇分解层逻辑

输入来自 `settlement_context`：

- `bcybnje`：本次医保内金额。
- `bcqfje`：本次起付金额。
- `bdtczfje`：本段统筹支付金额。
- `bdtczf`：本段统筹自付金额。
- `bddegwyzfje`：本段大额/公务员支付金额。
- `bddegwyzf`：本段大额/公务员自付金额。

计算节点：

1. 医保内金额。
2. 起付线。
3. 纳入待遇计算金额 = 医保内金额 - 起付线。
4. 基本统筹段：按调用方传入的 `BenefitSegmentRule` 逐段计算。
5. 大额医疗互助段 = 纳入待遇计算金额 - 基本统筹段金额。

第三段计算优先级：

1. 如果调用方提供 `annual_basic_fund_cap` 与 `basic_fund_paid_before_current`，则按年度统筹剩余额度推导可支付金额。
2. 否则按 SQL 实际 `bdtczfje` 扣减前几段理论统筹支付金额后反推。

大额段同时输出：

- 理论大额支付金额：按配置中的 `large_payment_ratio` 计算。
- 理论大额自付金额。
- SQL 实际大额支付金额。
- SQL 实际大额自付金额。
- 差异告警。

## 参数校验

`BenefitRuleConfig` 创建后需校验：

- 至少存在一个基本统筹分段。
- 每个分段比例必须在 `0` 到 `1` 之间。
- `start_amount`、`end_amount` 不能为负数。
- 有上限的分段必须满足 `end_amount > start_amount`。
- `large_payment_ratio` 必须在 `0` 到 `1` 之间。

参数错误应抛出 `ValueError`，避免生成错误解释树。

## 告警策略

以下情况写入 `warnings`：

- SQL 金额字段为空，按 `0` 参与计算。
- `fee_catalog_context` 未返回医保外明细。
- 理论统筹支付与 SQL 实际统筹支付差异超过 `0.01`。
- 理论统筹自付与 SQL 实际统筹自付差异超过 `0.01`。
- 理论大额支付与 SQL 实际大额支付差异超过 `0.01`。
- 理论大额自付与 SQL 实际大额自付差异超过 `0.01`。
- 大额段金额计算为负数时归零并告警。

## 手工验证样例

`test_claim_explain_tree.py` 默认样例：

- `settlement_id="1671213"`
- `fee_before="2025-06-29 00:00:00.000"`
- 分段配置由脚本显式传入：
  - 起付线～30000，统筹支付比例 `0.91`
  - 30000～40000，统筹支付比例 `0.94`
  - 40000～统筹封顶触发点，统筹支付比例 `0.97`
  - 大额支付比例 `0.80`

这些参数只在脚本样例中出现，核心模块不依赖固定数值。

## 验证方式

本次是手工 SQL Server 验证脚本，主要运行命令：

```bash
python -m src.knowledge_extension.rule_explanation.policy_retrieval.test_claim_explain_tree
```

由于依赖真实 SQL Server 环境变量和本地数据，自动化测试阶段只做语法编译检查：

```bash
python -m py_compile src/knowledge_extension/rule_explanation/policy_retrieval/claim_explain_tree.py src/knowledge_extension/rule_explanation/policy_retrieval/test_claim_explain_tree.py
```

如本地已配置真实 SQL Server，可再运行手工脚本核对输出树。
