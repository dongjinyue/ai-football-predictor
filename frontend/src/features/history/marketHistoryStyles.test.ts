import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

describe('市场详情布局样式', () => {
  it('keeps wide odds tables scrollable with a stable time column on small screens', () => {
    // 兼容从 frontend 目录或代码仓库根目录执行 Vitest（测试框架）。
    const localPath = resolve(process.cwd(), 'src/index.css')
    const cssPath = existsSync(localPath) ? localPath : resolve(process.cwd(), 'frontend/src/index.css')
    const css = readFileSync(cssPath, 'utf8')

    expect(css).toMatch(/\.odds-timeline-scroll\s*\{[^}]*overflow-x:\s*auto/s)
    expect(css).toMatch(/\.odds-timeline-table\s*\{[^}]*min-width:/s)
    expect(css).toMatch(/\.odds-timeline-table[^}]*th:first-child[^}]*position:\s*sticky/s)
    expect(css).toMatch(/@media\s*\(max-width:\s*640px\)[\s\S]*\.market-match-summary/s)
  })
})
