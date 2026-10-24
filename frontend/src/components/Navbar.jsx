import { NavLink } from 'react-router-dom'
import { useAuth } from '../context/useAuth'

const NAV_ICONS = {
  home: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1H5a1 1 0 0 1-2-1V9.5Z" /><path d="M9 21V12h6v9" />
    </svg>
  ),
  library: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 2.75h8l4 4V21H6a2 2 0 0 1-2-2V4.75a2 2 0 0 1 2-2Z" /><path d="M14 3v5h5M8 13h8M8 17h8" />
    </svg>
  ),
  ask: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-8.5a7.5 7.5 0 1 1 17 0Z" /><path d="M8 11h.01M12 11h.01M16 11h.01" />
    </svg>
  ),
  study: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 3.5h13a2 2 0 0 1 2 2v15H6a2 2 0 0 1-2-2v-15Z" /><path d="M7 7h8M7 11h8M7 15h5" />
    </svg>
  ),
  admin: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
    </svg>
  ),
}

const EMPLOYEE_LINKS = [
  { to: '/', label: 'Home', icon: 'home', end: true },
  { to: '/library', label: 'Knowledge Library', icon: 'library' },
  { to: '/ask', label: 'Ask BaseAI', icon: 'ask' },
  { to: '/study', label: 'Study PDFs', icon: 'study' },
]

const ADMIN_EXTRA = [{ to: '/admin', label: 'Administration', icon: 'admin' }]

export default function Navbar({ mobileOpen = false, onNavigate = () => {} }) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'ADMIN'
  const links = isAdmin ? [...EMPLOYEE_LINKS, ...ADMIN_EXTRA] : EMPLOYEE_LINKS

  return (
    <aside className={`sidebar${mobileOpen ? ' sidebar-open' : ''}`}>
      <NavLink className="brand" to="/" aria-label="Enterprise Knowledge Base" onClick={onNavigate}>
        <span className="brand-mark">K</span>
        <span className="brand-name">
          Enterprise KB
          <span>KNOWLEDGE PLATFORM</span>
        </span>
      </NavLink>

      <nav className="side-nav" aria-label="Main navigation">
        {links.map(({ to, label, icon, end }) => (
          <NavLink key={to} to={to} end={end} onClick={onNavigate}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            {NAV_ICONS[icon]}
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-bottom">
        <div className="user-card">
          <span className="avatar">{user?.name?.trim()?.[0]?.toUpperCase() || 'U'}</span>
          <span className="user-meta">
            <strong>{user?.name || 'Employee'}</strong>
            <small>{isAdmin ? 'Administrator' : user?.department || 'Employee'}</small>
          </span>
        </div>
      </div>
    </aside>
  )
}
