import { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

/*
  What can be attached, checked in the browser before anything is sent.

  The server checks again, against the file's own bytes, and is the authority.
  Checking here as well is about not making somebody wait for a 200 MB upload
  to finish only to be told it was never going to be accepted.
*/
const IMAGE = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'heif']
const VIDEO = ['mp4', 'mov', 'm4v', 'webm', 'mkv', 'avi']
const DOCS = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'zip',
  'txt', 'log', 'csv', 'json', 'xml', 'md']
const ACCEPT = [...IMAGE, ...VIDEO, ...DOCS].map((e) => '.' + e).join(',') +
  ',image/*,video/*'

const ext = (n) => (n.split('.').pop() || '').toLowerCase()
export const kindOf = (f) => IMAGE.includes(ext(f.name)) ? 'image'
  : VIDEO.includes(ext(f.name)) ? 'video'
  : DOCS.includes(ext(f.name)) ? 'document' : null

export const size = (b) => b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB`
  : b >= 1024 ? `${Math.round(b / 1024)} KB` : `${b} B`

let LIMITS = { max_file_mb: 25, max_video_mb: 250, max_files: 10 }
let limitsLoaded = null
function loadLimits() {
  if (!limitsLoaded) {
    limitsLoaded = api.authOptions().then((o) => { if (o?.uploads) LIMITS = o.uploads })
      .catch(() => {})
  }
  return limitsLoaded
}

function problemWith(f) {
  const k = kindOf(f)
  if (!k) return 'not a type that can be attached'
  const cap = (k === 'video' ? LIMITS.max_video_mb : LIMITS.max_file_mb) * 1048576
  if (f.size > cap) {
    return `${size(f.size)} — the limit for ${k === 'video' ? 'a video' : 'this kind of file'} is ${
      k === 'video' ? LIMITS.max_video_mb : LIMITS.max_file_mb} MB`
  }
  if (f.size === 0) return 'empty'
  return null
}

/** One file waiting to go up, with a preview where a preview helps. */
function Pending({ f, onRemove }) {
  const [url, setUrl] = useState(null)
  const k = kindOf(f)
  useEffect(() => {
    if (k !== 'image' && k !== 'video') return undefined
    const u = URL.createObjectURL(f)
    setUrl(u)
    return () => URL.revokeObjectURL(u)
  }, [f, k])
  return (
    <div className="upl-item">
      <div className="upl-thumb">
        {k === 'image' && url ? <img src={url} alt="" />
          : k === 'video' && url ? <video src={url} muted preload="metadata" />
          : <span className="upl-doc">{ext(f.name).toUpperCase() || 'FILE'}</span>}
        {k === 'video' && <span className="upl-badge">video</span>}
      </div>
      <div className="upl-name" title={f.name}>{f.name}</div>
      <div className="upl-size">{size(f.size)}</div>
      <button type="button" className="upl-x" onClick={onRemove}
              aria-label={`Remove ${f.name}`}>×</button>
    </div>
  )
}

/**
 * Drag files in, or choose them. Images and video show what they are before
 * they go; anything that would be refused is refused here, with the reason.
 */
export function FilePicker({ files, setFiles, label = 'Screenshots, videos or documents' }) {
  const ref = useRef(null)
  const [over, setOver] = useState(false)
  const [refused, setRefused] = useState([])
  const [, force] = useState(0)
  useEffect(() => { loadLimits().then(() => force((n) => n + 1)) }, [])

  function add(list) {
    const incoming = [...list]
    const bad = []
    const good = []
    for (const f of incoming) {
      const why = problemWith(f)
      if (why) bad.push(`${f.name}: ${why}`)
      else if (files.some((x) => x.name === f.name && x.size === f.size)) continue
      else good.push(f)
    }
    const room = LIMITS.max_files - files.length
    if (good.length > room) {
      bad.push(`Only ${LIMITS.max_files} files can go on at once; ${good.length - room} left out`)
      good.length = Math.max(0, room)
    }
    setRefused(bad)
    if (good.length) setFiles([...files, ...good])
    if (ref.current) ref.current.value = ''
  }

  const total = files.reduce((a, f) => a + f.size, 0)
  return (
    <div className="fld">
      <label>{label}</label>
      <div className={`upl-drop ${over ? 'over' : ''}`}
           onClick={() => ref.current?.click()}
           onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ref.current?.click() } }}
           onDragOver={(e) => { e.preventDefault(); setOver(true) }}
           onDragLeave={() => setOver(false)}
           onDrop={(e) => { e.preventDefault(); setOver(false); add(e.dataTransfer.files) }}
           role="button" tabIndex={0}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="1.8" aria-hidden="true"><path d="M12 16V4M6 10l6-6 6 6M4 20h16" /></svg>
        <div>
          <b>Drop files here, or choose them</b>
          <span>Images up to {LIMITS.max_file_mb} MB, video up to {LIMITS.max_video_mb} MB,
            PDF, Office, ZIP or text. {LIMITS.max_files} at a time.</span>
        </div>
        <input ref={ref} type="file" multiple accept={ACCEPT} hidden
               onChange={(e) => add(e.target.files)} />
      </div>
      {refused.length > 0 && (
        <div className="upl-refused">
          {refused.map((r, i) => <div key={i}>{r}</div>)}
        </div>
      )}
      {files.length > 0 && (
        <>
          <div className="upl-grid">
            {files.map((f, i) => (
              <Pending key={`${f.name}-${f.size}-${i}`} f={f}
                       onRemove={() => setFiles(files.filter((_, j) => j !== i))} />
            ))}
          </div>
          <div className="upl-total">{files.length} file{files.length === 1 ? '' : 's'},
            {' '}{size(total)} in all</div>
        </>
      )}
    </div>
  )
}

/** A thin bar while the files are on their way. */
export function UploadProgress({ progress }) {
  if (progress == null) return null
  const pct = Math.round(progress * 100)
  return (
    <div className="upl-progress" role="progressbar" aria-valuenow={pct}
         aria-valuemin={0} aria-valuemax={100}>
      <div className="upl-bar"><i style={{ width: `${pct}%` }} /></div>
      <span>{pct < 100 ? `Uploading — ${pct}%` : 'Uploaded, saving the ticket…'}</span>
    </div>
  )
}

/**
 * Attachments as they are: pictures as pictures, video as a player, and
 * documents as something to download. Every link is the signed one the API
 * issued for this ticket, so it works in an <img> or <video> tag.
 */
export function AttachmentGallery({ list }) {
  const [big, setBig] = useState(null)
  if (!list?.length) return null
  const images = list.filter((a) => a.kind === 'image')
  const videos = list.filter((a) => a.kind === 'video')
  const docs = list.filter((a) => a.kind !== 'image' && a.kind !== 'video')
  return (
    <div className="gal">
      {images.length > 0 && (
        <div className="gal-imgs">
          {images.map((a) => (
            <button key={a.id} type="button" className="gal-img" onClick={() => setBig(a)}
                    title={`${a.fileName} · ${size(a.sizeBytes)} · by ${a.uploadedBy}`}>
              <img src={a.url} alt={a.fileName} loading="lazy" />
            </button>
          ))}
        </div>
      )}
      {videos.map((a) => (
        <figure key={a.id} className="gal-vid">
          {/* preload=metadata: the frame and length, not the whole file */}
          <video src={a.url} controls preload="metadata" playsInline />
          <figcaption>{a.fileName} · {size(a.sizeBytes)} · by {a.uploadedBy}</figcaption>
        </figure>
      ))}
      {docs.length > 0 && (
        <div className="attlist">
          {docs.map((a) => (
            <a key={a.id} className="att" href={`${a.url}&download=1`}
               title={`${a.fileName} · ${size(a.sizeBytes)} · by ${a.uploadedBy}`}>
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor"
                   strokeWidth="2"><path d="M21 12l-8.5 8.5a5 5 0 01-7-7L14 5a3.5 3.5 0 015 5l-8.5 8.5a2 2 0 01-3-3L15 8" /></svg>
              {a.fileName} <span className="muted">({size(a.sizeBytes)})</span>
            </a>
          ))}
        </div>
      )}
      {big && (
        <div className="gal-over" onClick={() => setBig(null)} role="dialog"
             aria-label={big.fileName}>
          <img src={big.url} alt={big.fileName} />
          <div className="gal-cap">{big.fileName} — click anywhere to close</div>
        </div>
      )}
    </div>
  )
}
