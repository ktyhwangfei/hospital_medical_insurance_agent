'use client'

// 术语业务释义：技术词 hover 显示业务解释（面向非技术用户）。
// 术语字典与 V3.0 设计文档 §1.1 对齐；新增术语在此登记。
import { useState, type ReactNode } from 'react'

const GLOSSARY: Record<string, string> = {
  '水位线': '上次同步到哪个时间点；下次只拉这之后新产生的数据',
  '回看窗口': '从水位线往前多拉几分钟，防止源系统写入延迟导致漏数',
  '物化': '把数据模型变成数据库里可查询的视图，供指标和问数使用',
  '勾稽': '金额之间的恒等校验（如 总费用 = 统筹支付 + 个人支付），不相等即数据有问题',
  'CDC': '变更数据捕获：数据库级实时同步，需要 DBA 在源库开通',
  '增量同步': '只同步上次之后变化的数据（快），依赖时间字段',
  '全量同步': '整表重新拉取覆盖（慢但彻底），每日限频',
  '值域': '字段允许取值的码表（如险种：职工/居民），用于口径统一',
  '主键': '唯一标识一行数据的字段（如交易号），用于去重',
  '落地表': '源库数据同步到治理底座 PostgreSQL 后的表',
  '消费契约': 'Flow 发布的指标白名单，问数只能查契约内的指标',
  '结构契约': '数据模型定义的可信数据结构（粒度+字段+角色），是数据消费的标准',
}

export function Term({ children }: { children: string }) {
  const [show, setShow] = useState(false)
  const text = typeof children === 'string' ? children : String(children)
  const explanation = GLOSSARY[text]
  if (!explanation) return <>{children}</>
  return (
    <span className="relative inline-block"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}>
      <span className="cursor-help border-b border-dashed border-slate-400">{children}</span>
      {show && (
        <span role="tooltip"
          className="absolute bottom-full left-0 z-50 mb-1 w-56 rounded-lg border border-slate-200 bg-slate-900 px-3 py-2 text-xs leading-5 text-white shadow-lg">
          {explanation}
        </span>
      )}
    </span>
  )
}
