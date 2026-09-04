# issue-33 §8.6 加固②：broad 有效期 / publish_status 硬过滤

背景：加固①(structured 空 ctx 拒答) 已完成推送（b0b7b26/d0fd4b4/e9f6b02）。structured 负例误答清零，但 broad 侧 FAR 仍在 39.6% 高位——报告将 broad 的 19 条负例分为四类，其中「无有效期/版本硬过滤(5)」与「住院通用规则空值保留(6)」是 broad FAR 最主要贡献。本次做版本/有效期硬过滤这组最大杠杆。

根因（broad 把已失效或无版本约束的政策语料当成可答）：broad_retriever 命中后未对 语料的 effective_date/expiry_date/publish_status/policy_version/适用对象 做硬排除，导致过期/失效/不适用段被检索为答案源，触发负例误答（报告 §8.4 broad 分类）。

目标行为：
1. 过期段（expiry 已过 / effective 未到 / publish_status=失效 或 未发布）在 broad 检索出口一律硬排除，命中即丢弃，不进入候选更不进入回答上下文。
2. 「住院通用规则空值保留」类：确认是"无该 key 或空值"的字段在过滤时不误杀可答通用规则，仅排"明确失效/过期/版本不符"，不排"字段缺省"。若 5 条版本类全由此解决即达标，先不动住院空值那组（属加固③候选，避免一次改动面过大）。
3. structured 已有 release resolver（feat f478416/6ac3355 读路径统一接入 release resolver），broad 侧需对齐同一有效期语义，避免结构侧硬、broad 侧软的不一致——两 reading path 用同一版本/有效期判定函数（复用一个 helper，不各自实现；若 resolver 不适用 broad 场景就抽公共 helper 落到 shared 层）。
4. gate 判定只认三项全过（诚实拒答率>80% / FAR<8% / P@3>90%）；本次至少应显著压低 broad FAR，目标到可接受量级再谈 P@3 是否有射程分流问题。

验收：
- broad 负例子集复测：FAR 显著低于现在的 39.6%，具体数字由你在真实语料 eval(82 条用例脚本 scripts/eval/issue33_*)上跑出并列 diff（对比 bb2ea67 基线）。
- 不影响 structured 已达标项（FAR 0% / 拒答 100% 不回退）。
- 正例 recall 不回退；新增防再过期的单测（有效期边界/status 边界 各 ≥2 条断言，含 sec-前后一年/精确当天逻辑）。
- 只动读路径 + 共享有效期 helper，不改存量数据结构；改动尽量小。
- 落档：更新 issue #33 需求迭代记录 + PROGRESS.md + §9 下一节；按 Angular 规范 commit，message 前缀带【加固②broad有效期/status硬过滤】。

完成后回报：改动文件、新增断言数、real-corpus eval 三项门禁数字与 bb2ea67 基线 diff、是否已接近/达成 FAR<8%。门禁口令不变（三项全过才复测放行），本次达标与否只认数据。
