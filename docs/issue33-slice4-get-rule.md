# issue-33 派工：slice④ get_rule 只读句柄（收口 #60）

来源：#60 slice④ —— 语义 registry 做 rule_ref 同库只读存在性校验，需要知识侧暴露 get_rule 只读句柄。

## 背景
- #60 政策承载规格：policy_rule_ref 绑 zcgz 结构化提取行的实体主键
- 语义 registry 发布门禁需要校验 "rule_ref 指向的 zcgz 实体是否存在"
- 知识侧已有 CachedRuleStorage.get_rule(rule_id) 只读能力（data_platform/storage/rule/）
- 需要暴露一个稳定的只读句柄供 semantic registry 调用

## 实现要求
1. **只读**：暴露的句柄只能查询规则存在性，不能写/改/删
2. **接口稳定**：函数签名清晰，返回 dict 或 None（保持与 CachedRuleStorage.get_rule 一致）
3. **复用现有存储**：不新建数据源，复用 data_platform/storage/rule/ 的 CachedRuleStorage 或 postgres 实现
4. **对齐 #60 接口**：与 #60 的 policy_carrier rule_ref 校验逻辑对接

## 验收
- 新增/暴露的只读函数可被 semantic registry 导入并调用
- 测试：传入存在的 rule_id 返回规则 dict，传入不存在的返回 None
- 不回退 #33 路由 T1/T2（3bbd16d）和前端门修复（3f29223 在 issue-33-frontend-anchor-passthrough 分支）
- commit 前缀【slice④】

## 参考
- 知识侧规则存储：src/data_platform/storage/rule/（cached.py / postgres.py 都有 get_rule）
- #60 的 rule_ref 校验：src/semantic_layer/ 或 src/semantic_registry/ 的发布门禁逻辑
- 工作区：C:/Users/于金宝/orca/workspaces/hospital_medical_insurance_agent/issue-33

完成后回报：暴露的函数路径、测试用例、commit hash。
