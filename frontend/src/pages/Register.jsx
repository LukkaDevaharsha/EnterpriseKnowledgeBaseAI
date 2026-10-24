import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../context/useAuth'
import { ErrorMessage } from '../components/Feedback'
import { authApi } from '../api/client'

const INITIAL_FORM = { name: '', email: '', department: '', password: '' }

export default function Register() {
  const { register, token, user, loading } = useAuth()
  const [form, setForm] = useState(INITIAL_FORM)
  const [pendingEmail, setPendingEmail] = useState(() => sessionStorage.getItem('pendingRegistrationEmail') || '')
  const [code, setCode] = useState('')
  const [verifiedUser, setVerifiedUser] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  if (loading) return <div className="auth-loading">Restoring session…</div>
  if (token && user) return <Navigate to="/" replace />

  async function submitRegistration(event) {
    event.preventDefault()
    if (busy) return
    setError(''); setNotice('')
    if (form.name.trim().length === 0 || form.department.trim().length === 0) {
      setError('Enter your name and department.'); return
    }
    if (form.password.length < 8 || form.password.length > 128) {
      setError('Password must be between 8 and 128 characters.'); return
    }
    setBusy(true)
    try {
      const email = form.email.trim().toLowerCase()
      const result = await register({
        name: form.name.trim(), email, department: form.department.trim(), password: form.password,
      })
      setPendingEmail(email)
      sessionStorage.setItem('pendingRegistrationEmail', email)
      setNotice(result.message || 'Check your email for a verification code.')
    } catch (err) {
      setError(err.payload?.errors ? Object.values(err.payload.errors).join(' ') : err.message)
    } finally { setBusy(false) }
  }

  async function verify(event) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      const payload = await authApi.verify({ email: pendingEmail, code })
      setVerifiedUser(payload.user)
      sessionStorage.removeItem('pendingRegistrationEmail')
      setNotice(payload.message || 'Email verified.')
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function resend() {
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    try {
      const payload = await authApi.resendVerification(pendingEmail)
      setNotice(payload?.message || 'If registration is pending, a new code will be sent when allowed.')
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  return <main className="auth-page"><div className="auth-aside"><div className="auth-brand"><span className="brand-mark">K</span> Knowledge Base</div><div className="auth-pitch"><span className="eyebrow">BUILT FOR YOUR TEAM</span><h1>Good work starts with shared knowledge.</h1><p>Create your employee account to search trusted company documents and get grounded answers.</p><div className="auth-decoration" aria-hidden="true"><span>◈</span><i /><i /><i /></div></div><small className="auth-foot">Enterprise Knowledge Base</small></div>
    <section className="auth-main"><div className="auth-form-wrap register-wrap"><span className="eyebrow">GET STARTED</span><h2>{verifiedUser ? 'Your email is verified' : pendingEmail ? 'Check your inbox' : 'Create your account'}</h2>
      <p className="auth-subtitle">{verifiedUser ? 'Your employee account is ready.' : pendingEmail ? `Enter the six-digit code sent to ${pendingEmail}.` : 'Register with your employee details.'}</p>
      <ErrorMessage>{error}</ErrorMessage>{notice && <div className="alert alert-success" role="status">{notice}</div>}
      {verifiedUser ? <div className="verified-account"><span className="verified-check">✓</span><p>Employee ID</p><strong>{verifiedUser.employee_id}</strong><Link className="button button-primary button-full" to="/login">Continue to sign in <span>→</span></Link></div> : pendingEmail ? <form onSubmit={verify} className="form-stack"><label htmlFor="verification-code">Verification code</label><input id="verification-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} placeholder="000000" /><button className="button button-primary button-full" disabled={busy || code.length !== 6}>{busy ? 'Verifying…' : 'Verify email'}<span>→</span></button><button type="button" className="resend-button" onClick={resend} disabled={busy}>Resend code</button></form> : <form onSubmit={submitRegistration} className="form-stack register-grid">
        <div><label htmlFor="name">Full name</label><input id="name" required maxLength={120} autoComplete="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Jordan Lee" /></div>
        <div><label htmlFor="register-email">Work email</label><input id="register-email" type="email" required maxLength={255} autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@company.com" /></div>
        <div className="field-wide"><label htmlFor="department">Department</label><input id="department" required maxLength={100} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} placeholder="Department" /></div>
        <div className="field-wide"><label htmlFor="new-password">Password</label><input id="new-password" type="password" autoComplete="new-password" required minLength={8} maxLength={128} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><small className="field-hint">Use 8 to 128 characters.</small></div>
        <button className="button button-primary button-full field-wide" disabled={busy}>{busy ? 'Sending verification…' : 'Create employee account'}<span>→</span></button>
      </form>}
      {!verifiedUser && <p className="auth-switch">Already registered? <Link to="/login">Sign in</Link></p>}
    </div></section></main>
}
