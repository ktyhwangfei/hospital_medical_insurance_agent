# Pull Request 模板

> 本模板根据 `docs/governance/AI-CHANGE-EVIDENCE-TEMPLATE.md` 精简，适用于日常 PR。
> 完整证据包模板（8 章节）见 `docs/governance/AI-CHANGE-EVIDENCE-TEMPLATE.md`，R3/R4 改动必须使用完整版。

---

## 变更概览

<!-- 勾选一个 -->
- [ ] 🟢 R1 绿区（skills/、docs/ 等低风险区域）
- [ ] 🟡 R2 黄区（observability/、apps/ 前端等）
- [ ] 🟠 R3 橙区（runtime/、model_service/、knowledge_extension/、adapters/ 等核心链路）
- [ ] 🔴 R4 红区（domain/、storage/、security/、schemas/ 等关键边界）

> 风险等级定义参考：`docs/governance/AI-CODING-MODULE-BOUNDARIES.md` §4

**涉及目录**：
```
<!-- 列出变更的文件路径或目录 -->
```

---

## 验证证据

<!-- R1：仅需单元测试。R2+：必须提供测试证据。 -->

| 测试层级 | 执行命令 | 结果 |
|----------|---------|------|
| 单元测试 | `python -m pytest src/tests/unit/<模块> -v` | ✅ / ❌ / 未运行 |
| API 测试 | `python -m pytest src/tests/integration/api/<文件> -v` | ✅ / ❌ / 未运行 |
| Flow 测试 | `python -m pytest src/tests/integration/flow -v -k "<关键词>"` | ✅ / ❌ / 未运行 |

> 若某层级未执行，必须说明原因：`<!-- 例：仅修改前端展示，不涉及后端流程 -->`

---

## 异常分支

<!-- 列出已覆盖的异常路径。若无，说明为什么不需要。 -->
- [ ] 已覆盖异常路径（见下方说明）
- [ ] 不涉及异常路径（原因：<!-- 填写 -->）

```
<!-- 已覆盖的异常路径及对应测试 -->
```

---

## 可观测性

<!-- 勾选是否有变化 -->
- [ ] 新增/修改日志
- [ ] 新增/修改审计
- [ ] 新增/修改指标
- [ ] 新增/修改追踪
- [ ] 无变化（原因：<!-- 填写 -->）

---

## 一票否决自检

<!-- 逐项确认。任一项为"是"则本 PR 不得合并。 -->

| 否决条件 | 是否触发 |
|----------|----------|
| 修改红区但无人工先行设计说明 | 否 |
| 引入跨层调用，绕开统一入口 | 否 |
| 涉及高风险动作但未进入人工确认链路 | 否 |
| 没有异常分支测试且无合理豁免 | 否 |
| 缺失来源引用、脱敏或权限边界 | 否 |

---

## 回滚说明

```
<!-- 如果本 PR 上线后出问题，怎么回滚？影响范围多大？ -->
```
