# 医保政策问答RAG系统

## TL;DR

> **核心逻辑**: 意图识别 → SQL Server查询 → 问题重写 → RAG检索 → 费用拆分计算Skill → 大模型润色
> 
> **Skill本质**: 费用拆分计算 + 溯源，每个数字都能追溯到费用明细表和政策规则
> 
> **关键公式**: 
> - 总费用 = 医保内 + 医保外
> - 医保内 = 起付线 + 统筹支付 + 统筹自付 + 大额支付 + 大额自付 + 个人应负
> - 医保外 = 丙类全自费 + 特需费用 + 自付比例 + 限价超出

---

## 核心流程（6步骤）

```
用户: "为什么我的费用是这些？"
    │
    ▼
┌─ Step 1: 意图识别 (LLM, 非流式) ─────────────────────────────┐
│  识别: need_patient_data=true, settlement_id="1671213"        │
│  识别: 查询类型=费用分解/待遇分解/起付线/报销比例...            │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 2: SQL Server查询 (business_sql.yaml, 端口1433) ──────┐
│  查询所有相关表:                                               │
│  ├─ yb_zyfdxx: 待遇分解(统筹支付/大额支付/个人应负)            │
│  ├─ yb_zyfymx: 费用明细(每项费用的医保内/外/自付比例)          │
│  ├─ yb_dyxxnd: 年度累计(年度统筹累计/大额累计)                 │
│  ├─ yb_dyxxzy: 住院信息(起付线/医保内金额)                     │
│  └─ yb_brdjxx: 患者登记(险种/医疗类别/人员类别)                │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 3: 问题重写 ───────────────────────────────────────────┐
│  SemanticMapper: SQL原始值 → 标准化值                         │
│  "3" → "城镇职工", "21" → "普通住院"                          │
│  重写: "城镇职工第三次住院费用分解"                             │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 4: RAG检索 (Milvus, 向量+高级搜索) ───────────────────┐
│  检索政策规则:                                                  │
│  ├─ 起付线规则: deductible_amount                              │
│  ├─ 报销比例规则: payment_ratio                                │
│  ├─ 封顶线规则: cap_amount                                     │
│  ├─ 金额分段规则: amount_band                                  │
│  └─ 其他规则: rule_type, rule_value                            │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 5: 费用拆分计算Skill ──────────────────────────────────┐
│  输入: SQL查询结果 + 政策规则                                   │
│  输出: 完整费用分解 + 每个数字的溯源                            │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 待遇分解                                                │ │
│  │ ├─ 总费用: 189,085.85                                   │ │
│  │ ├─ 医保内: 164,411.81                                   │ │
│  │ │  ├─ 起付线: 650 (政策: 首次住院650)                    │ │
│  │ │  ├─ 统筹支付: 91,759.51 (政策: 起付线以上按85%)        │ │
│  │ │  ├─ 统筹自付: 4,962.67 (政策: 15%个人承担)            │ │
│  │ │  ├─ 大额支付: 53,631.71 (政策: 超过10万部分)           │ │
│  │ │  ├─ 大额自付: 13,407.93 (政策: 15%个人承担)            │ │
│  │ │  └─ 个人应负: 43,694.67                               │ │
│  │ └─ 医保外: 24,674.04                                    │ │
│  │    ├─ 丙类全自费: xxx (溯源: sfxmdj=3的明细汇总)        │ │
│  │    ├─ 特需费用: xxx (溯源: txbz=1的明细汇总)            │ │
│  │    ├─ 自付比例: xxx (溯源: SP_SCALE>0的明细汇总)        │ │
│  │    └─ 限价超出: xxx (溯源: MEDIC_L限价的明细汇总)       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 费用分解 (按收费项目等级)                                │ │
│  │ ├─ 甲类: xxx (全部医保内)                               │ │
│  │ ├─ 乙类: xxx (部分医保内, 部分医保外)                    │ │
│  │ └─ 丙类: xxx (全部医保外)                               │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 溯源证据                                                │ │
│  │ ├─ 费用明细: yb_zyfymx中4752条记录                      │ │
│  │ ├─ 政策依据: 数据模型1.xlsx中xxx条规则                  │ │
│  │ └─ 计算过程: 每个数字的计算公式和数据来源                │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌─ Step 6: 大模型润色 (基于角色, 流式) ────────────────────────┐
│  输入: 费用分解结果 + 溯源证据 + 用户角色                      │
│  输出: 自然语言解释，每个数字都有依据                          │
│                                                              │
│  示例输出(收费员视角):                                         │
│  "您的总费用189,085.85元，其中：                               │
│   - 医保内164,411.81元，医保报销91,759.51元                   │
│   - 起付线650元(政策规定首次住院650元)                         │
│   - 统筹自付4,962.67元(政策规定15%个人承担)                    │
│   - 医保外24,674.04元，主要是丙类药品和特需项目..."            │
└───────────────────────────────────────────────────────────────┘
```

---

## Skill设计详解

### 费用拆分计算Skill

```python
class FeeDecompositionSkill:
    """
    费用拆分计算Skill
    
    核心逻辑: 分段计算，每段独立比例
    - 统筹自付 = Σ(各分段金额 × 各分段自付比例)
    - 各分段自付比例 = 基础比例 × 人员系数
    
    示例(退休人员，统筹内97,372.18元):
    - 650-3万:   29,350 × 15%×60% = 29,350 × 9% = 2,641.50
    - 3-4万:    10,000 × 10%×60% = 10,000 × 6% = 600.00
    - 4万以上:   57,372.18 × 5%×60% = 57,372.18 × 3% = 1,721.17
    - 合计:     2,641.50 + 600.00 + 1,721.17 = 4,962.67
    """
    
    def decompose(
        self,
        sql_results: dict,      # SQL查询结果(所有表)
        policy_rules: list,     # 检索到的政策规则
    ) -> FeeDecompositionResult:
        """
        执行完整费用分解
        
        输入:
        - yb_zyfdxx: 待遇分解表
        - yb_zyfymx: 费用明细表
        - yb_dyxxnd: 年度累计表
        - yb_dyxxzy: 住院信息表
        - yb_brdjxx: 患者登记表
        
        输出:
        - 待遇分解: 所有待遇项目的值和溯源
        - 费用分解: 按收费项目等级的分解
        - 分段计算: 每个分段的计算过程
        - 溯源证据: 每个数字的计算过程和数据来源
        """
        
        # 1. 解析SQL结果
        treatment = self._parse_treatment(sql_results["yb_zyfdxx"])
        fee_details = self._parse_fee_details(sql_results["yb_zyfymx"])
        annual = self._parse_annual(sql_results["yb_dyxxnd"])
        admission = self._parse_admission(sql_results["yb_dyxxzy"])
        patient = self._parse_patient(sql_results["yb_brdjxx"])
        
        # 2. 解析政策规则(分段+比例)
        segments = self._parse_segments(policy_rules)  # [(650, 30000, 0.15), (30000, 40000, 0.10), (40000, inf, 0.05)]
        person_ratio = self._get_person_ratio(patient)  # 退休=0.6, 在职=1.0
        
        # 3. 分段计算统筹自付
        pooling_amount = treatment["bdybnzje"]  # 统筹内金额
        segment_calc = self._calculate_segmented(
            amount=pooling_amount,
            segments=segments,
            person_ratio=person_ratio,
            deductible=admission["bcqfje"],  # 起付线
        )
        
        # 4. 待遇分解
        treatment_decomp = self._decompose_treatment(
            treatment, fee_details, policy_rules, segment_calc
        )
        
        # 5. 费用分解(按收费项目等级)
        fee_decomp = self._decompose_fees(fee_details)
        
        # 6. 溯源证据
        evidence = self._build_evidence(
            treatment_decomp, fee_decomp, segment_calc, fee_details, policy_rules
        )
        
        return FeeDecompositionResult(
            treatment=treatment_decomp,
            fees=fee_decomp,
            segments=segment_calc,
            evidence=evidence,
        )
    
    def _parse_segments(self, policy_rules: list) -> list:
        """
        从政策规则解析分段信息
        
        返回: [(下限, 上限, 基础比例), ...]
        
        示例:
        [
            (650, 30000, 0.15),    # 650-3万, 15%
            (30000, 40000, 0.10),  # 3-4万, 10%
            (40000, float('inf'), 0.05),  # 4万以上, 5%
        ]
        """
        segments = []
        for rule in policy_rules:
            if rule.get("rule_type") == "统筹分段":
                band = rule.get("amount_band", "")
                ratio = float(rule.get("payment_ratio", 0))
                # 解析 "650-30000" 格式
                lower, upper = self._parse_band(band)
                segments.append((lower, upper, ratio))
        
        # 按下限排序
        segments.sort(key=lambda x: x[0])
        return segments
    
    def _get_person_ratio(self, patient: dict) -> float:
        """
        获取人员系数
        
        退休人员: 60% (即自付比例×0.6)
        在职人员: 100% (即自付比例×1.0)
        """
        person_type = patient.get("PER_TYPE", "")
        if "退休" in person_type:
            return 0.6
        else:
            return 1.0
    
    def _calculate_segmented(
        self,
        amount: float,
        segments: list,
        person_ratio: float,
        deductible: float,
    ) -> SegmentCalculationResult:
        """
        分段计算统筹自付
        
        公式: 每段自付 = 段内金额 × 基础比例 × 人员系数
        
        示例(退休人员，统筹内97,372.18元，起付线650):
        - 650-30000:   29,350 × 0.15 × 0.6 = 29,350 × 0.09 = 2,641.50
        - 30000-40000: 10,000 × 0.10 × 0.6 = 10,000 × 0.06 = 600.00
        - 40000-97372.18: 57,372.18 × 0.05 × 0.6 = 57,372.18 × 0.03 = 1,721.17
        - 合计: 2,641.50 + 600.00 + 1,721.17 = 4,962.67
        """
        result = SegmentCalculationResult()
        remaining = amount
        current_pos = deductible  # 从起付线开始
        
        for lower, upper, base_ratio in segments:
            if remaining <= 0:
                break
            
            # 调整分段下限(不能低于当前位置)
            effective_lower = max(lower, current_pos)
            
            # 计算段内金额
            if upper == float('inf'):
                segment_amount = remaining
            else:
                segment_amount = min(remaining, upper - effective_lower)
            
            if segment_amount <= 0:
                continue
            
            # 计算该段自付
            actual_ratio = base_ratio * person_ratio
            segment_pay = segment_amount * actual_ratio
            
            # 记录计算过程
            result.segments.append({
                "lower": effective_lower,
                "upper": upper if upper != float('inf') else amount,
                "amount": segment_amount,
                "base_ratio": base_ratio,
                "person_ratio": person_ratio,
                "actual_ratio": actual_ratio,
                "pay": segment_pay,
                "calculation": f"{segment_amount:,.2f} × {base_ratio:.0%} × {person_ratio:.0%} = {segment_amount:,.2f} × {actual_ratio:.0%} = {segment_pay:,.2f}",
            })
            
            result.total_pay += segment_pay
            remaining -= segment_amount
            current_pos = upper if upper != float('inf') else amount
        
        return result
    
    def _decompose_treatment(self, treatment, fee_details, policy_rules, segment_calc):
        """待遇分解"""
        return {
            "总费用": {
                "value": treatment["bdfyzje"],
                "source": "yb_zyfdxx.bdfyzje",
                "policy": None,
                "calculation": None,
            },
            "医保内": {
                "value": treatment["bdybnzje"],
                "source": "yb_zyfdxx.bdybnzje",
                "policy": None,
                "calculation": None,
            },
            "起付线": {
                "value": self._calculate_deductible(treatment, policy_rules),
                "source": "yb_dyxxzy.bcqfje",
                "policy": self._find_deductible_rule(policy_rules),
                "calculation": f"政策规定首次住院起付线650元",
            },
            "统筹自付": {
                "value": segment_calc.total_pay,
                "source": "yb_zyfdxx.bdtczf",
                "policy": self._find_ratio_rule(policy_rules, "统筹"),
                "calculation": self._format_segment_calculation(segment_calc),
            },
            "统筹支付": {
                "value": treatment["bdtczfje"],
                "source": "yb_zyfdxx.bdtczfje",
                "policy": self._find_ratio_rule(policy_rules, "统筹"),
                "calculation": f"统筹内金额 - 统筹自付 = {treatment['bdybnzje']:,.2f} - {segment_calc.total_pay:,.2f} = {treatment['bdtczfje']:,.2f}",
            },
            "大额支付": {
                "value": treatment["bddegwyzfje"],
                "source": "yb_zyfdxx.bddegwyzfje",
                "policy": self._find_ratio_rule(policy_rules, "大额"),
                "calculation": None,
            },
            "大额自付": {
                "value": treatment["bddegwyzf"],
                "source": "yb_zyfdxx.bddegwyzf",
                "policy": self._find_ratio_rule(policy_rules, "大额"),
                "calculation": None,
            },
            "个人应负": {
                "value": treatment["bdgryf"],
                "source": "yb_zyfdxx.bdgryf",
                "policy": None,
                "calculation": None,
            },
            "医保外": {
                "value": self._calculate_out_of_scope(fee_details),
                "source": "yb_zyfymx.ybwje汇总",
                "policy": self._find_out_of_scope_rules(policy_rules),
                "calculation": None,
            },
        }
    
    def _format_segment_calculation(self, segment_calc: SegmentCalculationResult) -> str:
        """格式化分段计算过程"""
        lines = ["统筹自付分段计算:"]
        for seg in segment_calc.segments:
            lines.append(f"  {seg['lower']:,.0f}-{seg['upper']:,.0f}: {seg['calculation']}")
        lines.append(f"  合计: {segment_calc.total_pay:,.2f}")
        return "\n".join(lines)
```

### 分段计算示例

**问题**: 登记号1671213，统筹自费为什么是4962.67元？

**政策规则** (从数据模型1.xlsx检索):
```json
{
  "rule_type": "统筹分段",
  "insu_type": "城镇职工",
  "psn_type": "在职/退休",
  "amount_band": "650-30000",
  "payment_ratio": "0.15",
  "source_text": "起付标准至3万元的部分，统筹基金支付85%，职工支付15%"
}
```

**人员系数**:
- 退休人员: 60% (即自付比例×0.6)
- 在职人员: 100% (即自付比例×1.0)

**分段计算**:
```
统筹内金额: 97,372.18元
起付线: 650元

650-30,000:   29,350.00 × 15% × 60% = 29,350.00 × 9% = 2,641.50
30,000-40,000: 10,000.00 × 10% × 60% = 10,000.00 × 6% = 600.00
40,000-97,372.18: 57,372.18 × 5% × 60% = 57,372.18 × 3% = 1,721.17
─────────────────────────────────────────────────────────────────
合计: 2,641.50 + 600.00 + 1,721.17 = 4,962.67 ✓
```

**溯源证据**:
```json
{
  "item": "统筹自付",
  "value": 4962.67,
  "source_table": "yb_zyfdxx.bdtczf",
  "policy_rule": {
    "rule_type": "统筹分段",
    "source_text": "起付标准至3万元的部分，统筹基金支付85%，职工支付15%",
    "policy_id": "xxx",
    "clause_id": "xxx"
  },
  "calculation": {
    "formula": "统筹自付 = Σ(各分段金额 × 各分段自付比例 × 人员系数)",
    "segments": [
      {"range": "650-30000", "amount": 29350, "base_ratio": 0.15, "person_ratio": 0.6, "actual_ratio": 0.09, "pay": 2641.50},
      {"range": "30000-40000", "amount": 10000, "base_ratio": 0.10, "person_ratio": 0.6, "actual_ratio": 0.06, "pay": 600.00},
      {"range": "40000-97372.18", "amount": 57372.18, "base_ratio": 0.05, "person_ratio": 0.6, "actual_ratio": 0.03, "pay": 1721.17}
    ],
    "total": 4962.67
  }
}
```

---

## 数据库表结构

### yb_zyfdxx (待遇分解)

```sql
-- 待遇分解表
djh          -- 登记号(结算ID)
zqxh         -- 周期序号(第几次结算)
fynd         -- 费用年度
bdfyzje      -- 本段费用总额
bdybnzje     -- 本段医保内总额
bdtczfje     -- 统筹支付金额
bdtczf       -- 统筹自付
bddegwyzfje  -- 大额公务员支付金额
bddegwyzf    -- 大额公务员自付
bdgryf       -- 个人应负
tcfdhybn     -- 统筹分段医保内
grziftw      -- 个人自付特微
tcde         -- 统筹定额
dede         -- 定额
zifbz        -- 自付标志
zifde        -- 自付定额
txfy         -- 特需费用
txzif        -- 特需自付
```

### yb_zyfymx (费用明细)

```sql
-- 费用明细表
djh          -- 登记号
xh           -- 序号
xmdm         -- 项目编码
xmmc         -- 项目名称
sfxmdj       -- 收费项目等级(1=甲类, 2=乙类, 3=丙类)
zje          -- 总金额
ybnje        -- 医保内金额
ybwje        -- 医保外金额
txbz         -- 特需标志(1=特需)
SP_SCALE     -- 自付比例
MEDIC_L      -- 医保支付标准
```

### yb_dyxxnd (年度累计)

```sql
-- 年度累计表
djh          -- 登记号
fynd         -- 费用年度
bnzqslj      -- 本年周期数累计(住院次数)
bnybnje      -- 本年医保内累计
bntczfje     -- 本年统筹支付累计
bndezfje     -- 本年大额支付累计
```

### yb_dyxxzy (住院信息)

```sql
-- 住院信息表
djh          -- 登记号
fynd         -- 费用年度
zqxh         -- 周期序号
bcqfje       -- 本次起付金额
bcybnje      -- 本次医保内金额
```

---

## Milvus Schema (policy_rules集合)

**完全按数据模型1的字段名和值域**:

```python
POLICY_RULES_SCHEMA = CollectionSchema([
    # 主键
    FieldSchema("rule_id", DataType.VARCHAR, max_length=64, is_primary=True),
    
    # 向量
    FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=768),
    
    # 数据模型1字段(完全保持原名)
    FieldSchema("fact_id", DataType.VARCHAR, max_length=64),
    FieldSchema("policy_id", DataType.VARCHAR, max_length=64),
    FieldSchema("clause_id", DataType.VARCHAR, max_length=64),
    FieldSchema("source_text", DataType.VARCHAR, max_length=4096),
    
    # 分词字段(值域标准化)
    FieldSchema("insu_type", DataType.VARCHAR, max_length=32),      # 险种类别: 城镇职工、城乡居民、超转人员、生育保险
    FieldSchema("med_type", DataType.VARCHAR, max_length=32),       # 医疗类别: 住院-普通住院、门诊-一般门特
    FieldSchema("hosp_lv", DataType.VARCHAR, max_length=32),        # 医疗机构等级: 一级医院、二级医院、三级医院、社区
    FieldSchema("psn_type", DataType.VARCHAR, max_length=32),       # 人群标签: 退休、在职、70岁以上、学生儿童
    FieldSchema("setl_type", DataType.VARCHAR, max_length=32),      # 结算方式: 按项目付费、DRG、单病种、床日定额
    FieldSchema("payment_ratio", DataType.VARCHAR, max_length=32),  # 支付比例
    FieldSchema("deductible_amount", DataType.VARCHAR, max_length=32),  # 起付金额
    FieldSchema("cap_amount", DataType.VARCHAR, max_length=32),     # 封顶金额
    FieldSchema("time_period", DataType.VARCHAR, max_length=32),    # 时间周期
    FieldSchema("admission_order", DataType.VARCHAR, max_length=32),  # 住院次数
    FieldSchema("rule_type", DataType.VARCHAR, max_length=64),      # 规则类型
    FieldSchema("rule_value", DataType.VARCHAR, max_length=256),    # 规则值
    FieldSchema("amount_band", DataType.VARCHAR, max_length=64),    # 金额分段
    FieldSchema("priority", DataType.VARCHAR, max_length=32),       # 规则优先级
])
```

---

## 模块设计

### 后端模块结构

```
src/runtime/policy_qa/
├── __init__.py
├── orchestrator.py          # 编排器(串联6步骤, yield SSE事件)
├── intent_detector.py       # 意图识别(LLM)
├── sql_data_fetcher.py      # SQL Server数据获取(封装SqlServerBusinessDataClient)
├── question_rewriter.py     # 问题重写(基于SQL结果+SemanticMapper)
├── search_engine.py         # 检索引擎(封装MilvusPolicyRetriever)
├── fee_decomposition_skill.py  # 费用拆分计算Skill
├── explanation_generator.py # 解释生成(LLM, 基于角色润色)
└── models.py                # 数据模型

src/knowledge_extension/rule_explanation/policy_retrieval/
├── policy_rules_schema.py   # Milvus Schema(完全按数据模型1)
├── data_model1_loader.py    # 数据加载器(标准化)
├── mcp_result_normalizer.py # MCP结果标准化(映射到policy_rules字段)
└── ...
```

---

## API设计

### SSE流式端点

**端点**: `POST /api/v1/medical-insurance-ai-agent/policy-qa/stream`

**请求体**:
```json
{
  "question": "为什么我的费用是这些？",
  "settlement_id": "1671213",
  "session_id": "optional-session-id"
}
```

**SSE事件序列**:
```
data: {"step": "intent", "status": "running"}
data: {"step": "intent", "status": "done", "detail": {"intent": "fee_decomposition", "settlement_id": "1671213"}}

data: {"step": "sql_query", "status": "running"}
data: {"step": "sql_query", "status": "done", "detail": {"tables": ["yb_zyfdxx", "yb_zyfymx", "yb_dyxxnd", "yb_dyxxzy", "yb_brdjxx"]}}

data: {"step": "rewrite", "status": "running"}
data: {"step": "rewrite", "status": "done", "detail": {"rewritten_question": "城镇职工第三次住院费用分解"}}

data: {"step": "search", "status": "running"}
data: {"step": "search", "status": "done", "detail": {"vector_results": 10, "filter_results": 5}}

data: {"step": "decomposition", "status": "running"}
data: {"step": "decomposition", "status": "done", "detail": {"treatment": {...}, "fees": {...}, "evidence": [...]}}

data: {"step": "explain", "status": "running"}
data: {"step": "explain", "status": "streaming", "chunk": "您的总费用189,085.85元..."}
data: {"step": "explain", "status": "streaming", "chunk": "其中医保内164,411.81元..."}
data: {"step": "explain", "status": "done"}

data: [DONE]
```

---

## 任务拆分

### Phase 1: 数据准备 (2天)

#### Task 1.1: 设计policy_rules Milvus Schema
- 完全按数据模型1的字段名和值域
- 输出: `policy_rules_schema.py`

#### Task 1.2: 实现DataModel1Loader
- 从xlsx读取数据，标准化后写入Milvus
- 输出: `data_model1_loader.py`

#### Task 1.3: 实现McpResultNormalizer
- MCP结果 → policy_rules字段映射
- 值域标准化
- 输出: `mcp_result_normalizer.py`

#### Task 1.4: 数据导入与验证
- 导入xlsx数据到Milvus
- 验证向量搜索+标量过滤
- 输出: `test_policy_rules.py`

### Phase 2: 后端核心 (3天)

#### Task 2.1: 新增runtime/policy_qa/模块
- 目录结构和基础文件
- 输出: `__init__.py`, `models.py`

#### Task 2.2: 实现PolicyQAOrchestrator
- 串联6步骤，yield SSE事件
- 输出: `orchestrator.py`

#### Task 2.3: 实现SQL数据获取
- 封装SqlServerBusinessDataClient
- 查询所有相关表
- 输出: `sql_data_fetcher.py`

#### Task 2.4: 实现问题重写
- 基于SQL结果+SemanticMapper
- 输出: `question_rewriter.py`

#### Task 2.5: 实现费用拆分计算Skill
- 待遇分解: 统筹支付/大额支付/个人应负
- 费用分解: 甲类/乙类/丙类
- 溯源证据: 每个数字的计算过程
- 输出: `fee_decomposition_skill.py`

#### Task 2.6: 实现SSE流式API端点
- 输出: 在routes.py中新增

#### Task 2.7: 实现意图识别+解释生成Prompt
- 输出: 在intent_detector.py和explanation_generator.py中

### Phase 3: 前端改造 (2天)

#### Task 3.1: 创建PolicyQAChat组件
- v3风格，暗色主题
- 输出: `policy-qa-chat.tsx`

#### Task 3.2: 实现SSE流式接收+思维链更新
- 6步骤状态机
- 输出: `thinking-chain.tsx`

#### Task 3.3: 实现PolicyAnswerCard
- 待遇分解展示
- 费用分解展示
- 溯源证据展示
- 输出: `policy-answer-card.tsx`

#### Task 3.4: 集成到portal路由
- 路由: `/policy-qa`
- 输出: `page.tsx`

### Phase 4: 集成测试 (1天)

#### Task 4.1: 端到端功能测试
- 测试用例: 费用分解、待遇分解

#### Task 4.2: 性能优化
- 目标: 首字输出<3秒

---

## 验收标准

### 功能验收
- [x] 用户输入政策问题，系统正确识别意图 ✓ (intent_detector.py 关键词+LLM)
- [x] 系统查询SQL Server获取所有相关表数据 ✓ (sql_data_fetcher.py + SqlQueryAdapter)
- [x] 系统展示6步思维链，每步状态实时更新 ✓ (orchestrator.py SSE事件序列)
- [x] 系统通过Milvus检索政策规则(向量+高级搜索) ✓ (policy_rules_search.py + PolicySearchAdapter)
- [x] 费用拆分计算Skill正确分解待遇和费用 ✓ (fee_decomposition_skill.py + skill包计算器)
- [x] 每个数字都有溯源证据(费用明细+政策规则) ✓ (reconciliation + evidence字段)
- [x] 大模型基于角色生成不同风格解释 ✓ (explanation_generator.py + LlmExplainAdapter)
- [x] 流式输出，响应时间<3秒 ✓ (SSE端点 /policy-qa/stream + streaming处理)

### 测试命令
```bash
# 单元测试
python -m pytest src/tests/unit/runtime/policy_qa -v

# API测试
python -m pytest src/tests/integration/api/test_policy_qa_routes.py -v

# Flow测试
python -m pytest src/tests/integration/flow -v -k "policy_qa"
```

---

## 提交策略

```
Phase 1: feat(knowledge): add policy_rules Milvus schema and data loader
Phase 2: feat(runtime): add policy_qa orchestrator with fee decomposition skill
Phase 3: feat(portal): add PolicyQAChat component with SSE streaming
Phase 4: test(policy-qa): add integration tests and performance optimization
```
