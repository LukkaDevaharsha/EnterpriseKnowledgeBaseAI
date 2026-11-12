import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { createPortal } from 'react-dom'
import { useCallback, useEffect, useRef, useState } from 'react'
import { conversationsApi } from '../api/client'
import { useAuth } from '../context/useAuth'
import ConfirmDialog from './ConfirmDialog'

const ACTION_ICONS = {
  rename: <><path d="m4 16.5-.8 4.3 4.3-.8L19.8 7.7a2.1 2.1 0 0 0-3-3L4 16.5Z" /><path d="m14.8 6.7 3 3" /></>,
  pin: <><path d="m16 3 5 5-3 1-4 4 1 4-2 2-3-5-5-5 2-2 4 1 4-4 1-1Z" /><path d="m9 15-5 5" /></>,
  lock: <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 1 1 8 0v3" /></>,
  unlock: <><rect x="4" y="10" width="16" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 7-2" /></>,
  share: <><path d="M12 16V3m-5 5 5-5 5 5" /><path d="M5 13v7h14v-7" /></>,
  archive: <><path d="M3 4h18v4H3zM5 8v12h14V8" /><path d="M9 12h6" /></>,
  restore: <><path d="M3 4h18v4H3zM5 8v12h14V8" /><path d="M9 14h6" /></>,
  delete: <><path d="M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6" /><path d="M10 10v6m4-6v6" /></>,
}

function ActionIcon({ name }) {
  return <svg className="chat-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ACTION_ICONS[name]}</svg>
}

const NAV_ICONS = {
  home: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1H5a1 1 0 0 1-2-1V9.5Z" /><path d="M9 21V12h6v9" />
    </svg>
  ),
  library: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 2.75h8l4 4V21H6a2 2 0 0 1-2-2V4.75a2 2 0 0 1 2-2Z" /><path d="M14 3v5h5M8 13h8M8 17h8" />
    </svg>
  ),
  ask: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-8.5a7.5 7.5 0 1 1 17 0Z" /><path d="M8 11h.01M12 11h.01M16 11h.01" />
    </svg>
  ),
  study: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 3.5h13a2 2 0 0 1 2 2v15H6a2 2 0 0 1-2-2v-15Z" /><path d="M7 7h8M7 11h8M7 15h5" />
    </svg>
  ),
  admin: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m12 3 8 3v5c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-3Z" /><path d="M9 12h6m-3-3v6" />
    </svg>
  ),
  profile: (
    <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
    </svg>
  ),
}

const EMPLOYEE_LINKS = [
  { to: '/', label: 'Home', icon: 'home', end: true },
  { to: '/library', label: 'Knowledge Library', icon: 'library' },
  { to: '/ask', label: 'Ask BaseAI', icon: 'ask' },
  { to: '/study', label: 'Study Documents', icon: 'study' },
  { to: '/profile', label: 'My Profile', icon: 'profile' },
]

const ADMIN_EXTRA = [{ to: '/admin', label: 'Administration', icon: 'admin' }]

export default function Navbar({ mobileOpen = false, collapsed = false, compactSidebarLayout = false, onToggle = () => {}, onNavigate = () => {} }) {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [conversations, setConversations] = useState([])
  const [menuId, setMenuId] = useState(null)
  const [menuPosition, setMenuPosition] = useState({ top: 0, left: 0 })
  const [recentsOpen, setRecentsOpen] = useState(true)
  const [archivedOpen, setArchivedOpen] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [renameId, setRenameId] = useState(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleteCandidate, setDeleteCandidate] = useState(null)
  const [shareDialog, setShareDialog] = useState(null)
  const [unlockCandidate, setUnlockCandidate] = useState(null)
  const [unlockPassword, setUnlockPassword] = useState('')
  const [unlockError, setUnlockError] = useState('')
  const [unlockBusy, setUnlockBusy] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const [pendingConversation, setPendingConversation] = useState(undefined)
  const popupRef = useRef(null)
  const menuTriggerRef = useRef(null)
  const isAdmin = user?.role === 'ADMIN'
  const links = isAdmin ? [...EMPLOYEE_LINKS, ...ADMIN_EXTRA] : EMPLOYEE_LINKS

  const refreshHistory = useCallback(async () => {
    try {
      const result = await conversationsApi.list(token)
      setConversations(result?.conversations || [])
      setHistoryError('')
    } catch (error) { setHistoryError(error.message) }
  }, [token])
  useEffect(() => {
    if (!token) return undefined
    const timer = window.setTimeout(refreshHistory, 0)
    return () => window.clearTimeout(timer)
  }, [refreshHistory, token])
  useEffect(() => {
    const refresh = () => refreshHistory()
    window.addEventListener('conversation:changed', refresh)
    const select = (event) => setSelectedId(event.detail?.conversationId ?? null)
    window.addEventListener('conversation:selected', select)
    return () => {
      window.removeEventListener('conversation:changed', refresh)
      window.removeEventListener('conversation:selected', select)
    }
  }, [refreshHistory])
  useEffect(() => {
    if (menuId === null) return undefined
    function dismiss(event) {
      if (event.type === 'keydown' && event.key === 'Escape') setMenuId(null)
      if (event.type === 'pointerdown' && !popupRef.current?.contains(event.target) && !menuTriggerRef.current?.contains(event.target)) setMenuId(null)
    }
    document.addEventListener('keydown', dismiss)
    document.addEventListener('pointerdown', dismiss)
    return () => { document.removeEventListener('keydown', dismiss); document.removeEventListener('pointerdown', dismiss) }
  }, [menuId])
  useEffect(() => {
    if (location.pathname !== '/ask' || pendingConversation === undefined) return
    const timer = window.setTimeout(() => {
      window.dispatchEvent(new CustomEvent('conversation:open', { detail: pendingConversation }))
      setPendingConversation(undefined)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [location.pathname, pendingConversation])
  async function newChat() {
    setSelectedId(null)
    setPendingConversation({ conversationId: null, create: true })
    navigate('/ask')
    onNavigate()
  }
  async function openChat(conversation) {
    if (conversation.is_locked) return
    setSelectedId(conversation.id)
    setPendingConversation({ conversationId: conversation.id })
    navigate('/ask')
    onNavigate()
  }
  async function changeChat(chat, changes) {
    try {
      await conversationsApi.update(token, chat.id, changes)
      await refreshHistory()
      setMenuId(null)
      if (changes.is_locked) window.dispatchEvent(new CustomEvent('conversation:locked', { detail: { conversationId: chat.id } }))
      if (changes.is_archived) window.dispatchEvent(new CustomEvent('conversation:unavailable', { detail: { conversationId: chat.id, reason: 'This chat is archived. Restore it to continue.' } }))
      return true
    } catch (error) { setHistoryError(error.message); return false }
  }
  async function shareChat(chat) {
    try {
      const updated = await conversationsApi.update(token, chat.id, { share: true })
      setMenuId(null)
      setShareDialog({ id: chat.id, title: chat.title, url: `${window.location.origin}/shared/${updated.share_token}` })
    } catch (error) { setHistoryError(error.message) }
  }
  async function removeChat(chat) {
    try {
      await conversationsApi.remove(token, chat.id)
      await refreshHistory(); setMenuId(null)
      setDeleteCandidate(null)
      window.dispatchEvent(new CustomEvent('conversation:unavailable', { detail: { conversationId: chat.id, reason: 'This chat was deleted.' } }))
    }
    catch (error) { setHistoryError(error.message) }
  }
  async function saveRename(chat) {
    if (!renameValue.trim()) return
    if (await changeChat(chat, { title: renameValue.trim() })) setRenameId(null)
  }
  function toggleMenu(event, chat) {
    event.stopPropagation()
    if (menuId === chat.id) { setMenuId(null); return }
    const rect = event.currentTarget.getBoundingClientRect()
    const popupWidth = Math.min(224, window.innerWidth - 16)
    const popupHeight = 322
    const top = rect.bottom + popupHeight < window.innerHeight
      ? rect.top
      : Math.max(8, rect.bottom - popupHeight)
    const left = Math.max(8, Math.min(rect.right - popupWidth, window.innerWidth - popupWidth - 8))
    menuTriggerRef.current = event.currentTarget
    setMenuPosition({ top, left })
    setMenuId(chat.id)
  }
  async function unlockChat() {
    if (!unlockCandidate || !unlockPassword) return
    setUnlockBusy(true); setUnlockError('')
    try {
      await conversationsApi.unlock(token, unlockCandidate.id, unlockPassword)
      const chat = unlockCandidate
      setUnlockCandidate(null); setUnlockPassword(''); setUnlockBusy(false)
      await refreshHistory()
      openChat({ ...chat, is_locked: false })
    } catch (error) { setUnlockError(error.message); setUnlockBusy(false) }
  }
  const recentChats = conversations.filter((chat) => !chat.is_archived)
  const archivedChats = conversations.filter((chat) => chat.is_archived)

  return (
    <aside id="primary-navigation" className={`sidebar${mobileOpen ? ' sidebar-open' : ''}${collapsed ? ' sidebar-icons-only' : ''}`}>
      <button type="button" className={collapsed && compactSidebarLayout ? 'nav-link chat-history-section-toggle' : 'sidebar-toggle'} onClick={onToggle}
        aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
        aria-expanded={!collapsed} title={collapsed ? 'Expand navigation' : 'Collapse navigation'}>
        <svg className={collapsed && compactSidebarLayout ? 'nav-icon' : undefined} viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4" width="17" height="16" rx="2" /><path d={collapsed ? 'M8 4v16m4-11 3 3-3 3' : 'M9 4v16m7-11-3 3 3 3'} /></svg>
      </button>
      <NavLink className="brand" to="/" aria-label="Enterprise Knowledge Base" onClick={onNavigate}>
        <span className="brand-mark" aria-hidden="true"><img className="brand-logo-img" src="/Screenshot%202026-11-09%20010326.png" alt="" /></span>
        <span className="brand-name">
          Enterprise KB
          <span>KNOWLEDGE PLATFORM</span>
        </span>
      </NavLink>

      <nav className="side-nav" aria-label="Main navigation">
        {links.map(({ to, label, icon, end }) => (
          <NavLink key={to} to={to} end={end} onClick={onNavigate}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>
            {NAV_ICONS[icon]}
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>

      <section className="chat-history" aria-label="Chat history">
        <div className="chat-history-heading"><strong>Chats</strong><button type="button" onClick={newChat} title="New chat" aria-label="New chat">＋</button></div>
        {historyError && <p className="chat-history-note" role="status">{historyError}</p>}
        <div className="chat-history-list">
          <button type="button" className="chat-history-section-toggle" aria-expanded={recentsOpen} onClick={() => setRecentsOpen((open) => !open)}>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d={recentsOpen ? 'm4 6 4 4 4-4' : 'm6 4 4 4-4 4'} /></svg><span>Recents</span>
          </button>
          {recentsOpen && <div className="chat-history-section">
            {recentChats.map((chat) => <div className={`chat-history-row${selectedId === chat.id ? ' selected' : ''}`} key={chat.id}>
              {renameId === chat.id ? <form className="chat-history-rename" onSubmit={(event) => { event.preventDefault(); saveRename(chat) }}>
                <input aria-label="Conversation title" autoFocus maxLength={200} value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenameId(null) }} />
                <button type="submit" aria-label="Save title">✓</button><button type="button" aria-label="Cancel rename" onClick={() => setRenameId(null)}>×</button>
              </form> : <button type="button" className="chat-history-title" onClick={() => chat.is_locked ? setUnlockCandidate(chat) : openChat(chat)} title={chat.title}>
                {chat.is_pinned && <ActionIcon name="pin" />}<span>{chat.title}</span>{chat.is_locked && <ActionIcon name="lock" />}
              </button>}
              <button type="button" className={`chat-history-menu-toggle${menuId === chat.id ? ' open' : ''}`} data-chat-menu-trigger="true" aria-label={`Actions for ${chat.title}`} aria-expanded={menuId === chat.id} onClick={(event) => toggleMenu(event, chat)}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" /></svg>
              </button>
            </div>)}
            {!recentChats.length && <p className="chat-history-empty">Your conversations will appear here.</p>}
          </div>}
          {archivedChats.length > 0 && <>
            <button type="button" className="chat-history-section-toggle archived-toggle" aria-expanded={archivedOpen} onClick={() => setArchivedOpen((open) => !open)}>
              <svg viewBox="0 0 16 16" aria-hidden="true"><path d={archivedOpen ? 'm4 6 4 4 4-4' : 'm6 4 4 4-4 4'} /></svg><span>Archived Chats</span><small>{archivedChats.length}</small>
            </button>
            {archivedOpen && archivedChats.map((chat) => <div className={`chat-history-row${selectedId === chat.id ? ' selected' : ''}`} key={chat.id}>
              {renameId === chat.id ? <form className="chat-history-rename" onSubmit={(event) => { event.preventDefault(); saveRename(chat) }}>
                <input aria-label="Conversation title" autoFocus maxLength={200} value={renameValue} onChange={(event) => setRenameValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenameId(null) }} />
                <button type="submit" aria-label="Save title">✓</button><button type="button" aria-label="Cancel rename" onClick={() => setRenameId(null)}>×</button>
              </form> : <button type="button" className="chat-history-title" onClick={() => chat.is_locked ? setUnlockCandidate(chat) : openChat(chat)} title={chat.title}><span>{chat.title}</span>{chat.is_locked && <ActionIcon name="lock" />}</button>}
              <button type="button" className={`chat-history-menu-toggle${menuId === chat.id ? ' open' : ''}`} data-chat-menu-trigger="true" aria-label={`Actions for ${chat.title}`} aria-expanded={menuId === chat.id} onClick={(event) => toggleMenu(event, chat)}>
                <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.5" /><circle cx="12" cy="12" r="1.5" /><circle cx="19" cy="12" r="1.5" /></svg>
              </button>
            </div>)}
          </>}
        </div>
      </section>

      {menuId !== null && createPortal(<div className="chat-history-menu" ref={popupRef} role="menu" style={{ top: menuPosition.top, left: menuPosition.left }}>
        {(() => {
          const chat = conversations.find((item) => item.id === menuId)
          if (!chat) return null
          return <>
            <button role="menuitem" onClick={() => { setRenameId(chat.id); setRenameValue(chat.title); setMenuId(null) }}><ActionIcon name="rename" /><span>Rename</span></button>
            <button role="menuitem" onClick={() => changeChat(chat, { is_pinned: !chat.is_pinned })}><ActionIcon name="pin" /><span>{chat.is_pinned ? 'Unpin' : 'Pin'}</span></button>
            <button role="menuitem" onClick={() => {
              setMenuId(null)
              if (chat.is_locked) { setUnlockCandidate(chat); setUnlockError(''); setUnlockPassword('') }
              else changeChat(chat, { is_locked: true })
            }}><ActionIcon name={chat.is_locked ? 'unlock' : 'lock'} /><span>{chat.is_locked ? 'Unlock Chat' : 'Lock Chat'}</span></button>
            <div className="chat-history-menu-separator" />
            <button role="menuitem" onClick={() => shareChat(chat)} disabled={chat.is_locked}><ActionIcon name="share" /><span>Share</span></button>
            <div className="chat-history-menu-separator" />
            <button role="menuitem" onClick={() => changeChat(chat, { is_archived: !chat.is_archived })}><ActionIcon name={chat.is_archived ? 'restore' : 'archive'} /><span>{chat.is_archived ? 'Restore from archive' : 'Archive'}</span></button>
            <div className="chat-history-menu-separator" />
            <button role="menuitem" className="danger" onClick={() => { setDeleteCandidate(chat); setMenuId(null) }}><ActionIcon name="delete" /><span>Delete</span></button>
          </>
        })()}
      </div>, document.body)}

      {unlockCandidate && <div className="history-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target && !unlockBusy) setUnlockCandidate(null) }}>
        <form className="history-dialog" role="dialog" aria-modal="true" aria-labelledby="unlock-chat-title" onSubmit={(event) => { event.preventDefault(); unlockChat() }}>
          <span className="eyebrow">SECURE CONVERSATION</span><h2 id="unlock-chat-title">Unlock this chat</h2><p>Verify your account password to access “{unlockCandidate.title}”.</p>
          <label htmlFor="unlock-chat-password">Account password</label><input id="unlock-chat-password" type="password" autoComplete="current-password" autoFocus value={unlockPassword} onChange={(event) => setUnlockPassword(event.target.value)} />
          {unlockError && <p className="history-dialog-error" role="alert">{unlockError}</p>}
          <div className="history-dialog-actions"><button type="button" className="button button-secondary" disabled={unlockBusy} onClick={() => setUnlockCandidate(null)}>Cancel</button><button type="submit" className="button button-primary" disabled={unlockBusy || !unlockPassword}>{unlockBusy ? 'Verifying…' : 'Unlock chat'}</button></div>
        </form>
      </div>}
      {shareDialog && <div className="history-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) setShareDialog(null) }}>
        <section className="history-dialog" role="dialog" aria-modal="true" aria-labelledby="share-chat-title">
          <span className="eyebrow">SHARE CONVERSATION</span><h2 id="share-chat-title">Share “{shareDialog.title}”</h2><p>Anyone with this link can view the conversation. Your documents remain private.</p>
          <label htmlFor="share-chat-link">Read-only link</label><input id="share-chat-link" readOnly value={shareDialog.url} onFocus={(event) => event.target.select()} />
          <div className="history-dialog-actions"><button type="button" className="button button-tertiary" onClick={async () => { try { await conversationsApi.update(token, shareDialog.id, { share: false }); setShareDialog(null); setHistoryError('Sharing link disabled.') } catch (error) { setHistoryError(error.message) } }}>Disable link</button><button type="button" className="button button-primary" onClick={async () => { try { await navigator.clipboard.writeText(shareDialog.url); setShareDialog(null); setHistoryError('Share link copied.') } catch { setHistoryError('Clipboard access is unavailable. Select and copy the link above.') } }}>Copy link</button></div>
        </section>
      </div>}
      <ConfirmDialog open={Boolean(deleteCandidate)} title="Delete conversation?" description={deleteCandidate ? `“${deleteCandidate.title}” and all its messages will be permanently deleted.` : ''} confirmLabel="Delete chat" onCancel={() => setDeleteCandidate(null)} onConfirm={() => removeChat(deleteCandidate)} />

      <div className="sidebar-bottom">
        <div className="user-card">
          <span className="avatar">{user?.name?.trim()?.[0]?.toUpperCase() || 'U'}</span>
          <span className="user-meta">
            <strong>{user?.name || 'Employee'}</strong>
            <small>{isAdmin ? 'Administrator' : user?.department || 'Employee'}</small>
          </span>
        </div>
      </div>
    </aside>
  )
}
