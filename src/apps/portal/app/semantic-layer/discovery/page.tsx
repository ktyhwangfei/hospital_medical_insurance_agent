'use client'

// 语义层 · 数据发现页（壳）：主体能力已提取为共享组件 DiscoveryCenter，
// 数据治理中心探查页复用同一组件（mappingBaseUrl 指向语义层映射台）。
import { Suspense } from 'react'
import { DiscoveryCenter } from '@/components/discovery/discovery-center'

export default function SemanticDiscoveryPage() {
  return (
    <Suspense fallback={<div className="py-16 text-center text-sm text-slate-400">加载发现中心…</div>}>
      <DiscoveryCenter mappingBaseUrl="/semantic-layer/mapping" />
    </Suspense>
  )
}
