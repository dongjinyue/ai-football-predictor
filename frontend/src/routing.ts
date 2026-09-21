const legacyHashRoutes: Record<string, string> = {
  '#今日赛事': '#today',
  '#历史比赛': '#history',
  '#历史回测': '#backtest',
  '#数据质量': '#quality',
  '#模型管理': '#models',
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    // 地址栏中的异常编码保持原值，避免规范化过程阻断页面加载。
    return value
  }
}

/** 读取哈希中的页面路由，不读取路由后面的查询参数。 */
export function hashRoute(value: string): string {
  const routePart = value.replace(/^#/, '').split('?')[0]
  if (!routePart) return ''

  const decodedRoute = safeDecode(routePart)
  const legacyRoute = legacyHashRoutes[`#${routePart}`] ?? legacyHashRoutes[`#${decodedRoute}`]
  return (legacyRoute ?? `#${routePart}`).slice(1)
}

/** 读取 `#history?` 后面的查询参数。 */
export function hashParams(value: string): URLSearchParams {
  const queryStart = value.indexOf('?')
  return queryStart === -1 ? new URLSearchParams() : new URLSearchParams(value.slice(queryStart + 1))
}

/** 将路由和查询参数拼成稳定的哈希地址。 */
export function buildHash(route: string, params: URLSearchParams = new URLSearchParams()): string {
  const query = params.toString()
  return `#${route}${query ? `?${query}` : ''}`
}

/** 创建详情地址，并把当前列表哈希作为返回目标保存。 */
export function buildMatchDetailHash(matchId: string, returnHash: string): string {
  const params = new URLSearchParams({ return: returnHash || '#history' })
  return buildHash(`history/match/${encodeURIComponent(matchId)}`, params)
}

/** 解析历史比赛详情子路由；非法百分号编码视为无效路由。 */
export function matchDetailRoute(
  value: string,
): { matchId: string; returnHash: string } | null {
  const match = hashRoute(value).match(/^history\/match\/([^/]+)$/)
  if (!match) return null
  try {
    const requestedReturn = hashParams(value).get('return')
    // 返回目标只允许历史列表及其筛选参数，不能把地址栏输入变成任意可执行链接。
    const returnHash = requestedReturn === '#history' || requestedReturn?.startsWith('#history?')
      ? requestedReturn
      : '#history'
    return {
      matchId: decodeURIComponent(match[1]),
      returnHash,
    }
  } catch {
    return null
  }
}

/** 规范化哈希本身，但不移动哈希前面的旧查询参数。 */
export function normalizeHash(value: string): string {
  if (!value || value === '#') return value

  const route = hashRoute(value)
  if (!route) return value
  return buildHash(route, hashParams(value))
}

/** 将历史版本放在 `?` 前面的查询参数迁移到哈希路由后面。 */
export function normalizeLocation(value: URL): URL {
  const normalizedHash = normalizeHash(value.hash)
  const route = hashRoute(normalizedHash)

  if (route === 'history') {
    const params = new URLSearchParams(value.search)
    hashParams(normalizedHash).forEach((entryValue, key) => params.set(key, entryValue))
    value.search = ''
    value.hash = buildHash('history', params).slice(1)
  } else {
    value.hash = normalizedHash.startsWith('#') ? normalizedHash.slice(1) : normalizedHash
  }

  return value
}
