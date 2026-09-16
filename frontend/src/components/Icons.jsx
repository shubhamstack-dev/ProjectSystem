// Small inline icons for row actions. No icon library needed.
export const IcoOpen = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 6h16M4 12h10M4 18h7"/><path d="M17 15l3 3-3 3"/></svg>
export const IcoEdit = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 20h4l10-10-4-4L4 16v4z"/><path d="M12.5 7.5l4 4"/></svg>
export const IcoTrash = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M4 7h16M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/></svg>

export function RowActions({ onOpen, onEdit, onDelete }) {
  return (
    <span className="actions">
      {onOpen && <button className="ib" title="Open plan" aria-label="Open plan" onClick={onOpen}><IcoOpen /></button>}
      {onEdit && <button className="ib" title="Edit" aria-label="Edit" onClick={onEdit}><IcoEdit /></button>}
      {onDelete && <button className="ib danger" title="Delete" aria-label="Delete" onClick={onDelete}><IcoTrash /></button>}
    </span>
  )
}
