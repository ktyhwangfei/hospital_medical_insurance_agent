# 政策承载约定：政策指标·文号/地域/生效期 承载结构草案（供数据起稿 → 知识口径注释）

基线：#35 审结 + 架构④ 政策附加（政策口径类指标(结算法则/报销规则类)发布门禁额外硬挂 文号/地域/生效期；运营类不强制）。
已知前提：Metric 现无专用政策承载字段；zcgz(政策规则)对象承载结构化政策提取（19字段）。本草案回答"政策指标怎么把 文号/地域适用/生效期 带进定义并被发布门禁硬卡"。

## 1. 分派二类（此为数据结构假设，口径分类待知识逐类注释/校准）
- **A 政策绑定类**（发布必须挂 文号 + 地域适用 + 生效期）：任何描述"报销比例/限额/自付段/结算法则/起付封顶"等由具体政策文件（文号）口径决定的指标。定义值随文号生效区间而变。
- **B 运营/事实类**（当前 4 门禁指标等 aggregation of 结算事实）：本身不带政策文号；若有政策语境，走 synonyms/definition 描述性约定，不进硬门禁。

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
