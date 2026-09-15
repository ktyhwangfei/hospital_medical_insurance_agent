import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AgentSwitcher from '@/components/policy-qa/agent-switcher'

afterEach(() => cleanup())

describe('AgentSwitcher', () => {
  it('渲染三个智能体 chip，当前智能体 aria-pressed 高亮', () => {
    render(<AgentSwitcher agent="policy" onChange={() => {}} />)

    expect(screen.getByTestId('agent-switcher-policy')).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByTestId('agent-switcher-settlement')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByTestId('agent-switcher-ops')).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByText('政策问答')).toBeInTheDocument()
    expect(screen.getByText('结算解释')).toBeInTheDocument()
    expect(screen.getByText('运营问数')).toBeInTheDocument()
  })

  it('点击 chip 触发 onChange(id)', () => {
    const onChange = vi.fn()
    render(<AgentSwitcher agent="policy" onChange={onChange} />)

    fireEvent.click(screen.getByTestId('agent-switcher-ops'))
    expect(onChange).toHaveBeenCalledWith('ops')

    fireEvent.click(screen.getByTestId('agent-switcher-settlement'))
    expect(onChange).toHaveBeenCalledWith('settlement')
  })

  it('disabled 时禁止切换', () => {
    const onChange = vi.fn()
    render(<AgentSwitcher agent="policy" onChange={onChange} disabled />)

    const chip = screen.getByTestId('agent-switcher-ops')
    expect(chip).toBeDisabled()
    fireEvent.click(chip)
    expect(onChange).not.toHaveBeenCalled()
  })
})
