import { useEffect, useRef, useState } from 'react'
import { conversationsApi, ragApi } from '../api/client'
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

export default function BaseAI({ documentId, documentTitle, compact = false, fullPage = false, suggestions = [] }) {
  const { token } = useAuth()
  const [question, setQuestion] = useState('')
  const [response, setResponse] = useState(null)
  const [messages, setMessages] = useState([])
  const [conversationId, setConversationId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const controllerRef = useRef(null)

  useEffect(() => () => controllerRef.current?.abort(), [documentId])

  useEffect(() => {
    if (!fullPage || documentId) return undefined
    async function openConversation(event) {
      controllerRef.current?.abort()
      setLoading(false); setError(''); setResponse(null); setQuestion('')
      if (event.detail?.create || !event.detail?.conversationId) {
        setConversationId(null); setMessages([]); return
      }
      try {
        const result = await conversationsApi.get(token, event.detail.conversationId)
        setConversationId(result.id); setMessages(result.messages || [])
        window.dispatchEvent(new CustomEvent('conversation:selected', { detail: { conversationId: result.id } }))
      } catch (err) { setConversationId(null); setMessages([]); setError(err.message) }
    }
    function handleLock(event) {
      if (event.detail?.conversationId === conversationId) {
        setConversationId(null); setMessages([]); setError('This chat is locked. Unlock it in Chat history to continue.')
      }
    }
    function handleUnavailable(event) {
      if (event.detail?.conversationId === conversationId) {
        setConversationId(null); setMessages([]); setError(event.detail.reason || 'This chat is no longer available.')
      }
    }
    window.addEventListener('conversation:open', openConversation)
    window.addEventListener('conversation:locked', handleLock)
    window.addEventListener('conversation:unavailable', handleUnavailable)
    return () => {
      window.removeEventListener('conversation:open', openConversation)
      window.removeEventListener('conversation:locked', handleLock)
      window.removeEventListener('conversation:unavailable', handleUnavailable)
    }
  }, [conversationId, documentId, fullPage, token])

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
    const prompt = question.trim()
    try {
      let activeConversationId = conversationId
      if (fullPage && !documentId) {
        if (!activeConversationId) {
          const created = await conversationsApi.create(token)
          activeConversationId = created.id
          setConversationId(created.id)
          window.dispatchEvent(new CustomEvent('conversation:selected', { detail: { conversationId: created.id } }))
        }
        await conversationsApi.addMessage(token, activeConversationId, { role: 'user', content: prompt })
        setMessages((current) => [...current, { role: 'user', content: prompt, citations: [], metadata: {} }])
        window.dispatchEvent(new Event('conversation:changed'))
      }
      const result = await ragApi.ask(token, prompt, 5, {
        documentId: documentId || undefined,
        signal: controller.signal,
      })
      if (!controller.signal.aborted) {
        if (fullPage) {
          if (!documentId) {
            await conversationsApi.addMessage(token, activeConversationId, {
              role: 'assistant', content: result.answer || '', citations: result.citations || [],
              metadata: { answer_type: result.answer_type, insufficient_evidence: result.insufficient_evidence },
            })
            window.dispatchEvent(new Event('conversation:changed'))
          }
          setMessages((current) => [...current,
            { role: 'assistant', content: result.answer || '', citations: result.citations || [], metadata: { answer_type: result.answer_type, insufficient_evidence: result.insufficient_evidence } },
          ])
          setQuestion('')
        } else setResponse(result)
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err.message)
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  function handleQuestionKeyDown(event) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (!loading && question.trim()) {
      event.currentTarget.form?.requestSubmit()
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

  return <section className={`baseai-panel${compact ? ' baseai-compact' : ''}${fullPage ? ' baseai-full-page' : ''}`} aria-label="BaseAI question assistant">
    <div className="baseai-heading">
      {!compact && <span className="baseai-mark" aria-hidden="true"><img className="baseai-icon" src="/Screenshot%202026-11-09%20010326.png" alt="" /></span>}
      <div><span className="eyebrow">{documentId ? 'DOCUMENT STUDY' : 'KNOWLEDGE ASSISTANT'}</span>
        <h2>{documentId ? 'Ask about this PDF' : 'Ask BaseAI'}</h2>
      </div>
    </div>
    {documentId
      ? <p className="baseai-scope">Questions are searched only in <strong>{documentTitle || 'the selected PDF'}</strong>.</p>
      : <p className="baseai-scope">Answers use documents you are authorized to access. General responses are labeled clearly.</p>}
    {fullPage && !messages.length && <div className="baseai-welcome"><h3>What would you like to know?</h3><p>Ask a question about your company’s knowledge. BaseAI will search your authorized documents and cite its sources.</p></div>}
    {fullPage && messages.length > 0 && <div className="baseai-transcript" aria-label="Conversation messages">
      {messages.map((message, index) => <article className={`baseai-message baseai-message-${message.role}`} key={message.id || `${message.role}-${index}`}>
        {message.role === 'user' ? <p>{message.content}</p> : <>
          <span className="answer-label">{message.metadata?.answer_type === 'general' ? 'General information · not company policy' : message.metadata?.insufficient_evidence ? 'Insufficient evidence' : 'Grounded in authorized documents'}</span>
          <FormattedAnswer text={message.content || ''} />
          {message.citations?.length > 0 && <div className="citation-list" aria-label="Answer sources">{message.citations.map((citation) => <article className="citation-card" key={`${message.id || index}-${citation.source_id}`}><span className="citation-marker">[{citation.source_id}]</span><div className="citation-content"><strong>{citation.document_title}</strong><small>{citation.source_reference || (citation.chunk_index != null ? `Chunk ${citation.chunk_index + 1}` : '')}</small>{citation.excerpt && <p>{citation.excerpt}</p>}</div></article>)}</div>}
        </>}
      </article>)}
    </div>}
    <ErrorMessage>{error}</ErrorMessage>
    <form className="baseai-form" onSubmit={submit}>
      <label className="sr-only" htmlFor={documentId ? 'study-baseai-question' : 'baseai-question'}>Your question</label>
      <textarea id={documentId ? 'study-baseai-question' : 'baseai-question'} rows={compact ? 3 : 4}
        maxLength={2000} value={question} disabled={loading}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={handleQuestionKeyDown}
        placeholder={documentId ? `Ask a question about ${documentTitle || 'this PDF'}…` : 'Ask about a policy, process, or company resource…'} />
      <div className="baseai-form-actions"><span>{question.length}/2000</span>
        <button className="button button-primary" disabled={loading || !question.trim()}>
          {loading ? <><span className="spinner spinner-light" /> Thinking…</> : 'Get answer'}
        </button>
      </div>
    </form>
    {suggestions.length > 0 && !response && !messages.length && <div className="baseai-suggestions">
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
            <small>{citation.source_reference || `Chunk ${citation.chunk_index + 1}`}</small>
            {citation.excerpt && <p>{citation.excerpt}</p>}
          </div>
        </article>)}
      </div>}
      {!response.insufficient_evidence && response.answer_type !== 'general' && !response.citations?.length
        && <EmptyState title="No citations were returned">Check the answer against the document before relying on it.</EmptyState>}
    </div>}
  </section>
}
