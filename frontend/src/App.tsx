import {
  Activity,
  BarChart3,
  CalendarDays,
  CircleGauge,
  DatabaseZap,
  ShieldCheck,
} from 'lucide-react'

const navigation = [
  { label: '今日赛事', icon: CalendarDays, current: true },
  { label: '历史回测', icon: BarChart3, current: false },
  { label: '数据质量', icon: DatabaseZap, current: false },
  { label: '模型管理', icon: CircleGauge, current: false },
]

const foundationItems = [
  { label: '前端工作台', detail: 'React + TypeScript', ready: true },
  { label: '后端服务', detail: 'FastAPI', ready: true },
  { label: '预测模型', detail: '等待后续模块', ready: false },
]

function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>

        <div className="brand-copy">
          <p className="eyebrow">AI Football Predictor</p>
          <p className="brand-title">赛前分析台</p>
        </div>

        <nav aria-label="主要导航" className="primary-nav">
          {navigation.map(({ label, icon: Icon, current }) => (
            <a
              aria-current={current ? 'page' : undefined}
              className="nav-link"
              href={`#${label}`}
              key={label}
            >
              <Icon aria-hidden="true" size={19} strokeWidth={1.75} />
              <span>{label}</span>
              {!current && <span className="coming-soon">待建</span>}
            </a>
          ))}
        </nav>

        <div className="sidebar-note">
          <ShieldCheck aria-hidden="true" size={18} />
          <p>概率不是结果。所有输出必须附带数据时间与质量说明。</p>
        </div>
      </aside>

      <main className="main-content">
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
              <p className="eyebrow">Foundation status</p>
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
            <p className="eyebrow">Next module</p>
            <h2 id="empty-title">预测模型尚未接入</h2>
            <p>
              当前页面只验证项目结构和前后端运行基础，不展示示例胜率，避免把占位数据误认为真实预测。
            </p>
          </div>
        </section>

        <footer className="research-notice">
          <span>研究边界</span>
          <p>本系统仅供分析与研究，不承诺收益，也不提供自动购票功能。</p>
        </footer>
      </main>
    </div>
  )
}

export default App
