# Issue #65 Phase 4：Governed Flow View 性能基线

**日期**：2026-09-07
**范围**：已发布 `v_flow_flow_op_outpatient_processed` 的只读查询热路径

## 测量方法

测试文件：`src/tests/performance/test_governed_flow_view.py`

- 复用生产读取 seam `PostgresFlowViewReader.read()`，不绕过视图直接查表；
- 顺序热连接 30 次，记录 P50/P95；
- 10 个独立 PostgreSQL 连接并发，每个连接 5 次，共 50 次；
- 排除首次连接建立时间，只测查询热路径；
- 只读接口阈值沿用 `src/tests/performance/config.py`：P95 ≤ 300ms；
- PostgreSQL 或目标 View 不可用时测试跳过，不伪造性能结论。

## 结果

| 场景 | 样本 | P50 | P95 | 结果 |
|---|---:|---:|---:|---|
| 顺序热连接 | 30 | 1.82ms | 2.91ms | 通过 |
| 10 并发独立连接 | 50 | 2.81ms | 4.30ms | 通过 |

执行命令：

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/performance/test_governed_flow_view.py -q -s
```

## Phase 4 决策

当前不增加物化表、调度器、缓存或异步运行层。理由：

1. 当前顺序和 10 并发 P95 均显著低于 300ms，只读 View 没有已证实的性能瓶颈；
2. 当前生产测试快照只有 1 行，结果仅作为小规模基线，不能外推到大规模数据；
3. 物化、调度和缓存会新增刷新一致性、失效、权限和审计边界，当前没有足够测量证据支撑这些复杂度。

## 后续触发条件

在接入代表性生产规模数据后重新执行同一基准；只有顺序或目标并发 P95 超过 300ms，或出现明确的数据库资源瓶颈，才进入物化/调度/缓存方案评估。届时必须同时测量刷新延迟、发布版本一致性、缓存失效和回滚行为。

