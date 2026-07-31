window.slideDataMap.set(10, `
  <div class="w-[1440px] h-[810px] shadow-2xl relative overflow-hidden slide-bg">
    <div class="absolute top-0 left-0 w-full h-[112px] px-16 flex flex-col justify-center">
      <div class="flex items-center gap-3">
        <div class="w-1.5 h-9 bg-accent-1 rounded"></div>
        <span class="text-sm font-semibold tracking-[0.2em] text-neutral uppercase font-body">八、资源需求与下一步计划 · RESOURCES</span>
      </div>
      <h1 class="text-[38px] font-bold text-primary font-title mt-1">协调 3 项关键资源，2–4 周即可迈入生产运营</h1>
    </div>

    <div class="absolute top-[126px] left-16 right-16 rounded-2xl p-6" style="background:#16335B;">
      <div class="text-[15px] font-bold text-white font-title mb-4">请求领导支持（3 项资源，均靠协调而非研发加班）</div>
      <div class="grid grid-cols-3 gap-5">
        <div class="rounded-xl p-4" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);">
          <div class="text-[14px] font-bold text-accent-2 font-title mb-1">① MODEL_API_KEY</div>
          <div class="text-[13px] text-white/80 font-body leading-relaxed">解锁 P8.4 重提取与 P10 灰度切换，兑现知识管线价值。</div>
        </div>
        <div class="rounded-xl p-4" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);">
          <div class="text-[14px] font-bold text-accent-2 font-title mb-1">② 医院 SSO / 账号体系文档</div>
          <div class="text-[13px] text-white/80 font-body leading-relaxed">支撑安全审计与等保上线。</div>
        </div>
        <div class="rounded-xl p-4" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);">
          <div class="text-[14px] font-bold text-accent-2 font-title mb-1">③ 真实医保 / DRG 系统 API 与测试环境</div>
          <div class="text-[13px] text-white/80 font-body leading-relaxed">把内存适配器替换为真实业务闭环。</div>
        </div>
      </div>
    </div>

    <div class="absolute top-[330px] left-16 right-16 bottom-[140px] grid grid-cols-3 gap-6">
      <div class="rounded-2xl bg-white shadow-sm overflow-hidden flex flex-col">
        <div class="px-6 py-4" style="background:#0E9F6E;">
          <div class="text-[13px] text-white/80 font-body tracking-wide">近期</div>
          <div class="text-[22px] font-bold text-white font-title">2–4 周 · 价值兑现</div>
        </div>
        <div class="p-6 flex-1">
          <ul class="space-y-3 text-[14.5px] text-neutral font-body">
            <li class="flex gap-2"><span class="text-accent-1 font-bold">▸</span><span>完成 P8.4 重提取，拉高填充率</span></li>
            <li class="flex gap-2"><span class="text-accent-1 font-bold">▸</span><span>P10 灰度切换（M7）</span></li>
            <li class="flex gap-2"><span class="text-accent-1 font-bold">▸</span><span>政策问答跑在新模型，旧路径下线</span></li>
          </ul>
          <div class="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#E6F6EF]"><span class="w-2 h-2 rounded-full bg-accent-2"></span><span class="text-[13px] text-primary font-semibold font-body">需要：MODEL_API_KEY</span></div>
        </div>
      </div>
      <div class="rounded-2xl bg-white shadow-sm overflow-hidden flex flex-col">
        <div class="px-6 py-4" style="background:#16335B;">
          <div class="text-[13px] text-white/80 font-body tracking-wide">中期</div>
          <div class="text-[22px] font-bold text-white font-title">1–2 月 · 收口与对接</div>
        </div>
        <div class="p-6 flex-1">
          <ul class="space-y-3 text-[14.5px] text-neutral font-body">
            <li class="flex gap-2"><span class="text-primary font-bold">▸</span><span>推进单元 → verified 正式验证</span></li>
            <li class="flex gap-2"><span class="text-primary font-bold">▸</span><span>对接医院 SSO，完成安全审计</span></li>
            <li class="flex gap-2"><span class="text-primary font-bold">▸</span><span>真实医保/DRG 接口替换内存适配器</span></li>
          </ul>
          <div class="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-[#E7F0F8]"><span class="w-2 h-2 rounded-full bg-primary"></span><span class="text-[13px] text-primary font-semibold font-body">需要：SSO 文档 / 真实 API</span></div>
        </div>
      </div>
      <div class="rounded-2xl bg-white shadow-sm overflow-hidden flex flex-col">
        <div class="px-6 py-4" style="background:#475569;">
          <div class="text-[13px] text-white/80 font-body tracking-wide">远期</div>
          <div class="text-[22px] font-bold text-white font-title">Q3+ · 场景拓展</div>
        </div>
        <div class="p-6 flex-1">
          <ul class="space-y-3 text-[14.5px] text-neutral font-body">
            <li class="flex gap-2"><span class="text-neutral font-bold">▸</span><span>拒付申诉助手 / DRG-DIP 运营助手</span></li>
            <li class="flex gap-2"><span class="text-neutral font-bold">▸</span><span>病案首页风险导办</span></li>
            <li class="flex gap-2"><span class="text-neutral font-bold">▸</span><span>科室医保整改闭环</span></li>
          </ul>
          <div class="mt-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-100"><span class="w-2 h-2 rounded-full bg-neutral"></span><span class="text-[13px] text-primary font-semibold font-body">形成"问查算办管"全链路闭环</span></div>
        </div>
      </div>
    </div>

    <div class="absolute bottom-[64px] left-16 right-16 rounded-2xl px-7 py-4 flex items-center gap-4" style="background:#0E9F6E;">
      <span class="text-[24px]">🎯</span>
      <span class="text-[18px] text-white font-body font-semibold">协调上述 3 项依赖，即可在 <span class="font-bold">2–4 周内</span> 完成价值兑现（M7），迈入生产运营。</span>
    </div>

    <div class="absolute bottom-5 left-16 right-16 flex justify-between items-center text-xs text-neutral/70 font-body">
      <span>院端医保智能体系统 · 建设项目汇报</span><span>10 / 11</span>
    </div>
  </div>
`);
