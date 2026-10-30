import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { studyApi } from '../api/client'
import BaseAI from '../components/BaseAI'
import { EmptyState, ErrorMessage, PageLoading } from '../components/Feedback'
import { useAuth } from '../context/useAuth'
import { getDistinctFilename, getDocumentTitle } from '../utils/documentName'

function highlightText(text, query) {
  const terms = [...new Set(query.trim().split(/\s+/).filter((term) => term.length > 1))]
    .sort((first, second) => second.length - first.length)
  if (!terms.length) return text
  const expression = new RegExp(`(${terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'ig')
  return text.split(expression).map((part, index) => (
    terms.some((term) => part.toLocaleLowerCase() === term.toLocaleLowerCase())
      ? <mark key={`${index}-${part}`}>{part}</mark> : part
  ))
}

function makeOutlineTree(entries) {
  const roots = []
  const stack = []
  entries.forEach((entry, index) => {
    const node = { ...entry, key: `${entry.page_number}-${index}`, children: [] }
    while (stack.length && stack[stack.length - 1].level >= node.level) stack.pop()
    if (stack.length) stack[stack.length - 1].children.push(node)
    else roots.push(node)
    stack.push(node)
  })
  return roots
}

function OutlineItems({ items, collapsed, toggle, goToPage, currentPage }) {
  return items.map((item) => <li key={item.key}>
    <div className="outline-row" style={{ '--outline-level': Math.max(0, item.level - 1) }}>
      {item.children.length > 0 && <button type="button" className="outline-toggle"
        aria-label={`${collapsed.has(item.key) ? 'Expand' : 'Collapse'} ${item.title}`}
        aria-expanded={!collapsed.has(item.key)} onClick={() => toggle(item.key)}>
        {collapsed.has(item.key) ? '+' : '−'}
      </button>}
      {item.children.length === 0 && <span className="outline-spacer" />}
      <button type="button" className={`outline-link${item.page_number === currentPage ? ' active' : ''}`}
        aria-current={item.page_number === currentPage ? 'location' : undefined} onClick={() => goToPage(item.page_number)}>
        <span>{item.title}</span><small>{item.page_number}</small>
      </button>
    </div>
    {item.children.length > 0 && !collapsed.has(item.key)
      && <ul><OutlineItems items={item.children} collapsed={collapsed} toggle={toggle} goToPage={goToPage} currentPage={currentPage} /></ul>}
  </li>)
}

function LibraryIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21V5.5Z" /><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20M8 7h8M8 10h8" /></svg>
}

function AssistantIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 13.7 9l5.3 1.8-5.3 1.7-1.7 5.5-1.8-5.5L5 10.8 10.2 9 12 3.5Z" /><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></svg>
}

function DocumentPreview({ document: doc, pages }) {
  if (!doc || !pages.length) return <div className="reader-empty"><EmptyState title="Preview unavailable">This document has no readable extracted content.</EmptyState></div>
  const tabular = ['CSV', 'XLSX'].includes(doc.file_type)
  return <div className="pdf-pages-scroll document-preview" aria-label={`${doc.file_type} document preview`}>
    {pages.map((page, index) => <article className="panel document-preview-page" key={`${doc.id}:${index}`}>
      {page.page_number && <h3>Slide {page.page_number}</h3>}
      {tabular ? <div className="table-wrap"><table className="documents-table"><tbody>{page.text.split('\n').filter(Boolean).map((line, row) => {
        const cells = line.replace(/^Row \d+: /, '').split(' | ')
        return <tr key={row}>{row === 0 && doc.file_type === 'CSV' ? cells.map((cell, col) => <th key={col}>{cell}</th>) : cells.map((cell, col) => <td key={col}>{cell}</td>)}</tr>
      })}</tbody></table></div> : <div className="document-preview-text">{page.text.split('\n').map((line, row) => {
        const heading = /^#{1,6}\s+/.test(line) || line.startsWith('Heading: ')
        return heading ? <h3 key={row}>{line.replace(/^#{1,6}\s+/, '').replace(/^Heading: /, '')}</h3> : <p key={row}>{line || '\u00a0'}</p>
      })}</div>}
    </article>)}
  </div>
}

function StudyPDFPage({ token, documentId, page, index, query, fitWidth, zoom, onVisible, isCurrent }) {
  const [nearViewport, setNearViewport] = useState(false)
  const [image, setImage] = useState(null)
  const [error, setError] = useState(null)
  const [retry, setRetry] = useState(0)
  const elementRef = useRef(null)
  const pageNumber = page.page_number || index + 1
  const imageKey = `${documentId}:${pageNumber}:${query}:${retry}`

  useEffect(() => {
    const element = elementRef.current
    if (!element || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) setImage(null)
      setNearViewport(entry.isIntersecting)
    }, {
      rootMargin: '600px 0px',
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const element = elementRef.current
    if (!element || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && entry.intersectionRatio >= 0.15) onVisible(index)
    }, { threshold: 0.15 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [index, onVisible])

  useEffect(() => {
    if (!nearViewport && typeof IntersectionObserver !== 'undefined') return undefined
    let active = true
    let objectUrl = ''
    const key = imageKey
    studyApi.renderPage(token, documentId, pageNumber, query.trim(), 1.5)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        if (!active) { URL.revokeObjectURL(objectUrl); return }
        setImage({ key, url: objectUrl })
      })
      .catch((requestError) => { if (active) setError({ key, message: requestError.message }) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [nearViewport, token, documentId, pageNumber, query, retry, imageKey])

  const inRenderRange = nearViewport || typeof IntersectionObserver === 'undefined'
  const ready = inRenderRange && image?.key === imageKey
  const failed = error?.key === imageKey
  const reference = useCallback((node) => { elementRef.current = node }, [])

  return <article id={`study-pdf-page-${index}`} ref={reference}
    className={`rendered-pdf-page${isCurrent ? ' current' : ''}`} aria-label={`PDF page ${pageNumber}`}>
    <div className="rendered-pdf-page-surface">
      {ready && <img src={image.url} alt={`Page ${pageNumber}`} className="study-pdf-page"
        style={{ width: fitWidth ? '100%' : `${zoom}%` }} />}
      {!inRenderRange && !ready && <div className="pdf-page-placeholder" aria-hidden="true" />}
      {inRenderRange && !ready && !failed && <div className="pdf-page-status" role="status"><PageLoading label={`Loading page ${pageNumber}…`} /></div>}
      {failed && <div className="pdf-page-status"><ErrorMessage>{error.message}</ErrorMessage>
        <button className="button button-secondary button-small" type="button" onClick={() => setRetry((count) => count + 1)}>Retry page</button></div>}
    </div>
    <span className="rendered-pdf-page-label">Page {pageNumber}</span>
  </article>
}

export default function StudyPDF() {
  const { token } = useAuth()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedDocumentId = searchParams.get('document_id')
  const requestedPageNumber = Number(searchParams.get('page'))
  const initialSearchQuery = location.state?.searchQuery || ''
  const [sourceExcerpt, setSourceExcerpt] = useState(() => location.state?.sourceExcerpt || '')
  const [documents, setDocuments] = useState([])
  const [documentId, setDocumentId] = useState('')
  const [pages, setPages] = useState([])
  const [outline, setOutline] = useState([])
  const [pageIndex, setPageIndex] = useState(0)
  const [query, setQuery] = useState(() => initialSearchQuery)
  const [matchIndex, setMatchIndex] = useState(0)
  const [pdfUrl, setPdfUrl] = useState('')
  const [listLoading, setListLoading] = useState(true)
  const [documentLoading, setDocumentLoading] = useState(false)
  const [error, setError] = useState('')
  const [retryCount, setRetryCount] = useState(0)
  const [collapsed, setCollapsed] = useState(() => new Set())
  const [libraryOpen, setLibraryOpen] = useState(() => !window.matchMedia('(max-width: 1200px)').matches)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [zoom, setZoom] = useState(100)
  const [fitWidth, setFitWidth] = useState(true)
  const initialScrollKey = useRef('')
  const onPageVisible = useCallback((index) => setPageIndex(index), [])

  useEffect(() => {
    let active = true
    studyApi.documents(token).then((result) => {
      if (!active) return
      const available = (result.documents || []).filter((doc) => doc.status === 'PROCESSED')
      const initial = available.find((doc) => String(doc.id) === requestedDocumentId) || available[0]
      setDocuments(available)
      setDocumentId(initial ? String(initial.id) : '')
      setDocumentLoading(Boolean(initial))
      setPages([])
      setOutline([])
      setPdfUrl('')
      setPageIndex(0)
      setQuery(initialSearchQuery)
      setMatchIndex(0)
      setCollapsed(new Set())
    }).catch((err) => { if (active) setError(err.message) })
      .finally(() => { if (active) setListLoading(false) })
    return () => { active = false }
  }, [token, requestedDocumentId, retryCount, initialSearchQuery])

  useEffect(() => {
    if (!documentId) return undefined
    let active = true
    let objectUrl = ''
    Promise.all([studyApi.pages(token, documentId), studyApi.pdf(token, documentId)])
      .then(([pageData, blob]) => {
        objectUrl = URL.createObjectURL(blob)
        if (!active) { URL.revokeObjectURL(objectUrl); return }
        const nextPages = pageData.pages || []
        setPages(nextPages)
        setOutline(pageData.outline || [])
        const pageIndexFromUrl = nextPages.findIndex((page, index) => (page.page_number || index + 1) === requestedPageNumber)
        setPageIndex(pageIndexFromUrl >= 0 ? pageIndexFromUrl : 0)
        setPdfUrl(objectUrl)
      }).catch((err) => { if (active) setError(err.message) })
      .finally(() => { if (active) setDocumentLoading(false) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [token, documentId, retryCount, requestedPageNumber])

  useEffect(() => {
    if (!pages.length || !documentId || !Number.isInteger(requestedPageNumber) || requestedPageNumber < 1) return
    const key = `${documentId}:${requestedPageNumber}`
    if (initialScrollKey.current === key) return
    const index = pages.findIndex((page, position) => (page.page_number || position + 1) === requestedPageNumber)
    if (index < 0) return
    initialScrollKey.current = key
    requestAnimationFrame(() => document.getElementById(`study-pdf-page-${index}`)?.scrollIntoView({ behavior: 'auto', block: 'start' }))
  }, [pages, documentId, requestedPageNumber])



  const matches = useMemo(() => {
    const term = query.trim().toLocaleLowerCase()
    if (!term) return []
    const exact = pages.flatMap((page, index) => {
      const text = page.text.toLocaleLowerCase()
      const found = []
      let offset = 0
      while ((offset = text.indexOf(term, offset)) !== -1) {
        found.push({ pageIndex: index, offset })
        offset += Math.max(1, term.length)
      }
      return found
    })
    if (exact.length) return exact
    const terms = [...new Set(term.match(/[\p{L}\p{N}_]+/gu) || [])].filter((word) => word.length > 1)
    return pages.flatMap((page, index) => {
      const text = page.text.toLocaleLowerCase()
      return terms.flatMap((word) => {
        const found = []
        let offset = 0
        while ((offset = text.indexOf(word, offset)) !== -1) {
          found.push({ pageIndex: index, offset })
          offset += word.length
        }
        return found
      }).sort((first, second) => first.offset - second.offset)
    })
  }, [pages, query])
  const outlineTree = useMemo(() => makeOutlineTree(outline), [outline])
  const currentPage = pages[pageIndex]
  const selectedDocument = documents.find((doc) => String(doc.id) === documentId)
  const pageNumber = currentPage?.page_number || pageIndex + 1
  const pageMatches = matches.filter((match) => match.pageIndex === pageIndex)
  const matchingExcerpt = currentPage?.text && pageMatches.length
    ? currentPage.text.slice(Math.max(0, pageMatches[0].offset - 150), pageMatches[0].offset + 570)
    : ''
  const sourcePageIsCurrent = Number.isInteger(requestedPageNumber) && pageNumber === requestedPageNumber
  const visibleExcerpt = sourcePageIsCurrent ? sourceExcerpt || matchingExcerpt : matchingExcerpt


  useEffect(() => {
    if (!assistantOpen) return undefined
    function closeOnEscape(event) { if (event.key === 'Escape') setAssistantOpen(false) }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [assistantOpen])

  function selectDocument(id) {
    if (!id || id === documentId) return
    setDocumentId(id)
    setDocumentLoading(true)
    setError('')
    setPages([])
    setOutline([])
    setPdfUrl('')
    setPageIndex(0)
    setQuery('')
    setSourceExcerpt('')
    setMatchIndex(0)
    setCollapsed(new Set())
    if (window.matchMedia('(max-width: 1200px)').matches) setLibraryOpen(false)
    setSearchParams({ document_id: id })
  }

  function goToPage(number) {
    const index = pages.findIndex((page, position) => (page.page_number || position + 1) === number)
    if (index >= 0) {
      setPageIndex(index)
      document.getElementById(`study-pdf-page-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  function navigateMatch(direction) {
    if (!matches.length) return
    const next = (matchIndex + direction + matches.length) % matches.length
    setMatchIndex(next)
    goToPage(pages[matches[next].pageIndex]?.page_number || matches[next].pageIndex + 1)
  }

  function toggleOutline(key) {
    setCollapsed((previous) => {
      const updated = new Set(previous)
      if (updated.has(key)) updated.delete(key)
      else updated.add(key)
      return updated
    })
  }

  function retry() {
    setError('')
    if (documentId) setDocumentLoading(true)
    else setListLoading(true)
    setRetryCount((count) => count + 1)
  }

  if (listLoading) return <div className="page-content"><PageLoading label="Loading available documents…" /></div>
  if (error && documents.length === 0) return <div className="page-content"><ErrorMessage>{error}</ErrorMessage><button className="button button-secondary" onClick={retry}>Retry</button></div>
  if (!documents.length) return <div className="page-content study-page">
    <PageHeading />
    <EmptyState title="No indexed documents available">Upload a supported document to your files, or ask an administrator to share one with your workspace.</EmptyState>
  </div>

  return <div className="page-content study-page">
    <header className="page-heading study-heading">
      <div><span className="eyebrow">READ · SEARCH · STUDY</span><h1>Study Documents</h1>
        <p>Read authorized documents and ask BaseAI questions grounded in the selected file.</p>
      </div>
      <span className="study-document-count">{documents.length} {documents.length === 1 ? 'document' : 'documents'}</span>
    </header>
    <ErrorMessage>{error}</ErrorMessage>
    <div className={`study-workspace${libraryOpen ? ' library-open' : ''}`}>
      {libraryOpen && <aside className="study-library panel" aria-label="PDF library and table of contents">
        <div className="study-panel-heading"><div><span className="eyebrow">DOCUMENT LIBRARY</span><h2>Study materials</h2></div><span className="heading-count">{documents.length}</span></div>
        <nav className="study-document-list" aria-label="Available documents">
          {documents.map((doc) => {
            const title = getDocumentTitle(doc)
            const filename = getDistinctFilename(doc)
            return <button key={doc.id} type="button" aria-current={documentId === String(doc.id) ? 'page' : undefined}
              className={`study-document-option${documentId === String(doc.id) ? ' selected' : ''}`}
              onClick={() => selectDocument(String(doc.id))}>
              <span className={`file-badge ${doc.file_type.toLowerCase()}`}>{doc.file_type}</span><span><strong title={title}>{title}</strong>{filename && <small title={filename}>{filename}</small>}</span>
            </button>
          })}
        </nav>
        <div className="study-outline-heading"><span className="eyebrow">TABLE OF CONTENTS</span></div>
        {selectedDocument?.file_type === 'PDF' && outlineTree.length
          ? <ul className="study-outline"><OutlineItems items={outlineTree} collapsed={collapsed} toggle={toggleOutline} goToPage={goToPage} currentPage={pageNumber} /></ul>
          : selectedDocument?.file_type === 'PDF' && <p className="outline-empty">This PDF has no saved bookmarks. Use page navigation or search its text.</p>}
      </aside>}
      {libraryOpen && <button type="button" className="study-library-backdrop" aria-label="Close PDF navigation" onClick={() => setLibraryOpen(false)} />}

      <section className="study-reader panel" aria-label="Document reader">
        <div className="reader-toolbar">
          <button type="button" className="reader-icon-button" aria-label={libraryOpen ? 'Hide PDF navigation' : 'Show PDF navigation'}
            aria-expanded={libraryOpen} onClick={() => setLibraryOpen((open) => !open)}><LibraryIcon /></button>
          <div className="reader-document-title"><span className={`file-badge ${selectedDocument?.file_type?.toLowerCase() || 'pdf'}`}>{selectedDocument?.file_type || 'PDF'}</span><div><strong title={getDocumentTitle(selectedDocument)}>{getDocumentTitle(selectedDocument)}</strong>{getDistinctFilename(selectedDocument) && <small>{getDistinctFilename(selectedDocument)}</small>}</div></div>
          <div className="reader-toolbar-actions">
            {pdfUrl && <a className="button button-secondary button-small" href={pdfUrl} download={selectedDocument?.original_filename || 'document.pdf'}>Download</a>}
            <button type="button" className="reader-icon-button assistant-launcher" aria-label="Open BaseAI study assistant"
              aria-expanded={assistantOpen} onClick={() => setAssistantOpen(true)}><AssistantIcon /><span>Ask BaseAI</span></button>
          </div>
        </div>
        {selectedDocument?.file_type === 'PDF' && <div className="reader-search-tools">
          <label className="sr-only" htmlFor="study-search">Search this PDF</label>
          <input id="study-search" type="search" value={query} onChange={(event) => { setQuery(event.target.value); setMatchIndex(0) }} placeholder="Search text in this PDF" />
          <span className="study-match-count" aria-live="polite">{query ? `${matches.length ? matchIndex + 1 : 0} of ${matches.length} matches` : 'Search within PDF'}</span>
          <button type="button" className="button button-secondary button-small" onClick={() => navigateMatch(-1)} disabled={!matches.length} aria-label="Previous search match">Previous</button>
          <button type="button" className="button button-secondary button-small" onClick={() => navigateMatch(1)} disabled={!matches.length} aria-label="Next search match">Next</button>
          <button type="button" className="button button-tertiary button-small" onClick={() => { setQuery(''); setMatchIndex(0) }} disabled={!query}>Clear</button>
        </div>}
        {selectedDocument?.file_type === 'PDF' && <div className="reader-controls">
          <button className="button button-secondary button-small" type="button" disabled={pageIndex <= 0} onClick={() => goToPage(pageNumber - 1)}>Previous page</button>
          <label>Page <input aria-label="Current page" type="number" min="1" max={pages.length} value={pageNumber}
            onChange={(event) => goToPage(Number(event.target.value))} /></label>
          <span>of {pages.length}</span>
          <button className="button button-secondary button-small" type="button" disabled={pageIndex >= pages.length - 1} onClick={() => goToPage(pageNumber + 1)}>Next page</button>
          <span className="reader-control-divider" />
          <button className="button button-tertiary button-small" type="button" aria-label="Zoom out" disabled={fitWidth || zoom <= 50} onClick={() => setZoom((value) => Math.max(50, value - 10))}>−</button>
          <span className="zoom-value">{fitWidth ? 'Fit width' : `${zoom}%`}</span>
          <button className="button button-tertiary button-small" type="button" aria-label="Zoom in" disabled={fitWidth || zoom >= 200} onClick={() => setZoom((value) => Math.min(200, value + 10))}>+</button>
          <button className="button button-tertiary button-small" type="button" onClick={() => setFitWidth((fit) => !fit)}>{fitWidth ? 'Set zoom' : 'Fit width'}</button>
        </div>}
        {documentLoading ? <div className="reader-empty"><PageLoading label="Opening document preview…" /></div>
          : error ? <div className="reader-empty"><ErrorMessage>{error}</ErrorMessage><button className="button button-secondary" onClick={retry}>Retry document</button></div>
            : selectedDocument?.file_type !== 'PDF' ? <DocumentPreview document={selectedDocument} pages={pages} />
            : <>
              {visibleExcerpt && <details className="study-source-excerpt" open>
                <summary>{sourceExcerpt && sourcePageIsCurrent ? 'Retrieved source passage' : `Matching text excerpt ? page ${pageNumber}`}</summary>
                <p>{highlightText(visibleExcerpt, query)}</p>
                <small>{pageMatches.length
                  ? 'Exact text matches are highlighted on this rendered page and in the excerpt.'
                  : 'This is the retrieved source excerpt. The page highlights exact text matches for the current search.'}</small>
              </details>}
              <div className="pdf-pages-scroll" aria-label="PDF pages">
                {pages.map((page, index) => <StudyPDFPage key={`${documentId}:${page.page_number || index + 1}`}
                  token={token} documentId={documentId} page={page} index={index} query={query}
                  fitWidth={fitWidth} zoom={zoom} onVisible={onPageVisible} isCurrent={pageIndex === index} />)}
        </div>
              {query && matches.length === 0 && <p className="reader-no-match">No exact text matches in this PDF. A retrieved passage may still be shown above.</p>}
            </>}
      </section>
    </div>

    <div className={`study-assistant-layer${assistantOpen ? ' open' : ''}`} aria-hidden={!assistantOpen}>
      <button type="button" className="study-assistant-backdrop" aria-label="Close BaseAI assistant" tabIndex={assistantOpen ? 0 : -1}
        onClick={() => setAssistantOpen(false)} />
      <aside className="study-assistant panel" role="dialog" aria-modal="true" aria-label="BaseAI study assistant">
        <div className="study-assistant-heading"><div><span className="eyebrow">STUDY ASSISTANT</span><strong>{selectedDocument?.title}</strong></div>
          <button type="button" className="reader-icon-button" aria-label="Close BaseAI assistant" onClick={() => setAssistantOpen(false)}>×</button></div>
        <BaseAI key={documentId} compact documentId={documentId} documentTitle={selectedDocument?.title} />
      </aside>
    </div>
  </div>
}

function PageHeading() {
  return <header className="page-heading"><div><span className="eyebrow">READ · SEARCH · STUDY</span><h1>Study Documents</h1><p>Read authorized documents and search extracted text.</p></div></header>
}
