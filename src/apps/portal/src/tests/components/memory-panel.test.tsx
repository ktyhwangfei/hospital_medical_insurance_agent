/**
 * MemoryPanel 组件测试
 *
 * 覆盖设计文档 §4.2：
 * - 记忆卡按类型分组展示
 * - 来源标注：✓ 来自记忆 / ✨ 本轮新查 / 📌 跨话题保留
 * - 空态
 * - lastContextNeed 加载来源指示
 */

import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import MemoryPanel from '@/components/policy-qa/memory-panel'
import type { MemoryCard, ContextNeedSnapshot } from '@/lib/policy-qa-session'

afterEach(() => cleanup())

function makeCard(partial: Partial<MemoryCard>): MemoryCard {
  return {
    memoryId: 'm-x',
    type: 'settlement',
    refId: null,
    importance: 0.5,
    expirePolicy: 'session',
    snapshotKeys: [],
    hitThisTurn: false,
    isNewThisTurn: false,
    ...partial,
  }
}

describe('MemoryPanel', () => {
  it('空态提示', () => {
    render(<MemoryPanel memories={[]} />)
    expect(screen.getByText(/暂无会话记忆/)).toBeInTheDocument()
    expect(screen.getByText('0 条')).toBeInTheDocument()
  })

  it('按类型分组渲染记忆卡', () => {
    const memories = [
      makeCard({ memoryId: 'm-settle', type: 'settlement', refId: '1671213', expirePolicy: 'topic' }),
      makeCard({ memoryId: 'm-policy', type: 'policy', expirePolicy: 'sticky' }),
    ]
    render(<MemoryPanel memories={memories} />)
    expect(screen.getByText('结算')).toBeInTheDocument()
    expect(screen.getByText('政策')).toBeInTheDocument()
    expect(screen.getByText('1671213')).toBeInTheDocument()
    const cards = screen.getAllByTestId('memory-card')
    expect(cards).toHaveLength(2)
    expect(cards[0]).toHaveAttribute('data-type', 'settlement')
    expect(cards[1]).toHaveAttribute('data-type', 'policy')
  })

  it('命中记忆标注 来自记忆', () => {
    const memories = [makeCard({ memoryId: 'm-1', hitThisTurn: true })]
    render(<MemoryPanel memories={memories} />)
    expect(screen.getByText('来自记忆')).toBeInTheDocument()
  })

  it('本轮新查标注 本轮新查（未命中时不重复标注）', () => {
    const memories = [makeCard({ memoryId: 'm-1', isNewThisTurn: true, hitThisTurn: false })]
    render(<MemoryPanel memories={memories} />)
    expect(screen.getByText('本轮新查')).toBeInTheDocument()
    expect(screen.queryByText('来自记忆')).toBeNull()
  })

  it('STICKY 记忆标注 跨话题保留', () => {
    const memories = [makeCard({ memoryId: 'm-1', expirePolicy: 'sticky' })]
    render(<MemoryPanel memories={memories} />)
    expect(screen.getByText('跨话题保留')).toBeInTheDocument()
  })

  it('渲染 snapshot_keys 字段标签（无业务值时）', () => {
    const memories = [makeCard({ memoryId: 'm-1', snapshotKeys: ['settlement_id', 'total_fee'] })]
    render(<MemoryPanel memories={memories} />)
    expect(screen.getByText('settlement_id')).toBeInTheDocument()
    expect(screen.getByText('total_fee')).toBeInTheDocument()
  })

  it('渲染 snapshot 业务键值（键: 值）', () => {
    const memories = [
      makeCard({
        memoryId: 'm-1',
        snapshotKeys: ['settlement_id', 'total_fee'],
        snapshot: { settlement_id: '1671213', total_fee: 189085.85 },
      }),
    ]
    render(<MemoryPanel memories={memories} />)
    expect(screen.getByText('settlement_id: 1671213')).toBeInTheDocument()
    expect(screen.getByText('total_fee: 189085.85')).toBeInTheDocument()
  })

  it('lastContextNeed 命中时显示本轮复用记忆条数', () => {
    const contextNeed: ContextNeedSnapshot = {
      objectTypes: ['Policy'],
      memoryIds: ['m-1'],
      mustQuerySemantic: true,
      topicChanged: false,
      subjectChanged: false,
    }
    const memories = [makeCard({ memoryId: 'm-1', hitThisTurn: true })]
    render(<MemoryPanel memories={memories} lastContextNeed={contextNeed} />)
    expect(screen.getByText(/本轮复用记忆/)).toBeInTheDocument()
  })

  it('无命中时显示需检索的类型', () => {
    const contextNeed: ContextNeedSnapshot = {
      objectTypes: ['Settlement', 'Rule'],
      memoryIds: [],
      mustQuerySemantic: true,
      topicChanged: false,
      subjectChanged: false,
    }
    render(<MemoryPanel memories={[]} lastContextNeed={contextNeed} />)
    expect(screen.getByText(/本轮需检索：Settlement \/ Rule/)).toBeInTheDocument()
  })
})
