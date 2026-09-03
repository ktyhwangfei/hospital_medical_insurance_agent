# Issue #33 P0-4 真实语料检索基线报告

> 日期：2026-09-02
> 评估对象：`StructuredPolicyRuleRetriever`（current/enhanced 两组）与 `BroadPolicyRetriever`，对照 BM25 纯文本基线
> 语料来源：Milvus active release `policy_rules_REL_20260827_MZ8_V3`（纯只读）
> 复现命令：`uv run python scripts/eval/issue25_retrieval_baseline.py --corpus real`
> 逐案原始结果：`scripts/eval/issue33_real_baseline_result.json`；用例集文档：`docs/reviews/2026-09-02-issue33-real-golden-cases.md`

## 1. 语料规模与过滤口径

- release 集合总条数：**418**；按范围纪律（issue #33：仅门诊+通用）过滤
  `med_type in ("门诊-普通门急诊","门诊-急诊留观","门诊-一般门特") or med_type == ""`
  后保留 **351** 条，排除 `住院-普通住院` **67** 条。[实测：MilvusRuleStore.list_rules 全量取回后过滤]
- 351 条规则全部自带 768 维 bge 向量（复用库内向量，查询侧用 sentence_transformers bge-base-zh-v1.5 现场编码）。
- 规则类型分布：通用规则 166 / 适用范围 65 / 支付比例 64 / 排除规则 34 / 起付线 9 / 封顶线 6 / 大额互助比例 4 / eligibility 2 / deductible 1。
- 险种分布：城镇职工 171 / 城乡居民 159 / 城乡居民大病保险 9 / 大病保险 5 / 工伤保险 1 / 空 6。
- 文档构成（主题 [推断：基于 source_text 通读]）：北京市城镇职工基本医疗保险规定 121 条（doc_1d44e2e1db0c，2001 年施行）、城乡居民实施细则 105 条（doc_466953309ccf，2018）、城乡居民办法 50 条（doc_ebea08e4d59d，2018）、职工门诊统筹分段比例 25 条（doc_7173172eb649，含冲突值与碎片规则）、门诊大额医疗互助调整 13 条（doc_7a1fbf7480d4，2010）、职工门诊分段比例与起付线 10 条（doc_4bf8d92facc0）、城乡居民大病保险 6 条（doc_a73c31a7630e，2019）、大病倾斜政策 10 条（doc_7ec146a78b34）、其余 11 条为排除规则与提取碎片（doc_592c820eb140 / doc_22c5625f58e2）。（2026-09-02 勘误：初版将 doc_7a1fbf7480d4 误标为 2019 大病保险、doc_4bf8d92facc0 误标为 2010 大额互助，经逐条核对字段后更正。）
- **关键实测：该 release 固定 schema 仅 11 个字段**（rule_id/fact_id/doc_id/rule_type/insu_type/med_type/hosp_lv/psn_type/setl_type/schema_version/vector），Issue #25 的适用性字段（region/effective_date/expiry_date/publish_status/policy_version/is_remote/amount_band_min/max）**不在固定 schema 中**，`field_quality_score = 0.0`。（2026-09-02 更正：这些字段实际以 dynamic key 存在于实体中——该 collection 开启了 `enable_dynamic_field`，describe 看不到但可按名过滤/取回；初版"全部不存在"的表述不准确，详见 §8。）灌入 `_FakeMilvusClient` 时 `describe_collection` 按此 11 字段返回并开启 dynamic field，与生产一致。

## 2. 黄金用例标注方法

以现有 58 条合成用例的"问题意图"为骨架逐条处理（`_build_real_golden_cases()`），标注前先对 351 条规则全文 dump 通读（`scripts/eval/real_corpus_dump.json` / `real_corpus_listing.txt`），禁止臆造 rule_id，并由脚本护栏强制校验：非跳过用例的 expected_rule_ids 必须 ⊆ 语料实际 rule_id 集合（该护栏在本轮开发中实际拦下过一次 skip 用例残留合成 ID 的错误）。

处理结果：**映射 4 条 / 转负例 48 条 / 跳过 6 条**。

### 映射用例（4 条）

| 用例 | 问题意图 | 期望真实规则 | 依据 |
|------|----------|--------------|------|
| BJ_EMP_TERT_OP | 在职职工三级医院门诊报销比例 | rule_bd19807063be1fd8（2万以下70%）+ rule_e04620a0f3dffeb2（2万以上60%） | doc_7173172eb649 门诊统筹分段， hosp_lv=三级/psn=在职职工 精确匹配；完整答案需两条同时召回 |
| BJ_CAP | 职工住院年度最高支付限额 | rule_e44e75c149f9（统筹基金封顶 10 万元） | med_type 为空的通用规则，适用住院场景；rule_eb4c465e6f2e 仅引用条款无数值不计入 |
| BROAD_CAP | 宽泛问北京医保封顶线 | rule_e44e75c149f9 + rule_9da07fdaeaf8（居民大病 15 万） | 问题未限定险种，两者均为有效答案 |
| BROAD_OUTPATIENT | 宽泛问门诊报销比例 | rule_74af12a735aef785（在职 2万以下 70%） | 合成原例期望的"在职门诊 70%"的实盘对应；退休/居民门诊规则召回计为 FAR 信号 |

### 转负例（48 条）

语料中不存在对应规则、正确行为是诚实拒答（零召回）的用例，按缺失原因分组：

- **住院类（范围纪律排除，33 条）**：全部分段/退休/二级住院用例、BULK_051–062、BROAD_DEDUCTIBLE/RETIREE_RATIO/AMOUNT_BAND 等——语料无任何住院规则。
- **地区/险种/异地类（5 条）**：SH_* 上海 2 条（语料全部为本市政策）、BJ_EMP_REMOTE/BROAD_REMOTE（语料只有居民异地备案/垫付流程规则，无异地支付比例规则，且 is_remote 字段缺失）、BJ_RESIDENT_TERT_IP（居民住院被排除）。
- **时间/状态机制类（8 条）**：NEG_EXPIRED_2023 / NEG_FUTURE_2025 / BJ_EMP_TERT_IP_2025* / NEG_PILOT / NEG_REVOKED / BJ_EMP_TERT_IP_DRAFT / NEG_REMOTE_FALSE——语料无有效期与发布状态字段，且无对应规则。
- **维度隔离验证（2 条，真实语料下变得有区分度）**：NEG_OUTPATIENT_VS_IP（语料含 80 条门诊规则，验证住院问题不误召回门诊规则）、NEG_INSU_RESIDENT（语料同时含职工 171 条与居民 159 条，验证险种隔离）。

### 跳过（6 条，不计入指标）

| 用例 | 理由 |
|------|------|
| BJ_EMP_TERT_IP_NEAR_EXPIRY / EXPIRY_DAY / NEW_YEAR | 语料 effective_date/expiry_date 字段全缺失，时间边界过滤机制无法评估 |
| BJ_EMP_TERT_IP_DEFAULT_REGION | 语料 region 字段全缺失（全部为本市政策），默认地区逻辑无法评估 |
| BJ_EMP_TERT_IP_NO_DATE | 无有效期字段，无结算日期场景退化为普通过滤，评测价值低 |
| BJ_EMP_TERT_IP_VERSION_MISMATCH | 语料 policy_version 字段全缺失，版本过滤机制无法评估 |

## 3. 指标结果（52 条有效用例 = 4 映射 + 48 负例，Top-K=3）

| 基线 | P@3 | Recall | FAR | Complete 率 | 诚实拒答率 |
|------|-----|--------|-----|-------------|------------|
| text_only（BM25） | 0.0% | 7.7% | **92.3%** | 7.7% | 8.3%（4/48） |
| current_hybrid（structured） | 0.0% | 80.8% | **17.3%** | 80.8% | 87.5%（42/48） |
| enhanced_hybrid（structured） | 0.0% | 80.8% | **17.3%** | 80.8% | 87.5%（42/48） |
| broad_hybrid | 0.0% | 92.3% | 0.0% | 92.3% | 100%（48/48，空召回） |

> 注意指标口径：Recall/Complete 被 48 条负例主导（负例零召回即 recall=1、complete=true）。**4 条映射正例在全部四条基线上 recall 均为 0**——没有任何基线召回过任何一条期望的真实规则。

正例/负例子集拆分：

| 基线 | 正例 recall（4 条） | 正例 FAR | 负例 FAR | 负例诚实拒答 |
|------|---------------------|----------|----------|--------------|
| text_only | 0.0% | 100% | 91.7% | 4/48 |
| current/enhanced | 0.0% | 75.0% | 12.5% | 42/48 |
| broad | 0.0% | 0%（全空） | 0%（全空） | 48/48 |

### 与门禁目标的差距

| 门禁 | 目标 | structured（enhanced） | broad | 判定 |
|------|------|------------------------|-------|------|
| FAR | < 8% | 17.3%（负例子集 12.5%） | 0%（真空达标） | structured **未达**（+9.3pt）；broad 靠全空召回"达标"，无参考价值 |
| P@3 | > 90% | 0% | 0% | **均未达**（-90pt） |
| 诚实拒答 | > 80% | 87.5% | 100%（真空达标） | structured 达标但有 6 条系统性失败 |

## 4. FAR 与零召回的归因（按贡献排序）

1. **broad_hybrid 全量空召回（生产级缺陷）**：`BroadPolicyRetriever._build_applicability_expr` 硬编码 `publish_status == "published"` 过滤，且不做字段存在性检查。已对生产 Milvus 只读实证：在 `policy_rules_REL_20260827_MZ8_V3` 上执行该过滤返回 **0 行**。即当前 broad 路径对 active release 的任何问题都返回空证据——FAR=0 与诚实拒答 100% 全是真空指标。
2. **structured 查询计划是住院特化的**：query1（分段比例）关键词 `起付标准至3万元/超过3万元至4万元/超过4万元` 在 351 条真实规则中命中 **0** 条（该分段是北京住院旧制口径），导致 query1 对一切上下文均空；门诊分段（2 万档）完全不在查询计划内。这是映射正例 BJ_EMP_TERT_OP recall=0 的直接原因。
3. **query2（退休折算）关键词 `"60%"` 系统性误召回**：6 条 BROAD_* 负例（问上海/异地/版本/起付线等无关话题）全部召回同样两条规则（rule_03131e7a5600f41a、rule_1b5d162145d9c088，均为"统筹支付 60%"的门诊分段规则）。根因：structured retriever 不消费问题文本，空上下文时 query2 只剩 `rule_type=支付比例` 约束，含 "60%" 字样的规则（共 6 条，含缴费基数 60% 等不相关规则）即成为万金油答案。这 6 条是负例 FAR 12.5% 的全部来源。
4. **候选池先截断后过滤**：`execute_query` 标量查询 `limit=20` 在关键词过滤**之前**生效。BJ_EMP_TERT_OP 的 query2 实际命中 27 条候选，期望规则 rule_e04620a0f3dffeb2 排在第 22 位被截断（实测探针确认）。合成语料仅 32 条从未触发该路径；真实语料 351 条下该截断必然丢候选。
5. **适用性字段全缺失使 enhanced ≡ current**：两组结果逐案完全一致（已逐案比对确认）。region/有效期/发布状态/异地/金额段过滤全部被逐字段跳过，Issue #25 的增强在真实语料上零收益——不是实现问题，是数据问题（field_quality=0）。
6. **text_only 高 FAR 的来源**：BM25 语料文本取自 `str(FieldTrace dict)`（含 `'value':` 等元信息噪声），且无任何维度过滤；48 条负例中 44 条被灌入无关规则（最高频误召回 rule_5f5aa6c9f68a 居民参保范围规则出现 21 次）。映射正例上 BM25 能召回语义相近规则（如门诊问题召回大额互助规则），但均非标注期望，FAR=100%。
7. **数据质量次生问题（标注过程发现）**：doc_7173172eb649 存在同维度同分段多条规则且 `payment_ratio` 语义不一致（如"一级/在职/2万以下"同时有 0.9 / 0.1 / 0.3 三条，部分记录存基金比例、部分存个人比例）；另有提取碎片规则（source_text 仅 "0.08。"/"0。"）。这些规则一旦进入召回结果就是确定性错误适用。

## 5. 合成模式回归保护

改动前后各跑一遍 `--corpus synthetic`（默认，bge 编码），四基线指标逐位一致：

| 基线 | 改动前 P/R/FAR | 改动后 P/R/FAR |
|------|----------------|----------------|
| text_only | 0.132/0.448/0.713 | 0.132/0.448/0.713 |
| current_hybrid | 0.115/0.282/0.799 | 0.115/0.282/0.799 |
| enhanced_hybrid | 0.167/0.264/0.730 | 0.167/0.264/0.730 |
| broad_hybrid | 0.201/0.534/0.799 | 0.201/0.534/0.799 |

（日志：`scripts/eval/synthetic_pre_change.log` / `synthetic_post_change.log`）

> 注：本工作区存在并行任务对 `src/runtime/policy_qa/` 的未提交修改，因此上述"改动前"基准是当前工作区状态而非 git 已提交版报告的数值（已提交报告中 broad_hybrid 为 14.4%/36.2%/85.6%，差异来自并行任务的 src 改动，与本脚本改动无关）。`--corpus` 默认 `synthetic`，合成模式的评估行为与改动前完全一致；生成文档仅有两处附加变化（标注口径新增第 7 条"跳过"说明、JSON 块每用例新增 `"skip": false` 字段）。

## 6. 不确定性与后续建议

- 正例仅 4 条，P@3 的统计功效不足；建议后续任务为真实语料单独撰写门诊/门特/大病保险正向用例集（本次已定位可用锚点：门诊分段 25 条、大额互助 10 条、大病保险 23 条、门特 9 条）。
- 负例占比 48/52 是范围纪律（排除住院）的直接后果，诚实拒答率的解读需结合该偏斜。
- `_FakeMilvusClient` 的候选截断顺序为插入序，生产 Milvus 为内部序——归因 4 的"第 22 位"是本次实测位置，机制（27 候选 > limit 20）本身与顺序无关、必然发生。
- 修复优先级建议：① broad 路径 publish_status 硬过滤对缺字段 collection 的兼容（生产全空）；② structured 查询计划泛化到门诊分段或按 rule_type 动态规划；③ query2 关键词改为结构化折算标识而非 "60%" 文本；④ execute_query 先关键词过滤再截断（或上调 limit）；⑤ 适用性字段回填（Issue #25 存量回填流水线）否则 enhanced 永远等于 current。

[来源： scripts/eval/issue33_real_baseline_result.json 逐案实测；Milvus describe_collection/query 只读实测；scripts/eval/real_corpus_dump.json 全文通读]

---

## 7. 回填后复测（2026-09-02，Issue #33 P0-2/P0-3 已 --apply 到 active release 集合）

回填动作：`scripts/backfill_amount_band.py --apply`（27 条金额段数值化，含解析器扩展"X以下/以内/不超过X"后仅 1 条"50000-"未解析）；`scripts/backfill_applicability_outpatient.py --apply --reviewed-by policy-admin`（门诊+通用 351 条 × 6 适用性字段 = 2106 项）。写入目标为统一 resolver 定位的 active release 集合 `policy_rules_REL_20260827_MZ8_V3`；实测核验：总行 418、published 351、住院 67 条全部保持未回填、金额段已数值化 27 条。

| 基线 | P@K | Recall | FAR | Complete | 诚实拒答 |
|------|-----|--------|-----|----------|----------|
| text_only | 0.000 | 0.077 | 0.923 | 0.077 | 0.083 |
| current_hybrid | 0.000 | 0.808 | 0.173 | 0.808 | 0.875 |
| enhanced_hybrid | 0.000 | 0.808 | 0.173 | 0.808 | 0.875 |
| broad_hybrid | 0.006 | 0.115 | 0.897 | 0.096 | 0.104 |

（命令：`uv run python scripts/eval/issue25_retrieval_baseline.py --corpus real`；结果 JSON 已被本次运行覆盖。）

**变化解读**：broad 路径不再全空召回（§4 发现 1 的 `publish_status == "published"` 硬过滤因适用性字段已回填而生效，召回恢复），但随之而来诚实拒答率从 100%（真空）跌至 10.4%——召回恢复后负例开始误召，拒答出口成为真实需求。structured 两组指标不变（回填前字段缺失时过滤被跳过，回填后过滤生效但本用例集的负例区分度主要来自维度硬过滤，前后等价）。

### 7.1 拒答阈值校准结论（实测，bge 向量）

- 生产集合 COSINE 探针：负例 top-1 分布在 0.64–0.835（"城乡居民大病"0.835、"上海住院"0.737），正例 0.69–0.80（"门诊分段"0.725、"封顶"0.795）——**正负例向量分数区间完全重叠，纯向量分数阈值在本语料上不可分**；`BROAD_MIN_VECTOR_SCORE` 0.35/0.45/0.55/0.65 扫描结果逐位一致（所有分数都在 0.65 以上）。
- 等效 BM25-only 门限（阈值设为 2.0 使向量条件恒真）：broad 诚实拒答 0.104→0.333、Recall 0.115→0.250——词面零重叠可拦 16/48 负例，但其余 32 条负例与库内规则存在词面重叠（如"60%"万金油），词面/语义信号均无法可靠拦截。
- **结论**：诚实拒答的可行路径是"硬维度冲突检测 + 零词面重叠"，而非语义分数阈值；broad 路径若要对齐 structured 的 87.5%，需要把问题推断出的显式维度（地区/险种/医疗类别）从软精排升级为硬冲突排除。threshold 机制（`BROAD_MIN_VECTOR_SCORE`）保留默认关闭。

### 7.2 门禁差距（复测后）

- FAR < 8%：structured 17.3% 未达（主因 §4 发现 2-4：住院特化查询计划、"60%"万金油、limit=20 截断）；broad 89.7% 未达。
- P@3 > 90%：正例仅 4 条，统计功效不足，需先补真实语料正向用例集（§6 锚点：门诊分段 25 条、大额互助 10 条、大病保险 23 条、门特 9 条）。
- 诚实拒答 > 80%：structured 87.5% 已达；broad 需硬维度冲突排除（§7.1）。

---

## 8. 终态复测（2026-09-02，全部 P0/P1 修复 + 82 条用例集完成后干净复跑）

复跑前置：本节数字是最后一轮机制改动（dynamic field 修复、specificity 排序、FAR 三修、broad 硬维度冲突排除）全部落定、且无并行写竞争条件下的干净复跑。命令仍为 `uv run python scripts/eval/issue25_retrieval_baseline.py --corpus real`；语料 `policy_rules_REL_20260827_MZ8_V3`（351 条，门诊+通用）；用例 82 条 = 正向 28 + 负例 48 + 跳过 6。

### 8.1 dynamic field 修复（本轮最重要的生产修复）

回填 --apply 后复测时发现：适用性过滤在生产环境**从未生效**。根因：release collection 由旧版 pipeline 产物拷贝而来，固定 schema 仅 11 字段，适用性字段以 dynamic key 存储；`_get_collection_fields` 只读 `describe_collection` 的固定字段列表，导致 region/publish_status/金额段等过滤被逐字段静默跳过。修复：`structured_policy_retriever._get_collection_fields` 在 `desc["enable_dynamic_field"]` 为真时并入已知可过滤动态键白名单（`_KNOWN_DYNAMIC_FILTERABLE_FIELDS`：region/effective_date/expiry_date/publish_status/policy_version/is_remote/amount_band_min/amount_band_max）。实证：修复后生产探针 missing=[]、无 skip 警告；`MilvusClient.query/search` 的 output_fields 可按名取回 dynamic key（实测 amount_band_min/max 有值，specificity 的金额段分支非死代码）。

eval 侧对齐：`_FakeMilvusClient.describe_collection` 增加 `enable_dynamic_field` 返回，真实语料模式注册时开启，保证 eval 的 `_get_collection_fields` 行为与生产逐字一致（合成语料固定 schema 已含适用性字段，保持关闭）。

### 8.2 终态指标（82 条用例）

| 基线 | P@3 | Recall | FAR | Complete | 诚实拒答 |
|------|-----|--------|-----|----------|----------|
| text_only | 0.118 | 0.285 | 0.829 | 0.066 | 0.083 |
| current_hybrid | 0.026 | 0.605 | 0.237 | 0.553 | 0.875 |
| enhanced_hybrid | 0.031 | 0.618 | 0.232 | 0.553 | 0.875 |
| broad_hybrid | 0.088 | 0.555 | 0.491 | 0.382 | 0.604 |

（P@3/Recall/FAR 为全 76 条非跳过用例的均值；负例空召回时 P/R 计 0，拉低均值。current 与 enhanced 不再相等——dynamic field 修复使 enhanced 的适用性过滤真实生效。）

正向（28 条）按 structured 计划器射程拆分：

| 子集 | n | structured P@3 / R / FAR | broad P@3 / R / FAR |
|------|---|--------------------------|---------------------|
| 统筹自付射程内 | 14 | 0.167 / 0.357 / 0.833 | 0.143 / 0.286 / 0.786 |
| 射程外（起付线/大病自付/就医流程/支付范围/个人账户/缴费） | 14 | 0.000 / 0.000 / 0.000（全部空召回） | 0.333 / 0.655 / 0.524 |

### 8.3 门禁终态判定

| 门禁 | 目标 | structured（enhanced） | broad | 判定 |
|------|------|------------------------|-------|------|
| FAR | < 8% | 负例子集 12.5%（6/48） | 负例子集 39.6%（19/48） | **均未达** |
| P@3 | > 90% | 正向 8.3%（射程内 16.7%） | 正向 23.8% | **均未达** |
| 诚实拒答率 | > 80% | **87.5% 达标** | 60.4% | structured 达，broad 未达 |

### 8.4 剩余失败归因（逐案，来自 issue33_real_baseline_result.json）

**structured 负例误答 6/48**：全部是 BROAD_* 空上下文用例，且召回完全相同的 3 条门诊支付比例规则（rule_03131e7a5600f41a / rule_043714511e59df14 / rule_0c32d785a8011676）。根因：structured retriever 不消费问题文本，空 ctx 时 query2 只剩 `rule_type=支付比例 + "个人支付"关键词` 约束。生产上 structured 只在带 settlement_id 的结算解释链路被调用（ctx 非空），宽泛问题由路由进 broad——这 6 条是 eval harness 全量过 structured 的口径产物，但暴露了"空 ctx 时 structured 应当拒答而非放行"的真实加固点。

**broad 负例误答 19/48**，四类：
1. 住院类 6 条（BJ_EMP_TERT_IP_BAND_2 / BJ_EMP_SEC_IP_BAND_2 / BJ_EMP_TERT_IP_2025 / BJ_RESIDENT_TERT_IP / BJ_DEDUCT_TERT / NEG_OUTPATIENT_VS_IP）：范围纪律排除了全部住院规则，但 `med_type` 为空的通用规则按"空值保留"设计仍可召回——住院问题在只含门诊+通用的库里无法被维度冲突拦截，这是范围纪律与空值保留的固有张力。
2. 版本/有效期类 5 条（NEG_EXPIRED_2023 / NEG_FUTURE_2025 / NEG_REVOKED / BJ_EMP_TERT_IP_DRAFT / BROAD_VERSION）：broad 路径无有效期/版本/publish_status 硬过滤（structured 有），问已废止/草案/未来版本的问题按词面重叠召回了现行规则。
3. 词面重叠类（BROAD_DEDUCTIBLE / BROAD_RETIREE_RATIO / BROAD_AMOUNT_BAND 等）：如"北京住院起付线"召回大病保险起付线（rule_5c825a5842dc）——与 §7.1 结论一致，词面/语义信号均不可分。
4. 推断歧义类（NEG_INSU_RESIDENT）：问题同时含"城镇职工""城乡居民"，维度推断取主体险种后规则匹配放行。

**structured 正向射程内 P@3=16.7%** 的主因：门诊 query1 无文本判别（target_amount=0 时无金额段过滤），大额互助/门诊统筹/门特规则在 `rule_type=支付比例` 下同场竞争，specificity 排序不足以区分（REAL_LMAA_* 三条全部误召无关规则）；叠加 §4 发现 7 的数据质量（doc_7173172eb649 同维度多条冲突比例规则，召回即错）。

### 8.5 合成模式回归

`--corpus synthetic` 干净复跑：text_only 逐位一致（0.132/0.448/0.713，纯脚本内部对照）；其余三基线较 §5 表变化（current 0.126/0.299/0.839、enhanced 0.149/0.333/0.816、broad 0.247/0.615/0.667），系本 issue 内有意的检索改动（FAR 三修、broad 硬冲突排除、specificity 排序）所致，非 eval 脚本噪声。

### 8.6 本期不做、建议后续的候选（如实记录，不为凑门禁数字加机制）

- broad 路径补有效期/publish_status/publish 状态硬过滤（dynamic field 修复后已具备可过滤性，可消灭版本/有效期类 5 条负例误答）；
- structured `plan_queries` 泛化到起付线/大病自付等 target_field，或显式声明射程并让 eval 按射程分别出数（当前 14 条射程外正向全空是结构性结果，非回归）；
- structured 空 ctx 拒答加固（§8.4）；
- eval harness 按生产路由分流（BROAD_* 不进 structured）；
- doc_7173172eb649 提取质量治理（同维度冲突比例规则去重与口径统一）。

[来源：scripts/eval/issue33_real_baseline_result.json 逐案实测（2026-09-02 干净复跑）；Milvus describe_collection/query 只读探针]


---

## 9. 加固①落地：structured 空上下文必须拒答（2026-09-02，需求方排入下一轮）

### 9.1 实现

- 新增 `_is_empty_policy_context(ctx)`：险种/医疗类别/人群/医院等级/结算单号**全部为空**即判空上下文（target_amount/region/date 等修饰量不算区分性维度）。
- `plan_queries` 空上下文直接返回 `[]` 并 warning（纵深防御，独立调用者同样受保护）。
- `retrieve` 空上下文且未显式传 `custom_queries` 时短路返回空证据，`StructuredRetrievalResult` 新增 `refusal_reason`（`"empty_context"`）与 `refusal_message`（"缺少可依据的政策上下文（无险种/医疗类别/人群/医院等级/结算单号），无法回答该问题。"）字段，**不触碰 Milvus**；显式传 `custom_queries` 的调用方自负规划责任，不受限。下游零证据走既有诚实拒答通道（`answer_status=unavailable`），不得编造兜底答案。
- 先红后绿：新增 4 例（空 ctx 拒规划 / 部分维度照常规划 / retrieve 拒答且零 Milvus 调用 / custom_queries 放行），随后实现转绿。

### 9.2 验证

- 单元 818 passed / 1 skipped；API 回归 105 passed（`test_policy_qa_routes` + `policy_workbench_api` + `policy_qa_verification_api`）。
- 生产调用方核对：`policy_qa_routes` 与 `policy_strategy` 均带结算单号或维度进入，不受影响；空 settlement_context 走 Composer 时现在安全地得到空证据而非泛化规则。

### 9.3 真实语料复测（加固后，干净复跑）

| 基线 | P@3 | Recall | FAR | Complete | 诚实拒答 |
|------|-----|--------|-----|----------|----------|
| current_hybrid | 0.026 | 0.684 | 0.132 | 0.632 | **1.000** |
| enhanced_hybrid | 0.031 | 0.697 | 0.127 | 0.632 | **1.000** |
| broad_hybrid | 0.088 | 0.555 | 0.491 | 0.382 | 0.604 |

- structured 负例误答 **0/48**（此前 6/48，全部是空 ctx BROAD_* 用例召回同 3 条门诊规则）；负例子集 FAR 12.5% → **0%**，诚实拒答 87.5% → **100%**。Recall 0.605→0.684 系 6 条负例从误召转为诚实拒答（空召回的负例 recall 计 1.0），非正例召回提升。
- 正向 28 条均带非空 ctx，P@3（0.083）、Recall 不受影响；BROAD_CAP / BROAD_OUTPATIENT 两条空 ctx 正向映射用例转为拒答，其基线值本就为 0（未命中期望），无指标损失。

### 9.4 合成模式新基线

text_only 对照逐位一致（0.132/0.448/0.713）；structured 两组 FAR 下降（current 0.839→0.707、enhanced 0.816→0.684，合成 BROAD_* 负例同样被空 ctx 拒答拦截）；broad 不变（0.247/0.615/0.667）。上述为拒答加固后的**新预期基线**，后续 synthetic 回归以本节为准。

### 9.5 门禁进展（加固后）

| 门禁 | 目标 | structured | broad | 判定 |
|------|------|-----------|-------|------|
| FAR（负例子集） | < 8% | **0% 达标** | 39.6% | structured 达，broad 未达 |
| 诚实拒答率 | > 80% | **100% 达标** | 60.4% | structured 达，broad 未达 |
| P@3 | > 90% | 8.3%（射程内 16.7%） | 23.8% | **均未达** |

structured 三项已过两项；**门禁整体保持关闭**——broad 路径 FAR/诚实拒答与双路径 P@3 未变。剩余工作即 §8.6 的 ③（plan_queries 射程泛化或 eval 按生产路由分流）与 ④（doc_7173172eb649 冲突比例规则数据治理），以及 broad 有效期硬过滤（原 §8.6 ①）。

[来源：scripts/eval/issue33_real_baseline_result.json 加固后逐案实测；合成模式 stdout]
