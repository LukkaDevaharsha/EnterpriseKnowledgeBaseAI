import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { adminApi, documentsApi } from '../api/client'
import { EmptyState, ErrorMessage, PageLoading } from '../components/Feedback'
import { useAuth } from '../context/useAuth'
import { getDistinctFilename, getDocumentTitle } from '../utils/documentName'

const fmtDate = (v) => v ? new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '—'

function MetricIcon({ name }) {
  if (name === 'people') return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8" r="3" /><path d="M3.5 19a5.5 5.5 0 0 1 11 0M16 5.5a3 3 0 0 1 0 5.8M17 14a4.8 4.8 0 0 1 3.5 4.6" /></svg>
  if (name === 'layers') return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 9 5-9 5-9-5 9-5Z" /><path d="m3 12 9 5 9-5M3 16l9 5 9-5" /></svg>
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4V21H6a2 2 0 0 1-2-2V5.5a2 2 0 0 1 2-2Z" /><path d="M14 4v5h5M8 13h8M8 17h8" /></svg>
}

function ActionIcon({ name }) {
  const paths = {
    upload: <><path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" /><path d="M5 14v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4.5 4.5" /></>,
    ask: <><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-8.5a7.5 7.5 0 1 1 17 0Z" /><path d="M9 10h.01M12 10h.01M15 10h.01" /></>,
    study: <><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v18H6.5A2.5 2.5 0 0 0 4 22V4.5Z" /><path d="M4 18a2.5 2.5 0 0 1 2.5-2H20M8 7h8M8 11h8" /></>,
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>
}

export default function Dashboard() {
  const { token, user } = useAuth()
  const [data, setData] = useState(null)
  const [adminStats, setAdminStats] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reloadCount, setReloadCount] = useState(0)

  useEffect(() => {
    let active = true
    const load = user?.role === 'ADMIN'
      ? Promise.all([adminApi.documents(token), adminApi.stats(token)]).then(([documents, statistics]) => {
        if (active) { setData(documents); setAdminStats(statistics.stats) }
      })
      : documentsApi.list(token, 1, 5).then((documents) => { if (active) setData(documents) })
    load.catch((err) => { if (active) setError(err.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, user?.role, reloadCount])

  const docs = data?.documents || []
  const isAdmin = user?.role === 'ADMIN'

  const statCards = isAdmin ? [
    { label: 'Employees', value: adminStats?.employees ?? '—', to: '/admin', accentClass: 'accent-blue', icon: 'people' },
    { label: 'Shared documents', value: adminStats?.shared_documents ?? '—', to: '/admin', accentClass: 'accent-indigo', icon: 'document' },
    { label: 'Indexed chunks', value: adminStats?.indexed_chunks ?? '—', to: '/admin', accentClass: 'accent-green', icon: 'layers' },
  ] : [
    { label: 'Your documents', value: loading ? '—' : data?.pagination?.total ?? 0, to: '/library', accentClass: 'accent-blue', icon: 'document' },
  ]

  return (
    <div className="page-content">
      <div className="welcome-banner">
        <div className="welcome-text">
          <span className="eyebrow">YOUR KNOWLEDGE WORKSPACE</span>
          <h1>Welcome back, {user?.name?.split(' ')[0] || 'there'}.</h1>
          <p>Find trusted information across your team's documents.</p>
          <Link to="/library" className="button button-primary button-small">Open Knowledge Library <span aria-hidden="true">→</span></Link>
        </div>
      </div>

      <ErrorMessage>{error}</ErrorMessage>
      {error && <button className="button button-secondary button-small retry-button"
        onClick={() => { setError(''); setLoading(true); setReloadCount((c) => c + 1) }}>Retry</button>}

      <div className="dashboard-stats">
        {statCards.map((s) => (
          <Link key={s.label} to={s.to} className={`stat-card ${s.accentClass}`}>
            <span className={`stat-icon ${s.accentClass}`}><MetricIcon name={s.icon} /></span>
            <span className="stat-copy"><span className="stat-label">{s.label}</span><strong className="stat-value">{s.value}</strong></span>
          </Link>
        ))}
      </div>

      <div className="dashboard-grid">
        <section className="panel recent-docs">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">{isAdmin ? 'WORKSPACE FILES' : 'YOUR LIBRARY'}</span>
              <h2>Recent documents</h2>
            </div>
            <Link className="button button-secondary button-small" to={isAdmin ? '/admin' : '/library'}>
              {isAdmin ? 'Administration' : 'View all'}
            </Link>
          </div>
          {loading
            ? <PageLoading label="Loading…" />
            : error ? null
            : docs.length === 0
              ? <EmptyState title="Library is empty" action={<Link className="button button-primary button-small" to="/library">Upload a document</Link>}>Add a PDF or TXT to make knowledge searchable.</EmptyState>
              : <div className="recent-list">
                {docs.slice(0, 5).map((doc) => {
                  const title = getDocumentTitle(doc)
                  const filename = getDistinctFilename(doc)
                  return (
                  <div className="recent-row" key={doc.id}>
                    <span className={`file-badge ${doc.file_type === 'PDF' ? 'pdf' : 'txt'}`}>{doc.file_type}</span>
                    <div className="recent-info">
                      <strong title={title}>{title}</strong>
                      <div className="recent-meta">
                        {filename && <span title={filename}>{filename}</span>}
                        <time dateTime={doc.created_at || undefined}>Added {fmtDate(doc.created_at)}</time>
                      </div>
                    </div>
                    <span className={`status-pill status-${doc.status?.toLowerCase()}`}>{doc.status?.replaceAll('_', ' ')}</span>
                  </div>
                )})}
              </div>
          }
        </section>

        <section className="quick-actions panel">
          <div className="panel-heading"><div><span className="eyebrow">QUICK ACTIONS</span><h2>Get started</h2></div></div>
          <div className="quick-list">
            <Link className="quick-item" to="/library">
              <span className="quick-icon"><ActionIcon name="upload" /></span>
              <span><strong>Upload document</strong><small>Add a PDF or text file</small></span>
            </Link>
            <Link className="quick-item" to="/library?tab=search">
              <span className="quick-icon"><ActionIcon name="search" /></span>
              <span><strong>Search library</strong><small>Find passages by topic or question</small></span>
            </Link>
            <Link className="quick-item" to="/ask">
              <span className="quick-icon"><ActionIcon name="ask" /></span>
              <span><strong>Ask BaseAI</strong><small>Get an evidence-grounded answer</small></span>
            </Link>
            <Link className="quick-item" to="/study">
              <span className="quick-icon"><ActionIcon name="study" /></span>
              <span><strong>Study PDFs</strong><small>Read and search authorized PDFs</small></span>
            </Link>
          </div>
        </section>
      </div>
    </div>
  )
}
