window.slideDataMap.set(7, `
  <div class="w-[1440px] h-[810px] shadow-2xl relative overflow-hidden slide-bg">
    <div class="absolute top-0 left-0 w-full h-[112px] px-16 flex flex-col justify-center">
      <div class="flex items-center gap-3">
        <div class="w-1.5 h-9 bg-accent-1 rounded"></div>
        <span class="text-sm font-semibold tracking-[0.2em] text-neutral uppercase font-body">五、技术架构与核心能力 · ARCHITECTURE</span>
      </div>
      <h1 class="text-[38px] font-bold text-primary font-title mt-1">构建"可解释、可溯源、可回滚"的技术底座，以工程纪律筑牢可信</h1>
    </div>

    <div class="absolute top-[126px] left-16 right-16">
      <div class="text-[13px] font-semibold tracking-widest text-primary mb-2 font-body">四层技术架构体系</div>
      <div class="flex items-stretch gap-2">
        <div class="flex-1 rounded-xl px-4 py-2.5 text-center bg-white shadow-sm border-t-4 border-primary"><div class="text-[15px] font-bold text-primary font-title">SaaS 应用产品层</div><div class="text-[12px] text-neutral/70 font-body">统一门户 / 嵌入式组件</div></div>
        <div class="flex items-center text-2xl text-neutral/40">›</div>
        <div class="flex-1 rounded-xl px-4 py-2.5 text-center bg-white shadow-sm border-t-4 border-accent-1"><div class="text-[15px] font-bold text-primary font-title">PaaS 平台支撑层</div><div class="text-[12px] text-neutral/70 font-body">七类服务域（核心）</div></div>
        <div class="flex items-center text-2xl text-neutral/40">›</div>
        <div class="flex-1 rounded-xl px-4 py-2.5 text-center bg-white shadow-sm border-t-4 border-accent-1"><div class="text-[15px] font-bold text-primary font-title">DaaS 数据与知识层</div><div class="text-[12px] text-neutral/70 font-body">结构化 / 向量 / 缓存</div></div>
        <div class="flex items-center text-2xl text-neutral/40">›</div>
        <div class="flex-1 rounded-xl px-4 py-2.5 text-center bg-white shadow-sm border-t-4 border-neutral"><div class="text-[15px] font-bold text-primary font-title">接入与基础设施层</div><div class="text-[12px] text-neutral/70 font-body">医保 / HIS / EMR 等</div></div>
      </div>
    </div>

    <div class="absolute top-[236px] left-16 right-16">
      <div class="text-[13px] font-semibold tracking-widest text-primary mb-2 font-body">PaaS 七类服务域</div>
      <div class="flex flex-wrap gap-2.5">
        <span class="px-4 py-2 rounded-full text-[14px] font-semibold font-body bg-[#E7F0F8] text-primary">接入安全</span>
        <span class="px-4 py-2 rounded-full text-[14px] font-semibold font-body bg-[#E6F6EF] text-accent-1">会话上下文</span>
        <span class="px-4 py-2 rounded-full text-[14px] font-semibold font-body bg-[#E7F0F8] text-primary">智能编排</span>
        <span class="px-4 py-2 rounded-full text-[14px] font-semibold font-body bg-[#E6F6EF] text-accent-1">模型服务</span>
        <span class="px-4 py-2 rounded-full text-[14px] font-semibold font-body bg-[#E7F0F8] text-primary">知识服务</span>
        <span class="px-4 py-2 rounded-full text-[14px] font-semibold font-body bg-[#E6F6EF] text-accent-1">业务适配</span>
        <span class="px-4 py-2 rounded-full text-[14px] font-semibold font-body bg-[#E7F0F8] text-primary">任务闭环</span>
      </div>
    </div>

    <div class="absolute top-[338px] left-16 right-16 rounded-xl px-6 py-3 bg-white shadow-sm border-l-4 border-accent-1 flex items-center gap-4">
      <span class="text-[14px] font-bold text-primary font-title shrink-0">主线突破</span>
      <span class="text-[15px] text-neutral font-body">政策知识管线"平行建新通路（*_v2 collection）→ 最后一把灰度切换（P10）"，<span class="font-semibold text-primary">生产零停摆、可随时回滚</span>；M1–M6 已达成，仅差 M7 价值兑现点。</span>
    </div>

    <div class="absolute top-[408px] left-16 right-16 bottom-[108px]">
      <div class="text-[13px] font-semibold tracking-widest text-primary mb-3 font-body">四条工程纪律（硬约束，经得起推敲）</div>
      <div class="grid grid-cols-4 gap-5 h-[300px]">
        <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col">
          <div class="w-10 h-10 rounded-xl bg-primary text-white flex items-center justify-center text-[20px] font-bold font-title mb-3">1</div>
          <div class="text-[16px] font-bold text-primary font-title mb-2">领域语言统一</div>
          <div class="text-[13.5px] text-neutral/80 font-body leading-relaxed">命名遵循通用语言字典，禁止同一概念多命名；新增概念同步字典。</div>
        </div>
        <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col">
          <div class="w-10 h-10 rounded-xl bg-primary text-white flex items-center justify-center text-[20px] font-bold font-title mb-3">2</div>
          <div class="text-[16px] font-bold text-primary font-title mb-2">解耦纪律</div>
          <div class="text-[13.5px] text-neutral/80 font-body leading-relaxed">业务逻辑严禁耦合外部系统接口，必须经 adapters 防腐层封装；替换真实系统只需实现 Protocol。</div>
        </div>
        <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col">
          <div class="w-10 h-10 rounded-xl bg-primary text-white flex items-center justify-center text-[20px] font-bold font-title mb-3">3</div>
          <div class="text-[16px] font-bold text-primary font-title mb-2">来源可追溯</div>
          <div class="text-[13.5px] text-neutral/80 font-body leading-relaxed">AI 输出必须携带 citations 或声明 uncertainties，禁止无来源的确定性结论。</div>
        </div>
        <div class="rounded-2xl bg-white shadow-sm p-5 flex flex-col">
          <div class="w-10 h-10 rounded-xl bg-primary text-white flex items-center justify-center text-[20px] font-bold font-title mb-3">4</div>
          <div class="text-[16px] font-bold text-primary font-title mb-2">高风险拦截</div>
          <div class="text-[13.5px] text-neutral/80 font-body leading-relaxed">涉及结算/病案修改/费用调整等高风险动作，必须拦截转人工确认，保留完整依据与审计。</div>
        </div>
      </div>
    </div>

    <div class="absolute bottom-[64px] left-16 right-16 rounded-xl px-6 py-3 bg-[#E6F6EF] border border-accent-1/30 flex items-center gap-3">
      <span class="text-[14px] font-bold text-accent-1 font-title">边界纪律</span>
      <span class="text-[14px] text-neutral font-body">不替代结算 / 事前审核 / DRG / 病案 / 费用调整；高风险动作一律拦截转人工确认；AI 输出必带 citations 或声明 uncertainties。</span>
    </div>

    <div class="absolute bottom-5 left-16 right-16 flex justify-between items-center text-xs text-neutral/70 font-body">
      <span>院端医保智能体系统 · 建设项目汇报</span><span>07 / 11</span>
    </div>
  </div>
`);
