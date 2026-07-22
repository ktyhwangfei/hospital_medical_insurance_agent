# Cognitive Infrastructure Specification
认知基础设施规范
防止业务跑偏

Version: 1.0

## 核心目标

本项目的目标不是生成代码。

本项目的目标是持续产出可上线的软件产品。

代码只是结果。

认知才是资产。

---

# 第一原则

## 产品质量来自认知质量

禁止以下认知：

* 页面完成 = 功能完成
* 接口返回 = 功能正确
* 测试通过 = 产品可上线

产品完成必须同时满足：

* 功能正确
* 业务正确
* 数据正确
* 解释正确

---

# 第二原则

## AI必须先理解，再实现

禁止直接进入编码阶段。

每个任务必须先完成：

### Intent Understanding

回答：

这个功能为什么存在？

### Business Understanding

回答：

解决什么业务问题？

### Data Understanding

回答：

依赖哪些数据？

### User Understanding

回答：

用户最终想获得什么？

完成以上四项后才能开始开发。

---

# 第三原则

## 认知交付与代码交付同等重要

禁止仅提交代码。

每次开发任务必须输出：

### What

修改了什么

### Why

为什么修改

### Impact

影响哪些功能

### Assumption

依赖哪些业务假设

### Risk

存在什么风险

如果无法解释以上内容：

视为未完成理解。

---

# 第四原则

## 优先沉淀推理模式

禁止只沉淀结果。

必须沉淀：

为什么得到结果。

---

示例：

错误沉淀：

统筹自付 = 4962.67

正确沉淀：

统筹自付解释模式：

Step1:
识别费用所属险种

Step2:
识别医院等级

Step3:
识别支付比例

Step4:
计算个人承担部分

Step5:
生成患者可理解解释

---

项目资产是推理过程。

不是最终数字。

---

# 第五原则

## 建立 Reasoning Pattern Library

目录：

/reasoning-patterns

每个业务能力必须形成推理模式。

例如：

费用解释模式

政策解释模式

指标溯源模式

异常分析模式

风险识别模式

案例归因模式

---

推理模式格式：

Name:

Business Goal:

Inputs:

Reasoning Steps:

Decision Points:

Output Format:

Common Errors:

Verification Method:

---

# 第六原则

## AI必须显式引用认知资产

开发前必须声明：

使用了哪些：

* Knowledge
* Decision
* Pattern

禁止凭空实现功能。

---

示例：

Knowledge:
统筹自付定义

Decision:
ADR-003

Pattern:
费用解释模式

---

# 第七原则

## 验收认知链而非结果

禁止只验收结果。

必须验收：

结果从何而来。

验收内容：

数据来源是否明确

推理步骤是否完整

业务逻辑是否成立

结论是否可解释

---

# 第八原则

## 人类负责决策

AI负责实现。

AI不得拥有：

业务定义权

指标定义权

架构决策权

发布决策权

以上事项必须人工确认。

---

# 第九原则

## 产品演化必须保持认知连续性

任何重构必须保证：

新成员能够理解：

为什么这样设计

为什么这样计算

为什么这样解释

如果无法理解：

视为产品质量下降。

---

# 第十原则

## 项目终极资产

本项目最终资产不是：

代码

页面

模型

Prompt

Agent

而是：

Reasoning Patterns

Business Knowledge

Architecture Decisions

Verification Cases

这些资产必须独立于任何模型存在。

模型可以替换。

认知资产不可丢失。

---

# Success Criteria

六个月后：

即使：

更换模型

更换开发工具

更换开发人员

系统仍然能够：

持续开发

持续验证

持续上线

并保持业务逻辑一致性。

这才视为项目成功。
