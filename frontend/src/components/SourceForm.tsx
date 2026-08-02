import { useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { Source, SourceConfig, SourceType } from '../types'
import { Icon } from './Icon'

interface FormState {
  name: string
  type: SourceType
  url_or_path: string
  library_id: string
  token: string
  user_id: string
  verify_ssl: boolean
  tmdb_token: string
  schedule_enabled: boolean
  schedule_minutes: number
  remote_path: string
  local_path: string
}

const initial: FormState = {
  name: '', type: 'filesystem', url_or_path: '/media', library_id: '', token: '', user_id: '', verify_ssl: true, tmdb_token: '', schedule_enabled: false, schedule_minutes: 360, remote_path: '', local_path: '',
}

export function SourceForm({ source, onSaved, onCancel }: { source?: Source | null; onSaved: (source: Source) => void; onCancel: () => void }) {
  const seed = useMemo<FormState>(() => source ? {
    name: source.name,
    type: source.type,
    url_or_path: source.url_or_path,
    library_id: source.library_id || '',
    token: source.config.token || '',
    user_id: source.config.user_id || '',
    verify_ssl: source.config.verify_ssl !== false,
    tmdb_token: source.config.tmdb_token || '',
    schedule_enabled: source.schedule_enabled,
    schedule_minutes: source.schedule_minutes,
    remote_path: source.config.path_mappings?.[0]?.remote || '',
    local_path: source.config.path_mappings?.[0]?.local || '',
  } : initial, [source])
  const [form, setForm] = useState<FormState>(seed)
  const [libraries, setLibraries] = useState<Array<{ id: string; name: string }>>([])
  const [status, setStatus] = useState<{ type: 'idle' | 'loading' | 'success' | 'error'; message: string }>({ type: 'idle', message: '' })
  const [saving, setSaving] = useState(false)

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm(current => ({ ...current, [key]: value }))
  const config = (): SourceConfig => ({
    ...(form.type !== 'filesystem' && form.token ? { token: form.token } : {}),
    ...(form.user_id ? { user_id: form.user_id } : {}),
    verify_ssl: form.verify_ssl,
    ...(form.tmdb_token ? { tmdb_token: form.tmdb_token } : {}),
    ...(form.remote_path && form.local_path ? { path_mappings: [{ remote: form.remote_path, local: form.local_path }] } : {}),
  })

  async function test() {
    setStatus({ type: 'loading', message: 'Testing connection…' })
    try {
      const result = await api.testConnection({ type: form.type, url_or_path: form.url_or_path, library_id: form.library_id || null, config: config() })
      setLibraries(result.libraries)
      setStatus({ type: result.ok ? 'success' : 'error', message: result.message })
    } catch (error) {
      setStatus({ type: 'error', message: error instanceof Error ? error.message : 'Connection test failed' })
    }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    try {
      const payload = {
        name: form.name,
        type: form.type,
        url_or_path: form.url_or_path,
        library_id: form.library_id || null,
        config: config(),
        schedule_enabled: form.schedule_enabled,
        schedule_minutes: form.schedule_minutes,
        enabled: true,
      }
      const saved = source ? await api.updateSource(source.id, payload as Partial<Source>) : await api.createSource(payload)
      onSaved(saved)
    } catch (error) {
      setStatus({ type: 'error', message: error instanceof Error ? error.message : 'Could not save source' })
    } finally {
      setSaving(false)
    }
  }

  return <div className="modal-backdrop" onMouseDown={onCancel}>
    <form className="source-modal" onSubmit={save} onMouseDown={event => event.stopPropagation()}>
      <div className="modal-header"><div><span className="eyebrow">Connection setup</span><h2>{source ? 'Edit media source' : 'Add media source'}</h2></div><button type="button" className="icon-button" onClick={onCancel} aria-label="Close"><Icon name="x"/></button></div>
      <div className="form-grid two">
        <label><span>Display name</span><input value={form.name} onChange={event => set('name', event.target.value)} placeholder="Living Room Plex" required /></label>
        <label><span>Source type</span><select value={form.type} onChange={event => { const type = event.target.value as SourceType; set('type', type); set('url_or_path', type === 'filesystem' ? '/media' : 'http://'); }}><option value="filesystem">Filesystem</option><option value="plex">Plex</option><option value="jellyfin">Jellyfin</option><option value="emby">Emby</option></select></label>
      </div>
      <label><span>{form.type === 'filesystem' ? 'Container media path' : 'Server URL'}</span><input value={form.url_or_path} onChange={event => set('url_or_path', event.target.value)} placeholder={form.type === 'filesystem' ? '/media' : 'http://192.168.1.50:32400'} required /><small>{form.type === 'filesystem' ? 'This must match a read-only path mounted in docker-compose.yml.' : 'Use the base address of the media server.'}</small></label>
      {form.type !== 'filesystem' && <div className="form-grid two"><label><span>Read-only API token</span><input type="password" value={form.token} onChange={event => set('token', event.target.value)} placeholder={source ? 'Leave masked value unchanged' : 'API token'} /></label>{form.type !== 'plex' && <label><span>User ID (optional)</span><input value={form.user_id} onChange={event => set('user_id', event.target.value)} placeholder="Server user ID" /></label>}</div>}
      {libraries.length > 0 && <label><span>Movie library</span><select value={form.library_id} onChange={event => set('library_id', event.target.value)} required><option value="">Select a library</option>{libraries.map(library => <option value={library.id} key={library.id}>{library.name}</option>)}</select></label>}
      {form.type !== 'filesystem' && <details className="advanced"><summary>Path mapping and network options</summary><div className="form-grid two"><label><span>Server path prefix</span><input value={form.remote_path} onChange={event => set('remote_path', event.target.value)} placeholder="D:\Movies or /mnt/movies" /></label><label><span>Mounted container prefix</span><input value={form.local_path} onChange={event => set('local_path', event.target.value)} placeholder="/media" /></label></div><label className="check-row"><input type="checkbox" checked={form.verify_ssl} onChange={event => set('verify_ssl', event.target.checked)} /><span>Verify TLS certificates</span></label></details>}
      <details className="advanced"><summary>Metadata and schedule</summary><label><span>TMDB API read token (optional)</span><input type="password" value={form.tmdb_token} onChange={event => set('tmdb_token', event.target.value)} placeholder="Used only for missing posters and descriptions" /></label><div className="schedule-row"><label className="check-row"><input type="checkbox" checked={form.schedule_enabled} onChange={event => set('schedule_enabled', event.target.checked)} /><span>Enable automatic rescans</span></label><label><span>Every</span><select value={form.schedule_minutes} onChange={event => set('schedule_minutes', Number(event.target.value))}><option value={60}>1 hour</option><option value={360}>6 hours</option><option value={720}>12 hours</option><option value={1440}>24 hours</option><option value={10080}>Weekly</option></select></label></div></details>
      {status.type !== 'idle' && <div className={`connection-status ${status.type}`}><Icon name={status.type === 'success' ? 'check' : status.type === 'loading' ? 'refresh' : 'warning'} className={status.type === 'loading' ? 'spin' : ''}/><span>{status.message}</span></div>}
      <div className="modal-actions"><button type="button" className="button secondary" onClick={test}>Test connection</button><div className="action-spacer"/><button type="button" className="button ghost" onClick={onCancel}>Cancel</button><button type="submit" className="button primary" disabled={saving || !form.name || !form.url_or_path}>{saving ? 'Saving…' : source ? 'Save changes' : 'Add source'}</button></div>
    </form>
  </div>
}
