window.slideDataMap.set(9, `
  <div class="w-[1440px] h-[810px] shadow-2xl relative overflow-hidden slide-bg">
    <div class="absolute top-0 left-0 w-full h-[112px] px-16 flex flex-col justify-center">
      <div class="flex items-center gap-3">
        <div class="w-1.5 h-9 bg-accent-1 rounded"></div>
        <span class="text-sm font-semibold tracking-[0.2em] text-neutral uppercase font-body">七、质量保障与风险管控 · QUALITY & RISK</span>
      </div>
      <h1 class="text-[38px] font-bold text-primary font-title mt-1">核心套件全绿运行，技术债透明披露，风险清单可审查可追溯</h1>
    </div>

    <div class="absolute top-[126px] left-16 right-16">
      <div class="text-[13px] font-semibold tracking-widest text-primary mb-2 font-body">已通过验证（全绿套件）</div>
      <div class="grid grid-cols-4 gap-5">
        <div class="rounded-2xl bg-white shadow-sm p-5 border-t-4 border-accent-1"><div class="text-[34px] font-bold text-accent-1 font-title leading-none">139</div><div class="text-[14px] text-neutral font-body mt-2 font-semibold">semantic_layer 单元</div><div class="text-[12px] text-neutral/60 font-body">passed</div></div>
        <div class="rounded-2xl bg-white shadow-sm p-5 border-t-4 border-accent-1"><div class="text-[34px] font-bold text-accent-1 font-title leading-none">142</div><div class="text-[14px] text-neutral font-body mt-2 font-semibold">rule_explanation 单元</div><div class="text-[12px] text-neutral/60 font-body">+ 流式，含 Milvus 真集</div></div>
        <div class="rounded-2xl bg-white shadow-sm p-5 border-t-4 border-accent-1"><div class="text-[34px] font-bold text-accent-1 font-title leading-none">3</div><div class="text-[14px] text-neutral font-body mt-2 font-semibold">提取契约 API</div><div class="text-[12px] text-neutral/60 font-body">passed</div></div>
        <div class="rounded-2xl bg-white shadow-sm p-5 border-t-4 border-accent-1"><div class="text-[30px] font-bold text-accent-1 font-title leading-none">0 ✗</div><div class="text-[14px] text-neutral font-body mt-2 font-semibold">前端 5 tab</div><div class="text-[12px] text-neutral/60 font-body">tsc 零错误 + dev 烟测</div></div>
      </div>
    </div>

    <div class="absolute top-[286px] left-16 right-16 rounded-xl px-6 py-3 bg-[#E6F6EF] border border-accent-1/30 flex items-center gap-3">
      <span class="text-[14px] font-bold text-accent-1 font-title">验证纪律</span>
      <span class="text-[14px] text-neutral font-body">单元 → API → Flow 三阶段，全过才算完成（风险等级 R1–R4 对应最低验证要求）。</span>
    </div>

    <div class="absolute top-[350px] left-16 right-16">
      <div class="text-[13px] font-semibold tracking-widest text-accent-2 mb-2 font-body">技术债透明披露（全量回归 ~56 failed，均为预存债务，非当前任务引入）</div>
      <div class="flex flex-wrap gap-2.5">
        <span class="px-4 py-2 rounded-full text-[13.5px] font-body bg-white shadow-sm text-neutral">端点迁移 404 <span class="font-bold text-accent-2">~46</span></span>
        <span class="px-4 py-2 rounded-full text-[13.5px] font-body bg-white shadow-sm text-neutral">skill_infra <span class="font-bold text-accent-2">33</span></span>
        <span class="px-4 py-2 rounded-full text-[13.5px] font-body bg-white shadow-sm text-neutral">error_code stub <span class="font-bold text-accent-2">4</span></span>
        <span class="px-4 py-2 rounded-full text-[13.5px] font-body bg-white shadow-sm text-neutral">data_platform <span class="font-bold text-accent-2">2</span></span>
        <span class="px-4 py-2 rounded-full text-[13.5px] font-body bg-white shadow-sm text-neutral">test_service <span class="font-bold text-accent-2">1</span></span>
      </div>
    </div>

    <div class="absolute top-[446px] left-16 right-16 bottom-[64px] grid grid-cols-2 grid-rows-2 gap-4">
      <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col border-l-4 border-accent-2">
        <div class="flex items-center gap-3 mb-2"><span class="w-8 h-8 rounded-lg bg-accent-2 text-white flex items-center justify-center text-[16px] font-bold font-title">1</span><span class="text-[16px] font-bold text-primary font-title">P8.4 重提取拉高填充率</span></div>
        <div class="space-y-1.5 text-[13.5px] font-body"><div class="flex gap-2"><span class="text-neutral/50 w-[52px] shrink-0">现状</span><span class="text-neutral">填充率 3/15，依赖 LLM 调用</span></div><div class="flex gap-2"><span class="text-accent-2 w-[52px] shrink-0 font-semibold">解锁</span><span class="text-neutral">配置 MODEL_API_KEY</span></div></div>
      </div>
      <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col border-l-4 border-primary">
        <div class="flex items-center gap-3 mb-2"><span class="w-8 h-8 rounded-lg bg-primary text-white flex items-center justify-center text-[16px] font-bold font-title">2</span><span class="text-[16px] font-bold text-primary font-title">P10 灰度切换（M7）</span></div>
        <div class="space-y-1.5 text-[13.5px] font-body"><div class="flex gap-2"><span class="text-neutral/50 w-[52px] shrink-0">现状</span><span class="text-neutral">M7 未开始，依赖 P8 完成</span></div><div class="flex gap-2"><span class="text-accent-1 w-[52px] shrink-0 font-semibold">解锁</span><span class="text-neutral">完成 P8.4 或跳过重提取直接切</span></div></div>
      </div>
      <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col border-l-4 border-accent-2">
        <div class="flex items-center gap-3 mb-2"><span class="w-8 h-8 rounded-lg bg-accent-2 text-white flex items-center justify-center text-[16px] font-bold font-title">3</span><span class="text-[16px] font-bold text-primary font-title">安全与审计（SSO/RBAC）</span></div>
        <div class="space-y-1.5 text-[13.5px] font-body"><div class="flex gap-2"><span class="text-neutral/50 w-[52px] shrink-0">现状</span><span class="text-neutral">待外部依赖，pending</span></div><div class="flex gap-2"><span class="text-accent-1 w-[52px] shrink-0 font-semibold">解锁</span><span class="text-neutral">获取医院 SSO 文档与账号体系</span></div></div>
      </div>
      <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col border-l-4 border-neutral">
        <div class="flex items-center gap-3 mb-2"><span class="w-8 h-8 rounded-lg bg-neutral text-white flex items-center justify-center text-[16px] font-bold font-title">4</span><span class="text-[16px] font-bold text-primary font-title">适配器真实接入</span></div>
        <div class="space-y-1.5 text-[13.5px] font-body"><div class="flex gap-2"><span class="text-neutral/50 w-[52px] shrink-0">现状</span><span class="text-neutral">当前内存实现，blocked</span></div><div class="flex gap-2"><span class="text-accent-1 w-[52px] shrink-0 font-semibold">解锁</span><span class="text-neutral">真实系统 API 文档 + 测试环境</span></div></div>
      </div>
    </div>

    <div class="absolute bottom-5 left-16 right-16 flex justify-between items-center text-xs text-neutral/70 font-body">
      <span>院端医保智能体系统 · 建设项目汇报</span><span>09 / 11</span>
    </div>
  </div>
`);
