import { useEffect, useRef } from 'react'

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  busy = false,
  onConfirm,
  onCancel,
}) {
  const cancelRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    cancelRef.current?.focus()
    function closeOnEscape(event) {
      if (event.key === 'Escape' && !busy) onCancel()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [busy, onCancel, open])

  if (!open) return null
  return <div className="confirm-backdrop" role="presentation"
    onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onCancel()
    }}>
    <section className="confirm-dialog panel" role="alertdialog" aria-modal="true"
      aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-description">
      <span className="eyebrow">PLEASE CONFIRM</span>
      <h2 id="confirm-dialog-title">{title}</h2>
      <p id="confirm-dialog-description">{description}</p>
      <div className="confirm-actions">
        <button ref={cancelRef} type="button" className="button button-secondary"
          onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className="button button-danger"
          onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </button>
      </div>
    </section>
  </div>
}
