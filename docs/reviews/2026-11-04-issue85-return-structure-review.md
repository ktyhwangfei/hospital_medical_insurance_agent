# 费用分解返回结构审查：字段落点、实际重复与优化优先级

2026-11-04，Issue #85。分析对象为实际运行的issue-78四链路实现。本轮只读重建两张真实结算单的同源公开投影，检查三个单行模型载荷，并离线复算上轮拒绝原因；不调用模型、不修改运行时代码。结论：**优先修正作用域和证据状态的使用，再精简模型视图，最后规范公共返回的共享数据。**

## 1. 新字段实际落在哪里

| 消费位置 | 字段路径/行为 | 来源 |
|---|---|---|
| 后端费用行 | FeeItemExplanation.payment_condition_context | fee_items.py:92；PaymentConditionContext定义于payment_condition_context.py:27 |
| 工作台POST /api/v1/medical-insurance-ai-agent/fee-decomposition/decompose | 响应根fee_items[i].payment_condition_context | fee_decomposition_routes.py:128—147与public_view.py:447 |
| 聊天SSE的result事件 | 事件data.result.fee_decomposition.fee_items[i].payment_condition_context | policy_qa_routes.py:1020—1029、2212 |
| 前端会话状态 | feeDecomposition.feeItems[i].paymentConditionContext | policy-qa-stream.ts:233、941—969；内部仍保留该DTO的snake_case |
| 实际模型用户消息JSON | decomposition.fee_items[i].payment_condition_context；同单名称在顶层billed_items | model_explanation.py:1128—1193、1744—1772 |
| 模型审计噪声过滤 | source_hash、read_at从模型JSON剔除；仍在公开返回中 | model_explanation.py:1767 |

前端已经解析，但组件没有消费paymentConditionContext，**当前页面没有新增bz/诊断展示区**。工作台可在网络面板查看上述POST响应；聊天要查看SSE的result事件。模型正文回退不会删除结构化返回里的这些字段。

没有新增bz数据库表，也没有修改院内源记录。工作台仅实时返回；会话分解实例另缓存在进程LRU中。经policy-qa完成问答并成功持久化时，整个公开结果进入policy_qa_trajectories.payload.result，所以新增上下文也会随之保存；配置内存存储或PG失败回退时不保证落PG。本次回放脚本没有创建问答轨迹。[实现依据：trajectory_storage.py:25—35、93—116、161—177及policy_qa_routes.py:2243—2259]

工作台POST每次重算；同会话同单且链路相同的可复用结果命中LRU后不会再读取，当前缓存容量64、没有TTL。补录诊断或更新目录后，应明确刷新/失效及快照时点，不能把每次聊天都理解为重新查源库。[实现：policy_qa_routes.py:1162—1187、integration.py:456—494]

## 2. 真实返回有多大，重复在哪里

下表为紧凑UTF-8 JSON的核心公开投影字节数，不含HTTP压缩、工作台meta或SSE外壳，也不是模型token数。统计整张单全部明细，不是之前的受限甲乙医保内候选集合。[逐字段证据](2026-11-04-issue85-return-structure-evidence.json)

| 单据别名 | 费用行 | 公开投影字节 | 新上下文增量 | 诊断投影份数/不同内容数 | 源处方数 |
|---|---:|---:|---:|---:|---:|
| eadf82c0aee0，居民门诊 | 11 | 154,038 | 16,081，约10.4% | 44/4 | 3 |
| a1f3048c9526，职工门诊 | 32 | 282,837 | 32,636，约11.5% | 32/1 | 3 |

**“不同内容数”按现有诊断投影字段计算，不等于独立临床记录数。** 两张单均有3个处方，不能把内容相同的诊断直接合并成同一事件。安全去重必须保留原处方/诊断记录的来源关系。

重复已确认：本院等级在每个上下文及settlement_facts中重复；同一读取批次的hash/read_at重复11或32次；目录起止日期与对应费用行字段重复；诊断和科室/医师等级随着每条费用重复。全体积大头还包括fee_items（54,847/136,074字节）、fields（32,021/50,466字节）、calculations、formula_inputs及template_explanations，不能把全部体积归因于新加bz。

## 3. 模型输入已经裁剪，但仍混入整单信息与多份状态

三个单行的实际序列化载荷分别为艾普拉唑14,873、卡络磺钠8,260、西甲硅油16,374字节。decomposition.fee_items已收窄为当前行，同单名称单列billed_items；但每份仍保留settlement_facts的16项整单金额，并同时以fee_items和line_evidence表达本行金额/方法。模型还收到整单uncertainties的代码与关联字段，只过滤了message。

源行键、展示序号和裁剪后下标也须区分：西甲硅油line_id=6、展示第7行、模型目标数组下标0。现有QuestionTarget已提供这些定位，模型专用视图应统一用display_no对用户表达，line_id仅作稳定引用；上轮卡络磺钠草稿出现“第10行（本单行号9）”的混写。

卡络磺钠的真实模型行同时有：status=calculated、verification_status=unverified、explainable=false、division_method=ratio、self_pay_ratio=null；缺口原因在line_evidence中，费用行自己的explanation_reason又为null。它们代表执行、参数/取整留痕、金额可解释性等不同维度，不应合并成一个“正确/错误”标签；但当前命名和重复位置容易让模型沿用ratio，把未提供比例解释为10%。上轮草稿确实发生了这种推断。

clinical_conditions_verified则始终为false，只代表尚未运行条件核验，与金额能否解释无关。宜在能力/核验状态处说明一次，避免每行的false被理解成该项目条件不成立。

## 4. 两类退回已确定有校验误判，不能靠加字段解决

**单行/整单作用域错位。** 单行问题目标已在target_kind/display_no/line_id中确定，但_answer_issues仍用完整public构造_label_amounts。艾普拉唑本行自付二5.26、卡络磺钠本行约1.53，被拿去与该映射中的整单“自付二3.34”比较，触发字段金额归属不符。这里3.34是校验器采用的整单值，不证明整单与所有明细已核平。把相同句子放回本行作用域检查可通过，错误本行金额仍可拒绝。[实现：model_explanation.py:1733、_label_amounts、_attribution_ok；复算见证据JSON]

**排版“-”被当成负号。** 正确式“单价52.60元×数量1.00＝52.60元”通过；前面加列表符“- ”，左边被解析为-52.6000而右边是52.60，报金额不一致。“- 医保内金额＝33.00－3.30＝29.70元”等又因孤立负号报无法解析。无需新模型调用即可复现。[实现：answer_validation.py:10—36、88—106]

这证明了上述具体拒绝理由存在误判，**不证明整段模型回答都正确**。卡络磺钠草稿仍有不该反推10%的问题；不能因此关闭校验或扩大金额容差。

另一个返回/校验耦合问题：_supported_numbers遍历整个模型载荷，行号、诊断码、日期也会贡献“允许数字”。当前样例的行号9能进入白名单，上轮草稿又出现9:1比例；这不能证明模型因行号生成比例，但能证明白名单通过不等于参数有来源。财务数字应来自明确金额、采用参数和已执行操作数；临床阈值按其语境使用，不能由“JSON中出现过这个数字”证明费用结论。

## 5. 建议的优化顺序

| 顺序 | 最小改动 | 验收条件 |
|---|---|---|
| P1：校验与目标一致 | 复用现有target_kind、行号/行键和amount_semantics；单行金额在本行核对，多行逐行绑定；区分排版符与数学负号 | 5.26不能被整单3.34误拒；错写本行金额仍拒；列表正确等式通过，真正负数/错式仍拒 |
| P1：模型专用投影 | 在现有build_model_input中形成一份目标事实视图；本行金额只保留一份，采用公式/参数与原始目录/诊断事实分开；仅保留相关整单上下文和依赖 | 保持现有公开API兼容；金额与公式来源不丢；未核平行不再携带可误认已采用的ratio；症状未取得仍明确 |
| P2：公共返回去重 | 本院资料与读取快照放结算单级；诊断按可靠处方/记录键共享，费用行引用；目录有效期明确唯一权威位置 | 3个处方的关联不丢；同名诊断不能按文本误合并；原分解目录与补充备注版本一致后再合并 |
| P2：数据可用性与版本 | 区分备注present/empty/not_mapped/not_found/ambiguous/unavailable；临床核验用not_performed表达 | 未取字段不能当源值为空；目录唯一命中不等于官方政策版本已验证 |

优先项无需建设新规则库或重新设计四套金额算法。公共返回承担页面、核对与历史回放；模型使用目标专用视图，两个消费者按现有适配函数各取需要的数据。

保留关键金额、原始精度、规格单位、自付二包含于医保外的关系及必要依据引用；不要只以字节减少验收。读取时间/哈希已不进模型，移动这两个字段只能减公共返回重复，不能宣称减少模型token。缓存刷新与源版本补录列为随后校验项。

## 6. 最小模型视图的设计示意

下面只展示西甲硅油的关键事实形状，不是正在运行的新契约；正式实现还须保留该行已执行公式及必要依据引用。同单线索示意选取两项检查，实际实现不能凭关键词静默丢掉必要证据。

```json
{
  "target": {"kind": "fee_line", "display_no": 7, "line_id": "6", "item_name": "西甲硅油乳剂"},
  "settlement_context": {"hospital_level_code": "02", "hospital_level_name": "三级甲等"},
  "observed_amounts": {"total": "33.0000", "in_scope": "29.7000", "out_scope": "3.3000", "self_pay_2": "3.3000"},
  "amount_semantics": {"self_pay_2_included_in": "out_scope"},
  "catalog_note": {"availability": "present", "source_kind": "hospital_catalog_snapshot", "bz": "限胃肠镜检查和腹部影像学检查"},
  "clinical_facts": {
    "diagnoses": [{"code": "R19.400", "name": "大便习惯改变", "association": "same_prescription"}],
    "independent_symptoms": {"availability": "not_mapped"}
  },
  "billed_items": [
    {"item_name": "电子胃镜检查", "association": "same_settlement_charge_only"},
    {"item_name": "电子结肠镜检查", "association": "same_settlement_charge_only"}
  ],
  "clinical_review": {"status": "not_performed"}
}
```

这一形状让模型先确定“问哪一行、这一行原单金额是什么”，再看“备注要求什么、事实关联到哪层”。金额核对、临床条件和实际结算原因继续各有依据，不能由一个状态互相代替。

## 7. 本轮验证边界

已完成两张同源公开投影、三个目标的实际序列化测量；保存调用路径、字节数、重复统计、目标事实及拒绝片段，并用断言核验两类误判。公共接口、模型提示词、金额算法与校验器均未改动；去重/专用视图的体积和模型效果改善尚未实测，不声称实施后一定提升。
