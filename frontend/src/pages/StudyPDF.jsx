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

function highlightRuns(runs, fallback, query) {
  if (!runs?.length) return highlightText(fallback, query)
  const fullText = runs.map((run) => run.text).join('')
  const terms = [...new Set(query.trim().split(/\s+/).filter((term) => term.length > 1))]
    .sort((first, second) => second.length - first.length)
  const expression = terms.length
    ? new RegExp(terms.map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'ig')
    : null
  const ranges = []
  if (expression) {
    for (const match of fullText.matchAll(expression)) ranges.push([match.index, match.index + match[0].length])
  }

  function renderRun(text, offset) {
    const end = offset + text.length
    const pieces = []
    let cursor = offset
    ranges.forEach(([start, finish], index) => {
      const from = Math.max(start, offset)
      const to = Math.min(finish, end)
      if (from >= to) return
      if (from > cursor) pieces.push(text.slice(cursor - offset, from - offset))
      pieces.push(<mark key={`${from}-${to}-${index}`}>{text.slice(from - offset, to - offset)}</mark>)
      cursor = to
    })
    if (!pieces.length) return text
    if (cursor < end) pieces.push(text.slice(cursor - offset))
    return pieces
  }

  let offset = 0
  return runs.map((run, index) => {
    const text = run.text
    let content = renderRun(text, offset)
    offset += text.length
    if (run.superscript) content = <sup>{content}</sup>
    if (run.subscript) content = <sub>{content}</sub>
    if (run.strike) content = <s>{content}</s>
    if (run.underline) content = <u>{content}</u>
    if (run.italic) content = <em>{content}</em>
    if (run.bold) content = <strong>{content}</strong>
    return <span key={index}>{content}</span>
  })
}

function MatchMarkerRail({ matches, textLength, activeMatchIndex, onSelectMatch, className = '' }) {
  if (!matches.length) return null
  return <div className={`pdf-search-marker-rail ${className}`} aria-label="Search matches">
    {matches.map((match) => <button key={match.matchIndex} type="button"
      className={`pdf-search-marker${match.matchIndex === activeMatchIndex ? ' active' : ''}`}
      style={{ top: `${match.top ?? Math.max(1, Math.min(98, (match.offset / Math.max(1, textLength)) * 100))}%` }}
      aria-label={`Search match ${match.matchIndex + 1}`} title={`Match ${match.matchIndex + 1}`}
      onClick={() => onSelectMatch(match.matchIndex, match.pageIndex)} />)}
  </div>
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

function DocxRuns({ runs, fallback, query }) {
  return highlightRuns(runs, fallback, query)
}

function DocxBlocks({ blocks, query }) {
  const rendered = []
  for (let index = 0; index < blocks.length;) {
    const block = blocks[index]
    if (block.type === 'list_item') {
      const ordered = Boolean(block.ordered)
      const items = []
      while (index < blocks.length && blocks[index].type === 'list_item' && Boolean(blocks[index].ordered) === ordered) {
        items.push({ ...blocks[index], unitIndex: index })
        index += 1
      }
      const List = ordered ? 'ol' : 'ul'
      rendered.push(<List className="docx-list" key={`list-${index}`}>
        {items.map((item, itemIndex) => <li id={`study-unit-${item.unitIndex}`} key={itemIndex} style={{ marginLeft: `${Math.max(0, item.level || 0) * 20}px` }}>
          <DocxRuns runs={item.runs} fallback={item.text} query={query} />
        </li>)}
      </List>)
      continue
    }

    const key = `block-${index}`
    const content = <DocxRuns runs={block.runs} fallback={block.text} query={query} />
    if (block.type === 'table') {
      rendered.push(<div className="docx-table-wrap docx-block" id={`study-unit-${index}`} key={key}><table className="docx-table"><tbody>
        {block.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => rowIndex === 0
          ? <th key={cellIndex} scope="col">{highlightText(cell, query)}</th>
          : <td key={cellIndex}>{highlightText(cell, query)}</td>)}</tr>)}
      </tbody></table></div>)
    } else if (block.type === 'title') rendered.push(<h1 className="docx-title docx-block" id={`study-unit-${index}`} key={key}>{content}</h1>)
    else if (block.type === 'subtitle') rendered.push(<p className="docx-subtitle docx-block" id={`study-unit-${index}`} key={key}>{content}</p>)
    else if (block.type === 'heading') {
      const Heading = `h${Math.min(6, Math.max(2, block.level || 2))}`
      rendered.push(<Heading className="docx-heading docx-block" id={`study-unit-${index}`} key={key}>{content}</Heading>)
    } else rendered.push(<p className="docx-paragraph docx-block" id={`study-unit-${index}`} key={key}>{content}</p>)
    index += 1
  }
  return rendered
}

function PreviewUnit({ index, onVisible, className, style, matches, textLength, activeMatchIndex, onSelectMatch, children }) {
  const elementRef = useRef(null)
  useEffect(() => {
    const element = elementRef.current
    if (!element || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && entry.intersectionRatio >= 0.15) onVisible(index)
    }, { threshold: 0.15 })
    observer.observe(element)
    return () => observer.disconnect()
  }, [index, onVisible])

  return <article id={`study-unit-${index}`} ref={elementRef} className={className} style={style}>
    {children}
    <MatchMarkerRail matches={matches} textLength={textLength} activeMatchIndex={activeMatchIndex}
      onSelectMatch={onSelectMatch} className="document-search-marker-rail" />
  </article>
}

function PptxSlidePreview({ token, documentId, page, index, zoom, fitWidth, query, matches, activeMatchIndex, onVisible, onSelectMatch }) {
  const slideNumber = page.page_number || index + 1
  const [nearViewport, setNearViewport] = useState(false)
  const [image, setImage] = useState(null)
  const [error, setError] = useState(null)
  const [retry, setRetry] = useState(0)
  const elementRef = useRef(null)
  const imageKey = `${documentId}:${slideNumber}:${query}:${retry}`

  useEffect(() => {
    const element = elementRef.current
    if (!element || typeof IntersectionObserver === 'undefined') return undefined
    const observer = new IntersectionObserver(([entry]) => {
      setNearViewport(entry.isIntersecting)
      if (!entry.isIntersecting) setImage(null)
    }, { rootMargin: '700px 0px' })
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
    studyApi.renderSlide(token, documentId, slideNumber, 1.5, query.trim())
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob)
        if (!active) { URL.revokeObjectURL(objectUrl); return }
        setError(null)
        setImage({ key: imageKey, url: objectUrl })
      })
      .catch((requestError) => { if (active) setError({ key: imageKey, message: requestError.message }) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [nearViewport, token, documentId, slideNumber, query, retry, imageKey])

  const readyImage = image?.key === imageKey ? image : null
  const renderError = error?.key === imageKey ? error : null

  return <article id={`study-unit-${index}`} ref={elementRef} className={`pptx-slide-card${matches.length ? ' has-matches' : ''}`} aria-label={`Slide ${slideNumber}`}
    style={{ zoom: zoomScale(fitWidth, zoom) }}>
    <div className="pptx-slide-viewport">
      {readyImage && <img className="pptx-slide-image" src={readyImage.url} alt={`Slide ${slideNumber}`} />}
      {!readyImage && !renderError && <div className="pptx-slide-placeholder" aria-hidden="true"><PageLoading label={`Rendering slide ${slideNumber}…`} /></div>}
      {renderError && <div className="pptx-slide-error"><ErrorMessage>{renderError.message}</ErrorMessage>
        <button type="button" className="button button-secondary button-small" onClick={() => setRetry((count) => count + 1)}>Retry slide</button></div>}
    </div>
    <MatchMarkerRail matches={matches} textLength={page.text.length} activeMatchIndex={activeMatchIndex}
      onSelectMatch={onSelectMatch} className="pptx-slide-marker-rail" />
    <span className="rendered-pdf-page-label">Slide {slideNumber}</span>
  </article>
}

function locateSpreadsheetCell(text, offset) {
  let cursor = 0
  const lines = text.split('\n')
  for (const line of lines) {
    const rowPrefix = line.match(/^Row (\d+): /)
    if (!rowPrefix) { cursor += line.length + 1; continue }
    const rowIndex = Number(rowPrefix[1]) - 1
    let cellStart = cursor + rowPrefix[0].length
    const cells = line.slice(rowPrefix[0].length).split(' | ')
    for (let columnIndex = 0; columnIndex < cells.length; columnIndex += 1) {
      const end = cellStart + cells[columnIndex].length
      if (offset >= cellStart && offset <= end) return { rowIndex, columnIndex }
      cellStart = end + 3
    }
    cursor += line.length + 1
  }
  return null
}

function columnName(index) {
  let number = index + 1
  let label = ''
  while (number > 0) {
    number -= 1
    label = String.fromCharCode(65 + number % 26) + label
    number = Math.floor(number / 26)
  }
  return label
}

function zoomScale(fitWidth, zoom) {
  return fitWidth ? 1 : zoom / 100
}

function cloneSheets(spreadsheets) {
  return spreadsheets.map((sheet) => ({ name: sheet.name, rows: sheet.rows.map((row) => [...row]) }))
}

function SpreadsheetEditor({ document: doc, spreadsheets, pages, query, zoom, fitWidth, activeSheetIndex, matches, activeMatchIndex, canEdit, token, onSelectUnit, onSelectMatch, onSaved }) {
  const [sheets, setSheets] = useState(() => cloneSheets(spreadsheets))
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveMessage, setSaveMessage] = useState('')
  const sheetIndex = Math.max(0, Math.min(activeSheetIndex, sheets.length - 1))
  const sheet = sheets[sheetIndex]
  if (!sheet) return <div className="reader-empty"><EmptyState title="Spreadsheet is empty">No worksheet data is available.</EmptyState></div>

  const pageText = pages[sheetIndex]?.text || ''
  const sheetMatches = matches.filter((match) => match.pageIndex === sheetIndex)
  const activeMatch = matches.find((match) => match.matchIndex === activeMatchIndex && match.pageIndex === sheetIndex)
  const activeCell = activeMatch ? locateSpreadsheetCell(pageText, activeMatch.offset) : null
  const columnCount = Math.max(1, ...sheet.rows.map((row) => row.length))

  function updateCell(rowIndex, columnIndex, value) {
    setSheets((previous) => previous.map((item, currentSheet) => {
      if (currentSheet !== sheetIndex) return item
      const rows = item.rows.map((row) => [...row])
      while (rows.length <= rowIndex) rows.push([])
      while (rows[rowIndex].length <= columnIndex) rows[rowIndex].push('')
      rows[rowIndex][columnIndex] = value
      return { ...item, rows }
    }))
    setSaveMessage('')
  }

  function addRow() {
    setSheets((previous) => previous.map((item, currentSheet) => currentSheet === sheetIndex
      ? { ...item, rows: [...item.rows, Array(columnCount).fill('')] }
      : item))
    setEditing(true)
    setSaveMessage('')
  }

  function changesToSave() {
    const changes = []
    const appendRows = []
    spreadsheets.forEach((original, currentSheet) => {
      const updated = sheets[currentSheet]
      original.rows.forEach((row, rowIndex) => {
        const nextRow = updated.rows[rowIndex] || []
        for (let columnIndex = 0; columnIndex < Math.max(row.length, nextRow.length); columnIndex += 1) {
          const before = row[columnIndex] ?? ''
          const after = nextRow[columnIndex] ?? ''
          if (before !== after) changes.push({ sheet_index: currentSheet, row_index: rowIndex, column_index: columnIndex, value: after })
        }
      })
      updated.rows.slice(original.rows.length).forEach((row) => {
        if (row.some((value) => value !== '')) appendRows.push({ sheet_index: currentSheet, values: row })
      })
    })
    return { changes, append_rows: appendRows }
  }

  const pendingChanges = changesToSave()
  const hasChanges = pendingChanges.changes.length > 0 || pendingChanges.append_rows.length > 0

  async function save() {
    setSaving(true)
    setSaveError('')
    setSaveMessage('')
    try {
      await studyApi.updateSpreadsheet(token, doc.id, pendingChanges)
      setEditing(false)
      setSaveMessage('Changes saved.')
      onSaved()
    } catch (error) {
      setSaveError(error.message)
    } finally {
      setSaving(false)
    }
  }

  function cancel() {
    setSheets(cloneSheets(spreadsheets))
    setEditing(false)
    setSaveError('')
    setSaveMessage('')
  }

  function selectMarker(matchIndex, unitIndex) {
    onSelectMatch(matchIndex, unitIndex)
    const match = matches.find((item) => item.matchIndex === matchIndex)
    const cell = match && locateSpreadsheetCell(pages[unitIndex]?.text || '', match.offset)
    if (cell) requestAnimationFrame(() => document.getElementById(`spreadsheet-cell-${unitIndex}-${cell.rowIndex}-${cell.columnIndex}`)?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' }))
  }

  return <section id={`study-unit-${sheetIndex}`} className="spreadsheet-editor">
    {sheets.length > 1 && <div className="spreadsheet-tabs" role="tablist" aria-label="Worksheets">
      {sheets.map((item, index) => <button key={`${index}-${item.name}`} type="button" role="tab"
        aria-selected={sheetIndex === index} className={sheetIndex === index ? 'active' : ''}
        onClick={() => onSelectUnit(index)}>{item.name}</button>)}
    </div>}
    <div className="spreadsheet-toolbar">
      <span>{sheet.name} · {sheet.rows.length} rows</span>
      <div className="spreadsheet-edit-actions">
        {canEdit && !editing && <button className="button button-secondary button-small" type="button" onClick={() => { setEditing(true); setSaveMessage('') }}>Edit cells</button>}
        {canEdit && editing && <>
          <button className="button button-secondary button-small" type="button" onClick={addRow}>Add row</button>
          <button className="button button-primary button-small" type="button" disabled={!hasChanges || saving} onClick={save}>{saving ? 'Saving…' : 'Save changes'}</button>
          <button className="button button-tertiary button-small" type="button" disabled={saving} onClick={cancel}>Cancel</button>
        </>}
      </div>
    </div>
    {saveError && <div className="alert alert-error">{saveError}</div>}
    {saveMessage && <div className="alert alert-success">{saveMessage}</div>}
    <div className="spreadsheet-table-scroll">
      <table className="spreadsheet-table" style={{ zoom: zoomScale(fitWidth, zoom) }}>
        <thead><tr><th className="spreadsheet-row-number" aria-label="Row number">#</th>
          {Array.from({ length: columnCount }, (_, index) => <th key={index}>{columnName(index)}</th>)}
        </tr></thead>
        <tbody>{sheet.rows.map((row, rowIndex) => <tr key={rowIndex}>
          <th className="spreadsheet-row-number" scope="row">{rowIndex + 1}</th>
          {Array.from({ length: Math.max(columnCount, row.length) }, (_, columnIndex) => {
            const value = row[columnIndex] ?? ''
            const selected = activeCell?.rowIndex === rowIndex && activeCell?.columnIndex === columnIndex
            return <td id={`spreadsheet-cell-${sheetIndex}-${rowIndex}-${columnIndex}`} key={columnIndex} className={selected ? 'active-match' : ''}
              ref={selected ? (element) => element?.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' }) : undefined}>
              {editing
                ? <input aria-label={`${sheet.name}, row ${rowIndex + 1}, column ${columnName(columnIndex)}`} value={value}
                  onChange={(event) => updateCell(rowIndex, columnIndex, event.target.value)} />
                : highlightText(value, query)}
            </td>
          })}
        </tr>)}</tbody>
      </table>
    </div>
    <MatchMarkerRail matches={sheetMatches} textLength={pageText.length} activeMatchIndex={activeMatchIndex}
      onSelectMatch={selectMarker} className="spreadsheet-search-marker-rail" />
  </section>
}

function DocumentPreview({ document: doc, pages, structure = [], spreadsheet = [], token, documentId, query, zoom, fitWidth, matches, docxMarkers, docxTotalTextLength, activeMatchIndex, activeSheetIndex, canEdit, onSelectUnit, onVisible, onSelectMatch, onSaved }) {
  if (!doc || !pages.length) return <div className="reader-empty"><EmptyState title="Preview unavailable">This document has no readable extracted content.</EmptyState></div>
  if (['CSV', 'XLSX'].includes(doc.file_type)) {
    return <SpreadsheetEditor key={`${doc.id}:${doc.updated_at || ''}`} document={doc} spreadsheets={spreadsheet}
      pages={pages} query={query} zoom={zoom} fitWidth={fitWidth} activeSheetIndex={activeSheetIndex} matches={matches}
      activeMatchIndex={activeMatchIndex} canEdit={canEdit} token={token} onSelectUnit={onSelectUnit}
      onSelectMatch={onSelectMatch} onSaved={onSaved} />
  }
  if (doc.file_type === 'PPTX') {
    return <div className="pptx-slides-preview" aria-label="PowerPoint slide preview">
      {pages.map((page, index) => <PptxSlidePreview key={`${doc.id}:${page.page_number || index + 1}`}
        token={token} documentId={documentId} page={page} index={index} zoom={zoom} fitWidth={fitWidth} query={query}
        matches={matches.filter((match) => match.pageIndex === index)} activeMatchIndex={activeMatchIndex}
        onVisible={onVisible} onSelectMatch={onSelectMatch} />)}
    </div>
  }
  if (doc.file_type === 'DOCX' && structure.length) {
    return <div className="pdf-pages-scroll document-preview docx-preview" aria-label="Structured Word document preview">
      <article className="docx-document" style={{ zoom: zoomScale(fitWidth, zoom), paddingRight: docxMarkers.length ? '32px' : undefined }}>
        <DocxBlocks blocks={structure} query={query} />
        <MatchMarkerRail matches={docxMarkers} textLength={docxTotalTextLength} activeMatchIndex={activeMatchIndex}
          onSelectMatch={onSelectMatch} className="docx-search-marker-rail" />
      </article>
    </div>
  }
  return <div className="pdf-pages-scroll document-preview" aria-label={`${doc.file_type} document preview`}>
    {pages.map((page, index) => <PreviewUnit index={index} onVisible={onVisible} className="panel document-preview-page" key={`${doc.id}:${index}`} style={{ width: '100%', zoom: zoomScale(fitWidth, zoom), paddingRight: matches.some((match) => match.pageIndex === index) ? '18px' : undefined }}
      matches={matches.filter((match) => match.pageIndex === index)} textLength={page.text.length}
      activeMatchIndex={activeMatchIndex} onSelectMatch={onSelectMatch}>
      {page.page_number && <h3>Slide {page.page_number}</h3>}
      <div className="document-preview-text">{page.text.split('\n').map((line, row) => {
        const heading = /^#{1,6}\s+/.test(line) || line.startsWith('Heading: ')
        return heading ? <h3 key={row}>{highlightText(line.replace(/^#{1,6}\s+/, '').replace(/^Heading: /, ''), query)}</h3> : <p key={row}>{line ? highlightText(line, query) : '\u00a0'}</p>
      })}</div>
    </PreviewUnit>)}
  </div>
}

function StudyPDFPage({ token, documentId, page, index, query, fitWidth, zoom, onVisible, isCurrent, matches, onSelectMatch }) {
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
    className={`rendered-pdf-page${isCurrent ? ' current' : ''}`} aria-label={`PDF page ${pageNumber}`}
    style={{ zoom: zoomScale(fitWidth, zoom) }}>
    <div className="rendered-pdf-page-content" style={{ width: 'min(100%, 1100px)' }}>
      <div className="rendered-pdf-page-surface">
        {ready && <img src={image.url} alt={`Page ${pageNumber}`} className="study-pdf-page"
          style={{ width: '100%' }} />}
        {!inRenderRange && !ready && <div className="pdf-page-placeholder" aria-hidden="true" />}
        {inRenderRange && !ready && !failed && <div className="pdf-page-status" role="status"><PageLoading label={`Loading page ${pageNumber}…`} /></div>}
        {failed && <div className="pdf-page-status"><ErrorMessage>{error.message}</ErrorMessage>
          <button className="button button-secondary button-small" type="button" onClick={() => setRetry((count) => count + 1)}>Retry page</button></div>}
      </div>
      {matches.length > 0 && <div className="pdf-search-marker-rail" aria-label={`Search matches on page ${pageNumber}`}>
        {matches.map((match) => <button key={match.matchIndex} type="button"
          className={`pdf-search-marker${match.matchIndex === match.activeMatchIndex ? ' active' : ''}`}
          style={{ top: `${Math.max(1, Math.min(98, (match.offset / Math.max(1, page.text.length)) * 100))}%` }}
          aria-label={`Search match ${match.matchIndex + 1} on page ${pageNumber}`}
          title={`Match ${match.matchIndex + 1} of ${match.totalMatches} · Page ${pageNumber}`}
          onClick={() => onSelectMatch(match.matchIndex)} />)}
      </div>}
    </div>
    <span className="rendered-pdf-page-label">Page {pageNumber}</span>
  </article>
}

const STUDY_PANEL_WIDTHS_KEY = 'study-documents-panel-widths'
const STUDY_PANEL_LIMITS = {
  library: { min: 190, max: 380, initial: 250 },
  assistant: { min: 280, max: 460, initial: 340 },
}

function clampStudyWidth(panel, value, availableWidth = Infinity) {
  const { min, max } = STUDY_PANEL_LIMITS[panel]
  return Math.max(min, Math.min(max, availableWidth, Math.round(value)))
}

function readStudyPanelWidths() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STUDY_PANEL_WIDTHS_KEY) || '{}')
    return {
      library: clampStudyWidth('library', Number(saved.library) || STUDY_PANEL_LIMITS.library.initial),
      assistant: clampStudyWidth('assistant', Number(saved.assistant) || STUDY_PANEL_LIMITS.assistant.initial),
    }
  } catch {
    return { library: STUDY_PANEL_LIMITS.library.initial, assistant: STUDY_PANEL_LIMITS.assistant.initial }
  }
}

function StudyResizeDivider({ panel, value, maxValue, onResizeStart, onResizeMove, onResizeEnd, onKeyDown }) {
  const limits = STUDY_PANEL_LIMITS[panel]
  return <div className="study-resize-divider" role="separator" aria-orientation="vertical" aria-label={`Resize ${panel} panel`}
    aria-valuemin={limits.min} aria-valuemax={maxValue ?? limits.max} aria-valuenow={value} tabIndex={0}
    onPointerDown={onResizeStart} onPointerMove={onResizeMove} onPointerUp={onResizeEnd}
    onPointerCancel={onResizeEnd} onLostPointerCapture={onResizeEnd} onKeyDown={onKeyDown}>
    <span aria-hidden="true">‹›</span>
  </div>
}

export default function StudyPDF() {
  const { token, user } = useAuth()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedDocumentId = searchParams.get('document_id')
  const requestedPageNumber = Number(searchParams.get('page'))
  const initialSearchQuery = location.state?.searchQuery || ''
  const [sourceExcerpt, setSourceExcerpt] = useState(() => location.state?.sourceExcerpt || '')
  const [documents, setDocuments] = useState([])
  const [documentId, setDocumentId] = useState('')
  const [pages, setPages] = useState([])
  const [docxStructure, setDocxStructure] = useState([])
  const [spreadsheetData, setSpreadsheetData] = useState([])
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
  const [panelWidths, setPanelWidths] = useState(readStudyPanelWidths)
  const [workspaceWidth, setWorkspaceWidth] = useState(0)
  const workspaceRef = useRef(null)
  const panelWidthsRef = useRef(panelWidths)
  const resizeDragRef = useRef(null)
  const [activeStudySection, setActiveStudySection] = useState('viewer')
  const [excerptOpen, setExcerptOpen] = useState(false)
  const [zoom, setZoom] = useState(100)
  const [fitWidth, setFitWidth] = useState(true)
  const initialScrollKey = useRef('')
  const onPageVisible = useCallback((index) => setPageIndex(index), [])

  useEffect(() => {
    const workspace = workspaceRef.current
    if (!workspace) return undefined
    const updateWidth = () => setWorkspaceWidth(workspace.getBoundingClientRect().width)
    updateWidth()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', updateWidth)
      return () => window.removeEventListener('resize', updateWidth)
    }
    const observer = new ResizeObserver(updateWidth)
    observer.observe(workspace)
    return () => observer.disconnect()
  }, [listLoading, documents.length])

  useEffect(() => {
    panelWidthsRef.current = panelWidths
  }, [panelWidths])

  useEffect(() => () => {
    document.documentElement.classList.remove('study-panels-resizing')
  }, [])

  function updatePanelWidth(panel, value, persist = false) {
    const limits = STUDY_PANEL_LIMITS[panel]
    const pairedColumn = libraryOpen && assistantOpen && threeColumnLayout
    const otherWidth = panel === 'library' ? panelWidthsRef.current.assistant : panelWidthsRef.current.library
    const currentAvailable = Math.max(limits.min, workspaceWidth - 360 - (pairedColumn ? otherWidth + 48 : 0))
    const nextWidth = clampStudyWidth(panel, value, Math.min(limits.max, currentAvailable))
    const nextWidths = { ...panelWidthsRef.current, [panel]: nextWidth }
    panelWidthsRef.current = nextWidths
    setPanelWidths(nextWidths)
    if (persist) {
      try { window.localStorage.setItem(STUDY_PANEL_WIDTHS_KEY, JSON.stringify(nextWidths)) } catch { /* Storage may be disabled. */ }
    }
  }

  function startPanelResize(panel, event) {
    if (event.button !== undefined && event.button !== 0) return
    event.preventDefault()
    event.currentTarget.setPointerCapture?.(event.pointerId)
    resizeDragRef.current = { panel, pointerId: event.pointerId, startX: event.clientX, startWidth: panelWidthsRef.current[panel] }
    document.documentElement.classList.add('study-panels-resizing')
  }

  function movePanelResize(event) {
    const drag = resizeDragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const direction = drag.panel === 'assistant' ? -1 : 1
    updatePanelWidth(drag.panel, drag.startWidth + (event.clientX - drag.startX) * direction)
  }

  function endPanelResize(event) {
    const drag = resizeDragRef.current
    if (!drag || (event.pointerId !== undefined && drag.pointerId !== event.pointerId)) return
    resizeDragRef.current = null
    document.documentElement.classList.remove('study-panels-resizing')
    try { window.localStorage.setItem(STUDY_PANEL_WIDTHS_KEY, JSON.stringify(panelWidthsRef.current)) } catch { /* Storage may be disabled. */ }
  }

  function handleResizeKey(panel, event) {
    const limits = STUDY_PANEL_LIMITS[panel]
    const direction = panel === 'assistant' ? -1 : 1
    let nextWidth
    if (event.key === 'ArrowLeft') nextWidth = panelWidthsRef.current[panel] - 16 * direction
    else if (event.key === 'ArrowRight') nextWidth = panelWidthsRef.current[panel] + 16 * direction
    else if (event.key === 'Home') nextWidth = limits.min
    else if (event.key === 'End') nextWidth = limits.max
    else return
    event.preventDefault()
    updatePanelWidth(panel, nextWidth, true)
  }

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
      setDocxStructure([])
      setSpreadsheetData([])
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
        setDocxStructure(pageData.structure || [])
        setSpreadsheetData(pageData.spreadsheet || [])
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



  const selectedDocument = documents.find((doc) => String(doc.id) === documentId)
  const canEditSpreadsheet = Boolean(selectedDocument && (user?.role === 'ADMIN' || String(selectedDocument.uploaded_by) === String(user?.id)))
  const searchUnits = useMemo(() => selectedDocument?.file_type === 'DOCX' && docxStructure.length
    ? docxStructure.map((block) => ({
      text: block.type === 'table' ? block.rows.map((row) => row.join(' | ')).join('\n') : block.text || '',
    }))
    : pages, [selectedDocument?.file_type, docxStructure, pages])
  const matches = useMemo(() => {
    const term = query.trim().toLocaleLowerCase()
    if (!term) return []
    const exact = searchUnits.flatMap((page, index) => {
      const text = page.text.toLocaleLowerCase()
      const found = []
      let offset = 0
      while ((offset = text.indexOf(term, offset)) !== -1) {
        found.push({ pageIndex: index, offset })
        offset += Math.max(1, term.length)
      }
      return found
    })
    if (exact.length) return exact.map((match, matchIndex) => ({ ...match, matchIndex }))
    const terms = [...new Set(term.match(/[\p{L}\p{N}_]+/gu) || [])].filter((word) => word.length > 1)
    return searchUnits.flatMap((page, index) => {
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
    }).map((match, matchIndex) => ({ ...match, matchIndex }))
  }, [searchUnits, query])
  const docxTotalTextLength = searchUnits.reduce((total, unit) => total + unit.text.length + 1, 0)
  const docxUnitOffsets = []
  searchUnits.forEach((unit, index) => {
    docxUnitOffsets[index] = index ? docxUnitOffsets[index - 1] + searchUnits[index - 1].text.length + 1 : 0
  })
  const docxMarkers = selectedDocument?.file_type === 'DOCX'
    ? matches.map((match) => ({ ...match, top: ((docxUnitOffsets[match.pageIndex] + match.offset) / Math.max(1, docxTotalTextLength)) * 100 }))
    : []
  const outlineEntries = selectedDocument?.file_type === 'DOCX'
    ? docxStructure.flatMap((block, index) => ['heading', 'title'].includes(block.type)
      ? [{ level: block.level || 1, title: block.text, page_number: index + 1 }]
      : [])
    : outline
  const outlineTree = useMemo(() => makeOutlineTree(outlineEntries), [outlineEntries])
  const currentPage = pages[pageIndex]
  const pageNumber = currentPage?.page_number || pageIndex + 1
  const pageMatches = matches.filter((match) => match.pageIndex === pageIndex)
  const activeMatch = matches[matchIndex]
  const activeMatchUnit = activeMatch ? searchUnits[activeMatch.pageIndex] : null
  const matchingExcerpt = selectedDocument?.file_type === 'PDF'
    ? currentPage?.text && pageMatches.length
      ? currentPage.text.slice(Math.max(0, pageMatches[0].offset - 150), pageMatches[0].offset + 570)
      : ''
    : activeMatchUnit?.text
      ? activeMatchUnit.text.slice(Math.max(0, activeMatch.offset - 150), activeMatch.offset + 570)
      : ''
  const sourcePageIsCurrent = Number.isInteger(requestedPageNumber) && pageNumber === requestedPageNumber
  const visibleExcerpt = sourcePageIsCurrent ? sourceExcerpt || matchingExcerpt : matchingExcerpt
  const canResizePanels = workspaceWidth >= 642
  const threeColumnLayout = canResizePanels && libraryOpen && assistantOpen
    && workspaceWidth >= panelWidths.library + panelWidths.assistant + 408
  const visibleLibraryWidth = canResizePanels && libraryOpen
    ? clampStudyWidth('library', panelWidths.library, Math.max(190, workspaceWidth - 360 - (threeColumnLayout ? panelWidths.assistant + 48 : 0)))
    : panelWidths.library
  const visibleAssistantWidth = canResizePanels && assistantOpen
    ? clampStudyWidth('assistant', panelWidths.assistant, Math.max(280, workspaceWidth - 360 - (threeColumnLayout ? panelWidths.library + 48 : 0)))
    : panelWidths.assistant
  const libraryMaxWidth = canResizePanels
    ? clampStudyWidth('library', STUDY_PANEL_LIMITS.library.max, Math.max(190, workspaceWidth - 360 - (threeColumnLayout ? panelWidths.assistant + 48 : 0)))
    : STUDY_PANEL_LIMITS.library.max
  const assistantMaxWidth = canResizePanels
    ? clampStudyWidth('assistant', STUDY_PANEL_LIMITS.assistant.max, Math.max(280, workspaceWidth - 360 - (threeColumnLayout ? panelWidths.library + 48 : 0)))
    : STUDY_PANEL_LIMITS.assistant.max
  const workspaceGridStyle = canResizePanels ? {
    '--study-library-width': `${visibleLibraryWidth}px`,
    '--study-assistant-width': `${visibleAssistantWidth}px`,
  } : undefined


  useEffect(() => {
    if (!assistantOpen) return undefined
    function closeOnEscape(event) {
      if (event.key === 'Escape') {
        setAssistantOpen(false)
        setActiveStudySection('viewer')
      }
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [assistantOpen])

  function selectDocument(id) {
    if (!id || id === documentId) return
    setDocumentId(id)
    setDocumentLoading(true)
    setError('')
    setPages([])
    setDocxStructure([])
    setSpreadsheetData([])
    setOutline([])
    setPdfUrl('')
    setPageIndex(0)
    setQuery('')
    setSourceExcerpt('')
    setMatchIndex(0)
    setCollapsed(new Set())
    if (window.matchMedia('(max-width: 1200px)').matches) setLibraryOpen(false)
    setActiveStudySection('viewer')
    setSearchParams({ document_id: id })
  }

  function goToPage(number) {
    const index = pages.findIndex((page, position) => (page.page_number || position + 1) === number)
    if (index >= 0) {
      setPageIndex(index)
      document.getElementById(`study-pdf-page-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  function goToUnitIndex(index) {
    if (!Number.isInteger(index) || index < 0 || index >= searchUnits.length) return
    setPageIndex(index)
    document.getElementById(`study-unit-${index}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  function navigateMatch(direction) {
    if (!matches.length) return
    const next = (matchIndex + direction + matches.length) % matches.length
    setExcerptOpen(false)
    setMatchIndex(next)
    if (selectedDocument?.file_type === 'PDF') {
      goToPage(pages[matches[next].pageIndex]?.page_number || matches[next].pageIndex + 1)
    } else {
      goToUnitIndex(matches[next].pageIndex)
    }
  }

  function selectSearchMatch(index, unitIndex) {
    setMatchIndex(index)
    setExcerptOpen(false)
    goToUnitIndex(unitIndex)
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

  return <div className={`page-content study-page${assistantOpen ? ' assistant-open' : ''}`}>
    <header className="page-heading study-heading">
      <div><span className="eyebrow">READ · SEARCH · STUDY</span><h1>Study Documents</h1>
        <p>Read authorized documents and ask BaseAI questions grounded in the selected file.</p>
      </div>
      <span className="study-document-count">{documents.length} {documents.length === 1 ? 'document' : 'documents'}</span>
    </header>
    <nav className="study-section-nav" aria-label="Study sections">
      <button type="button" aria-pressed={activeStudySection === 'documents'}
        className={activeStudySection === 'documents' ? 'active' : ''}
        onClick={() => { setActiveStudySection('documents'); setLibraryOpen(true); setAssistantOpen(false) }}>Documents</button>
      <button type="button" aria-pressed={activeStudySection === 'viewer'}
        className={activeStudySection === 'viewer' ? 'active' : ''}
        onClick={() => { setActiveStudySection('viewer'); setLibraryOpen(false); setAssistantOpen(false) }}>PDF Viewer</button>
      <button type="button" aria-pressed={activeStudySection === 'assistant'}
        className={activeStudySection === 'assistant' ? 'active' : ''}
        onClick={() => { setActiveStudySection('assistant'); setLibraryOpen(false); setAssistantOpen(true) }}>Study Assistant</button>
    </nav>
    <ErrorMessage>{error}</ErrorMessage>
    <div ref={workspaceRef} style={workspaceGridStyle}
      className={`study-workspace study-section-${activeStudySection}${libraryOpen ? ' library-open' : ''}${assistantOpen ? ' assistant-open' : ''}${canResizePanels ? ' study-panels-resizable' : ''}${threeColumnLayout ? ' study-panels-three-column' : ''}`}>
      {libraryOpen && <aside className="study-library panel" aria-label="Document library and table of contents">
        <div className="study-panel-heading"><div><span className="eyebrow">DOCUMENT LIBRARY</span><h2>Study materials</h2></div><span className="heading-count">{documents.length}</span></div>
        <nav className="study-document-list" aria-label="Available documents">
          {documents.map((doc) => {
            const title = getDocumentTitle(doc)
            const filename = getDistinctFilename(doc)
            return <button key={doc.id} type="button" aria-current={documentId === String(doc.id) ? 'page' : undefined}
              className={`study-document-option${documentId === String(doc.id) ? ' selected' : ''}`}
              onClick={() => { selectDocument(String(doc.id)); setActiveStudySection('viewer') }}>
              <span className={`file-badge ${doc.file_type.toLowerCase()}`}>{doc.file_type}</span><span><strong title={title}>{title}</strong>{filename && <small title={filename}>{filename}</small>}</span>
            </button>
          })}
        </nav>
        <div className="study-outline-heading"><span className="eyebrow">TABLE OF CONTENTS</span></div>
        {(selectedDocument?.file_type === 'PDF' || selectedDocument?.file_type === 'DOCX') && outlineTree.length
          ? <ul className="study-outline"><OutlineItems items={outlineTree} collapsed={collapsed} toggle={toggleOutline}
            goToPage={selectedDocument.file_type === 'DOCX' ? (number) => goToUnitIndex(number - 1) : goToPage}
            currentPage={selectedDocument.file_type === 'DOCX' ? pageIndex + 1 : pageNumber} /></ul>
          : selectedDocument?.file_type === 'PDF'
            ? <p className="outline-empty">This PDF has no saved bookmarks. Use page navigation or search its text.</p>
            : selectedDocument?.file_type === 'DOCX'
              ? <p className="outline-empty">This Word document has no heading styles for a table of contents.</p>
              : null}
      </aside>}
      {libraryOpen && <button type="button" className="study-library-backdrop" aria-label="Close PDF navigation" onClick={() => setLibraryOpen(false)} />}
      {canResizePanels && libraryOpen && <StudyResizeDivider panel="library" value={visibleLibraryWidth} maxValue={libraryMaxWidth}
        onResizeStart={(event) => startPanelResize('library', event)} onResizeMove={movePanelResize}
        onResizeEnd={endPanelResize} onKeyDown={(event) => handleResizeKey('library', event)} />}

      <section className="study-reader panel" aria-label="Document reader">
        <div className="reader-toolbar">
          <button type="button" className="reader-icon-button" aria-label={libraryOpen ? 'Hide PDF navigation' : 'Show PDF navigation'}
            aria-expanded={libraryOpen} onClick={() => { setLibraryOpen((open) => !open); setActiveStudySection(libraryOpen ? 'viewer' : 'documents') }}><LibraryIcon /></button>
          <div className="reader-document-title"><span className={`file-badge ${selectedDocument?.file_type?.toLowerCase() || 'pdf'}`}>{selectedDocument?.file_type || 'PDF'}</span><div><strong title={getDocumentTitle(selectedDocument)}>{getDocumentTitle(selectedDocument)}</strong>{getDistinctFilename(selectedDocument) && <small>{getDistinctFilename(selectedDocument)}</small>}</div></div>
          <div className="reader-toolbar-actions">
            {pdfUrl && <a className="button button-secondary button-small" href={pdfUrl} download={selectedDocument?.original_filename || 'document.pdf'}>Download</a>}
            <button type="button" className="reader-icon-button assistant-launcher" aria-label="Open BaseAI study assistant"
              title="Ask BaseAI" aria-expanded={assistantOpen} onClick={() => { setAssistantOpen(true); setActiveStudySection('assistant') }}>
              <img className="assistant-launcher-icon" src="/Screenshot%202026-11-09%20010326.png" alt="" />
            </button>
          </div>
        </div>
        {selectedDocument && <div className="reader-search-tools">
          <label className="sr-only" htmlFor="study-search">Search this {selectedDocument.file_type} document</label>
          <input id="study-search" type="search" value={query} onChange={(event) => { setQuery(event.target.value); setMatchIndex(0); setExcerptOpen(false) }} placeholder={`Search ${selectedDocument.file_type} content`} />
          <span className="study-match-count" aria-live="polite">{query ? `${matches.length ? matchIndex + 1 : 0} of ${matches.length} matches` : `Search within ${selectedDocument.file_type}`}</span>
          <button type="button" className="button button-secondary button-small" onClick={() => navigateMatch(-1)} disabled={!matches.length} aria-label="Previous search match">Previous</button>
          <button type="button" className="button button-secondary button-small" onClick={() => navigateMatch(1)} disabled={!matches.length} aria-label="Next search match">Next</button>
          <button type="button" className="button button-tertiary button-small" onClick={() => { setQuery(''); setMatchIndex(0); setExcerptOpen(false) }} disabled={!query}>Clear</button>
        </div>}
        {selectedDocument && <div className="reader-controls">
          {selectedDocument.file_type === 'PDF' && <>
            <button className="button button-secondary button-small" type="button" disabled={pageIndex <= 0} onClick={() => goToPage(pageNumber - 1)}>Previous page</button>
            <label>Page <input aria-label="Current page" type="number" min="1" max={pages.length} value={pageNumber}
              onChange={(event) => goToPage(Number(event.target.value))} /></label>
            <span>of {pages.length}</span>
            <button className="button button-secondary button-small" type="button" disabled={pageIndex >= pages.length - 1} onClick={() => goToPage(pageNumber + 1)}>Next page</button>
          </>}
          {selectedDocument.file_type === 'PPTX' && <>
            <button className="button button-secondary button-small" type="button" disabled={pageIndex <= 0} onClick={() => goToUnitIndex(pageIndex - 1)}>Previous slide</button>
            <span>Slide {pageIndex + 1} of {pages.length}</span>
            <button className="button button-secondary button-small" type="button" disabled={pageIndex >= pages.length - 1} onClick={() => goToUnitIndex(pageIndex + 1)}>Next slide</button>
          </>}
          {selectedDocument.file_type === 'XLSX' && <>
            <button className="button button-secondary button-small" type="button" disabled={pageIndex <= 0} onClick={() => goToUnitIndex(pageIndex - 1)}>Previous sheet</button>
            <span>Sheet {pageIndex + 1} of {pages.length}</span>
            <button className="button button-secondary button-small" type="button" disabled={pageIndex >= pages.length - 1} onClick={() => goToUnitIndex(pageIndex + 1)}>Next sheet</button>
          </>}
          <span className="reader-control-divider" />
          <button className="button button-tertiary button-small" type="button" aria-label="Zoom out" disabled={fitWidth || zoom <= 50} onClick={() => setZoom((value) => Math.max(50, value - 10))}>−</button>
          <span className="zoom-value">{fitWidth ? 'Fit width' : `${zoom}%`}</span>
          <button className="button button-tertiary button-small" type="button" aria-label="Zoom in" disabled={fitWidth || zoom >= 200} onClick={() => setZoom((value) => Math.min(200, value + 10))}>+</button>
          <button className="button button-tertiary button-small" type="button" onClick={() => setFitWidth((fit) => !fit)}>{fitWidth ? 'Set zoom' : 'Fit width'}</button>
        </div>}
        {documentLoading ? <div className="reader-empty"><PageLoading label="Opening document preview…" /></div>
          : error ? <div className="reader-empty"><ErrorMessage>{error}</ErrorMessage><button className="button button-secondary" onClick={retry}>Retry document</button></div>
            : selectedDocument?.file_type !== 'PDF' ? <>
              {query && visibleExcerpt && <section className="study-source-excerpt">
                <div className="study-excerpt-heading"><span>Match {matchIndex + 1} of {matches.length}</span>
                  <button type="button" className="button button-secondary button-small"
                    aria-expanded={excerptOpen} onClick={() => setExcerptOpen((open) => !open)}>
                    {excerptOpen ? 'Close excerpt' : 'Open excerpt'}
                  </button>
                </div>
                {excerptOpen && <p>{highlightText(visibleExcerpt, query)}</p>}
              </section>}
              {query && matches.length === 0 && <p className="reader-no-match">No matches found in this {selectedDocument.file_type} document.</p>}
              <DocumentPreview document={selectedDocument} pages={pages} structure={docxStructure} spreadsheet={spreadsheetData}
                token={token} documentId={documentId} query={query} zoom={zoom}
                fitWidth={fitWidth} matches={matches} docxMarkers={docxMarkers}
                docxTotalTextLength={docxTotalTextLength} activeMatchIndex={matchIndex}
                activeSheetIndex={pageIndex} canEdit={canEditSpreadsheet} onSelectUnit={goToUnitIndex}
                onVisible={onPageVisible} onSelectMatch={selectSearchMatch} onSaved={retry} />
            </>
            : <>
              {visibleExcerpt && <section className="study-source-excerpt">
                <div className="study-excerpt-heading">
                  <span>{sourceExcerpt && sourcePageIsCurrent ? 'Retrieved source passage' : `Matching text excerpt · page ${pageNumber}`}</span>
                  <button type="button" className="button button-secondary button-small"
                    aria-expanded={excerptOpen} onClick={() => setExcerptOpen((open) => !open)}>
                    {excerptOpen ? 'Close excerpt' : 'Open excerpt'}
                  </button>
                </div>
                {excerptOpen && <><p>{highlightText(visibleExcerpt, query)}</p>
                  <small>{pageMatches.length
                    ? 'Exact text matches are highlighted on this rendered page and in the excerpt.'
                    : 'This is the retrieved source excerpt. The page highlights exact text matches for the current search.'}</small></>}
              </section>}
              <div className="pdf-pages-scroll" aria-label="PDF pages">
                {pages.map((page, index) => <StudyPDFPage key={`${documentId}:${page.page_number || index + 1}`}
                  token={token} documentId={documentId} page={page} index={index} query={query}
                  fitWidth={fitWidth} zoom={zoom} onVisible={onPageVisible} isCurrent={pageIndex === index}
                  matches={matches.flatMap((match, globalMatchIndex) => match.pageIndex === index
                    ? [{ ...match, matchIndex: globalMatchIndex, activeMatchIndex: matchIndex, totalMatches: matches.length }]
                    : [])}
                  onSelectMatch={(selected) => { setMatchIndex(selected); setExcerptOpen(false); goToPage(page.page_number || index + 1) }} />)}
        </div>
              {query && matches.length === 0 && <p className="reader-no-match">No exact text matches in this PDF. A retrieved passage may still be shown above.</p>}
            </>}
      </section>
      {canResizePanels && assistantOpen && (!libraryOpen || threeColumnLayout) && <StudyResizeDivider panel="assistant" value={visibleAssistantWidth} maxValue={assistantMaxWidth}
        onResizeStart={(event) => startPanelResize('assistant', event)} onResizeMove={movePanelResize}
        onResizeEnd={endPanelResize} onKeyDown={(event) => handleResizeKey('assistant', event)} />}
      {assistantOpen && <aside className="study-assistant panel" role="dialog" aria-modal="false" aria-label="BaseAI study assistant">
        <div className="study-assistant-heading"><div><span className="eyebrow">STUDY ASSISTANT</span><strong>{selectedDocument?.title}</strong></div>
          <button type="button" className="reader-icon-button" aria-label="Close BaseAI assistant" onClick={() => { setAssistantOpen(false); setActiveStudySection('viewer') }}>×</button></div>
        <BaseAI key={documentId} compact documentId={documentId} documentTitle={selectedDocument?.title} />
      </aside>}
    </div>
  </div>
}

function PageHeading() {
  return <header className="page-heading"><div><span className="eyebrow">READ · SEARCH · STUDY</span><h1>Study Documents</h1><p>Read authorized documents and search extracted text.</p></div></header>
}
