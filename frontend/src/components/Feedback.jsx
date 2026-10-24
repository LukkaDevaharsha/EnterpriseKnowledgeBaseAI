export function ErrorMessage({ children }) {
  if (!children) return null
  return <div className="alert alert-error" role="alert">{children}</div>
}

export function PageLoading({ label = 'Loading…' }) {
  return <div className="loading-state" role="status"><span className="spinner" />{label}</div>
}

export function EmptyState({ title, children, action }) {
  return <div className="empty-state"><span className="empty-icon" aria-hidden="true">◇</span><h3>{title}</h3>{children && <p>{children}</p>}{action}</div>
}
