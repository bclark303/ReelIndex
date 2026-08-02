import type { MovieListItem } from '../types'
import { formatBytes, formatRuntime } from '../lib/format'
import { Poster } from './Poster'

export function MovieCard({ movie, onOpen }: { movie: MovieListItem; onOpen: () => void }) {
  return (
    <button className="movie-card" onClick={onOpen} aria-label={`Open details for ${movie.title}`}>
      <div className="movie-poster-wrap">
        <Poster src={movie.poster_url} title={movie.title} className="movie-poster" />
        <div className="poster-badges">
          {movie.resolutions.slice(0, 2).map(item => <span className="badge badge-solid" key={item}>{item}</span>)}
        </div>
        {movie.file_count > 1 && <span className="version-count">{movie.file_count} versions</span>}
      </div>
      <div className="movie-card-body">
        <h3 title={movie.title}>{movie.title}</h3>
        <div className="movie-subtitle"><span>{movie.year || 'Year unknown'}</span><span>·</span><span>{formatRuntime(movie.runtime_seconds)}</span></div>
        <div className="movie-meta-row"><span>{movie.video_codecs[0]?.toUpperCase() || 'Unknown codec'}</span><span>{formatBytes(movie.total_size_bytes)}</span></div>
      </div>
    </button>
  )
}
