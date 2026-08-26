# 门诊结算结果核验 Skill 实施计划

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 在不新增第二个门诊 Skill、不硬编码地区待遇比例的前提下，把现有 `draft-cf24aa3b34fe / mzsettlement_verify_skill` 完善为可从真实门诊结算数据取数、覆盖九类问题、确定性核验金额并携带政策证据的候选 Skill。

**Architecture:** 复用现有 `mzjyxx`、发现中心、`POST /semantic/metrics/batch`、语义查询模型、Skill 草稿/物化和 Policy QA 主链。语义层负责受控取数与质量证明；Skill 按 profile 选择已发布指标并用 `Decimal` 核验；Policy QA 只编排查询、政策检索和公开结果白名单。现有住院查询及 `settlement_explain_skill` 行为保持兼容。

**Tech Stack:** Python 3.13、Pydantic 2、FastAPI、SQLAlchemy Core、pyodbc、YAML/JSON Schema、pytest、现有 PostgreSQL/Milvus/SQL Server 治理通道。

**Design:** `docs/superpowers/specs/2026-08-26-mzsettlement-verify-skill-design.md`

**Risk:** R4。涉及医保金额、真实查询、语义模型发布和公开 API 契约。必须按 Unit → API → Flow 顺序验证；新数据库查询模式还要执行性能验证，SSE 契约扩展要执行 Portal E2E。

**Compatibility:** 只给现有枚举和公开模型增加可选值/可选字段；保留 `whole_admission`、`segment`、原住院质量字段和原 assembler 路径。门诊逻辑通过 assembler 能力检测进入，不按 Skill ID 写死业务分支。

**Rollback:** 不自动激活候选 Skill。语义对象通过不可变版本保留旧版；运行回滚时切回 `mzjyxx` 上一个发布版本并禁用候选 Skill。代码回滚使用对应原子提交的 `git revert`，不改写历史。

---

## Task 1：让现有语义查询器支持门诊交易和费用明细粒度

**Files:**

- Modify: `src/semantic_layer/query_planner.py`
- Modify: `src/tests/unit/semantic_layer/test_query_planner.py`
- Modify: `src/tests/unit/semantic_layer/test_query_model_registry.py`

现有 Query Planner 是已在工作区中的实现，继续复用，不另建查询引擎。当前硬编码 `whole_admission / segment`、`segment_end_date` 和两组住院重复计数，无法正确表示单次门诊交易及项目明细。

### Step 1：先写门诊查询失败用例

在 `test_query_planner.py` 增加内存注册表夹具，登记：

- `mz_trade`：锚点 `T_SetTid`，交易键 `T_TradeNo`；
- `mz_fee_item`：交易外键 `T_TradeNo`，项目主键 `T_TradeNo + ItemId + ItemNo`；
- `mz_trade_to_fee_item`：`one_to_many`；
- 汇总指标 `total_amount / in_scope_amount / out_of_scope_amount`；
- 明细指标 `item_fee / item_in_scope / item_out_of_scope / item_self_pay2`。

断言：

```python
summary = planner.compile(_outpatient_query(scope="whole_settlement"))
assert "SET-001" not in summary.sql
assert summary.params["anchor_value"] == "SET-001"
assert summary.plan.result_grain == ["outpatient_settlement"]

detail = planner.compile(_outpatient_query(scope="fee_item", group_by=[
    "mz_fee_item.item_name", "mz_fee_item.item_level",
]))
assert detail.plan.result_grain == ["outpatient_fee_item"]
assert "GROUP BY" in detail.sql
```

同时断言：锚点多笔有效交易、交易键重复、费用明细键重复均返回 `unavailable`；明细关联缺失返回 `partial`；住院原测试不变。

### Step 2：运行测试确认红灯

Run:

```powershell
uv run python -m pytest src/tests/unit/semantic_layer/test_query_planner.py src/tests/unit/semantic_layer/test_query_model_registry.py -q
```

Expected: 新门诊用例因未知 scope、强制 `segment_end_date` 或固定住院质量别名失败；既有住院用例仍通过。

### Step 3：做最小通用化

在 `query_planner.py` 中：

- 给 `QueryScope.query_scope` 和 `SemanticQueryResult.query_scope` 增加 `whole_settlement`、`fee_item`；
- 保留现有住院汇总编译路径；
- 增加一个受限的费用明细编译路径，只允许：已发布字段、已发布关系、锚点等值过滤、登记维度分组和登记事实聚合；
- 质量计数从固定“benefit/payment segment”改为按 coverage/related 数据集产生，同时兼容读取旧别名；
- 只有住院分段模型要求 `segment_end_date`，门诊交易日期直接来自登记的日期维度；
- 费用明细查询限制 `limit <= 100`，禁止任意列、任意 SQL、任意函数和跨数据源；
- 所有事实仍在关联前按目标粒度聚合，禁止交易总额被费用明细行数放大。

建议保留清晰分支，不抽象第二套 renderer：

```python
if query.scope.query_scope == "fee_item":
    return self._build_detail_statement(query, version)
return self._build_aggregate_statement(query, version)
```

### Step 4：运行查询规划器单测

Run:

```powershell
uv run python -m pytest src/tests/unit/semantic_layer/test_query_planner.py src/tests/unit/semantic_layer/test_query_model_registry.py -q
```

Expected: 门诊汇总、项目明细、失败关闭和全部住院回归通过。

### Step 5：提交

```powershell
git add src/semantic_layer/query_planner.py src/tests/unit/semantic_layer/test_query_planner.py src/tests/unit/semantic_layer/test_query_model_registry.py
git commit -m "feat: 支持门诊结算语义查询粒度"
```

---

## Task 2：建立可复现的 `mzjyxx` 查询模型和完整指标目录

**Files:**

- Modify: `src/semantic_layer/seed.py`
- Modify: `src/semantic_layer/registry.py`
- Modify: `src/tests/unit/semantic_layer/test_seed.py`
- Modify: `src/tests/unit/semantic_layer/test_seed_three_segment.py`

生产现有对象通过治理 API 更新；种子定义用于内存测试和新环境，二者字段口径必须一致。

### Step 1：先写完整性测试

在 `test_seed.py` 增加断言：

```python
assert {d.dataset_code for d in registry.list_datasets("mzjyxx")} == {
    "mz_trade", "mz_fee_item",
}
assert registry.validate_query_model("mzjyxx") == []
assert registry.get_metric("mzjyxx.T_FeeAll").semantic_type == "Amount"
assert registry.get_metric("mzjyxx.T_SetTid").semantic_type == "String"
assert registry.get_metric("mzjyxx.T_TradeDate").semantic_type == "Date"
assert registry.get_metric("mzjyxx.TB_MZTimes").semantic_type == "Count"
```

再断言敏感字段 `P_IDNo`、`P_ICNo`、`HisName`、`HisCode` 不在 `mzjyxx` 指标、字段和公开维度中。

### Step 2：运行测试确认红灯

Run:

```powershell
uv run python -m pytest src/tests/unit/semantic_layer/test_seed.py src/tests/unit/semantic_layer/test_seed_three_segment.py -q
```

Expected: `mzjyxx` 种子或查询模型不存在。

### Step 3：增加幂等门诊种子

在 `seed.py` 增加 `_seed_outpatient_query_model(store)`，并由 `seed_semantic_layer` 调用。严格使用设计规格 §5.4 的完整清单：

- 交易定位/状态：`T_TradeNo`、`T_SetTid`、`T_FeeNo`、`T_TradeDate`、`T_State`、`T_HasRefundmented`、`T_PartialReturnFlag`、`T_OraginalTradeNo`、`T_OraginalTradeDate`、`NP_Settle_State`、`SETL_DATE`、`NT_ReTradeFlag`、`T_DiagType`；
- 人群/待遇：`P_FundType`、`PN_PersonType`、`T_CureType`、`P_JCLevel`、`P_HospFlag`、`P_Official`、`PN_ChronicFlag`、`PN_IsChronicHosp`、`PN_NoRightReason`、`PN_OutTransaction`、`PN_NationFundType`、`PN_ChronicCode`、`P_retirementflag`、`P_CivilFlag`、`P_CivilType`、`RETIRE_OFFICER_FLAG`、`T_GFBelongFlag`、`T_CompHospFlag`、`T_SpSetlFlag`、`T_pneno`、`NT_AllSelfPayFlag`；
- 当次金额：`T_FirstPay`、`T_SelfPay1`、`T_SelfPay2`、`T_SelfPayAll`、`T_BigPay`、`T_BigSelfPay`、`T_BeyondBig`、`T_FundPay`、`T_PersonCountPay`、`T_CashPay`、`PN_PersonCount`、`T_PersonCountAfter`、`T_BCPay`、`T_JCPay`、`T_FeeAll`、`T_FeeIn`、`T_FeeOut`、`T_OfficalPay`、`T_BigillPay`、`NT_BasicPay`、`NT_CivilPay`、`NT_OtherPay`、`NT_AgencySumPay`、`RETIRE_OFFICER_PAY`、`NT_OUT2_SCALE`、`NT_OUT2_PRICE`；
- 年度累计：`TB_FeeIn`、`TA_FeeIn`、`TB_BigPay`、`TA_BigPay`、`TB_FeeAfterBig`、`TA_FeeAfterBig`、`TB_MZTimes`、`TA_MZTimes`、`TB_BeyondFeeIn`、`TA_BeyondFeeIn`、`TB_BigillComm`、`TA_BigillComm`、`TB_BigillPay`、`TA_BigillPay`、`TB_CivilComm`、`TA_CivilComm`、`TB_CivilPay`、`TA_CivilPay`、`TB_FeeInL1`、`TA_FeeInL1`、`TB_BigPayL1`、`TA_BigPayL1`、`TB_FeeAfterBigL1`、`TA_FeeAfterBigL1`；
- 明细：`T_TradeNo`、`ItemId`、`ItemNo`、`ItemCode`、`StandardCode`、`ItemName`、`ItemType`、`FeeType`、`F_LEVEL`、`Count`、`UnitPrice`、`Fee`、`FeeIn`、`FeeOut`、`SelfPay2`、`FEE_SP_SCALE`、`FEE_MEDIC_L`、`MEDIC_L`、`SPEDRUG_FLAG`、`State`。

每个字段显式设置 `String / Date / Enum / Amount / Count / Ratio`，禁止依赖默认 `Amount`。金额单位为元，比例单位为 `%`；枚举只引用已审核值域。

查询模型使用：

```text
mz_trade       dbo.o_Trade     outpatient_settlement
mz_fee_item    dbo.o_FeeItem   outpatient_fee_item
anchor         mz_trade.T_SetTid
relation       mz_trade.T_TradeNo 1:N mz_fee_item.T_TradeNo
```

增加 `publish_seed_outpatient_query_object(registry)`，与现有两个发布函数一样幂等；全局内存注册表启动时发布 `mzjyxx`，但不得修改已有 PostgreSQL 对象。

### Step 4：运行种子和发布回归

Run:

```powershell
uv run python -m pytest src/tests/unit/semantic_layer/test_seed.py src/tests/unit/semantic_layer/test_seed_three_segment.py src/tests/unit/semantic_layer/test_query_model_registry.py -q
```

Expected: `mzjyxx` 可发布、查询模型无结构问题，住院种子仍通过。

### Step 5：提交

```powershell
git add src/semantic_layer/seed.py src/semantic_layer/registry.py src/tests/unit/semantic_layer/test_seed.py src/tests/unit/semantic_layer/test_seed_three_segment.py
git commit -m "feat: 补齐门诊结算语义查询模型"
```

---

## Task 3：完善发现中心批量建指标的查询元数据能力

**Files:**

- Modify: `src/runtime/api/semantic_routes.py`
- Modify: `src/tests/integration/api/test_semantic_query_model_api.py`
- Modify: `src/tests/integration/api/test_semantic_metric_change_control_api.py`

不新增接口，只扩展现有 `/semantic/metrics/batch`，使一次治理提交能同时保存发现字段映射和查询指标元数据。

### Step 1：先写 API 失败用例

新增用例提交两个 item：一个金额汇总指标，一个枚举维度指标。断言批量创建保存：

```json
{
  "metric_code": "mzjyxx.T_FeeAll",
  "semantic_type": "Amount",
  "source_table": "o_Trade",
  "source_field": "T_FeeAll",
  "fact_field_code": "mz_trade.total_amount",
  "aggregation": "max"
}
```

同时断言 `GET /semantic/objects/mzjyxx/query-model` 的 `metrics` 返回当前草稿查询指标，而不是永远为空；已存在指标仍返回 `skipped`，不覆盖已审核定义。

### Step 2：运行 API 测试确认红灯

Run:

```powershell
uv run python -m pytest src/tests/integration/api/test_semantic_query_model_api.py src/tests/integration/api/test_semantic_metric_change_control_api.py -q
```

Expected: 批量请求字段被忽略或响应中的查询指标为空。

### Step 3：扩展现有请求模型和保存逻辑

给 `BatchCreateMetricItem` 增加与 `CreateMetricRequest` 已有字段相同的：

```python
fact_field_code: str | None = None
aggregation: str | None = None
expression: str | None = None
dependencies: list[str] = Field(default_factory=list)
non_additive_dimensions: list[str] = Field(default_factory=list)
```

直接传入现有 `Metric`，不增加新服务类。`_query_model_response` 使用 `ObjectVersionMetric.from_metric` 返回带 `fact_field_code` 或 `expression` 的当前指标。

### Step 4：运行 API 测试

Run:

```powershell
uv run python -m pytest src/tests/integration/api/test_semantic_query_model_api.py src/tests/integration/api/test_semantic_metric_change_control_api.py -q
```

Expected: created/skipped/error 行为、查询指标展示和 schema version 门禁全部通过。

### Step 5：提交

```powershell
git add src/runtime/api/semantic_routes.py src/tests/integration/api/test_semantic_query_model_api.py src/tests/integration/api/test_semantic_metric_change_control_api.py
git commit -m "feat: 批量登记语义查询指标"
```

---

## Task 4：修正 Skill 输入门禁，使已发布查询指标真正可选

**Files:**

- Modify: `src/runtime/skill_management/skill_input_service.py`
- Modify: `src/runtime/skill_management/draft_validator.py`
- Modify: `src/tests/unit/runtime/skill_management/test_skill_input_service.py`
- Modify: `src/tests/unit/runtime/skill_management/test_draft_validator_and_package.py`

当前门禁只认 adapter/source_field 或默认值，无法识别 `fact_field_code`/`expression`；同时 common metrics 没有实际执行 runtime_resolvable 校验。这两处会让门诊草稿出现错误通过或错误阻断。

### Step 1：写两组失败测试

断言：

```python
assert service.resolve_metric_capability(query_metric, published_object).resolution_type \
    == MetricResolutionType.SQL_EXPRESSION
assert service.resolve_metric_capability(derived_metric, published_object).resolution_type \
    == MetricResolutionType.DERIVED
```

再构造一个 common 中引用未发布指标的执行契约，断言出现 `METRIC_NOT_RUNTIME_RESOLVABLE`；common 内重复指标出现 `DUPLICATE_METRIC_INPUT`。

### Step 2：运行测试确认红灯

Run:

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_skill_input_service.py src/tests/unit/runtime/skill_management/test_draft_validator_and_package.py -q
```

### Step 3：修正唯一判定入口

在 `resolve_metric_capability` 中先检查发布状态，再按顺序识别：

```python
if metric.expression:
    resolution_type = MetricResolutionType.DERIVED
elif metric.fact_field_code and metric.aggregation:
    resolution_type = MetricResolutionType.SQL_EXPRESSION
```

只有这两项都不满足时才进入现有 adapter/default 判断。`build_query_plan` 和 selector 继续复用这一结果。

在 draft validator 中对 `contract.common.metric_inputs` 做去重和 `_validate_metric_resolvable`，然后再校验 profiles；不复制 capability 规则。

### Step 4：运行单测并提交

Run:

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_skill_input_service.py src/tests/unit/runtime/skill_management/test_draft_validator_and_package.py -q
```

Commit:

```powershell
git add src/runtime/skill_management/skill_input_service.py src/runtime/skill_management/draft_validator.py src/tests/unit/runtime/skill_management/test_skill_input_service.py src/tests/unit/runtime/skill_management/test_draft_validator_and_package.py
git commit -m "fix: 校验语义查询型Skill输入"
```

---

## Task 5：实现门诊核验 Skill 的确定性核心

**Files:**

- Create: `skills/mzsettlement_verify_skill/__init__.py`
- Create: `skills/mzsettlement_verify_skill/models.py`
- Create: `skills/mzsettlement_verify_skill/verifier.py`
- Create: `skills/mzsettlement_verify_skill/tests/__init__.py`
- Create: `skills/mzsettlement_verify_skill/tests/test_verifier.py`
- Create: `skills/mzsettlement_verify_skill/tests/case_image_golden.yaml`

### Step 1：先落图片黄金案例和失败测试

`case_image_golden.yaml` 必须逐项保存图片中的 19 个显示金额，包括所有 `0.00`。至少包含：1916.72、1812.37、104.35、485.94、838.56、590.29、292.14、1326.43、681.67、644.76，以及现金/大病/退役/军残/补充/救助等零值。

测试断言：

- `1916.72 = 1812.37 + 104.35`；
- `1916.72 = 1326.43 + 590.29`；
- `590.29 = 590.29 + 0.00`；
- 有政策比例证据时 `681.67 = (1812.37 - 838.56) × 70%`；
- 单位补充 644.76 可展示，但无单位政策时必须产生 uncertainty，不能生成伪公式；
- 所有明确零值状态为 `reported_zero`，缺字段为 `missing`；
- 金额差 0.01 通过，差 0.02 失败；
- 多专项基金同时非零时不盲目相加总额与分项。

### Step 2：运行测试确认红灯

Run:

```powershell
uv run python -m pytest skills/mzsettlement_verify_skill/tests/test_verifier.py -q
```

Expected: 模块不存在或断言失败。

### Step 3：定义严格 Skill 内部模型

`models.py` 使用 Pydantic，至少包含：

```python
MoneyState = Literal["non_zero", "reported_zero", "missing", "not_applicable"]
CheckStatus = Literal["passed", "failed", "not_evaluable"]

class MetricValue(BaseModel):
    name: str
    value: Decimal | str | int | None
    state: MoneyState

class AmountCheck(BaseModel):
    name: str
    equation: str
    actual: Decimal | None
    expected: Decimal | None
    difference: Decimal | None
    tolerance: Decimal = Decimal("0.01")
    status: CheckStatus
```

再定义 `OutpatientSettlementContext`、`OutpatientFeeItem` 和完整 `OutpatientVerificationResult`。不得用 `dict[str, Any]` 作为 verifier 返回类型。

### Step 4：实现最小确定性核验器

`verifier.py` 只实现设计 §6 已确认的关系：

```python
CENT = Decimal("0.01")

def money(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(CENT)

def state_of(value: object, *, applicable: bool | None = None) -> MoneyState:
    if applicable is False:
        return "not_applicable"
    if value is None:
        return "missing"
    return "reported_zero" if money(value) == 0 else "non_zero"
```

核验总费用、医保内外、基金/个人、账户/现金、交易前后累计。比例复算只有上下文和有效政策证据齐全时执行。任何失败只列差额并建议人工复核，不判定责任方。

### Step 5：运行测试并提交

Run:

```powershell
uv run python -m pytest skills/mzsettlement_verify_skill/tests/test_verifier.py -q
```

Commit:

```powershell
git add skills/mzsettlement_verify_skill
git commit -m "feat: 实现门诊结算确定性核验"
```

---

## Task 6：实现九个应用场景、语义查询声明和政策查询计划

**Files:**

- Create: `skills/mzsettlement_verify_skill/assembler.py`
- Create: `skills/mzsettlement_verify_skill/skill_manifest.yaml`
- Create: `skills/mzsettlement_verify_skill/SKILL.md`
- Create: `skills/mzsettlement_verify_skill/config.yaml`
- Create: `skills/mzsettlement_verify_skill/policy_queries.yaml`
- Create: `skills/mzsettlement_verify_skill/templates/answer.yaml`
- Create: `skills/mzsettlement_verify_skill/schemas/input.schema.json`
- Create: `skills/mzsettlement_verify_skill/schemas/output.schema.json`
- Create: `skills/mzsettlement_verify_skill/tests/test_profiles.py`

### Step 1：先写场景路由和依赖测试

对设计 §4 的九个 profile 每个至少写 3 个问法。断言易混淆边界：慢特病/异地“怎么办”不进入本 Skill，住院结算排除，退费/冲正标为高风险人工确认。

断言每个 profile 的查询只请求其所需指标；公共上下文只有 `question`、`settlement_id` 和可选 `hospital_id`，profile 不重复声明。

### Step 2：运行测试确认红灯

Run:

```powershell
uv run python -m pytest skills/mzsettlement_verify_skill/tests/test_profiles.py -q
```

### Step 3：实现轻量 assembler

Assembler 只做四件事：

1. 用 manifest 的 `routing_hints` 选择 profile；
2. 生成只含 `mzjyxx` 已发布 metric code 的 `SemanticQuery`；
3. 把查询结果规范化为 `OutpatientSettlementContext`，保留零/缺失差异；
4. 调用 verifier 并用模板组织回答。

不在 assembler 写 SQL，不调用外部 HTTP，不复制政策检索实现。提供运行时能力方法：

```python
def detect_profile(self, question: str) -> str: ...
def build_semantic_queries(self, settlement_id: str, profile_id: str) -> list[SemanticQuery]: ...
def build_context(self, results: list[SemanticQueryResult], profile_id: str) -> OutpatientSettlementContext: ...
def build_policy_context(self, context: OutpatientSettlementContext, profile_id: str) -> dict: ...
def build_policy_queries(self, profile_id: str) -> list: ...
def execute(self, settlement_context, policy_evidence=None, policy_status="no_policy_matched", target_fee_item="", profile_id=None): ...
```

最后一个方法保留全部现有参数，并增加可选 `profile_id`；旧调用方无需修改，新能力路径显式传入 profile，`target_fee_item` 不改变原语义。

`policy_queries.yaml` 按九类场景声明规则类型和必需维度，但不写固定人群比例。检索上下文至少含地区、日期、险种、人员类别、医疗类别、机构级别、异地、慢特病和专项待遇类型。

### Step 4：写输入/输出 Schema

输入只允许 question、settlement_id、hospital_id。输出严格实现：

```text
status, scenario_id, summary,
context_checks[], amount_checks[], field_explanations[], anomalies[],
citations[], uncertainties[], next_actions[]
```

`additionalProperties=false`；公开字段使用业务中文名/语义名，不出现 `o_Trade`、`o_FeeItem`、SQL 或物理字段编码。

### Step 5：运行 Skill 测试并提交

Run:

```powershell
uv run python -m pytest skills/mzsettlement_verify_skill/tests -q
```

Commit:

```powershell
git add skills/mzsettlement_verify_skill
git commit -m "feat: 完善门诊结算核验应用场景"
```

---

## Task 7：把新 Skill 接入 Policy QA，修复 null 转零

**Files:**

- Modify: `src/runtime/policy_qa/settlement_data_provider.py`
- Modify: `src/runtime/policy_qa/public_contract.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/tests/unit/runtime/policy_qa/test_semantic_settlement_provider.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
- Create: `src/tests/integration/flow/test_policy_qa_outpatient_settlement_flow.py`

### Step 1：先写失败测试

新增断言：

- provider 的可靠结果中，数据库 `NULL` 保持 `None`，明确 `0` 保持 `0.0`；
- 路由到具备 `build_semantic_queries` 的 assembler 时，Policy QA 通过现有 `SemanticQueryService` 执行，不走住院固定 query；
- 九类结果可进入公开白名单；
- `result` 后仍有 `done`，并携带 `attempt_count`/`halt_reason`；
- 输出不含物理表、字段、SQL、身份证、卡号、姓名；
- 退费/冲正请求返回 `waiting_human_confirmation`，没有任何写操作；
- 数据源超时只恢复一次，缺记录和确定性 partial 不重试。

### Step 2：运行测试确认红灯

Run:

```powershell
uv run python -m pytest src/tests/unit/runtime/policy_qa/test_semantic_settlement_provider.py src/tests/integration/api/test_policy_qa_routes.py src/tests/integration/flow/test_policy_qa_outpatient_settlement_flow.py -q
```

### Step 3：修复 null 转零根因

把 provider 中：

```python
return float(value or 0) if reliable else None
```

改为只对非空值转换：

```python
return float(value) if reliable and value is not None else None
```

不在每个调用方补 guard。

### Step 4：增加能力式查询路径

复用 provider 已持有的 `SemanticQueryService`，增加异步 `run_semantic_query(query)`；连接、超时和 pyodbc 异常继续走现有分类。

在 Policy QA 完成 Skill 路由后：

```python
if callable(getattr(assembler, "build_semantic_queries", None)):
    profile_id = assembler.detect_profile(request.question)
    results = [await provider.run_semantic_query(q) for q in assembler.build_semantic_queries(
        request.settlement_id, profile_id,
    )]
    settlement_context = assembler.build_context(results, profile_id)
else:
    settlement_context = await provider.get_settlement_context(request.settlement_id)
```

后续政策检索和 execute 继续复用现有步骤；能力路径用可选关键字把 `profile_id` 传给新 assembler。禁止按 `mzsettlement_verify_skill` 字符串写死分支。

### Step 5：扩展公开结果白名单

在 `public_contract.py` 增加严格 Pydantic 模型：`ContextCheck`、`AmountCheck`、`FieldExplanation`、`Anomaly`，并把设计 §8 字段作为 `PolicyQAPublicResult` 的可选扩展。`_build_public_result` 只接受这些白名单字段并再次清理内部实现标识。

现有前端依赖的 `answer`、`answer_status`、`case_context`、`calculation_steps`、`citations` 保持不变。

### Step 6：按层验证并提交

Run Unit:

```powershell
uv run python -m pytest src/tests/unit/runtime/policy_qa/test_semantic_settlement_provider.py -q
```

Run API（Unit 通过后）：

```powershell
uv run python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q
```

Run Flow（API 通过后）：

```powershell
uv run python -m pytest src/tests/integration/flow/test_policy_qa_outpatient_settlement_flow.py -q
```

Commit:

```powershell
git add src/runtime/policy_qa/settlement_data_provider.py src/runtime/policy_qa/public_contract.py src/runtime/api/policy_qa_routes.py src/tests/unit/runtime/policy_qa/test_semantic_settlement_provider.py src/tests/integration/api/test_policy_qa_routes.py src/tests/integration/flow/test_policy_qa_outpatient_settlement_flow.py
git commit -m "feat: 接入门诊结算核验主链"
```

---

## Task 8：通过发现中心治理生产 `mzjyxx` 数据模型

**Files:**

- No production code changes.
- Runtime state: PostgreSQL semantic registry and SQL Server read-only profiling.

此任务必须在代码能力通过 Task 1–4 测试后执行。所有写操作走现有语义治理 API；SQL Server 只做只读画像。

### Step 1：确认工作区服务和鉴权

Run:

```powershell
..\ws.ps1 restart issue-20
..\ws.ps1 list
```

Expected: issue-20 后端/前端健康；使用该工作区签发的 semantic review token，不复用其他工作区 token。

### Step 2：刷新并导出发现结果

通过 Portal 发现中心或现有 `/semantic/discovery/scan`、`/semantic/discovery/results`：

- 过滤 `o_Trade`、`o_FeeItem`；
- 核对设计 §5.4 全字段均在最新扫描；
- 记录类型、非空率、distinct 数、枚举频次和发现质量分；
- 任一核心字段未发现则停止，不猜字段。

### Step 3：在批准的只读 SQL 工具中验证候选键和金额口径

Run read-only SQL:

```sql
SELECT TOP (1) T_SetTid, COUNT_BIG(*) AS duplicate_count
FROM dbo.o_Trade
GROUP BY T_SetTid
HAVING T_SetTid IS NULL OR COUNT_BIG(*) > 1;

SELECT TOP (1) T_TradeNo, COUNT_BIG(*) AS duplicate_count
FROM dbo.o_Trade
GROUP BY T_TradeNo
HAVING T_TradeNo IS NULL OR COUNT_BIG(*) > 1;

SELECT TOP (1) T_TradeNo, ItemId, ItemNo, COUNT_BIG(*) AS duplicate_count
FROM dbo.o_FeeItem
GROUP BY T_TradeNo, ItemId, ItemNo
HAVING T_TradeNo IS NULL OR ItemId IS NULL OR ItemNo IS NULL OR COUNT_BIG(*) > 1;

SELECT T_State, T_HasRefundmented, T_PartialReturnFlag, COUNT_BIG(*) AS row_count
FROM dbo.o_Trade
GROUP BY T_State, T_HasRefundmented, T_PartialReturnFlag;
```

再以脱敏测试锚点比较 `o_Trade.T_FeeIn/T_FeeOut` 和 `o_FeeItem.FeeIn/FeeOut` 汇总。只有能证明口径一致才使用 `o_FeeItem`；否则按设计切换为 `yb_mzfymx_mz`，并在规格补充证据后再继续。不得同时汇总两个明细源。

### Step 4：批量创建和修正指标

使用 `/semantic/metrics/batch` 一次提交设计 §5.4 中缺失指标。每项显式传：metric_code、中文名、定义、semantic_type、单位、importance、value_domain、source_table、source_field；查询度量再传 fact_field_code、aggregation。

逐项核对：

```text
error > 0       立即停止
created         检查保存后的详情
skipped         逐条 GET，确认既有口径，不视为成功覆盖
```

既有错误类型通过 `PUT /semantic/metrics/{metric_code}` 修正，并携带 `expected_schema_version`。枚举先创建/更新值域和源值映射。

### Step 5：替换、校验和发布查询模型

通过 `PUT /semantic/objects/mzjyxx/query-model` 写入两数据集、键、字段、关系和质量规则；调用 validate，要求 `validation_issues=[]` 和 `queryable=true`。

先用脱敏锚点执行 `/semantic/query/test` 的汇总与明细查询，核对质量状态和人工金额，再调用 `/semantic/objects/mzjyxx/publish`。发布后断言：

```text
GET /semantic/objects/mzjyxx/query-model?published=true
queryable = true
datasets = mz_trade, mz_fee_item
```

保存发布版本号作为 Skill 评测证据。

---

## Task 9：把代码资产回写现有草稿并物化候选

**Files:**

- Modify runtime state: `draft-cf24aa3b34fe`
- Verify generated tree: `skills/mzsettlement_verify_skill/`
- Modify: `src/tests/integration/api/test_skill_draft_api.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`
- Modify: `src/tests/integration/api/test_skill_workbench_flow.py`

### Step 1：增加草稿契约 API 回归

用内存 storage 构造九 profile 草稿，断言：common metric 可解析、无 `COMMON_CONTEXT_REDECLARED`、package preview 保留真实 assembler、validated 草稿物化后 loader 可执行而不是 placeholder。

### Step 2：运行 API 测试确认基线

Run:

```powershell
uv run python -m pytest src/tests/integration/api/test_skill_draft_api.py src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_skill_workbench_flow.py -q
```

### Step 3：回写 revision 最新的现有草稿

先 GET 草稿，使用返回的最新 revision，不能硬编码当前 revision 5。PATCH 内容：

- basic：保留 skill_id，更新名称、说明、owner；
- business_mounting：`verify + settlement`、正向关键词、导办/住院/临床排除词；
- execution_contract：common + 设计 §4 九 profiles；
- schemas：Task 6 的 input/output schema；
- raw_files：Task 5–6 的真实 assembler、models、verifier、YAML 和测试资产。

保存后重新 GET，比较 raw_files 内容哈希与工作树文件一致。

### Step 4：校验、包预览、物化

依次调用：

```text
POST /infra-skills/drafts/draft-cf24aa3b34fe/validate
GET  /infra-skills/drafts/draft-cf24aa3b34fe/package-preview
POST /infra-skills/drafts/draft-cf24aa3b34fe/materialize
```

门禁：blocking_ok=true；预览含真实 `assembler.py`；materialize 返回 201。物化后比较生成文件与已测试资产，重新运行 Skill tests。只创建候选，不激活 Test。

### Step 5：运行 API 集成测试并提交测试

Run API:

```powershell
uv run python -m pytest src/tests/integration/api/test_skill_draft_api.py src/tests/integration/api/test_infra_skill_routes.py -q
```

Run workbench API integration:

```powershell
uv run python -m pytest src/tests/integration/api/test_skill_workbench_flow.py -q
```

Commit:

```powershell
git add src/tests/integration/api/test_skill_draft_api.py src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_skill_workbench_flow.py
git commit -m "test: 覆盖门诊核验Skill物化流程"
```

---

## Task 10：建立路由与行为评测资产

**Files:**

- Modify: `src/runtime/skill_management/governance_service.py`
- Modify: `src/tests/unit/runtime/skill_management/test_governance_service.py`
- Create: `skills/mzsettlement_verify_skill/tests/test_regression_matrix.py`

### Step 1：写路由黄金集失败测试

在 `GOLDEN_ROUTING_CASES` 增加每个 profile 3 个正向问法，并增加这些对照：

- 门诊待遇“为什么” → `mzsettlement_verify_skill`；
- 慢特病/异地“怎么办” → 不应由本 Skill 接管；
- 明确住院费用 → `settlement_explain_skill`；
- 临床使用问题 → 不匹配；
- 退费/冲正 → 本 Skill 识别但进入高风险状态。

测试断言 `seed_golden_cases()` 幂等，且候选路由无新的 false takeover。

### Step 2：实现并运行路由用例

Run:

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_governance_service.py -q
```

### Step 3：实现行为回归矩阵

`test_regression_matrix.py` 参数化覆盖设计 §9.2 全部 21 类边界。至少包括职工、居民、退休、慢特病、异地、公务员/公疗、军残、大病、民政救助、退役、多基金、医保外明细、乙类/超限价、零/缺失、算术差、政策缺失、退费/冲正、超时和敏感字段。

每个政策相关用例显式传入证据或空证据；不得依赖公网或生产 Milvus。

### Step 4：运行评测测试并提交

Run:

```powershell
uv run python -m pytest src/tests/unit/runtime/skill_management/test_governance_service.py skills/mzsettlement_verify_skill/tests/test_regression_matrix.py -q
```

Commit:

```powershell
git add src/runtime/skill_management/governance_service.py src/tests/unit/runtime/skill_management/test_governance_service.py skills/mzsettlement_verify_skill/tests/test_regression_matrix.py
git commit -m "test: 增加门诊结算核验评测矩阵"
```

物化后调用 `seed-golden` 和候选 route/behavior evaluation，保存 run_id。若行为治理库尚无图片对应的真实 QA 历史，图片案例先以 Skill 黄金测试生效；完成一次脱敏真实问答后，再按现有“历史入池 → transform → 人工 confirm”流程转为服务端 regression case，不伪造历史记录。

---

## Task 11：更新使用指南并完成 R4 审查闭环

**Files:**

- Modify: `docs/guides/门诊结算结果核验Skill-AI创建草稿指南.md`
- Modify: `src/tests/performance/scenarios/policy_qa_api.py`
- Modify: `src/tests/e2e/flows/portal/policy-qa.flow.ts`

### Step 1：更新指南中的过期事实

修正：

- skill_id 为 `mzsettlement_verify_skill`；
- 不再写“未发现门诊指标”；改为发现中心批量建指标、查询模型发布、九 profile、零/缺失/不适用四态；
- 补充图片黄金案例、正式评测和不自动激活步骤；
- 明确单位补充等缺政策时只解释实际支付。

### Step 2：让现有性能场景可选择门诊用例

`policy_qa_api.py` 从环境读取 question 和 settlement_id，默认值保持当前住院案例；验证门诊时显式设置脱敏测试 ID。不开新性能框架。

### Step 3：扩展现有 Policy QA E2E

在 `policy-qa.flow.ts` 增加环境驱动的门诊用例，断言页面收到完整 SSE、显示核验状态和政策/不确定性，且不显示物理字段。无脱敏门诊测试 ID 时保留现有住院 E2E，不把跳过写成通过证据。

### Step 4：完整审查

按需求和设计逐项检查 diff：

- 九 profile 与指标依赖完整；
- 零值没有被 truthiness 丢失；
- 任何基金总分项没有重复相加；
- 比例没有脱离有效政策复算；
- 高风险动作没有写通道；
- 公开结果没有物理字段、SQL、内部计划、姓名、身份证或卡号；
- 现有住院路径和 SSE 字段保持兼容。

发现问题先补失败测试，再修复并重新审查。

### Step 5：严格按顺序执行验证

Unit:

```powershell
uv run python -m pytest src/tests/unit/semantic_layer src/tests/unit/runtime/skill_management src/tests/unit/runtime/policy_qa skills/mzsettlement_verify_skill/tests -q
```

API（Unit 全通过后）：

```powershell
uv run python -m pytest src/tests/integration/api/test_semantic_query_model_api.py src/tests/integration/api/test_semantic_metric_change_control_api.py src/tests/integration/api/test_skill_draft_api.py src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_skill_workbench_flow.py src/tests/integration/api/test_policy_qa_routes.py -q
```

Flow（API 全通过后）：

```powershell
uv run python -m pytest src/tests/integration/flow/test_semantic_query_workbench_flow.py src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py src/tests/integration/flow/test_policy_qa_outpatient_settlement_flow.py -q
```

Performance（新数据库查询模式，必须）：

```powershell
..\ws.ps1 up issue-20
if (-not $env:PERF_SETTLEMENT_ID) { throw '先将 Task 8 取得的脱敏门诊测试结算 ID 写入 PERF_SETTLEMENT_ID' }
$env:PERF_POLICY_QA_QUESTION='核验这次门诊结算是否正确'; uv run locust -f src/tests/performance/locustfile.py --host http://127.0.0.1:8126 --headless --users 10 --spawn-rate 2 --run-time 60s --tags policy-qa
```

记录 P95、错误率和完整 `done` 比例；`PERF_SETTLEMENT_ID` 只能使用 Task 8 取得的脱敏门诊测试结算 ID。

Portal E2E（SSE 契约扩展，必须）：

```powershell
..\ws.ps1 up issue-20
Set-Location src/tests/e2e
npm test -- --grep "Policy QA"
```

若 E2E package 未定义 `npm test`，按其 `package.json` 中现有 Playwright 脚本运行 `flows/portal/policy-qa.flow.ts`，并记录实际命令与退出码。

### Step 6：最终验证和提交

Run:

```powershell
uv run python -m compileall -q src skills/mzsettlement_verify_skill
git diff --check
git status --short
```

Expected: 无新增语法/LSP错误、无空白错误；只提交本计划列出的文件，不带入工作区其他用户改动。

Commit:

```powershell
git add docs/guides/门诊结算结果核验Skill-AI创建草稿指南.md src/tests/performance/scenarios/policy_qa_api.py src/tests/e2e/flows/portal/policy-qa.flow.ts
git commit -m "docs: 完善门诊结算核验使用与验证说明"
```

最终交付证据必须包含：`mzjyxx` 发布版本、草稿 revision、materialize version_id、评测 run_id、Unit/API/Flow/Performance/E2E 命令与退出码、人工键/金额口径核验结论，以及未自动激活说明。
