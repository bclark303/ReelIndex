import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { formatBitrate, formatBytes, formatRuntime } from '../lib/format'
import type { MovieDetail } from '../types'
import { Icon } from './Icon'
import { Loading } from './Loading'
import { Poster } from './Poster'

function DetailItem({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="detail-item"><span>{label}</span><strong>{value || '—'}</strong></div>
}

export function MovieDetailDrawer({ movieId, onClose }: { movieId: string | null; onClose: () => void }) {
  const [movie, setMovie] = useState<MovieDetail | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!movieId) return
    setMovie(null)
    setError('')
    api.getMovie(movieId).then(setMovie).catch(err => setError(err.message))
  }, [movieId])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  if (!movieId) return null
  return (
    <div className="drawer-backdrop" onMouseDown={onClose} role="presentation">
      <aside className="detail-drawer" role="dialog" aria-modal="true" aria-label="Movie details" onMouseDown={event => event.stopPropagation()}>
        <button className="icon-button drawer-close" onClick={onClose} aria-label="Close details"><Icon name="x"/></button>
        {!movie && !error && <Loading label="Loading movie details" />}
        {error && <div className="error-panel"><Icon name="warning"/><p>{error}</p></div>}
        {movie && <>
          <div className="detail-hero">
            <Poster src={movie.poster_url} title={movie.title} className="detail-poster" />
            <div className="detail-heading">
              <span className="eyebrow">{movie.source_name}</span>
              <h1>{movie.title}</h1>
              <div className="detail-heading-meta"><span>{movie.year || 'Unknown year'}</span><span>·</span><span>{formatRuntime(movie.runtime_seconds)}</span><span>·</span><span>{movie.file_count} {movie.file_count === 1 ? 'file' : 'files'}</span></div>
              <div className="badge-list">{movie.resolutions.map(value => <span className="badge badge-solid" key={value}>{value}</span>)}{movie.video_codecs.map(value => <span className="badge" key={value}>{value.toUpperCase()}</span>)}</div>
            </div>
          </div>
          {movie.overview && <p className="overview">{movie.overview}</p>}
          <div className="detail-summary-grid">
            <DetailItem label="Total size" value={formatBytes(movie.total_size_bytes)} />
            <DetailItem label="Container" value={movie.containers.join(', ').toUpperCase()} />
            <DetailItem label="Source type" value={movie.source_type.toUpperCase()} />
            <DetailItem label="Last indexed" value={new Date(movie.updated_at).toLocaleString()} />
          </div>
          <section className="detail-section">
            <div className="section-heading"><div><span className="eyebrow">Technical inventory</span><h2>Media files</h2></div></div>
            <div className="file-stack">
              {movie.files.map((file, index) => <article className="file-card" key={file.id}>
                <div className="file-card-header"><div><span className="file-index">File {index + 1}</span><h3>{file.edition || file.filename}</h3>{file.edition && <p>{file.filename}</p>}</div><div className="badge-list">{file.resolution_label && <span className="badge badge-solid">{file.resolution_label}</span>}{file.container && <span className="badge">{file.container.toUpperCase()}</span>}</div></div>
                {file.probe_error && <div className="inline-warning"><Icon name="warning" size={17}/><span>{file.probe_error}</span></div>}
                <div className="technical-grid">
                  <DetailItem label="File size" value={formatBytes(file.size_bytes)} />
                  <DetailItem label="Runtime" value={formatRuntime(file.duration_seconds)} />
                  <DetailItem label="Video" value={file.video_codec?.toUpperCase()} />
                  <DetailItem label="Dimensions" value={file.width && file.height ? `${file.width} × ${file.height}` : '—'} />
                  <DetailItem label="Video bitrate" value={formatBitrate(file.video_bitrate)} />
                  <DetailItem label="Audio" value={file.audio_codec?.toUpperCase()} />
                  <DetailItem label="Channels" value={file.audio_channels ? `${file.audio_channels} ch` : '—'} />
                  <DetailItem label="Language" value={file.audio_languages} />
                </div>
                <div className="path-box"><Icon name="folder" size={16}/><code>{file.path}</code></div>
              </article>)}
            </div>
          </section>
        </>}
      </aside>
    </div>
  )
}
