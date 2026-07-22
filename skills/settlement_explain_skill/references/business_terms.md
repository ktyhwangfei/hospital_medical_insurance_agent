# 医保领域术语表

本文档定义 policy-fee-explanation skill 中使用的核心领域术语，
确保患者视角和医保办视角使用统一的中文表达。

## 费用相关

| 术语 | 英文 | 定义 |
|------|------|------|
| 统筹自付 | Basic Pooling Self-Pay | 基本医保统筹段内按政策比例由个人承担的金额 |
| 起付线 | Deductible | 医保开始报销前，先由个人承担的固定金额 |
| 大额自付 | Large Amount Self-Pay | 进入大额保障段后个人承担的部分 |
| 统筹支付 | Basic Pooling Payment | 基本医保统筹基金已经支付的部分 |
| 个人总支付 | Personal Total Pay | 包含多类个人负担的总和（统筹自付 + 大额自付 + 起付线 + 目录外自费等） |
| 医保内费用 | Medical Insurance Inner Amount | 医保目录范围内且进入统筹段的总费用 |
| 大额支付 | Large Amount Payment | 大额保障段统筹基金已支付的部分 |
| 目录外自费 | Out-of-Scope Self-Pay | 医保目录范围外完全由个人承担的费用 |
| 乙类先行自付 | Category B Pre-Self-Pay | 乙类药品/项目需个人先行承担的比例部分 |
| 封顶线 | Cap Amount | 统筹基金年度最高支付限额 |

## 人群相关

| 术语 | 定义 |
|------|------|
| 退休人员 | Retiree — 退休职工，享受退休人员特殊折算规则 |
| 在职人员 | Employee — 在职职工 |
| 城镇职工基本医疗保险 | Urban Employee Basic Medical Insurance |
| 城乡居民基本医疗保险 | Urban-Rural Resident Basic Medical Insurance |

## 规则相关

| 术语 | 定义 |
|------|------|
| 分段支付比例 | Segment Payment Ratio — 按费用区间分段设定统筹基金和个人支付比例 |
| 退休人员折算 | Retiree Factor — 退休人员个人支付比例 = 职工个人支付比例 × 60% |
| 三级医院 | Tertiary Hospital — 三级医院（最高等级） |
| 普通住院 | General Inpatient — 普通住院（非日间手术/急诊等） |
| 结构化政策规则 | Structured Policy Rule — Milvus 中按字段标签组织的政策规则 |
| 支付比例 | Payment Ratio — 统筹基金支付比例和职工个人支付比例 |
| 计算公式 | Calculation Formula — 计算类规则（如退休人员折算公式） |
