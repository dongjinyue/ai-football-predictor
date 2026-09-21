import { useEffect, useState } from 'react'
import {
  Activity,
  BarChart3,
  CalendarDays,
  CircleGauge,
  DatabaseZap,
  ShieldCheck,
} from 'lucide-react'
import HistoryPage from './features/history/HistoryPage'
import MatchMarketHistoryPage from './features/history/MatchMarketHistoryPage'
import DataQualityPage from './features/quality/DataQualityPage'
import { hashRoute, matchDetailRoute, normalizeLocation } from './routing'

const navigation = [
  { label: '今日赛事', route: 'today', icon: CalendarDays, ready: true },
  { label: '历史比赛', route: 'history', icon: CalendarDays, ready: true },
  { label: '历史回测', route: 'backtest', icon: BarChart3, ready: false },
  { label: '数据质量', route: 'quality', icon: DatabaseZap, ready: true },
  { label: '模型管理', route: 'models', icon: CircleGauge, ready: false },
]

const foundationItems = [
  { label: '前端工作台', detail: '前端界面', ready: true },
  { label: '后端服务', detail: '接口服务', ready: true },
  { label: '预测模型', detail: '等待后续模块', ready: false },
]

function App() {
  const [hash, setHash] = useState(() => normalizeLocation(new URL(window.location.href)).hash)
  const activeRoute = hashRoute(hash) || 'today'
  const detailRoute = matchDetailRoute(hash)
  const isMatchDetail = detailRoute !== null
  const isHistory = activeRoute === 'history' || detailRoute !== null
  const isQuality = activeRoute === 'quality'

  useEffect(() => {
    const updateHash = () => {
      const currentUrl = new URL(window.location.href)
      const normalizedUrl = normalizeLocation(currentUrl)
      const normalizedHash = normalizedUrl.hash
      const currentLocation = `${window.location.pathname}${window.location.search}${window.location.hash}`
      const normalizedLocation = `${normalizedUrl.pathname}${normalizedUrl.search}${normalizedUrl.hash}`

      if (normalizedLocation !== currentLocation) {
        window.history.replaceState(null, '', normalizedLocation)
      }

      setHash(normalizedHash)
    }

    window.addEventListener('hashchange', updateHash)
    updateHash()
    return () => window.removeEventListener('hashchange', updateHash)
  }, [])

  useEffect(() => {
    const pageTitles: Record<string, string> = {
      history: '历史比赛',
      quality: '数据质量',
      today: '今日赛事分析',
    }
    const pageTitle = isMatchDetail ? '市场详情' : pageTitles[activeRoute] ?? pageTitles.today
    document.title = `${pageTitle} · 赛前分析台`
  }, [activeRoute, isMatchDetail])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>

        <div className="brand-copy">
          <p className="eyebrow">智能足球预测</p>
          <p className="brand-title">赛前分析台</p>
        </div>

        <nav aria-label="主要导航" className="primary-nav">
          {navigation.map(({ label, route, icon: Icon, ready }) => (
            <a
              aria-current={(route === activeRoute || route === 'history' && isHistory) ? 'page' : undefined}
              className="nav-link"
              href={`#${route}`}
              key={label}
            >
              <Icon aria-hidden="true" size={19} strokeWidth={1.75} />
              <span>{label}</span>
              {!ready && <span className="coming-soon">待建</span>}
            </a>
          ))}
        </nav>

        <div className="sidebar-note">
          <ShieldCheck aria-hidden="true" size={18} />
          <p>概率不是结果。所有输出必须附带数据时间与质量说明。</p>
        </div>
      </aside>

      <main className="main-content">
        {detailRoute ? <MatchMarketHistoryPage
          matchId={detailRoute.matchId}
          returnHash={detailRoute.returnHash}
        /> : isHistory ? <HistoryPage /> : isQuality ? <DataQualityPage /> : <>
        <header className="page-header">
          <div>
            <p className="eyebrow page-index">工作台 / 基础骨架</p>
            <h1>今日赛事分析</h1>
            <p className="page-summary">
              项目结构已经就位。真实赛事、概率与模型解释将在后续模块接入。
            </p>
          </div>

          <div className="system-state" role="status">
            <span className="state-dot" aria-hidden="true" />
            基础服务可用
          </div>
        </header>

        <section className="status-board" aria-labelledby="foundation-title">
          <div className="board-heading">
            <div>
              <p className="eyebrow">基础状态</p>
              <h2 id="foundation-title">基础模块状态</h2>
            </div>
            <Activity aria-hidden="true" size={24} strokeWidth={1.5} />
          </div>

          <div className="foundation-grid">
            {foundationItems.map((item) => (
              <article className="foundation-item" key={item.label}>
                <div className="item-line">
                  <span>{item.label}</span>
                  <span className={item.ready ? 'tag ready' : 'tag pending'}>
                    {item.ready ? '已就绪' : '未接入'}
                  </span>
                </div>
                <p>{item.detail}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="empty-state" aria-labelledby="empty-title">
          <div className="pitch-orbit" aria-hidden="true">
            <span className="pitch-center" />
          </div>
          <div>
            <p className="eyebrow">后续模块</p>
            <h2 id="empty-title">预测模型尚未接入</h2>
            <p>
              当前页面只验证项目结构和前后端运行基础，不展示示例胜率，避免把占位数据误认为真实预测。
            </p>
          </div>
        </section>

        </>}
        <footer className="research-notice">
          <span>研究边界</span>
          <p>本系统仅供分析与研究，不承诺收益，也不提供自动购票功能。</p>
        </footer>
      </main>
    </div>
  )
}

export default App
