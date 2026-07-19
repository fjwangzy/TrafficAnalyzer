import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RouteErrorBoundary } from './RouterApp'

describe('route infrastructure', () => {
  it('contains a page crash and offers a recovery action', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    function BrokenPage() { throw new Error('page exploded') }

    render(<RouteErrorBoundary><BrokenPage /></RouteErrorBoundary>)

    expect(screen.getByRole('heading', { name: '页面加载失败' })).toBeInTheDocument()
    expect(screen.getByText('page exploded')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新加载页面' })).toBeInTheDocument()
  })
})
