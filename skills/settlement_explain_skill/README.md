# policy-fee-explanation

医保费用解释 Skill v2.0。自包含的医保费用解释能力包。

## 快速开始

```python
from src.skill_infra.skill_router import get_assembler

assembler = get_assembler("settlement_explain_skill")
result = assembler.execute(
    question="我的统筹自付为什么这么多",
    settlement_id="1671213",
)
print(result.patient_answer)
```

## 前置条件

1. SQL Server 可访问（settlement-data MCP）
2. Milvus 可访问（structured-policy-rule MCP）
3. 后端服务已启动（提供 MCP 运行时）

## 目录结构

```
settlement_explain_skill/
├── SKILL.md                     ← 技能规范（14步执行流程）
├── README.md                    ← 本文件
├── agents/openai.yaml           ← MCP 依赖声明
├── references/                  ← 参考文档
│   ├── business_terms.md        ←   领域术语
│   ├── policy_query_patterns.md ←   政策查询模式
│   ├── settlement_field_mapping.md ← 结算字段映射
│   └── answer_quality_standard.md  ← 回答质量标准
├── schemas/                     ← JSON Schema 定义
│   ├── input.schema.json
│   ├── output.schema.json
│   ├── trace_event.schema.json
│   └── policy_evidence.schema.json
├── templates/                   ← 解释模板
│   ├── patient_view.md
│   ├── office_view.md
│   ├── cannot_answer.md
│   └── partial_answer.md
├── scripts/                     ← 执行脚本
│   ├── normalize_fee_context.py
│   ├── validate_skill_result.py
│   └── build_trace_event.py
└── tests/                       ← 测试用例
    └── case_pooling_self_pay_1671213.yaml
```

## 支持的费用项

| 费用项 | 触发词 |
|--------|--------|
| `pooling_self_pay` | 统筹自付、基本统筹自付、统筹段个人承担 |
| `deductible` | 起付线、起付标准、门槛费 |
| `large_amount_self_pay` | 大额自付、大额互助 |
| `pooling_payment` | 统筹支付、统筹报销 |
| `personal_total_pay` | 个人总支付、个人负担 |
| `out_of_scope` | 医保外费用、自费、特需 |

## 新增费用项

1. 在 `references/policy_query_patterns.md` 添加查询模式
2. 在 `references/settlement_field_mapping.md` 添加字段说明
3. 在 `references/business_terms.md` 添加术语定义
4. 测试用例添加到 `tests/`
