import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { documentsApi } from '../api/client'
import { EmptyState, ErrorMessage, PageLoading } from '../components/Feedback'
import { useAuth } from '../context/useAuth'
import { documentVisibilityLabel } from '../utils/documentVisibility'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const formatBytes = (size) => size < 1024 * 1024 ? `${Math.max(1, Math.round(size / 1024))} KB` : `${(size / (1024 * 1024)).toFixed(1)} MB`
const formatDate = (date) => date ? new Date(date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '—'

export default function Documents() {
  const { token } = useAuth()
  const inputRef = useRef(null)
  const [documents, setDocuments] = useState([])
  const [pagination, setPagination] = useState(null)
  const [page, setPage] = useState(1)
  const [title, setTitle] = useState('')
  const [file, setFile] = useState(null)
  const [filterText, setFilterText] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const refresh = useCallback(async (targetPage) => {
    setLoading(true); setError('')
    try {
      const result = await documentsApi.list(token, targetPage, 10)
      setDocuments(result.documents || []); setPagination(result.pagination); setPage(targetPage)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [token])

  useEffect(() => {
    let active = true
    documentsApi.list(token, 1, 10).then((result) => {
      if (active) { setDocuments(result.documents || []); setPagination(result.pagination); setPage(1) }
    }).catch((err) => { if (active) setError(err.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [token])

  function chooseFile(event) {
    const selected = event.target.files?.[0] || null
    setError(''); setNotice('')
    if (selected && !/\.(pdf|docx|txt|md|pptx|csv|xlsx)$/i.test(selected.name)) { setFile(null); event.target.value = ''; setError('Choose a PDF, DOCX, TXT, MD, PPTX, CSV, or XLSX file.'); return }
    if (selected && selected.size === 0) { setFile(null); event.target.value = ''; setError('The selected file is empty.'); return }
    if (selected && selected.size > MAX_FILE_SIZE) { setFile(null); event.target.value = ''; setError('Files must be 10 MB or smaller.'); return }
    setFile(selected)
  }

  async function upload(event) {
    event.preventDefault(); if (busy) return
    setError(''); setNotice('')
    if (!file) { setError('Select a supported document file to upload.'); return }
    setBusy(true)
    try {
      const formData = new FormData(); formData.append('file', file)
      if (title.trim()) formData.append('title', title.trim())
      const result = await documentsApi.upload(token, formData)
      setNotice(result.message || 'Document uploaded.')
      setTitle(''); setFile(null); if (inputRef.current) inputRef.current.value = ''
      await refresh(1)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function download(doc) {
    setBusy(true); setError(''); setNotice('')
    try { await documentsApi.download(token, doc.id, doc.original_filename); setNotice(`Downloaded ${doc.original_filename}.`) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function remove(doc) {
    if (!window.confirm(`Delete “${doc.title}”? This removes the document from your library.`)) return
    setBusy(true); setError(''); setNotice('')
    try { const result = await documentsApi.remove(token, doc.id); setNotice(result.message || 'Document deleted.'); await refresh(page) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const visibleDocuments = documents.filter((doc) => {
    const matchesText = `${doc.title} ${doc.original_filename} ${doc.file_type}`.toLowerCase().includes(filterText.toLowerCase())
    return matchesText && (statusFilter === 'all' || doc.status === statusFilter)
  })

  return <div className="page-content">
    <div className="page-heading"><div><span className="eyebrow">KNOWLEDGE LIBRARY</span><h1>Documents</h1><p>Upload, review, and manage the files available in your workspace.</p></div><span className="heading-count">{pagination?.total ?? '—'} documents</span></div>
    <ErrorMessage>{error}</ErrorMessage>{notice && <div className="alert alert-success" role="status">{notice}</div>}
    <section className="panel upload-panel">
      <div className="panel-heading"><div><span className="eyebrow">ADD TO YOUR LIBRARY</span><h2>Upload a document</h2><p className="panel-subtitle">PDF, DOCX, TXT, MD, PPTX, CSV, or XLSX · up to 10 MB</p></div><span className="upload-symbol" aria-hidden="true">＋</span></div>
      <form onSubmit={upload} className="upload-form">
        <div className="upload-fields"><label className="field-label" htmlFor="document-title">Title <span className="optional">Optional</span><input id="document-title" type="text" maxLength={255} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Use the file name if left blank" /></label><div className="field-label"><span>File</span><span className="file-help">PDF, DOCX, TXT, MD, PPTX, CSV, XLSX</span></div></div>
        <div className="file-select-row"><input ref={inputRef} id="document-file" type="file" accept=".pdf,.docx,.txt,.md,.pptx,.csv,.xlsx,application/pdf,text/plain" onChange={chooseFile} /><span className="selected-file">{file ? `${file.name} · ${formatBytes(file.size)}` : 'No file selected'}</span><button className="button button-primary" disabled={busy || !file}>{busy ? 'Processing…' : 'Upload document'}</button></div>
      </form>
    </section>
    <section className="panel library-panel">
      <div className="panel-heading"><div><span className="eyebrow">YOUR FILES</span><h2>Document library</h2></div><div className="library-tools"><label><span className="sr-only">Filter current page by document</span><input type="search" value={filterText} onChange={(event) => setFilterText(event.target.value)} placeholder="Filter this page" /></label><label><span className="sr-only">Filter by processing status</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="PROCESSED">Processed</option><option value="PROCESSING">Processing</option><option value="PROCESSING_FAILED">Processing failed</option><option value="UPLOADED">Uploaded</option></select></label><button type="button" className="button button-secondary button-small" onClick={() => refresh(page)} disabled={loading || busy}>Refresh</button></div></div>
      {loading ? <PageLoading label="Loading documents…" /> : documents.length === 0 ? <EmptyState title="No documents yet">Upload a supported file above to get started.</EmptyState> : visibleDocuments.length === 0 ? <EmptyState title="No documents match these filters">Change the current-page search or processing status filter.</EmptyState> : <div className="table-wrap"><table className="documents-table"><thead><tr><th>DOCUMENT</th><th>TYPE</th><th>SIZE</th><th>STATUS</th><th>ACCESS</th><th>ADDED</th><th><span className="sr-only">Actions</span></th></tr></thead><tbody>{visibleDocuments.map((doc) => <tr key={doc.id}><td><div className="table-doc"><span className={`file-badge ${doc.file_type.toLowerCase()}`}>{doc.file_type}</span><span><strong>{doc.title}</strong><small>{doc.original_filename}</small></span></div></td><td>{doc.file_type}</td><td>{formatBytes(doc.file_size || 0)}</td><td><span className={`status-pill status-${doc.status?.toLowerCase()}`}>{doc.status?.replaceAll('_', ' ')}</span></td><td><span className={`status-pill ${doc.is_shared ? 'status-processed' : ''}`}>{documentVisibilityLabel(doc.is_shared)}</span></td><td>{formatDate(doc.created_at)}</td><td><div className="row-actions"><button type="button" onClick={() => download(doc)} disabled={busy} aria-label={`Download ${doc.title}`}>Download</button>{doc.status === 'PROCESSED' && <Link to={`/study?document_id=${doc.id}`} className="row-action-link">Study</Link>}<button type="button" onClick={() => remove(doc)} disabled={busy} aria-label={`Delete ${doc.title}`} className="danger-action">Delete</button></div></td></tr>)}</tbody></table></div>}
      {pagination?.pages > 1 && <div className="pagination"><span>Page {page} of {pagination.pages}</span><div><button className="button button-secondary button-small" disabled={page <= 1 || loading} onClick={() => refresh(page - 1)}>Previous</button><button className="button button-secondary button-small" disabled={page >= pagination.pages || loading} onClick={() => refresh(page + 1)}>Next</button></div></div>}
    </section>
  </div>
}
