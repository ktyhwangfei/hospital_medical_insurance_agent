# 政策字段数据库证据增强实施计划

> **执行要求：** 使用 `superpowers:executing-plans` 按本计划逐项实施；测试遵循 `superpowers:test-driven-development`，完成前使用 `superpowers:verification-before-completion`。

**目标：** 当政策结构化提案出现“机构类别”“基金归属”等新维度时，利用最新 bjyb 发现扫描的字段语义和值域统计生成可审核证据，并在统一语义提案页面展示采纳与排除理由。

**边界：** 本次只实现页面可验收的最小闭环；不新增数据表、不改变提案持久化、不自动发布字段、不迁移 Milvus collection schema。

## Task 1：锁定字段语义判断

- [x] 在 `src/tests/unit/knowledge_extension/test_semantic_alignment.py` 增加一个聚焦测试：机构类别应推荐 `m_institution.H_TYPE` 并排除 `H_LEVEL`；基金归属应推荐基金款项字段并排除描述为险种类型的 `FUND_TYPE`。
- [x] 运行该测试，确认因数据库证据匹配函数尚不存在而失败。
- [x] 在 `src/knowledge_extension/rule_explanation/semantic_alignment.py` 扩展 `DiscoveryEvidence`，并实现最小确定性匹配函数：语义角色优先、统计信息佐证、明确排除相邻语义轴、低基数样例限量输出。
- [x] 重跑单元测试至通过。

## Task 2：把数据库证据接入统一提案 API

- [x] 在 `src/tests/integration/api/test_semantic_alignment_api.py` 增加一个 API 测试，注入最新 discovery 字段，断言维度提案响应包含 database 证据和 rejected 候选。
- [x] 运行该测试，确认失败。
- [x] 在 `src/runtime/api/semantic_alignment_routes.py` 复用最新 DiscoveryStore 扫描结果，在列表/详情只读响应上追加证据；数据库不可用时返回原提案，不阻断政策审核。
- [x] 同步脱敏新增证据的描述、样例和理由，重跑 API 测试至通过。

## Task 3：页面展示证据与排除理由

- [x] 在 `src/apps/portal/src/tests/semantic-proposals.test.tsx` 增加一个页面测试，断言展开基金归属提案后显示“bjyb 数据证据”、候选字段、值域统计和“险种类型不是基金归属”的排除理由。
- [x] 运行该 Vitest，确认失败。
- [x] 在 `src/apps/portal/src/lib/policy-knowledge-api.ts` 补齐证据类型；在 `src/apps/portal/app/semantic-layer/proposals/page.tsx` 对政策证据与数据库证据分组展示。
- [x] 重跑页面测试至通过。

## Task 4：聚焦验证与页面交付

- [x] 按顺序运行新增单元测试、API 测试、Portal Vitest。
- [x] 运行 Portal TypeScript 检查，确认本次字段契约无新增错误。
- [x] 使用 `..\ws.ps1 restart issue-20` 刷新当前工作区服务，再用 `..\ws.ps1 list` 确认 8126/3126 健康，交给用户页面验证。
- [x] 更新 `PROGRESS.md` 和需求迭代记录，只记录本次聚焦验证证据与明确未做边界。
