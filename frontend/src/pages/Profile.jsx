import { useState } from 'react'
import { authApi } from '../api/client'
import { ErrorMessage } from '../components/Feedback'
import { useAuth } from '../context/useAuth'

export default function Profile() {
  const { token, user, updateUser } = useAuth()
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(user?.name || '')
  const [department, setDepartment] = useState(user?.department || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('')
    try {
      const result = await authApi.updateProfile(token, { name, department })
      updateUser(result.user); setName(result.user.name); setDepartment(result.user.department)
      setEditing(false); setNotice('Your profile has been updated.')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  function cancel() { setName(user?.name || ''); setDepartment(user?.department || ''); setError(''); setEditing(false) }
  return <div className="page-content profile-page">
    <header className="page-heading"><div><span className="eyebrow">ACCOUNT</span><h1>My Profile</h1><p>View and manage your personal information.</p></div>
      {!editing && <button className="button button-primary" onClick={() => { setError(''); setNotice(''); setEditing(true) }}>Edit Profile</button>}
    </header>
    <section className="panel profile-card" aria-label="Personal information">
      <div className="profile-card-heading"><span className="profile-avatar profile-avatar-large">{user?.name?.trim()?.[0]?.toUpperCase() || 'U'}</span><div><h2>{user?.name}</h2><p>{user?.role === 'ADMIN' ? 'Administrator' : 'Employee'}</p></div></div>
      {notice && <p className="profile-success" role="status">{notice}</p>}<ErrorMessage>{error}</ErrorMessage>
      {editing ? <form className="profile-form" onSubmit={save}>
        <label>Full Name<input value={name} maxLength={120} required onChange={(event) => setName(event.target.value)} /></label>
        <label>Email Address<input value={user?.email || ''} readOnly disabled /></label>
        <label>Department<input value={department} maxLength={100} required onChange={(event) => setDepartment(event.target.value)} /></label>
        <label>Employee ID<input value={user?.employee_id || ''} readOnly disabled /></label>
        <div className="profile-actions"><button type="button" className="button button-secondary" disabled={busy} onClick={cancel}>Cancel</button><button className="button button-primary" disabled={busy || !name.trim() || !department.trim()}>{busy ? 'Saving…' : 'Save Changes'}</button></div>
      </form> : <dl className="profile-details"><div><dt>Full Name</dt><dd>{user?.name || '—'}</dd></div><div><dt>Email Address</dt><dd>{user?.email || '—'}</dd></div><div><dt>Department</dt><dd>{user?.department || '—'}</dd></div><div><dt>Employee ID</dt><dd>{user?.employee_id || '—'}</dd></div><div><dt>Account created</dt><dd>{user?.created_at ? new Date(user.created_at).toLocaleDateString() : '—'}</dd></div></dl>}
    </section>
  </div>
}
