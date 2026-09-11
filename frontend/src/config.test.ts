import { afterEach, describe, expect, it, vi } from 'vitest'

describe('前端配置', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('使用 VITE_API_BASE_URL 作为后端接口地址', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.example.test')

    const { API_BASE_URL } = await import('./config')

    expect(API_BASE_URL).toBe('https://api.example.test')
  })
})
