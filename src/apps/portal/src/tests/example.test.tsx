import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

function HelloWorld({ name = 'World' }: { name?: string }) {
  return <div>Hello, {name}!</div>
}

describe('HelloWorld', () => {
  it('renders greeting', () => {
    render(<HelloWorld />)
    expect(screen.getByText('Hello, World!')).toBeInTheDocument()
  })

  it('renders with custom name', () => {
    render(<HelloWorld name="Vitest" />)
    expect(screen.getByText('Hello, Vitest!')).toBeInTheDocument()
  })
})
