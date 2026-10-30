import type { FormulaInputStatus, PolicyQAFeeDecomposition, PolicyQAFeeDecompositionCalculation, PolicyQARuleChoice } from '@/lib/policy-qa-stream'

const STATUS: Record<FormulaInputStatus, string> = { verified: '来源已确认', unverified: '来源未确认', missing: '来源未取得', conflict: '来源有冲突' }
const CHOICE = { selected: '本次采用', eligible: '条件符合', excluded: '已排除', unknown: '无法判断', conflict: '候选冲突' }
const CHECK = { met: '符合', unmet: '不符', unknown: '未确认' }
export const calculationAnchor = (id: string) => `formula-${id.replace(/[^a-zA-Z0-9_-]/g, '-')}`

export function orderedCalculations(data: PolicyQAFeeDecomposition, refs: string[]) {
  const seen = new Set<string>()
  const output: PolicyQAFeeDecompositionCalculation[] = []
  const visit = (id: string) => {
    if (seen.has(id)) return
    seen.add(id)
    const calc = data.calculations.find((item) => item.calculationId === id)
    if (!calc) return
    calc.operands.forEach((op) => { if (op.calculationRef) visit(op.calculationRef) })
    data.ruleChoices?.filter((group) => group.calculationRefs.includes(id)).forEach((group) => group.inputRefs.forEach((ref) => {
      const input = data.formulaInputs?.find((item) => item.inputId === ref)
      if (input?.calculationRef) visit(input.calculationRef)
    }))
    output.push(calc)
  }
  refs.forEach(visit)
  return output
}

export function formulaRegistry(data: PolicyQAFeeDecomposition, calculations: PolicyQAFeeDecompositionCalculation[], includeUnattachedRules = false, allRules = data.ruleChoices ?? []) {
  const firstInput = new Map<string, string>()
  const firstRule = new Map<string, string>()
  const inputNumbers = new Map((data.formulaInputs ?? []).map((input, index) => [input.inputId, index + 1]))
  const numbers = new Map(data.calculations.map((calc, index) => [calc.calculationId, index + 1]))
  const firstRounding = new Map<string, string>()
  const sourceNumbers = new Map([...new Set(allRules.flatMap((group) => group.candidates.map((row) => row.source)))].map((source, index) => [source, index + 1]))
  const firstPolicySource = new Map<string, string>()
  calculations.forEach((calc) => {
    if (calc.roundingRule && !firstRounding.has(calc.roundingRule)) firstRounding.set(calc.roundingRule, calc.calculationId)
    calc.operands.forEach((op) => {
      if (op.inputRef && !firstInput.has(op.inputRef)) firstInput.set(op.inputRef, calc.calculationId)
    })
    data.ruleChoices?.forEach((group) => {
      if (group.calculationRefs.includes(calc.calculationId) && !firstRule.has(group.groupId)) firstRule.set(group.groupId, calc.calculationId)
    })
  })
  data.ruleChoices?.filter((group) => includeUnattachedRules || firstRule.has(group.groupId)).forEach((group) => {
    group.inputRefs.forEach((ref) => { if (!firstInput.has(ref)) firstInput.set(ref, group.groupId) })
  })
  const visibleRules = [...calculations.flatMap((calc) => data.ruleChoices?.filter((group) => firstRule.get(group.groupId) === calc.calculationId) ?? []), ...(includeUnattachedRules ? data.ruleChoices?.filter((group) => !firstRule.has(group.groupId)) ?? [] : [])]
  visibleRules.forEach((group) => group.candidates.forEach((row) => {
    if (!firstPolicySource.has(row.source)) firstPolicySource.set(row.source, group.groupId)
  }))
  return { firstInput, firstRule, firstRounding, inputNumbers, numbers, sourceNumbers, firstPolicySource }
}
export type FormulaRegistry = ReturnType<typeof formulaRegistry>

function Verification({ status = 'unverified' }: { status?: FormulaInputStatus }) {
  return <span className={`whitespace-nowrap text-xs ${status === 'verified' ? 'text-emerald-800' : status === 'conflict' ? 'text-red-800' : 'text-amber-800'}`}>{STATUS[status]}</span>
}

export function RuleChoiceTable({ group, data, registry }: { group: PolicyQARuleChoice; data: PolicyQAFeeDecomposition; registry?: FormulaRegistry }) {
  const facts = [...new Set(group.candidates.flatMap((row) => row.checks.filter((check) => check.actual !== null && check.name !== '费用分段').map((check) => `${check.name}：${check.actual}`)))]
  const columns = [...new Set(group.candidates.flatMap((row) => row.checks.map((check) => check.name)))]
  const sources = group.candidates.filter((row, index, rows) => rows.findIndex((other) => other.source === row.source && other.version === row.version && other.effectiveFrom === row.effectiveFrom && other.effectiveTo === row.effectiveTo && other.confirmationStatus === row.confirmationStatus) === index)
  return <section id={group.groupId} className="min-w-0 scroll-mt-24 space-y-2 py-3 target:bg-blue-50" aria-label={group.title}>
    <h5 className="font-medium text-slate-900">{group.title}：候选档判定</h5>
    <p className="text-xs leading-6 text-slate-700">本单：{data.settlementFacts?.metadataNames?.person_type ? `患者人员类别 ${data.settlementFacts.metadataNames.person_type}；` : ''}{facts.join('；') || '判断所需事实未取得'}</p>
    <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs leading-6">{group.inputRefs.map((ref) => data.formulaInputs?.find((input) => input.inputId === ref)).map((input, index) => {
      if (!input) return <p key={index} className="text-amber-800">判断输入来源未取得，不能认定适用。</p>
      const owner = registry?.firstInput.get(input.inputId)
      const first = !owner || owner === group.groupId
      return <p key={input.inputId} id={first ? input.inputId : undefined} className="scroll-mt-24 target:bg-slate-100 target:outline-2 target:outline-blue-700"><span className="text-slate-800">I{registry?.inputNumbers.get(input.inputId)} · {input.name}：{input.value ?? '未取得'}</span> · <Verification status={input.status} /><span className="block text-slate-600">{first ? input.source : <a href={`#${input.calculationRef ? calculationAnchor(input.calculationRef) : input.inputId}`} className="text-blue-800 underline underline-offset-4">沿用首次来源</a>}{first && input.reason ? ` · ${input.reason}` : ''}</span></p>
    })}</div>
    <div className="max-w-full overflow-x-auto rounded-md border border-slate-200" tabIndex={0} role="region" aria-label={`${group.title}候选档表`}>
      <table className="w-full min-w-[640px] text-left text-xs leading-5">
        <thead className="bg-slate-50 text-slate-700"><tr><th className="px-3 py-2 font-medium">档位 / 参数</th>{columns.map((name) => <th key={name} className="px-3 py-2 font-medium">{name}要求</th>)}<th className="px-3 py-2 font-medium">本次判定</th></tr></thead>
        <tbody className="divide-y divide-slate-200">{group.candidates.map((row) => <tr key={row.ruleId} className={row.status === 'selected' ? 'bg-blue-50' : ''}>
          <th scope="row" className="max-w-56 px-3 py-2 align-top font-normal"><span className="block text-slate-900">{row.name}</span><strong className="tabular-nums">{row.value ?? '未确认'} {row.unit}</strong></th>
          {columns.map((name) => { const check = row.checks.find((item) => item.name === name); return <td key={name} className="px-3 py-2 align-top">{check ? <>{check.expected}<span className={`block ${check.outcome === 'unmet' ? 'text-slate-600' : check.outcome === 'unknown' ? 'text-amber-800' : 'text-emerald-800'}`}>{CHECK[check.outcome]}</span></> : '不参与判定'}</td> })}
          <td className="max-w-64 px-3 py-2 align-top"><strong className={row.status === 'selected' ? 'text-blue-800' : row.status === 'conflict' ? 'text-red-800' : 'text-slate-800'}>{CHOICE[row.status]}</strong><span className={`mt-1 block ${row.status === 'selected' ? 'text-blue-800' : 'text-slate-600'}`}>{row.reason}</span></td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className="text-xs leading-5 text-slate-600">{sources.map((row, index) => {
      const number = registry?.sourceNumbers.get(row.source)
      const first = (!registry || registry.firstPolicySource.get(row.source) === group.groupId) && sources.findIndex((item) => item.source === row.source) === index
      return <p key={index} id={first && number ? `policy-source-${number}` : undefined} className="scroll-mt-24 target:bg-slate-100 target:outline-2 target:outline-blue-700">依据：{first || !number ? `${number ? `S${number} · ` : ''}${row.source || '来源未取得'}` : <a href={`#policy-source-${number}`} className="text-blue-800 underline underline-offset-4">沿用来源 S{number}</a>} · {row.version} · {row.effectiveFrom ?? '生效日未确认'} 至 {row.effectiveTo ?? '截止日未确认'} · {row.confirmationStatus}</p>
    })}</div>
  </section>
}

export function FormulaCalculation({ calculation: calc, data, registry }: { calculation: PolicyQAFeeDecompositionCalculation; data: PolicyQAFeeDecomposition; registry: FormulaRegistry }) {
  const verified = calc.explainable === true
  const pendingFormula = calc.formula?.replace(/＝[^＝]*$/, '＝待核实')
  const unique = calc.operands.filter((op, index, all) => all.findIndex((other) => other.inputRef ? other.inputRef === op.inputRef : other.displayName === op.displayName && other.value === op.value) === index)
  const groups = data.ruleChoices?.filter((group) => registry.firstRule.get(group.groupId) === calc.calculationId) ?? []
  return <article id={calculationAnchor(calc.calculationId)} className="min-w-0 scroll-mt-24 border-t border-slate-200 py-4 text-sm target:bg-blue-50" data-testid={`formula-${calc.calculationId}`}>
    <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1"><h4 className="font-semibold text-slate-900">#{registry.numbers.get(calc.calculationId)} {calc.displayName}</h4></div>
    <p className="break-words text-base font-medium leading-7 text-slate-900">{verified ? calc.formula || `${calc.displayName}＝${calc.result ?? '未确定'}` : pendingFormula || `${calc.displayName}：独立计算待核实`}</p>
    {calc.verificationReason ? <p className="mt-1 text-xs leading-6 text-amber-800">{calc.verificationReason}</p> : null}
    {unique.length ? <div className="mt-3 max-w-full overflow-x-auto" tabIndex={0} role="region" aria-label={`${calc.displayName}的输入依据`}>
      <table className="w-full min-w-[520px] text-left text-xs leading-6"><thead className="text-slate-600"><tr><th className="w-2/5 px-2 py-1 font-normal">输入</th><th className="px-2 py-1 font-normal">本单值</th><th className="px-2 py-1 font-normal">验证</th><th className="px-2 py-1 font-normal">来源 / 上游</th></tr></thead>
        <tbody className="divide-y divide-slate-100">{unique.map((op, index) => {
          const input = data.formulaInputs?.find((item) => item.inputId === op.inputRef)
          const first = input && registry.firstInput.get(input.inputId) === calc.calculationId
          const upstream = input?.calculationRef
          return <tr key={`${op.inputRef ?? index}`} id={first && !upstream ? input.inputId : undefined} className="scroll-mt-24 align-top target:bg-blue-50">
            <th scope="row" className="px-2 py-2 font-normal text-slate-800">{input ? `I${registry.inputNumbers.get(input.inputId)} · ` : ''}{op.displayName}</th>
            <td className="whitespace-nowrap px-2 py-2 tabular-nums text-slate-900">{op.value || '未取得'}</td>
            <td className="px-2 py-2"><Verification status={input?.status} /></td>
            <td className="px-2 py-2 text-slate-600">{upstream ? <a className="text-blue-800 underline decoration-blue-300 underline-offset-4 focus-visible:outline-2" href={`#${calculationAnchor(upstream)}`}>见 #{registry.numbers.get(upstream)} {input.name}</a> : input && !first ? <a className="text-blue-800 underline decoration-blue-300 underline-offset-4 focus-visible:outline-2" href={`#${input.inputId}`}>沿用 I{registry.inputNumbers.get(input.inputId)} 的来源</a> : <>{input?.source || '输入来源未取得'}{input?.reason ? <span className="block text-amber-800">{input.reason}</span> : null}</>}{input?.ruleGroupRef ? <a className="ml-2 text-blue-800 underline underline-offset-4" href={`#${input.ruleGroupRef}`}>候选判定</a> : null}</td>
          </tr>
        })}</tbody>
      </table>
    </div> : <p className="mt-2 text-xs text-amber-800">未返回输入关联，无法继续追溯。</p>}
    {calc.roundingRule ? <p id={registry.firstRounding.get(calc.roundingRule) === calc.calculationId ? `rounding-${calculationAnchor(calc.calculationId)}` : undefined} className="mt-2 scroll-mt-24 text-xs leading-6 text-slate-600 target:bg-slate-100 target:outline-2 target:outline-blue-700">{registry.firstRounding.get(calc.roundingRule) === calc.calculationId ? `取整：${calc.roundingRule}` : <a className="text-blue-800 underline underline-offset-4" href={`#rounding-${calculationAnchor(registry.firstRounding.get(calc.roundingRule)!)}`}>沿用 #{registry.numbers.get(registry.firstRounding.get(calc.roundingRule)!)} 的取整规则</a>}</p> : null}
    {!verified && calc.result !== null ? <details className="mt-2 text-xs leading-6 text-slate-600"><summary className="w-fit cursor-pointer focus-visible:outline-2">查看已执行的候选运算记录</summary><p>{calc.formula || `运算记录值 ${calc.result}`}</p><p>执行记录不代表输入适用性已核实。</p></details> : null}
    {groups.map((group) => <RuleChoiceTable key={group.groupId} group={group} data={data} registry={registry} />)}
  </article>
}
