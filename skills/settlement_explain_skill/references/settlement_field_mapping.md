# 结算字段映射

SQL Server 结算表字段 → 标准化字段名 → 中文显示名 → 定义。

## 核心字段

| SQL 字段 | 标准化字段 | 中文显示 | 定义 |
|----------|-----------|---------|------|
| yb_zyfdxx.bdtczf | basic_pooling_self_pay | 统筹自付 | 基本医保统筹段内按政策比例由个人承担的金额 |
| yb_dyxxzy.bcqfje | deductible | 起付线 | 医保开始报销前，先由个人承担的金额 |
| yb_zyfdxx.bddegwyzf | large_amount_self_pay | 大额自付 | 进入大额保障段后个人承担的部分 |
| yb_zyfdxx.bdtczfje | basic_pooling_payment | 统筹支付 | 基本医保统筹基金已经支付的部分 |
| yb_zyfdxx.bddegwyzfje | large_amount_payment | 大额支付 | 大额保障段统筹基金支付金额 |
| yb_zyfdxx.bdgryf | personal_total_pay | 个人总支付 | 个人总支付金额 |
| yb_dyxxzy.bcybnje | medical_insurance_inner_amount | 医保内费用 | 医保目录范围且进入统筹段的总费用 |

## 上下文字段

| SQL 字段 | 标准化字段 | 中文显示 |
|----------|-----------|---------|
| yb_brdjxx.FUND_TYPE | insurance_type | 险种类型 |
| yb_zyjyxx.PER_TYPE | person_type | 人员类别 |
| yb_brdjxx.yllb | service_type | 医疗类别 |
| — | hospital_level | 医院等级（从字典表解析） |

## 人员类别映射

| PER_TYPE 值 | 标准化值 |
|------------|---------|
| 1 | 退休人员 |
| 2 | 在职人员 |
| 其他 | 保持原值 |

## 医疗类别映射

| 原始值 | 标准化值 |
|-------|---------|
| "普通住院" | 住院-普通住院 |
| "住院-*" | 保持原值 |
| 其他 | 住院-{原值} |
