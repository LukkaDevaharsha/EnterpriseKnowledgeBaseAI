import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { documentsApi } from '../api/client'
import { EmptyState, ErrorMessage, PageLoading } from '../components/Feedback'
import ConfirmDialog from '../components/ConfirmDialog'
import { useAuth } from '../context/useAuth'
import { documentVisibilityLabel } from '../utils/documentVisibility'
import { getDistinctFilename, getDocumentTitle } from '../utils/documentName'

/* ── shared helpers ─────────────────────────────────────────────────── */
const MAX_FILE_SIZE = 10 * 1024 * 1024
const PAGE_SIZE = 10
async function fetchAllDocuments(token) {
  const first = await documentsApi.list(token, 1, 100)
  const allDocuments = [...(first.documents || [])]
  const totalPages = first.pagination?.pages || 1
  for (let currentPage = 2; currentPage <= totalPages; currentPage += 1) {
    const next = await documentsApi.list(token, currentPage, 100)
    allDocuments.push(...(next.documents || []))
  }
  return allDocuments
}
const fmt = (size) => {
  if (!Number.isFinite(size) || size < 0) return '—'
  if (size < 1024) return `${size} B`
  return size < 1024 * 1024
    ? `${Math.max(1, Math.round(size / 1024))} KB`
    : `${(size / (1024 * 1024)).toFixed(1)} MB`
}
const fmtDate = (d) => d
  && Number.isFinite(Date.parse(d))
  ? new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  : '—'

/* ── Search result card ─────────────────────────────────────────────── */
function BrowseTab() {
  const { token } = useAuth()
  const inputRef = useRef(null)
  const [documents, setDocuments] = useState([])
  const [page, setPage] = useState(1)
  const [title, setTitle] = useState('')
  const [file, setFile] = useState(null)
  const [filterText, setFilterText] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sortBy, setSortBy] = useState('uploaded-newest')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [pendingDelete, setPendingDelete] = useState(null)

  const refresh = useCallback(async (requestedPage = 1) => {
    setLoading(true); setError('')
    try {
      const allDocuments = await fetchAllDocuments(token)
      setDocuments(allDocuments)
      const query = filterText.trim().toLocaleLowerCase()
      const matchingCount = allDocuments.filter((doc) =>
        (!query || `${doc.title || ''} ${doc.original_filename || ''}`.toLocaleLowerCase().includes(query))
          && (statusFilter === 'all' || doc.status === statusFilter)
      ).length
      setPage(Math.min(requestedPage, Math.max(1, Math.ceil(matchingCount / PAGE_SIZE))))
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }, [token, filterText, statusFilter])

  useEffect(() => {
    let active = true
    fetchAllDocuments(token).then((allDocuments) => {
      if (active) setDocuments(allDocuments)
    }).catch((err) => {
      if (active) setError(err.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [token])

  function chooseFile(e) {
    const f = e.target.files?.[0] || null
    setError(''); setNotice('')
    if (f && !/\.(pdf|docx|txt|md|pptx|csv|xlsx)$/i.test(f.name)) { setFile(null); e.target.value = ''; setError('Choose a PDF, DOCX, TXT, MD, PPTX, CSV, or XLSX file.'); return }
    if (f && f.size === 0) { setFile(null); e.target.value = ''; setError('The selected file is empty.'); return }
    if (f && f.size > MAX_FILE_SIZE) { setFile(null); e.target.value = ''; setError('Files must be 10 MB or smaller.'); return }
    setFile(f)
  }

  async function upload(e) {
    e.preventDefault(); if (busy) return
    setError(''); setNotice('')
    if (!file) { setError('Select a file to upload.'); return }
    setBusy(true)
    try {
      const fd = new FormData(); fd.append('file', file)
      if (title.trim()) fd.append('title', title.trim())
      const r = await documentsApi.upload(token, fd)
      setNotice(r.message || 'Document uploaded and indexed.')
      setTitle(''); setFile(null); if (inputRef.current) inputRef.current.value = ''
      await refresh(1)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function download(doc) {
    setBusy(true); setError(''); setNotice('')
    try { await documentsApi.download(token, doc.id, doc.original_filename) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  async function remove(doc) {
    setPendingDelete(null)
    setBusy(true); setError(''); setNotice('')
    try {
      const r = await documentsApi.remove(token, doc.id)
      setNotice(r.message || 'Deleted.')
      setPendingDelete(null)
      await refresh(page)
    }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const visible = useMemo(() => {
    const query = filterText.trim().toLocaleLowerCase()
    const matches = documents.filter((doc) => {
      const searchable = `${doc.title || ''} ${doc.original_filename || ''}`.toLocaleLowerCase()
      return (!query || searchable.includes(query))
        && (statusFilter === 'all' || doc.status === statusFilter)
    })
    const [field, direction] = sortBy.split('-')
    const multiplier = direction === 'oldest' || direction === 'az' || direction === 'smallest' ? 1 : -1
    matches.sort((a, b) => {
      let left
      let right
      if (field === 'name') {
        left = getDocumentTitle(a)
        right = getDocumentTitle(b)
      } else if (field === 'size') {
        left = a.file_size != null && a.file_size !== '' && Number.isFinite(Number(a.file_size)) ? Number(a.file_size) : null
        right = b.file_size != null && b.file_size !== '' && Number.isFinite(Number(b.file_size)) ? Number(b.file_size) : null
      } else {
        left = Date.parse(a.created_at || '')
        right = Date.parse(b.created_at || '')
        if (!Number.isFinite(left)) left = null
        if (!Number.isFinite(right)) right = null
      }
      if (left == null || right == null) return left == null ? (right == null ? 0 : 1) : -1
      const comparison = typeof left === 'string'
        ? left.localeCompare(right, undefined, { sensitivity: 'base' })
        : left - right
      return comparison * multiplier
    })
    return matches
  }, [documents, filterText, statusFilter, sortBy])
  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  const pageDocuments = visible.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const pagination = { total: documents.length, pages: pageCount }

  return (
    <div className="library-browse-tab">
      <ErrorMessage>{error}</ErrorMessage>
      {notice && <div className="alert alert-success" role="status">{notice}</div>}

      <section className="upload-section">
        <div className="upload-section-heading">
          <div><span className="section-label">ADD TO YOUR LIBRARY</span><h2>Upload a document</h2></div>
          <span className="upload-constraints">PDF, DOCX, TXT, MD, PPTX, CSV, or XLSX · up to 10 MB</span>
        </div>
        <form className="upload-form" onSubmit={upload}>
          <label className="form-field" htmlFor="doc-title">
            Title <span className="optional">optional</span>
            <input id="doc-title" type="text" maxLength={255} value={title}
              onChange={(e) => setTitle(e.target.value)} placeholder="Defaults to the file name" />
          </label>
          <div className="file-row">
            <input ref={inputRef} id="doc-file" type="file" accept=".pdf,.docx,.txt,.md,.pptx,.csv,.xlsx,application/pdf,text/plain" onChange={chooseFile} />
            <span className="file-name">{file ? `${file.name} · ${fmt(file.size)}` : 'No file selected'}</span>
            <button className="button button-primary" disabled={busy || !file}>
              {busy ? 'Processing…' : 'Upload'}
            </button>
          </div>
        </form>
      </section>

      <section className="docs-section">
        <div className="docs-section-header">
          <h2>Your documents <span className="doc-count">{pagination?.total ?? ''}</span></h2>
          <div className="docs-tools">
            <label className="sr-only" htmlFor="library-document-search">Search document names</label>
            <input id="library-document-search" type="search" value={filterText}
              onChange={(e) => { setFilterText(e.target.value); setPage(1) }}
              placeholder="Search titles and filenames" aria-label="Search document titles and filenames" />
            {filterText && <button type="button" className="button button-tertiary button-small"
              onClick={() => { setFilterText(''); setPage(1) }}>Clear</button>}
            <label className="sr-only" htmlFor="library-document-sort">Sort documents</label>
            <select id="library-document-sort" value={sortBy} onChange={(e) => { setSortBy(e.target.value); setPage(1) }} aria-label="Sort documents">
              <option value="name-az">Name: A–Z</option>
              <option value="name-za">Name: Z–A</option>
              <option value="pages-smallest" disabled>Total pages: Lowest first (unavailable)</option>
              <option value="pages-largest" disabled>Total pages: Highest first (unavailable)</option>
              <option value="size-smallest">File size: Smallest first</option>
              <option value="size-largest">File size: Largest first</option>
              <option value="uploaded-newest">Uploaded: Newest first</option>
              <option value="uploaded-oldest">Uploaded: Oldest first</option>
            </select>
            <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }} aria-label="Filter by status">
              <option value="all">All statuses</option>
              <option value="PROCESSED">Indexed</option>
              <option value="PROCESSING">Processing</option>
              <option value="PROCESSING_FAILED">Failed</option>
              <option value="UPLOADED">Uploaded</option>
            </select>
            <button type="button" className="button button-secondary button-small" onClick={() => refresh(page)} disabled={loading || busy}>Refresh</button>
          </div>
          <small className="library-metadata-note">Page counts are not stored in the document listing, so page-count sorting is unavailable.</small>
        </div>
        {loading
          ? <PageLoading label="Loading documents…" />
          : documents.length === 0
            ? <EmptyState title="No documents yet" action={<label htmlFor="doc-file" className="button button-primary button-small">Choose a file</label>}>Upload a supported document above to start building your knowledge library.</EmptyState>
            : visible.length === 0
              ? <EmptyState title="No documents match your search">Clear the search or change the status filter.</EmptyState>
              : (
                <div className="table-wrap">
                  <table className="docs-table">
                    <thead><tr>
                      <th>Document</th><th>Size</th><th>Status</th><th>Access</th><th>Added</th><th><span className="sr-only">Actions</span></th>
                    </tr></thead>
                    <tbody>
                      {pageDocuments.map((doc) => {
                        const title = getDocumentTitle(doc)
                        const filename = getDistinctFilename(doc)
                        return (
                        <tr key={doc.id}>
                          <td>
                            <div className="table-doc">
                              <span className={`file-badge ${doc.file_type === 'PDF' ? 'pdf' : 'txt'}`}>{doc.file_type}</span>
                              <span><strong title={title}>{title}</strong>{filename && <small title={filename}>{filename}</small>}</span>
                            </div>
                          </td>
                          <td className="td-sm">{doc.file_size != null && doc.file_size !== '' ? fmt(Number(doc.file_size)) : '—'}</td>
                          <td><span className={`status-pill status-${doc.status?.toLowerCase()}`}>{doc.status?.replaceAll('_', ' ')}</span></td>
                          <td><span className={`status-pill ${doc.is_shared ? 'status-processed' : ''}`}>{documentVisibilityLabel(doc.is_shared)}</span></td>
                          <td className="td-sm">{fmtDate(doc.created_at)}</td>
                          <td>
                            <div className="row-actions">
                              <button type="button" className="button button-secondary button-small" onClick={() => download(doc)} disabled={busy}>Download</button>
                              {doc.file_type === 'PDF' && <Link to={`/study?document_id=${doc.id}`} className="button button-secondary button-small">Study</Link>}
                              <button type="button" className="button button-danger button-small" onClick={() => setPendingDelete(doc)} disabled={busy}>Delete</button>
                            </div>
                          </td>
                        </tr>
                      )})}
                    </tbody>
                  </table>
                </div>
              )}
        {pagination?.pages > 1 && (
          <div className="pagination">
            <span>Page {page} of {pagination.pages} · {visible.length} matching {visible.length === 1 ? 'document' : 'documents'}</span>
            <div>
              <button className="button button-secondary button-small" disabled={page <= 1 || loading} onClick={() => setPage((current) => current - 1)}>Previous</button>
              <button className="button button-secondary button-small" disabled={page >= pagination.pages || loading} onClick={() => setPage((current) => current + 1)}>Next</button>
            </div>
          </div>
        )}
      </section>
      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={`Delete ${pendingDelete?.title || 'this document'}?`}
        description="This removes the document and its indexed search content. This action cannot be undone."
        confirmLabel="Delete document"
        busy={busy}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => remove(pendingDelete)}
      />
    </div>
  )
}

/* ── Library page (parent) ──────────────────────────────────────────── */
export default function Library() {
  return <div className="page-content library-page"><header className="page-heading"><div><span className="eyebrow">KNOWLEDGE LIBRARY</span><h1>Library</h1><p>Browse your documents, search filenames, and sort the collection.</p></div></header><BrowseTab /></div>
}
