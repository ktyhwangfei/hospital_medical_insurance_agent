# 政策提取单元去重设计（修订版）

> 状态：已实施（2026-08-25；验证记录见 §4.4 备注）
> 日期：2026-08-25
> 背景：语义发现检测器修复（issue-20）后，跨单元一致性检测归零；复盘确认其诱因是
> `policy_extractions` 活跃重复行。本设计在管线源头消除重复。

## 1. 问题（全部来自真实库 SQL，可复现）

**现象**：同 `doc_id + source_text_hash` 多行并存，其中 13 组为「一行 unit_id=NULL + 一行/多行带 unit」且 **13/13 组 NULL 行先建**（created 07-29，首轮提取未切单元；带 unit 行建于 08-12 之后重跑）。

典型组（doc_466953309ccf / hash 6c9107）：

```
ext_e92087cc4ab3  unit=NULL           reviewed  created 07-29
ext_076b4982f900  unit=n_Y31KNbERfkqa reviewed  created 08-19   ← 同一原文，两行活跃
```

影响：语义发现六类检测器把「同原文、两行提取」当作跨单元字段不一致（已加跨文档门限兜底，见 `bf8b409`）；知识构建、统计口径同样被双份行污染。另有 22 条「示例提取结果（dummy 模式）」archived 脏数据，仅污染统计，不在本设计范围内处理（附清理脚本）。

## 2. 根因（已证实）

两套写入路径的去重 SELECT 均按 `doc_id + unit_id + source_text_hash`（带 unit 时）匹配：

```sql
SELECT extraction_id FROM policy_extractions
WHERE doc_id=%s AND unit_id=%s AND source_text_hash=%s   -- unit_id=%s 对 NULL 永远失配
```

[来源: pipeline_store.py `batch_create_extractions` / `reconcile_extractions`]

时序：首轮写入 unit=NULL 行 → 重跑切出 unit → `unit_id='n_xxx'` 查重失配 → INSERT 新行 → 旧行留存，两行活跃。三个叠加缺陷：

1. **unit_id 漂移**：重跑切句边界变化，同一原文的 unit 变化后查重失效；
2. **NULL 不相等**：SQL `=` 对 NULL 恒 false，首轮 NULL 行永远匹配不上；
3. **SELECT 不滤 archived**：理论上存在「命中 archived 行 → UPDATE 复活为 draft」路径
   （batch_create 的 UPDATE 分支强制 `status='draft'`）——[推断] 代码路径存在，
   但当前库中未观察到由它产生的重复（13 组全部为漂移型），不作为主因。

## 3. 设计目标

1. 同一文档同一原文至多一行**活跃**记录，unit 漂移时更新原行而非插新行；
2. 保留「同一原文在同一文档两个不同单元合法出现」的能力（模板句/ boilerplate）；
3. archived 历史行不可被复活；
4. 存量 13 组漂移重复一次性收敛，迁移幂等可回滚。

## 4. 方案

### 4.1 应用层修复（主修复，两处同改）

`batch_create_extractions` 与 `reconcile_extractions` 的查重 SELECT 统一改为：

```sql
SELECT extraction_id FROM policy_extractions
WHERE doc_id=%s AND source_text_hash=%s AND status <> 'archived'
  AND (unit_id = %s OR unit_id IS NULL OR %s IS NULL)
ORDER BY (unit_id = %s) DESC   -- 精确 unit 命中优先，其次 NULL 行（漂移承接）
LIMIT 1
```

- 新行带 unit、旧行为 NULL → 命中旧行，UPDATE 承接（unit 从 NULL 补为实值）；
- 新行 unit 与旧行相同 → 精确命中，现状行为；
- 新行 unit 为 NULL、旧行带 unit → 命中旧行；UPDATE 处加 `unit_id=COALESCE(%s, unit_id)` 防 unit 倒退回 NULL（初稿漏掉的倒退 bug）；
- 新行 unit 与旧行不同且均非 NULL → 视为合法跨单元同文，INSERT 新行（§3.2 保留能力）。

### 4.2 数据库兜底（部分唯一索引，表达式索引）

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_ext_active_doc_unit_text
    ON policy_extractions (doc_id, COALESCE(unit_id, ''), source_text_hash)
    WHERE status <> 'archived';
```

- 防同 doc + 同 unit + 同原文的活跃双行（应用层查重漏网/并发时的硬约束）；
- NULL 归一为 '' 后纳入约束（普通 UNIQUE 对 NULL 视为互异，挡不住 NULL 重复）；
- 跨 unit 同文不被约束（§3.2）。

> ponytail: 不采用初稿的 `(doc_id, source_text_hash)` 裸索引——它会误杀
> 「同文档两个单元合法同文」，见 §7。

### 4.3 存量迁移（一次性，幂等）

对 13 组漂移重复，规则：**保留带 unit 的行，NULL 行置 archived**（带 unit 行是后续
重跑产物，单元信息完整；NULL 行内容相同，无信息损失，archived 保留可追溯）。
组内若有多行带 unit 且互不相同，保留 updated_at 最新者，其余置 archived。

配套 `scripts/purge_dummy_extractions.py`（按 `source_text LIKE '示例提取结果%' AND
status='archived'` 清理，运维手动执行）。

### 4.4 验证矩阵

| 项 | 方式 |
|---|---|
| 漂移承接 | 单测：先写 unit=NULL 行，再写同 doc+hash+unit 行 → 同一 extraction_id，无新行 |
| unit 不倒退 | 单测：旧行带 unit，新行 unit=None → unit 保持原值 |
| archived 不复活 | 单测：仅 archived 行存在时，写入走 INSERT 新行，archived 行不变 |
| 跨单元同文保留 | 单测：同 doc+hash 两个不同 unit → 两行并存 |
| 索引兜底 | 单测：绕过应用层直接双 INSERT 同 doc+unit+hash 活跃行 → UniqueViolation |
| 存量清零 | 迁移后 SQL：`GROUP BY doc_id, source_text_hash HAVING count(*) FILTER (WHERE status<>'archived') > 1` 返回 0 行 |
| 检测器侧 | PDSC 重扫，cross_unit_inconsistency 保持 0 |

## 5. 并发与事务

[来源: pipeline_store.py `reconcile_extractions`] 单文档写入已有
`pg_advisory_xact_lock(doc_id)` + `extraction_run_token` 幂等门，单文档并发已串行化。
索引冲突仅在跨路径（batch_create 与 reconcile 交错）时可能暴露，抛错由调用方重试即可，
提取是幂等重跑场景。初稿「不做应用层锁」的表述与代码事实不符，作废。

## 6. 非目标

- 不做「同文档同原文跨单元去重合并」（合法场景，见 §4.1）；
- 不清理 dummy archived 脏数据入主流程（独立运维脚本）；
- 不改提取切句逻辑本身（unit 漂移是上游切句的自然结果，本设计只保证承接正确）；
- 不建迁移日志表（迁移仅单向置 archived，回滚脚本按同样分组规则逆向恢复）。

## 7. 初稿勘误（为什么重写）

初稿（commit 616326a 前）存在三处错误，均已在本版修正：

1. **根因错误**：初稿断言主因为「batch_create 把 archived 行复活」，并将复活机制
   当已发生事实陈述。核实 13 组重复时间线：全部为「NULL 行先建（07-29）+ 带 unit 行
   后建（08 月）」的漂移型，复活型为 0 组。复活路径在代码上存在，降级为潜在风险（§2.3）。
2. **方案过度**：初稿裸 `(doc_id, source_text_hash)` 部分唯一索引会误杀「同文档两单元
   合法同文」（模板句），且未论证为何跳过应用层一行修复的最小方案。
3. **并发叙述错误**：初稿称「不做应用层锁」，而 `reconcile_extractions` 已有
   advisory lock + run_token（§5）。

## 8. 实施清单

- [x] `pipeline_store.py`：`_find_active_duplicate` 统一查重（两路径共用）+ `COALESCE` 防 unit 倒退
- [x] `_SCHEMA` 增表达式部分唯一索引（CREATE 幂等）
- [x] `scripts/migrate_dedup_extractions.py`（幂等+dry-run+rollback）+ `scripts/purge_dummy_extractions.py`
- [x] §4.4 单测 6 项（test_extraction_unit_dedup.py）+ 真实库 SQL 断言（活跃重复组 0）+ 索引兜底实测（UniqueViolation）
- [x] 需求迭代记录登记

**实施备注**：真实库迁移归档 9 行（保留行全部带 unit）；单测 6 passed；相关回归 41 passed
（trace_store 3 失败与 duplicate_unit_fix 1 失败为工作区预存：前者 HEAD 亦失败，后者依赖
另一 worktree 的 8135 活服务）。dummy 清理脚本待运维执行。
