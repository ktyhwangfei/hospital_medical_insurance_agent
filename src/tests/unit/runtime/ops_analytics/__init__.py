"""#40 P3 受控问数与运营指导 — 验收测试。

对应冻结验收（docs/superpowers/plans/2026-08-27-outpatient-p0-data-contract.md Task 5）：
1. 指标查询与下钻：六指标口径与口径句 v4 一致，下钻到就诊行级并携带指标批次。
2. 就诊人次保持 unavailable（HIS 关联是 P1 必需输入，禁止跨源临时 JOIN）。
3. 周报摘要每条结论可溯源到指标批次（metric_batch 引用）。
"""
