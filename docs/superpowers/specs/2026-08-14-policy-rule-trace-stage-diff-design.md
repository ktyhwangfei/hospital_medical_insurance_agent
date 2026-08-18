# 政策规则编译溯源逐阶段数据变化展示设计

> 日期：2026-08-14  
> 状态：已确认并实施  
> 范围：规则审核页中的 `RuleTraceDrawer` 视觉与交互重构

## 1. 背景与结论

现有规则编译链已经保存不可变输入、LLM 输出、每个确定性编译步骤的输入输出、问题、耗时、发布血缘和历史运行。后端采用确定性 Compiler、人工审核门禁和 fail-closed，整体设计合理，应继续保留。

当前问题位于 Portal 展示层：抽屉把所有内容渲染为纵向折叠 JSON。用户需要逐块展开并自行比较，无法快速回答：

1. 当前规则执行到了哪个阶段；
2. 本阶段实际改变了什么数据；
3. 哪些值是新增、修改、删除或计算推导；
4. 哪个变化导致 REVIEW/FAIL；
5. 下一步需要查看或处理什么。

本轮将抽屉改为“横向阶段轨道 + 当前阶段输入/输出对照 + 变化高亮”。不改变编译、存储、API、审核或发布行为。

## 2. 目标与非目标

### 2.1 目标

- 横向展示完整编译管线及每阶段真实状态、耗时和变化摘要。
- 点击阶段后直接比较该阶段输入和输出。
- 默认只展示变化，保留查看全部字段和完整 JSON 的能力。
- 对不同阶段使用符合业务语义的变化展示，避免误导。
- REVIEW/FAIL 能快速定位到错误码、相关事实/规则和建议动作。
- 使用现有 Trace API 完成，不重新计算规则，不伪造缺失数据。

### 2.2 非目标

- 不修改 `PolicyRuleCompiler` 或编译状态机。
- 不新增 Trace API、数据库字段或后端聚合接口。
- 不改治理概览页的阶段导航。
- 不建设 DAG 编辑器、通用 JSON Diff 平台或独立溯源门户。
- 不新增前端依赖。

## 3. 总体信息架构

抽屉继续复用现有 Dialog，宽度扩大至约 `96vw`，内部从上到下分为四层：

1. **运行摘要**：rule_id、规则版本、DIRECT/DERIVED、运行状态、编译器版本、发布时间。
2. **横向阶段轨道**：阶段状态、耗时、变化数量和未执行状态。
3. **阶段工作区**：输入、变化摘要、输出，以及字段级变化明细。
4. **辅助操作**：原文证据、完整 JSON、历史运行、上一处/下一处变化。

阶段切换只使用首次加载的 `RuleCompilationTrace`，不重复请求 API。

### 3.1 默认阶段

- 存在 REVIEW/FAIL 时，默认选中第一个异常阶段。
- 全部通过时，默认选中最后一个有变化的阶段。
- 没有变化时，选中最后一个实际执行阶段。
- `LEGACY_IMPORT` 使用单阶段历史导入模式。

### 3.2 阶段缺失

正常管线使用固定顺序：

```text
INPUT_SNAPSHOT → LLM_EXTRACTION → CANONICALIZE → COMPOSE
→ RESOLVE → DERIVE → VALIDATE → PUBLISH
```

若执行在中途结束，后续阶段显示“未执行”，不得显示成功或推测数据。接口返回未知阶段时，追加在实际步骤末尾并使用通用只读视图。

## 4. 各阶段展示口径

| 阶段 | 输入 | 输出/产物 | 变化表达 |
|---|---|---|---|
| INPUT_SNAPSHOT | 文档、单元、原文 | 不可变输入快照 | 审计基线，不计变化 |
| LLM_EXTRACTION | 原文快照 | 提取字段、事实、规则、置信度、证据 | 新提取字段、缺失项、未知项 |
| CANONICALIZE | PolicyFact 列表 | 规范化 PolicyFact | 按 fact_id 对齐字段；比例/金额等显示修改；非法事实显示过滤和 Issue |
| COMPOSE | 规范化事实 | Direct CanonicalRule + Relation | 规则生成、事实聚合、证据合并、冲突未产出 |
| RESOLVE | Direct Rule + Relation | 关系到基础规则的绑定 | 唯一绑定或 NOT_FOUND/AMBIGUOUS/CONFLICT |
| DERIVE | 已消解关系 | Derived CanonicalRule | 公式、基础值、计算结果、dependencies、合并证据 |
| VALIDATE | CanonicalRule 列表 | ValidationIssue | 通过项和问题项；关联已有 fact_id/rule_id，不猜测不存在的字段路径 |
| PUBLISH | release_id + rule_ids | facts/rules collection + lineage | 发布产物和血缘；未执行时显示阻断来源 |
| LEGACY_IMPORT | 历史规则快照 | 可用历史信息 | 明确中间历史缺失，不伪造步骤 |

## 5. 变化模型

### 5.1 视觉语义

| 类型 | 颜色 | 辅助标识 | 含义 |
|---|---|---|---|
| 新增 | 绿色 | `+` | 新提取字段、新规则、新依赖、新血缘 |
| 修改 | 黄色 | `~` | 同一业务字段的值或类型发生变化 |
| 删除/阻断 | 红色 | `−` / 错误图标 | 字段或事实被过滤，或阶段无法继续 |
| 计算推导 | 紫色 | `ƒ` | 由公式和基础规则确定性生成的值 |

颜色不能作为唯一识别方式，必须同时显示符号和文字。

### 5.2 对齐规则

相同结构的对象按以下稳定标识优先对齐：

```text
fact_id → rule_id → issue_id → 对象键 → 数组位置
```

只有缺少稳定标识时才使用数组位置。Diff 只比较 API 已返回的数据，不执行领域计算。

### 5.3 结构转换

阶段输入和输出不是同一对象类型时，不使用通用“删除全部输入、增加全部输出”的结果。使用阶段语义：

- COMPOSE 显示“事实生成规则/关系”；
- RESOLVE 显示“关系绑定基础规则”；
- DERIVE 显示“基础值 + 公式生成派生规则”；
- VALIDATE 显示“规则产生校验结论”；
- PUBLISH 显示“规则生成发布产物与血缘”。

无法识别的 payload 才降级到通用 JSON Diff，并明确标记“通用视图”。

## 6. 交互设计

- 阶段轨道固定在抽屉顶部；点击阶段只切换当前工作区。
- 默认开启“只看变化”，可切换“全部字段”“语义视图”“JSON Diff”。
- 支持按新增、修改、删除、推导、问题筛选。
- “上一处变化/下一处变化”在当前阶段内移动，越界后进入相邻阶段。
- 输入和输出独立滚动；嵌套字段按顶层业务字段分组折叠。
- 未变化字段折叠为“另有 N 个字段未变化”。
- 问题卡显示 severity、code、message、recommended_action 及关联 fact/rule。
- 完整 JSON 和历史运行保留为次级入口。

## 7. 响应式与可访问性

- 桌面端为输入/变化摘要/输出三栏。
- 窄屏保留横向阶段滚动，输入和输出改为上下排列。
- 阶段轨道使用 `tablist/tab` 语义及 `aria-selected`。
- 支持键盘左右切换阶段，Enter/Space 激活。
- 状态和变化类型同时使用文字、图标和颜色。
- 长值可换行并提供完整值查看，不通过横向溢出隐藏关键信息。

## 8. 加载、失败与降级

- 沿用现有懒加载、错误提示和重试。
- 切换 rule_id/run_id 时立即清空上一运行内容，避免证据串线。
- 空 payload 显示“本阶段没有可展示的数据变化”。
- 失败步骤优先展示 error 和 issues；后续阶段显示“未执行”。
- 未识别的对象结构使用通用 JSON Diff；通用 Diff 失败时退回现有 JSON Block。
- `LEGACY_IMPORT` 只展示可用快照和缺失说明。

## 9. 实施范围

### 9.1 代码

- 修改 `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`。
- 在同一文件内保留最小阶段注册表、数据归一化和递归 Diff 工具，避免为单一组件创建公共框架。
- 复用现有 Dialog、Tailwind 和 Lucide，不安装依赖。

### 9.2 测试

- 更新 `src/apps/portal/src/tests/policy-knowledge/rule-trace-drawer.test.tsx`。
- 只覆盖本次行为：阶段排序、默认选中、变化高亮、问题展示、未执行阶段、未知 payload 降级、切换运行不串线。
- 不扩大全仓测试范围。

## 10. 验证顺序

按项目要求串行执行已有相关验证：

1. 编译器聚焦单元测试；
2. Trace API 聚焦测试；
3. 编译发布聚焦 Flow 测试；
4. 溯源抽屉 Vitest；
5. `npx tsc --noEmit`；
6. `npm run build`。

前一步失败时先处理失败，不继续声称完成。

## 11. 验收标准

1. 用户打开任一规则的溯源抽屉，可横向查看所有实际或未执行阶段。
2. 每个实际阶段展示真实输入、输出、状态、耗时和问题。
3. 数据变化按新增、修改、删除/阻断、计算推导明确高亮。
4. 默认只看变化，用户可以查看全部字段和完整 JSON。
5. REVIEW/FAIL 默认聚焦，并能看到稳定错误码和建议动作。
6. 失败后下游阶段不显示伪造结果；LEGACY_IMPORT 不伪造历史。
7. 不新增后端接口，不重新计算业务结果，不影响审核发布链路。

## 12. 设计依据

- `docs/superpowers/specs/2026-08-11-policy-rule-compiler-trace-design.md`
- `src/knowledge_extension/rule_explanation/policy_compiler/compiler.py`
- `src/knowledge_extension/rule_explanation/policy_compiler/service.py`
- `src/knowledge_extension/rule_explanation/release_index.py`
- `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`
