import { useState } from 'react'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { SourceForm } from '../components/SourceForm'
import { api } from '../lib/api'
import { formatDate } from '../lib/format'
import type { Source } from '../types'

export function SourcesPage({ sources, onRefresh, onScan }: { sources: Source[]; onRefresh: () => Promise<void>; onScan: (source: Source) => Promise<void> }) {
  const [editing, setEditing] = useState<Source | 'new' | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  async function remove(source: Source) {
    if (!window.confirm(`Remove “${source.name}” and its cached inventory? Media files will not be changed.`)) return
    setBusy(source.id)
    try { await api.deleteSource(source.id); await onRefresh() } finally { setBusy(null) }
  }

  async function scan(source: Source) {
    setBusy(source.id)
    setMessage('')
    try { await onScan(source); setMessage(`Scan started for ${source.name}.`) } catch (error) { setMessage(error instanceof Error ? error.message : 'Could not start scan') } finally { setBusy(null) }
  }

  return <>
    <section className="page-heading split-heading"><div><span className="eyebrow">Portable configuration</span><h1>Media sources</h1><p>Credentials and server-specific paths stay outside the application code.</p></div><button className="button primary" onClick={() => setEditing('new')}>Add source</button></section>
    <div className="notice-card"><Icon name="info"/><div><strong>Read-only by design</strong><p>ReelIndex only reads library metadata and media files. Docker filesystem mounts should use the <code>:ro</code> flag.</p></div></div>
    {message && <div className="connection-status success"><Icon name="check"/><span>{message}</span></div>}
    {!sources.length ? <EmptyState title="No media sources configured" message="Connect a server or mounted folder, test the connection, and launch the first inventory scan." action={<button className="button primary" onClick={() => setEditing('new')}>Add media source</button>} /> : <div className="source-grid">{sources.map(source => <article className="source-card" key={source.id}>
      <div className="source-card-top"><div className="source-icon"><Icon name={source.type === 'filesystem' ? 'folder' : 'server'}/></div><div><span className="eyebrow">{source.type}</span><h2>{source.name}</h2><p className="source-location">{source.url_or_path}</p></div><span className={`status-pill ${source.last_scan_status || 'never'}`}>{source.last_scan_status || 'Not scanned'}</span></div>
      <div className="source-metrics"><div><strong>{source.movie_count}</strong><span>Movies</span></div><div><strong>{formatDate(source.last_scan_at)}</strong><span>Last scan</span></div><div><strong>{source.schedule_enabled ? `Every ${source.schedule_minutes / 60}h` : 'Manual'}</strong><span>Updates</span></div></div>
      <div className="source-card-actions"><button className="button secondary" disabled={busy === source.id} onClick={() => scan(source)}><Icon name="refresh" size={17}/>{busy === source.id ? 'Starting…' : 'Scan now'}</button><button className="button ghost" onClick={() => setEditing(source)}>Edit</button><button className="icon-button danger" disabled={busy === source.id} onClick={() => remove(source)} aria-label={`Remove ${source.name}`}><Icon name="trash" size={18}/></button></div>
    </article>)}</div>}
    {editing && <SourceForm source={editing === 'new' ? null : editing} onCancel={() => setEditing(null)} onSaved={async () => { setEditing(null); await onRefresh() }}/>} 
  </>
}
