'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CalendarDays,
  ChevronRight,
  LoaderCircle,
  RefreshCw,
  Search,
  UserRound,
} from 'lucide-react'

import {
  fetchPatientLookup,
  fetchSettlementsByDateRange,
  formatAmount,
  thisWeekRange,
  todayRange,
  type PatientSummaryDTO,
  type SettlementDecompositionChain,
  type SettlementListItemDTO,
  type SettlementPreset,
} from '@/lib/policy-qa-settlement-list'

/**
 * V4.0 结算解释智能体：患者定位 + 时间浏览（设计 §4.2）。
 *
 * 主输入链：先定位患者（身份证号/卡号，临时方案——正式由登录态给出
 * 患者身份），再按时段浏览该患者的结算单，点单看费用构成解释。
 * 未定位患者时不加载列表（隐私收敛：不按全院浏览）。
 */

interface SettlementTimeBrowserProps {
  selectedId: string | null
  /** 点选结算单：传整项（工作区需要结算时间/医疗类别渲染账单头） */
  onSelect: (item: SettlementListItemDTO) => void
  /** 患者定位/换人时通知工作区（用于清掉上一患者的选中结算单） */
  onPatientChange?: (patient: PatientSummaryDTO | null) => void
  /** 候选列表变化时上报（工作区 @换结算 只能命中等值条目） */
  onCandidatesChange?: (items: SettlementListItemDTO[]) => void
}

const CHAIN_BADGE: Record<Exclude<SettlementDecompositionChain, null>, string> = {
  outpatient: '门诊分解',
  special: '门特分解',
}

const PRESETS: Array<{ id: SettlementPreset; label: string }> = [
  { id: 'today', label: '今天' },
  { id: 'this_week', label: '本周' },
  { id: 'custom', label: '自定义' },
]

export default function SettlementTimeBrowser({
  selectedId,
  onSelect,
  onPatientChange,
  onCandidatesChange,
}: SettlementTimeBrowserProps) {
  // ── 患者定位（临时方案）─────────────────────────────────────
  const [patient, setPatient] = useState<PatientSummaryDTO | null>(null)
  const [patientKey, setPatientKey] = useState<string | null>(null)
  const [keyInput, setKeyInput] = useState('')
  const [lookupLoading, setLookupLoading] = useState(false)
  const [lookupError, setLookupError] = useState<string | null>(null)

  // ── 时段与列表 ──────────────────────────────────────────────
  const [preset, setPreset] = useState<SettlementPreset>('today')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [items, setItems] = useState<SettlementListItemDTO[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 患者/查询上下文代次：换人、重新定位、改时段、卸载都递增；
  // 旧请求（成功/失败/finally）只有代次匹配才能写回（R1）。
  const contextRef = useRef(0)
  const mountedRef = useRef(true)

  // 使在途列表请求失效并清空旧结果/候选（新查询、换人、改时段、卸载共用）。
  const invalidateList = useCallback(() => {
    contextRef.current += 1
    setItems([])
    setError(null)
    setLoading(false)
  }, [])

  const resolveRange = useCallback((): { dateFrom: string; dateTo: string } | null => {
    if (preset === 'today') return todayRange()
    if (preset === 'this_week') return thisWeekRange()
    if (customFrom && customTo && customFrom <= customTo) return { dateFrom: customFrom, dateTo: customTo }
    return null
  }, [preset, customFrom, customTo])

  const load = useCallback(async () => {
    const range = resolveRange()
    if (!range) {
      invalidateList()
      setError('请选择有效的自定义日期范围（开始 ≤ 结束）。')
      return
    }
    // 新请求让旧请求立即失效（同一患者换时段/刷新也不允许旧结果回写）
    const ticket = ++contextRef.current
    setLoading(true)
    setError(null)
    try {
      const data = await fetchSettlementsByDateRange(
        range.dateFrom,
        range.dateTo,
        50,
        patientKey ?? undefined,
      )
      if (ticket !== contextRef.current || !mountedRef.current) return
      setItems(data)
    } catch (e) {
      if (ticket !== contextRef.current || !mountedRef.current) return
      setError(e instanceof Error ? e.message : '结算单列表查询失败')
      setItems([])
    } finally {
      if (ticket === contextRef.current && mountedRef.current) setLoading(false)
    }
  }, [resolveRange, patientKey, invalidateList])

  // 定位患者后按当前预设时段自动加载；自定义模式由「查询」按钮触发
  useEffect(() => {
    if (patientKey && preset !== 'custom') void load()
  }, [patientKey, preset, load])

  // 候选列表上报给工作区：@换结算 命令按完整列表项复用选单入口。
  // 只在当前上下文代次的有效 items 上发布；换人/改时段/卸载已清空或不再发布。
  useEffect(() => {
    if (!mountedRef.current) return
    onCandidatesChange?.(items)
  }, [items, onCandidatesChange])

  // 卸载后不得再有在途结果改写状态或发布候选
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      contextRef.current += 1
    }
  }, [])

  const handleLocate = () => {
    const key = keyInput.trim()
    if (!key || lookupLoading) return
    setLookupLoading(true)
    setLookupError(null)
    // 新定位立即丢弃上一患者的在途列表与结果，不等待查询返回
    invalidateList()
    void (async () => {
      try {
        const found = await fetchPatientLookup(key)
        if (!mountedRef.current) return
        if (found) {
          setPatient(found)
          setPatientKey(key)
          onPatientChange?.(found)
        } else {
          setLookupError('未找到该患者，请核对身份证号或卡号。')
        }
      } catch (e) {
        if (!mountedRef.current) return
        setLookupError(e instanceof Error ? e.message : '患者定位失败')
      } finally {
        if (mountedRef.current) setLookupLoading(false)
      }
    })()
  }

  const handleSwitchPatient = () => {
    invalidateList()
    setPatient(null)
    setPatientKey(null)
    setKeyInput('')
    setLookupError(null)
    onPatientChange?.(null)
  }

  const range = resolveRange()

  return (
    <section data-testid="settlement-time-browser" className="space-y-4">
      {/* ── 患者定位卡（临时方案：正式由登录态取代）────────────── */}
      {patient ? (
        <div
          data-testid="patient-card"
          className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-slate-100">
            <UserRound className="size-5 text-slate-500" aria-hidden />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-900">
              {patient.name || '未知患者'}
              <span className="ml-2 text-xs font-normal text-slate-500">
                {[patient.gender, patient.birthDate].filter(Boolean).join(' · ')}
              </span>
            </p>
            <p className="tabular-amounts mt-0.5 text-xs text-slate-500">
              {[patient.idNoMasked, patient.cardNo && `卡号 ${patient.cardNo}`]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </div>
          <button
            type="button"
            onClick={handleSwitchPatient}
            aria-label="换人"
            className="ml-auto shrink-0 rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            换人
          </button>
        </div>
      ) : (
        <div
          data-testid="patient-locate-form"
          className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <Search className="size-4 shrink-0 text-slate-400" aria-hidden />
            <input
              value={keyInput}
              onChange={(event) => setKeyInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) handleLocate()
              }}
              placeholder="输入患者身份证号或卡号定位"
              aria-label="患者身份证号或卡号"
              disabled={lookupLoading}
              className="min-w-0 flex-1 rounded-lg border-0 px-1 py-1 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-agent-settlement/25"
            />
            <button
              type="button"
              onClick={handleLocate}
              disabled={!keyInput.trim() || lookupLoading}
              className="shrink-0 rounded-full bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {lookupLoading ? '定位中…' : '定位'}
            </button>
          </div>
          <p className="mt-2 text-[11px] leading-5 text-slate-400">
            定位后仅展示该患者的结算单；请核对患者信息后再办理。
          </p>
          {lookupError ? (
            <p role="alert" className="mt-2 text-xs text-amber-700">
              {lookupError}
            </p>
          ) : null}
        </div>
      )}

      {/* ── 时间选择器 ──────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <CalendarDays className="size-4 text-slate-400" aria-hidden />
        <div
          role="group"
          aria-label="结算时段选择"
          className="flex items-center gap-1 rounded-full bg-slate-100 p-0.5"
        >
          {PRESETS.map((item) => {
            const active = preset === item.id
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  // 改时段：旧列表/候选立即作废，等新查询成功后再恢复
                  invalidateList()
                  setPreset(item.id)
                }}
                aria-pressed={active}
                disabled={!patient}
                data-testid={`settlement-preset-${item.id}`}
                className={[
                  'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                  active
                    ? 'bg-white text-agent-settlement shadow-sm'
                    : 'text-slate-600 hover:text-slate-900',
                  !patient ? 'cursor-not-allowed opacity-50' : '',
                ].join(' ')}
              >
                {item.label}
              </button>
            )
          })}
        </div>
        {preset === 'custom' ? (
          <div className="flex items-center gap-1.5">
            <input
              type="date"
              aria-label="开始日期"
              value={customFrom}
              onChange={(event) => {
                invalidateList()
                setCustomFrom(event.target.value)
              }}
              className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700"
            />
            <span className="text-xs text-slate-400">至</span>
            <input
              type="date"
              aria-label="结束日期"
              value={customTo}
              min={customFrom || undefined}
              onChange={(event) => {
                invalidateList()
                setCustomTo(event.target.value)
              }}
              className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700"
            />
            <button
              type="button"
              onClick={() => void load()}
              disabled={!customFrom || !customTo}
              className="rounded-full bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-700 disabled:opacity-50"
            >
              查询
            </button>
          </div>
        ) : null}
        {preset !== 'custom' && range ? (
          <span className="tabular-amounts text-xs text-slate-400">
            {range.dateFrom} ~ {range.dateTo}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading || !patient}
          aria-label="刷新时段结算列表"
          className="ml-auto inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw className={`size-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden />
          刷新
        </button>
      </div>

      {/* 时段结算单列表：未定位患者时只显示引导（隐私收敛） */}
      {!patient ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white/70 px-4 py-8 text-center text-sm text-slate-400">
          先定位患者，再看 TA 的时段结算单。
        </div>
      ) : (
        <>
          {loading ? (
            <div role="status" className="flex items-center gap-2 py-4 text-sm text-slate-500">
              <LoaderCircle className="size-4 animate-spin" aria-hidden />
              正在加载该患者的时段结算单…
            </div>
          ) : null}

          {!loading && error ? (
            <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              {error}
            </div>
          ) : null}

          {!loading && !error ? (
            <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
              <p className="border-b border-slate-100 px-4 py-2.5 text-xs text-slate-500">
                {preset === 'today' ? '今日' : preset === 'this_week' ? '本周' : '所选时段'}结算单（{items.length} 笔）
              </p>
              {items.length === 0 ? (
                <p className="px-4 py-8 text-center text-sm text-slate-400">
                  该时段暂无结算单，切换时段或刷新试试。
                </p>
              ) : (
                <ul
                  className="max-h-[420px] divide-y divide-slate-100 overflow-y-auto"
                  data-testid="settlement-list"
                >
                  {items.map((item) => {
                    const selected = item.settlementId === selectedId
                    return (
                      <li key={item.settlementId}>
                        <button
                          type="button"
                          onClick={() => onSelect(item)}
                          aria-pressed={selected}
                          data-testid={`settlement-item-${item.settlementId}`}
                          className={[
                            'flex w-full items-center gap-3 px-4 py-3 text-left transition-colors',
                            selected ? 'bg-slate-50' : 'hover:bg-slate-50/70',
                          ].join(' ')}
                        >
                          <span className="tabular-amounts min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium text-slate-900">
                              {item.settlementId}
                            </span>
                            <span className="block truncate text-xs text-slate-500">
                              {[item.settlementDate.slice(0, 16), item.personType, item.serviceType]
                                .filter(Boolean)
                                .join(' · ')}
                            </span>
                          </span>
                          {item.decompositionChain ? (
                            <span
                              data-testid={`settlement-chain-badge-${item.settlementId}`}
                              className="shrink-0 rounded-full bg-agent-settlement/10 px-2 py-0.5 text-[11px] font-medium text-agent-settlement"
                            >
                              {CHAIN_BADGE[item.decompositionChain]}
                            </span>
                          ) : null}
                          {item.insuranceType ? (
                            <span className="hidden shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 sm:inline">
                              {item.insuranceType}
                            </span>
                          ) : null}
                          <span className="tabular-amounts shrink-0 text-sm font-semibold text-slate-900">
                            {formatAmount(item.totalAmount)}
                          </span>
                          <ChevronRight
                            className={`size-4 shrink-0 ${selected ? 'text-agent-settlement' : 'text-slate-300'}`}
                            aria-hidden
                          />
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          ) : null}
        </>
      )}
    </section>
  )
}
