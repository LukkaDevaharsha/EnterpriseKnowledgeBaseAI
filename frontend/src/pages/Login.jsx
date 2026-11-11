import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { ErrorMessage } from '../components/Feedback'

export default function Login() {
  const { login, token, user, loading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ identifier: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (loading) return <div className="auth-loading">Restoring session…</div>
  if (token && user) return <Navigate to="/" replace />
  async function submit(event) {
    event.preventDefault(); if (busy) return; setError('')
    if (!form.identifier.trim() || !form.password) { setError('Enter your work email or Employee ID and password.'); return }
    setBusy(true)
    try { await login({ identifier: form.identifier.trim(), password: form.password }); navigate(location.state?.from?.pathname || '/', { replace: true }) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return <main className="auth-page"><div className="auth-aside"><div className="auth-brand"><span className="brand-mark" aria-hidden="true"><svg className="brand-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5v-16Z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20M8 7h8M8 10.5h6"/></svg></span> Knowledge Base</div><div className="auth-pitch"><span className="eyebrow">YOUR COMPANY KNOWLEDGE</span><h1>Find the answers that move work forward.</h1><p>A single, searchable home for the policies and information your team relies on.</p><div className="auth-decoration" aria-hidden="true"><span>◈</span><i /><i /><i /></div></div><small className="auth-foot">Enterprise Knowledge Base</small></div><section className="auth-main"><div className="auth-form-wrap"><span className="eyebrow">WELCOME BACK</span><h2>Sign in to your workspace</h2><p className="auth-subtitle">Use your employee account to continue.</p><ErrorMessage>{error}</ErrorMessage><form onSubmit={submit} className="form-stack">
      <label htmlFor="identifier">Work email or Employee ID</label><input id="identifier" type="text" autoComplete="username" required maxLength={255} value={form.identifier} onChange={(e) => setForm({ ...form, identifier: e.target.value })} placeholder="you@company.com or EMP000001" />
      <label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Enter your password" />
      <button className="button button-primary button-full" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}<span aria-hidden="true">→</span></button>
    </form><p className="auth-switch">New to the workspace? <Link to="/register">Create an employee account</Link></p></div></section></main>
}
