import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import App from './App'

vi.mock('./features/history/api', () => ({
  fetchDataSummary: vi.fn(() => new Promise(() => {})),
  fetchMatchPage: vi.fn(() => new Promise(() => {})),
}))

afterEach(() => {
  cleanup()
  window.history.replaceState(null, '', '/')
})

describe('Dashboard shell', () => {
  it('opens the historical match route and returns to today', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('link', { name: '历史比赛' }))
    expect(await screen.findByRole('heading', { name: '历史比赛' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '历史比赛' })).toHaveAttribute('aria-current', 'page')
    act(() => {
      window.location.hash = '#今日赛事'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(screen.getByRole('heading', { name: '今日赛事分析' })).toBeInTheDocument()
  })

  it('shows the core analysis areas and makes unavailable predictions explicit', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', { name: '今日赛事分析' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toHaveTextContent('今日赛事')
    expect(screen.getByRole('navigation')).toHaveTextContent('历史回测')
    expect(screen.getByRole('navigation')).toHaveTextContent('数据质量')
    expect(screen.getByRole('navigation')).toHaveTextContent('模型管理')
    expect(screen.getByText('预测模型尚未接入')).toBeInTheDocument()
    expect(screen.getByText(/仅供分析与研究/)).toBeInTheDocument()
  })
})
