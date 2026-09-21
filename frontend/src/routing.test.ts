import { describe, expect, it } from 'vitest'

import { buildMatchDetailHash, matchDetailRoute } from './routing'

describe('比赛详情哈希路由', () => {
  it('往返保留比赛 ID 和原历史筛选地址', () => {
    const returnHash = '#history?season=2015&page=12&pageSize=20'
    const hash = buildMatchDetailHash('sporttery:70001', returnHash)
    expect(matchDetailRoute(hash)).toEqual({ matchId: 'sporttery:70001', returnHash })
  })

  it('缺少返回地址时回退到历史列表', () => {
    expect(matchDetailRoute('#history/match/sporttery%3A70001')).toEqual({
      matchId: 'sporttery:70001',
      returnHash: '#history',
    })
  })

  it('拒绝历史列表以外的返回地址', () => {
    expect(matchDetailRoute('#history/match/abc?return=javascript%3Aalert(1)')).toEqual({
      matchId: 'abc',
      returnHash: '#history',
    })
  })

  it('畸形比赛 ID 编码不会让应用崩溃', () => {
    expect(matchDetailRoute('#history/match/%E0%A4%A')).toBeNull()
  })
})
