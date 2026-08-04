/**
 * SessionAnchorBar 组件测试
 *
 * 覆盖设计文档 §4.2：
 * - 结算锚点徽标（有/无结算单）
 * - 患者/就诊/话题徽标渲染
 * - subject_changed=true → 主体切换横幅 + 关闭按钮
 */

import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import SessionAnchorBar from '@/components/policy-qa/session-anchor-bar'
import type { SessionAnchor } from '@/lib/policy-qa-session'

afterEach(() => cleanup())

function makeAnchor(partial: Partial<SessionAnchor> = {}): SessionAnchor {
  return {
    patientId: 'P001',
    patientName: null,
    encounterId: 'E001',
    settlementId: '1671213',
    topic: null,
    subjectChanged: false,
    subjectChangeMsg: null,
    ...partial,
  }
}

describe('SessionAnchorBar', () => {
  it('渲染患者/就诊/结算徽标', () => {
    render(<SessionAnchorBar anchor={makeAnchor()} />)
    expect(screen.getByText('患者 P001')).toBeInTheDocument()
    expect(screen.getByText('就诊 E001')).toBeInTheDocument()
    expect(screen.getByText('结算 1671213')).toBeInTheDocument()
  })

  it('无结算单时显示未锚定提示', () => {
    render(<SessionAnchorBar anchor={makeAnchor({ settlementId: null })} />)
    expect(screen.getByText(/未锚定结算单/)).toBeInTheDocument()
  })

  it('渲染话题徽标', () => {
    render(<SessionAnchorBar anchor={makeAnchor({ topic: '统筹自付偏少' })} />)
    expect(screen.getByText('话题 统筹自付偏少')).toBeInTheDocument()
  })

  it('subject_changed=true 时渲染主体切换横幅', () => {
    render(
      <SessionAnchorBar
        anchor={makeAnchor({
          subjectChanged: true,
          subjectChangeMsg: '已切换业务主体，旧结算上下文已清除',
        })}
      />,
    )
    expect(screen.getByTestId('subject-change-banner')).toBeInTheDocument()
    expect(screen.getByText(/已切换业务主体/)).toBeInTheDocument()
  })

  it('subject_changed=false 时不渲染横幅', () => {
    render(<SessionAnchorBar anchor={makeAnchor()} />)
    expect(screen.queryByTestId('subject-change-banner')).toBeNull()
  })

  it('点击「知道了」触发 onDismissSubjectChange', () => {
    const onDismiss = vi.fn()
    render(
      <SessionAnchorBar
        anchor={makeAnchor({ subjectChanged: true, subjectChangeMsg: 'msg' })}
        onDismissSubjectChange={onDismiss}
      />,
    )
    fireEvent.click(screen.getByText('知道了'))
    expect(onDismiss).toHaveBeenCalledTimes(1)
  })

  it('展示 sessionId（调试信息）', () => {
    render(<SessionAnchorBar anchor={makeAnchor()} sessionId="sess-abc" />)
    expect(screen.getByText('session: sess-abc')).toBeInTheDocument()
  })
})
