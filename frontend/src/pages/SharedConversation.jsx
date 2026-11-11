import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { conversationsApi } from '../api/client'

export default function SharedConversation() {
  const { shareToken } = useParams()
  const [conversation, setConversation] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    conversationsApi.shared(shareToken).then(setConversation).catch((err) => setError(err.message))
  }, [shareToken])
  return <main className="shared-conversation page-content">
    <header><span className="eyebrow">SHARED BASEAI CONVERSATION</span><h1>{conversation?.title || (error ? 'Conversation unavailable' : 'Loading conversation…')}</h1><p>Read-only shared conversation</p></header>
    {error && <p role="alert">{error}</p>}
    {conversation?.messages?.map((message) => <article className={`baseai-message baseai-message-${message.role}`} key={message.id}>
      <span className="answer-label">{message.role === 'user' ? 'You' : 'BaseAI'}</span>
      <p>{message.content}</p>
      {message.citations?.map((citation) => <p className="shared-citation" key={`${message.id}-${citation.source_id}`}>[{citation.source_id}] {citation.document_title}{citation.source_reference ? ` · ${citation.source_reference}` : ''}</p>)}
    </article>)}
    <Link className="button button-secondary" to="/login">Open Enterprise KB</Link>
  </main>
}
