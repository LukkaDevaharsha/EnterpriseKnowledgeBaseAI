import { useCallback, useEffect, useState } from 'react'
import { adminApi } from '../api/client'
import { EmptyState, ErrorMessage, PageLoading } from '../components/Feedback'
import ConfirmDialog from '../components/ConfirmDialog'
import { useAuth } from '../context/useAuth'
import { documentVisibilityLabel } from '../utils/documentVisibility'
import { getDistinctFilename, getDocumentTitle } from '../utils/documentName'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const formatBytes = (size = 0) => size < 1024 * 1024
  ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`

export default function Admin() {
  const { token, user } = useAuth()
  const [stats, setStats] = useState(null)
  const [employees, setEmployees] = useState([])
  const [employeePagination, setEmployeePagination] = useState(null)
  const [employeePage, setEmployeePage] = useState(1)
  const [documents, setDocuments] = useState([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [auditEvents, setAuditEvents] = useState([])
  const [inspectedDocument, setInspectedDocument] = useState(null)
  const [selectedEmployee, setSelectedEmployee] = useState(null)
  const [employeeQuery, setEmployeeQuery] = useState('')
  const [confirmation, setConfirmation] = useState(null)

  const refresh = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true)
    try {
      const [statResult, employeeResult, documentResult, auditResult] = await Promise.all([
        adminApi.stats(token), adminApi.employees(token, employeePage),
        adminApi.documents(token), adminApi.audit(token),
      ])
      setStats(statResult.stats)
      setEmployees(employeeResult.employees || [])
      setEmployeePagination(employeeResult.pagination)
      setDocuments(documentResult.documents || [])
      setAuditEvents(auditResult.events || [])
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [token, employeePage])

  useEffect(() => {
    let active = true
    Promise.all([
      adminApi.stats(token), adminApi.employees(token, employeePage),
      adminApi.documents(token), adminApi.audit(token),
    ]).then(([statResult, employeeResult, documentResult, auditResult]) => {
      if (!active) return
      setStats(statResult.stats)
      setEmployees(employeeResult.employees || [])
      setEmployeePagination(employeeResult.pagination)
      setDocuments(documentResult.documents || [])
      setAuditEvents(auditResult.events || [])
    }).catch((err) => { if (active) setError(err.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token, employeePage])

  async function updateEmployee(employee, changes) {
    setBusy(true); setError(''); setNotice('')
    try {
      await adminApi.updateEmployee(token, employee.id, changes)
      setNotice(`Updated ${employee.name}.`)
      await refresh(false)
      if (selectedEmployee?.id === employee.id) {
        setSelectedEmployee((current) => ({ ...current, ...changes }))
      }
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  function confirmEmployeeUpdate(employee, changes) {
    const title = changes.role
      ? `Change ${employee.name}'s role to ${changes.role}?`
      : `${changes.is_active ? 'Activate' : 'Deactivate'} ${employee.name}'s account?`
    setConfirmation({
      title,
      description: changes.is_active === false
        ? 'The employee will lose access to the workspace until reactivated.'
        : 'This updates the employee account using the existing access controls.',
      confirmLabel: changes.is_active === false ? 'Deactivate account' : 'Confirm update',
      onConfirm: () => {
        setConfirmation(null)
        updateEmployee(employee, changes)
      },
    })
  }

  async function upload(event) {
    event.preventDefault()
    if (busy) return
    const form = event.currentTarget
    const file = form.elements.file.files?.[0]
    if (!file) return
    if (!/\.(pdf|txt)$/i.test(file.name) || file.size === 0 || file.size > MAX_FILE_SIZE) {
      setError('Choose a non-empty PDF or TXT file up to 10 MB.')
      return
    }
    setBusy(true); setError(''); setNotice('')
    try {
      const body = new FormData()
      body.append('file', file)
      if (form.elements.title.value.trim()) body.append('title', form.elements.title.value.trim())
      const result = await adminApi.uploadDocument(token, body)
      setNotice(result.message || 'Shared document uploaded.')
      form.reset()
      await refresh(false)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function deleteDocument(doc) {
    setBusy(true); setError(''); setNotice('')
    try {
      const result = await adminApi.deleteDocument(token, doc.id)
      setNotice(result.message || 'Shared document deleted.')
      if (inspectedDocument?.id === doc.id) setInspectedDocument(null)
      await refresh(false)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function inspectDocument(doc) {
    setError('')
    try {
      const result = await adminApi.inspectDocument(token, doc.id)
      setInspectedDocument(result.document)
    } catch (err) { setError(err.message) }
  }

  const visibleEmployees = employees.filter((employee) =>
    `${employee.name} ${employee.email} ${employee.employee_id} ${employee.department}`
      .toLowerCase().includes(employeeQuery.toLowerCase()))

  return <div className="page-content admin-page">
    <header className="page-heading">
      <div><span className="eyebrow">WORKSPACE CONTROL</span><h1>Administration</h1>
        <p>Manage employee access and the shared knowledge library.</p></div>
      <button className="button button-secondary" type="button" onClick={() => refresh()} disabled={loading || busy}>Refresh data</button>
    </header>
    <ErrorMessage>{error}</ErrorMessage>
    {notice && <div className="alert alert-success" role="status">{notice}</div>}
    {loading ? <PageLoading label="Loading administration data…" /> : <>
      <section className="admin-stat-grid" aria-label="System statistics">
        {Object.entries(stats || {}).map(([key, value]) => <article className="admin-stat-card" key={key}>
          <span className="eyebrow">{key.replaceAll('_', ' ')}</span><strong>{value}</strong>
        </article>)}
      </section>

      <section className="panel admin-section" id="employees">
        <div className="section-header-row"><div><span className="eyebrow">PEOPLE</span><h2>Employee directory</h2>
          <p>Account details and access controls.</p></div>
          <label className="admin-search"><span className="sr-only">Search employees</span>
            <input type="search" value={employeeQuery} onChange={(event) => setEmployeeQuery(event.target.value)} placeholder="Search employees" />
          </label>
        </div>
        {visibleEmployees.length === 0
          ? <EmptyState title={employees.length ? 'No employees match this search' : 'No employee accounts'}>
            {employees.length ? 'Try a name, department, email, or Employee ID.' : 'Employee accounts will appear here.'}
          </EmptyState>
          : <div className="employee-grid">{visibleEmployees.map((employee) => {
            const isCurrentUser = employee.id === user?.id
            return <article className="employee-card" key={employee.id}>
              <div className="employee-card-top"><span className="employee-avatar" aria-hidden="true">{employee.name?.trim()?.[0]?.toUpperCase() || 'E'}</span>
                <div className="employee-identity"><h3>{employee.name}</h3><span>{employee.email}</span></div>
                {isCurrentUser && <span className="status-pill">You</span>}
              </div>
              <dl className="employee-details"><div><dt>Employee ID</dt><dd>{employee.employee_id}</dd></div>
                <div><dt>Department</dt><dd>{employee.department}</dd></div></dl>
              <div className="employee-status-row"><span className="status-pill">{employee.role}</span>
                <span className={`status-pill ${employee.is_active ? 'status-processed' : 'status-processing_failed'}`}>{employee.is_active ? 'Active' : 'Inactive'}</span>
                <span className={`status-pill ${employee.is_verified ? 'status-processed' : 'status-processing_failed'}`}>{employee.is_verified ? 'Verified' : 'Unverified'}</span>
              </div>
              <div className="employee-actions">
                <button type="button" className="button button-tertiary button-small" onClick={() => setSelectedEmployee(employee)}>View profile</button>
                {employee.role !== 'ADMIN' && <label className="employee-role-control">Role
                  <select aria-label={`Role for ${employee.name}`} value={employee.role} disabled={busy || isCurrentUser}
                    onChange={(event) => confirmEmployeeUpdate(employee, { role: event.target.value })}>
                    <option value="EMPLOYEE">Employee</option>
                  </select>
                </label>}
                <button type="button" className={`button button-small ${employee.is_active ? 'button-danger' : 'button-secondary'}`}
                  disabled={busy || (isCurrentUser && employee.is_active)}
                  onClick={() => confirmEmployeeUpdate(employee, { is_active: !employee.is_active })}>
                  {employee.is_active ? 'Deactivate' : 'Activate'}
                </button>
                {isCurrentUser && employee.is_active && <small className="field-hint">You cannot deactivate your own account.</small>}
              </div>
            </article>
          })}</div>}
        {employeePagination?.pages > 1 && <div className="pagination"><span>Page {employeePage} of {employeePagination.pages} · {employeePagination.total} accounts</span>
          <div><button className="button button-secondary button-small" disabled={employeePage <= 1 || loading} onClick={() => setEmployeePage((page) => page - 1)}>Previous</button>
            <button className="button button-secondary button-small" disabled={employeePage >= employeePagination.pages || loading} onClick={() => setEmployeePage((page) => page + 1)}>Next</button></div>
        </div>}
      </section>

      <section className="panel admin-section" id="shared-library">
        <div className="section-header-row"><div><span className="eyebrow">KNOWLEDGE MANAGEMENT</span><h2>Shared Library</h2>
          <p>Employees can retrieve documents after indexing completes successfully.</p></div></div>
        <form className="admin-upload" onSubmit={upload}>
          <label>Title <span className="optional">Optional</span><input name="title" maxLength="255" placeholder="Use the filename if blank" /></label>
          <label>PDF or TXT · up to 10 MB<input name="file" type="file" accept=".pdf,.txt,application/pdf,text/plain" required /></label>
          <button className="button button-primary" disabled={busy}>{busy ? 'Indexing…' : 'Upload shared document'}</button>
        </form>
        {documents.length === 0 ? <EmptyState title="The shared library is empty">Upload a PDF or text document to make it available to authorized employees.</EmptyState>
          : <div className="shared-document-list">{documents.map((doc) => {
            const title = getDocumentTitle(doc)
            const filename = getDistinctFilename(doc)
            return <article className="shared-document-row" key={doc.id}>
              <span className={`file-badge ${doc.file_type === 'PDF' ? 'pdf' : 'txt'}`}>{doc.file_type}</span>
              <div className="document-info"><strong title={title}>{title}</strong>
                <small>{filename && `${filename} · `}{formatBytes(doc.file_size)}{doc.uploaded_by != null && ` · Uploader ID ${doc.uploaded_by}`} · {doc.chunk_count ?? 0} chunks · {doc.indexed_chunk_count ?? 0} indexed</small>
                {doc.processing_error && <small className="processing-error">{doc.processing_error}</small>}
              </div>
              <span className={`status-pill status-${doc.status?.toLowerCase()}`}>{doc.status?.replaceAll('_', ' ')}</span>
              <span className={`status-pill ${doc.is_shared ? 'status-processed' : ''}`}>{documentVisibilityLabel(doc.is_shared)}</span>
              <div className="row-actions"><button type="button" className="button button-secondary button-small" onClick={() => inspectDocument(doc)}>Inspect</button>
                <button type="button" className="button button-danger button-small" disabled={busy || !doc.is_shared} onClick={() => setConfirmation({
                  title: `Delete ${title}?`,
                  description: 'This removes the shared document and its indexed content for the workspace. This action cannot be undone.',
                  confirmLabel: 'Delete document',
                  onConfirm: () => { setConfirmation(null); deleteDocument(doc) },
                })}>Delete</button></div>
            </article>
          })}</div>}
        {inspectedDocument && <section className="admin-inspection" aria-label={`Inspect ${inspectedDocument.title}`}>
          <div className="section-header-row"><div><span className="eyebrow">INDEX DETAILS</span><h3>{inspectedDocument.title}</h3>
            <p>{inspectedDocument.status} · {inspectedDocument.chunks?.length || 0} chunks</p></div>
            <button type="button" className="button button-tertiary button-small" onClick={() => setInspectedDocument(null)}>Close</button></div>
          {inspectedDocument.processing_error && <ErrorMessage>{inspectedDocument.processing_error}</ErrorMessage>}
          <div className="admin-chunks">{(inspectedDocument.chunks || []).map((chunk) => <article key={chunk.chunk_id}>
            <div><strong>Chunk {chunk.chunk_index + 1}</strong><span>{chunk.embedding_status}{chunk.page_number ? ` · page ${chunk.page_number}` : ''}</span></div><p>{chunk.content}</p>
          </article>)}</div>
        </section>}
      </section>

      <section className="panel admin-section"><div className="section-header-row"><div><span className="eyebrow">AUDIT TRAIL</span><h2>Recent administrator activity</h2></div></div>
        {auditEvents.length ? <div className="audit-list">{auditEvents.map((event) => <article key={event.id}>
          <span className="audit-dot" /><div><strong>{event.action.replaceAll('.', ' ')}</strong>
            <small>{event.subject_type}{event.subject_id ? ` · ${event.subject_id}` : ''} · {event.created_at ? new Date(event.created_at).toLocaleString() : ''}</small></div>
        </article>)}</div> : <EmptyState title="No audit events yet">Administrative actions will be listed here when available.</EmptyState>}
      </section>
    </>}
    {selectedEmployee && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedEmployee(null) }}>
      <section className="profile-dialog panel" role="dialog" aria-modal="true" aria-labelledby="employee-profile-title">
        <div className="section-header-row"><div><span className="eyebrow">EMPLOYEE PROFILE</span><h2 id="employee-profile-title">{selectedEmployee.name}</h2></div>
          <button className="button button-tertiary button-small" onClick={() => setSelectedEmployee(null)}>Close</button></div>
        <dl className="profile-details"><div><dt>Email</dt><dd>{selectedEmployee.email}</dd></div><div><dt>Employee ID</dt><dd>{selectedEmployee.employee_id}</dd></div>
          <div><dt>Department</dt><dd>{selectedEmployee.department}</dd></div><div><dt>Role</dt><dd>{selectedEmployee.role}</dd></div>
          <div><dt>Account</dt><dd>{selectedEmployee.is_active ? 'Active' : 'Inactive'}</dd></div><div><dt>Email verification</dt><dd>{selectedEmployee.is_verified ? 'Verified' : 'Unverified'}</dd></div>
        </dl>
      </section>
    </div>}
    <ConfirmDialog
      open={Boolean(confirmation)}
      title={confirmation?.title}
      description={confirmation?.description}
      confirmLabel={confirmation?.confirmLabel}
      busy={busy}
      onCancel={() => setConfirmation(null)}
      onConfirm={confirmation?.onConfirm || (() => setConfirmation(null))}
    />
  </div>
}
