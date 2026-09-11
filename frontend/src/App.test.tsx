import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('Dashboard shell', () => {
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
