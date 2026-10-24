import { BrowserRouter, Link, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import AuthProvider from './context/AuthContext'
import { useAuth } from './context/useAuth'
import ProtectedRoute from './components/ProtectedRoute'
import Navbar from './components/Navbar'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import Library from './pages/Library'
import AskQuestion from './pages/AskQuestion'
import Admin from './pages/Admin'
import StudyPDF from './pages/StudyPDF'
import './App.css'

const PAGE_TITLES = {
  '/': 'Home',
  '/library': 'Knowledge Library',
  '/ask': 'Ask BaseAI',
  '/study': 'Study PDFs',
  '/admin': 'Administration',
}

function ApplicationLayout() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const navigate = useNavigate()
  function signOut() { logout(); navigate('/login', { replace: true }) }
  const pageTitle = PAGE_TITLES[location.pathname] || 'Knowledge Base'

  return (
    <div className="app-shell">
      <Navbar mobileOpen={mobileNavOpen} onNavigate={() => setMobileNavOpen(false)} />
      {mobileNavOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <main className="main-area">
        <header className="topbar">
          <div className="topbar-leading">
            <button type="button" className="mobile-nav-toggle"
              aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'}
              aria-expanded={mobileNavOpen}
              onClick={() => setMobileNavOpen((o) => !o)}>
              <span /><span /><span />
            </button>
            <div className="breadcrumb">
              <span>Workspace</span>
              <span className="breadcrumb-sep">/</span>
              <strong>{pageTitle}</strong>
            </div>
          </div>
          <div className="header-actions">
            <div className="profile-summary">
              <span className="profile-avatar">{user?.name?.trim()?.[0]?.toUpperCase() || 'U'}</span>
              <span className="profile-meta">
                <strong>{user?.name || 'Employee'}</strong>
                <small>{user?.role === 'ADMIN' ? 'Administrator' : user?.department || 'Employee'}</small>
              </span>
            </div>
            <span className="header-divider" />
            <button type="button" className="header-logout" onClick={signOut}>Sign out</button>
          </div>
        </header>
        <Outlet />
        <footer className="app-footer">
          <span>Enterprise Knowledge Base</span>
          <Link to="/library">Browse your library</Link>
        </footer>
      </main>
    </div>
  )
}

function AdminRoute({ children }) {
  const { user } = useAuth()
  return user?.role === 'ADMIN' ? children : <Navigate to="/" replace />
}

function NotFound() {
  const { token, user, loading } = useAuth()
  if (loading) return <div className="route-loading">Restoring your session…</div>
  return (
    <div className="not-found">
      <span className="eyebrow">404 · PAGE NOT FOUND</span>
      <h1>This page isn't in the library.</h1>
      <p>The address may be out of date or the page may have moved.</p>
      <Link className="button button-primary" to={token && user ? '/' : '/login'}>Return to workspace</Link>
    </div>
  )
}

function RouteTree() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route element={<ProtectedRoute><ApplicationLayout /></ProtectedRoute>}>
        <Route index element={<Dashboard />} />
        <Route path="library" element={<Library />} />
        <Route path="ask" element={<AskQuestion />} />
        <Route path="study" element={<StudyPDF />} />
        <Route path="admin" element={<AdminRoute><Admin /></AdminRoute>} />
        {/* Legacy redirects */}
        <Route path="documents" element={<Navigate to="/library" replace />} />
        <Route path="search" element={<Navigate to="/library" replace />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}

export default function App() {
  return <BrowserRouter><AuthProvider><RouteTree /></AuthProvider></BrowserRouter>
}
