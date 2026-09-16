import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('浏览器图标', () => {
  it('提供页面引用的本地 favicon，避免浏览器产生 404', () => {
    const projectRoot = process.cwd()
    const indexHtml = readFileSync(resolve(projectRoot, 'index.html'), 'utf8')

    expect(indexHtml).toContain('href="/favicon.svg"')
    expect(existsSync(resolve(projectRoot, 'public', 'favicon.svg'))).toBe(true)
  })
})
