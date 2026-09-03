# 政策承载约定：政策指标·文号/地域/生效期 承载结构草案（供数据起稿 → 知识口径注释）

基线：#35 审结 + 架构④ 政策附加（政策口径类指标(结算法则/报销规则类)发布门禁额外硬挂 文号/地域/生效期；运营类不强制）。
已知前提：Metric 现无专用政策承载字段；zcgz(政策规则)对象承载结构化政策提取（19字段）。本草案回答"政策指标怎么把 文号/地域适用/生效期 带进定义并被发布门禁硬卡"。

## 1. 分派二类（=知识 Q1审结，2026-09-03）
**A 政策绑定类（发布必须挂 文号+地域适用+生效期）**。核心判据：definition 出现「报销比例/限额/自付段/起付封顶/目录内-外/待遇资格/慢病准入/退费纠错金额段」等政策语义词 → 必属 A。逐类（映射 metric.subkind）：
- **policy_rate（报销/统筹/补差金额类）**：统筹/大病/大额/民政/公务员补助/退役军人补助各支付额，及“起付线以上(beyond)/封顶外(FeeAfterBig)/乙类先自付/超限价自付/目录外自费额” → source 落 TA_/TB_/NT_/T_ 金额类中含支付判定者。
- **policy_elig（待遇资格/准入类）**：险种、是否可结算与未结算原因、慢病标识+病种、慢病医院范围、异地结算、退休/公务员/退役军人标识（数值随参保地政策与个人待遇档）。
**B 运营/事实类（不夹，可 synonyms/definition 描述）**：纯交易事实/审计属性——费用明细条数、统币、交易时间/原交易号、机构支付总额、总数量；及已治理 4 门禁运营指标（口径句写实“医保实际受理有效笔数”本身不漂移）。含 B 特例：计费“实付vs记账、负数=冲正”口径说明（defition 携带即可）。

## 2. 承载结构（拟 additions，随 schema_version 演化）
在 Metric / 其发布快照上补 **policy_carrier** 组（可空 JSONB），仅 A 类在发布前必须填写：
```
policy_carrier: {
  "doc_number": "京医保发〔2024〕xx号",     # 政策文号（来源可为 zcgz 提取）
  "region_scope": "北京市",                 # 地域适用（enum/范围）
  "effective_start": "2024-01-01",          # 生效起
  "effective_end": null,                    # 生效止（null=现行/未废止）
  "policy_rule_ref": "zcgz.<提取id|条款码>"   # 溯源：来自哪条结构化政策(可选，选填增强可审计)
}
```
对齐点：
- 若政策文号/生效期已以"结构化提取"存在于 zcgz，优先 **引用** zcgz 实体（policy_rule_ref），指标只冗余生效快照，避免两处口径漂移；文号语义单一源在 zcgz（与 #26 origin trust 一致）。
- 生效期校验跨两个口径：政策口径(section8 生效档) 决定指标现值；语义层自身 effective 用于查询不得用已废止时段值。

## 3. 发布门禁（架构④ 政策附加 → 具体到码）
后端 `publish_object` / `save_published_metric` 对 **metric_kind=="policy"/fact-dependency 且 semantics 属 A 类**（口径分类由知识给，落到一个 metric_kind/标签位）命中时：
- 缺失任一 = 拒绝并指出缺哪个（doc_number | region_scope | effective_start_required 等）。
- 现在后端唯一硬卡 owner+definition(tier1)；政策类在此之上加硬卡 policy_carrier 三件。
- 需要一个稳定判别位：建议加 `metric.subkind: "policy_rate" | "policy_rule" | ""`（或复用 metric_kind 扩展）把 "政策类" 显式化，门禁按 subtitle 跑，而不是靠 semantic_type 猜。

## 4. 存储/迁移/回滚
- semantic_metrics 增 JSONB 列(或并入现有 payload) + schema_version +=1；CREATE+ALTER 双写为防回归。
- 列宽松可空；仅 A 类发布时校验非空 → 存量运营指标不被迫填。
- 快照版本 (BusinessObjectVersion) 一并携带，随发布写入，回滚=版本指针。

## 5. 知识需要给的口径输入（我来固化的输入项）
1) A/B 的判定清单（哪些 semantic/metric 属"结算法则/报销规则类"被硬夹），并给样例指标对照；
2) region_scope 取值 (省/市/内蒙?), effective 的粒度单位建议；
3) 政策废止时 effective_end 是否必填推动(有 effective 但 pending end = 风险?)；
4) policy_rule_ref 溯源用 section vs rule_code 主键取主哪种。
数据据此把草案落成正式 spec + PO 后放入 #35 follow-up issue 与 schema 迁移一并排程。

—— 数据稿(苏杭) 2026-09-03；待知识 口径注释/样例校准后固化。
