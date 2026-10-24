import { useEffect, useRef, useState } from 'react'
import { ragApi } from '../api/client'
import { EmptyState, ErrorMessage } from './Feedback'
import { useAuth } from '../context/useAuth'

function proseBlocks(content, keyPrefix) {
  const lines = content.split('\n')
  const blocks = []
  let paragraph = []
  let listItems = []
  let listType = ''

  function flushParagraph() {
    if (!paragraph.length) return
    blocks.push(<p key={`${keyPrefix}-p-${blocks.length}`}>{paragraph.join(' ')}</p>)
    paragraph = []
  }

  function flushList() {
    if (!listItems.length) return
    const Tag = listType === 'ordered' ? 'ol' : 'ul'
    blocks.push(<Tag key={`${keyPrefix}-list-${blocks.length}`}>
      {listItems.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
    </Tag>)
    listItems = []
    listType = ''
  }

  lines.forEach((line) => {
    const match = line.match(/^\s*(?:([-*•])|(\d+)[.)])\s+(.+)$/)
    if (match) {
      flushParagraph()
      const nextType = match[2] ? 'ordered' : 'unordered'
      if (listType && listType !== nextType) flushList()
      listType = nextType
      listItems.push(match[3])
    } else if (!line.trim()) {
      flushParagraph()
      flushList()
    } else {
      flushList()
      paragraph.push(line.trim())
    }
  })
  flushParagraph()
  flushList()
  return blocks
}

function FormattedAnswer({ text }) {
  const sections = []
  const codePattern = /```([\w-]*)\n([\s\S]*?)```/g
  let cursor = 0
  let match
  while ((match = codePattern.exec(text)) !== null) {
    if (match.index > cursor) {
      sections.push(...proseBlocks(text.slice(cursor, match.index), `answer-${sections.length}`))
    }
    sections.push(<pre className="answer-code" key={`answer-code-${sections.length}`}>
      <code>{match[2].replace(/\n$/, '')}</code>
    </pre>)
    cursor = codePattern.lastIndex
  }
  if (cursor < text.length) {
    sections.push(...proseBlocks(text.slice(cursor), `answer-${sections.length}`))
  }
  return <div className="answer-content">{sections}</div>
}

export default function BaseAI({ documentId, documentTitle, compact = false, suggestions = [] }) {
  const { token } = useAuth()
  const [question, setQuestion] = useState('')
  const [response, setResponse] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const controllerRef = useRef(null)

  useEffect(() => () => controllerRef.current?.abort(), [documentId])

  async function submit(event) {
    event.preventDefault()
    if (loading) return
    if (!question.trim()) { setError('Enter a question to get started.'); return }
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setLoading(true)
    setError('')
    setResponse(null)
    try {
      const result = await ragApi.ask(token, question.trim(), 5, {
        documentId: documentId || undefined,
        signal: controller.signal,
      })
      if (!controller.signal.aborted) setResponse(result)
    } catch (err) {
      if (!controller.signal.aborted) setError(err.message)
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  function askAnother() {
    setQuestion('')
    setResponse(null)
    setError('')
  }

  const displayAnswer = response?.answer_type === 'general'
    ? response.answer.replace(/^General information\s*\(not company policy\):\s*/i, '')
    : response?.answer

  return <section className={`baseai-panel${compact ? ' baseai-compact' : ''}`} aria-label="BaseAI question assistant">
    <div className="baseai-heading">
      <span className="baseai-mark" aria-hidden="true">B</span>
      <div><span className="eyebrow">{documentId ? 'DOCUMENT STUDY' : 'KNOWLEDGE ASSISTANT'}</span>
        <h2>{documentId ? 'Ask about this PDF' : 'Ask BaseAI'}</h2>
      </div>
    </div>
    {documentId
      ? <p className="baseai-scope">Questions are searched only in <strong>{documentTitle || 'the selected PDF'}</strong>.</p>
      : <p className="baseai-scope">Answers use documents you are authorized to access. General responses are labeled clearly.</p>}
    <ErrorMessage>{error}</ErrorMessage>
    <form className="baseai-form" onSubmit={submit}>
      <label className="sr-only" htmlFor={documentId ? 'study-baseai-question' : 'baseai-question'}>Your question</label>
      <textarea id={documentId ? 'study-baseai-question' : 'baseai-question'} rows={compact ? 3 : 4}
        maxLength={2000} value={question} disabled={loading}
        onChange={(event) => setQuestion(event.target.value)}
        placeholder={documentId ? `Ask a question about ${documentTitle || 'this PDF'}…` : 'Ask about a policy, process, or company resource…'} />
      <div className="baseai-form-actions"><span>{question.length}/2000</span>
        <button className="button button-primary" disabled={loading || !question.trim()}>
          {loading ? <><span className="spinner spinner-light" /> Thinking…</> : 'Get answer'}
        </button>
      </div>
    </form>
    {suggestions.length > 0 && !response && <div className="baseai-suggestions">
      <span className="eyebrow">TRY A QUESTION</span>
      {suggestions.map((item) => <button type="button" key={item} disabled={loading}
        onClick={() => { setQuestion(item); setError('') }}>{item}</button>)}
    </div>}
    {loading && <div className="baseai-loading" role="status">Reviewing authorized evidence…</div>}
    {response && <div className="baseai-response" aria-live="polite">
      <div className="baseai-response-title"><span className="eyebrow">RESPONSE</span>
        <button type="button" className="button button-tertiary button-small" onClick={askAnother}>Ask another</button>
      </div>
      {response.insufficient_evidence
        ? <div className="abstention-card"><strong>Not enough supporting information</strong><p>{response.answer}</p></div>
        : <article className={`answer-card ${response.answer_type === 'general' ? 'answer-general' : ''}`}>
          <span className="answer-label">{response.answer_type === 'general' ? 'General information · not company policy' : 'Grounded in authorized documents'}</span>
          <FormattedAnswer text={displayAnswer || ''} />
        </article>}
      {response.citations?.length > 0 && <div className="citation-list" aria-label="Answer sources">
        {response.citations.map((citation) => <article className="citation-card" key={citation.source_id}>
          <span className="citation-marker">[{citation.source_id}]</span>
          <div className="citation-content"><strong>{citation.document_title}</strong>
            <small>Chunk {citation.chunk_index + 1}{citation.page_number ? ` · page ${citation.page_number}` : ''}</small>
            {citation.excerpt && <p>{citation.excerpt}</p>}
          </div>
        </article>)}
      </div>}
      {!response.insufficient_evidence && response.answer_type !== 'general' && !response.citations?.length
        && <EmptyState title="No citations were returned">Check the answer against the document before relying on it.</EmptyState>}
    </div>}
  </section>
}
