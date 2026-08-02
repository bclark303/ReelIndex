import type { MovieListItem } from '../types'
import { formatBytes, formatRuntime } from '../lib/format'
import { Poster } from './Poster'

export function MovieTable({ movies, onOpen }: { movies: MovieListItem[]; onOpen: (movie: MovieListItem) => void }) {
  return (
    <div className="table-shell">
      <table className="movie-table">
        <thead><tr><th>Movie</th><th>Source</th><th>Versions</th><th>Resolution</th><th>Codec</th><th>Size</th><th>Runtime</th></tr></thead>
        <tbody>
          {movies.map(movie => (
            <tr key={movie.id} onClick={() => onOpen(movie)} tabIndex={0} onKeyDown={event => { if (event.key === 'Enter') onOpen(movie) }}>
              <td><div className="table-title"><Poster src={movie.poster_url} title={movie.title} className="table-poster"/><div><strong>{movie.title}</strong><span>{movie.year || 'Unknown year'}</span></div></div></td>
              <td>{movie.source_name}</td>
              <td>{movie.file_count}</td>
              <td><div className="badge-list">{movie.resolutions.map(item => <span className="badge" key={item}>{item}</span>)}</div></td>
              <td>{movie.video_codecs.join(', ').toUpperCase() || '—'}</td>
              <td>{formatBytes(movie.total_size_bytes)}</td>
              <td>{formatRuntime(movie.runtime_seconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
