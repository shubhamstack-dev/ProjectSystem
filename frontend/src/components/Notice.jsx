// Shows an API refusal (409) with the rows that block it, or any other error.
export default function Notice({ error, onClose }) {
  if (!error) return null
  return (
    <div className="notice err" role="alert">
      <div style={{ display: 'flex', gap: 8 }}>
        <span style={{ flex: 1 }}>{error.message}</span>
        {onClose && <button className="link" onClick={onClose}>dismiss</button>}
      </div>
      {error.blockers?.length > 0 && <ul>{error.blockers.map((b, i) => <li key={i}>{b}</li>)}</ul>}
    </div>
  )
}
