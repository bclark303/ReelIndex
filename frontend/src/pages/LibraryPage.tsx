import { useEffect, useMemo, useState } from 'react'
import { EmptyState } from '../components/EmptyState'
import { Icon } from '../components/Icon'
import { Loading } from '../components/Loading'
import { MovieCard } from '../components/MovieCard'
import { MovieDetailDrawer } from '../components/MovieDetailDrawer'
import { MovieTable } from '../components/MovieTable'
import { api, type MovieQuery } from '../lib/api'
import { formatBytes } from '../lib/format'
import type { MovieListItem, PaginatedMovies, Source, Stats } from '../types'

export function LibraryPage({ sources, refreshKey, onGoSources }: { sources: Source[]; refreshKey: number; onGoSources: () => void }) {
  const [data, setData] = useState<PaginatedMovies | null>(null)
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [view, setView] = useState<'grid' | 'list'>(() => (localStorage.getItem('reelindex-view') as 'grid' | 'list') || 'grid')
  const [selected, setSelected] = useState<string | null>(null)
  const [query, setQuery] = useState<MovieQuery>({ sort: 'title', direction: 'asc', page_size: 100 })
  const [searchDraft, setSearchDraft] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(current => ({ ...current, search: searchDraft, page: 1 })), 220)
    return () => window.clearTimeout(timer)
  }, [searchDraft])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    Promise.all([api.listMovies(query), api.getStats()]).then(([movies, nextStats]) => {
      if (!cancelled) { setData(movies); setStats(nextStats); setLoading(false) }
    }).catch(err => { if (!cancelled) { setError(err.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [query, refreshKey])

  const activeFilters = useMemo(() => ['source_id', 'resolution', 'codec', 'container', 'missing_poster', 'multiple_versions', 'probe_errors'].filter(key => Boolean(query[key as keyof MovieQuery])).length, [query])
  const setFilter = (key: keyof MovieQuery, value: string | boolean | undefined) => setQuery(current => ({ ...current, [key]: value || undefined, page: 1 }))
  const changeView = (next: 'grid' | 'list') => { setView(next); localStorage.setItem('reelindex-view', next) }
  const clearFilters = () => setQuery({ sort: query.sort, direction: query.direction, page_size: 100, search: query.search })

  return <>
    <section className="page-heading library-heading">
      <div><span className="eyebrow">Read-only media inventory</span><h1>Your movie library</h1><p>Search, inspect, and compare every indexed media file.</p></div>
      {stats && <div className="stats-strip" aria-label="Library statistics"><div><strong>{stats.movies.toLocaleString()}</strong><span>Movies</span></div><div><strong>{stats.files.toLocaleString()}</strong><span>Files</span></div><div><strong>{formatBytes(stats.total_size_bytes)}</strong><span>Storage</span></div><div><strong>{stats.resolutions['4K'] || 0}</strong><span>4K files</span></div></div>}
    </section>

    <section className="toolbar-card">
      <div className="search-box"><Icon name="search"/><input value={searchDraft} onChange={event => setSearchDraft(event.target.value)} placeholder="Search by movie title…" aria-label="Search movies by title"/>{searchDraft && <button className="clear-search" onClick={() => setSearchDraft('')} aria-label="Clear search"><Icon name="x" size={16}/></button>}</div>
      <div className="toolbar-actions"><select aria-label="Sort movies" value={`${query.sort}:${query.direction}`} onChange={event => { const [sort, direction] = event.target.value.split(':'); setQuery(current => ({ ...current, sort, direction })) }}><option value="title:asc">Title A–Z</option><option value="title:desc">Title Z–A</option><option value="year:desc">Newest first</option><option value="year:asc">Oldest first</option><option value="size:desc">Largest first</option><option value="updated:desc">Recently indexed</option></select><div className="segmented" aria-label="View mode"><button className={view === 'grid' ? 'active' : ''} onClick={() => changeView('grid')} aria-label="Poster grid"><Icon name="grid"/></button><button className={view === 'list' ? 'active' : ''} onClick={() => changeView('list')} aria-label="List view"><Icon name="list"/></button></div></div>
    </section>

    <section className="filter-bar">
      <select value={query.source_id || ''} onChange={event => setFilter('source_id', event.target.value)} aria-label="Filter by source"><option value="">All sources</option>{sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}</select>
      <select value={query.resolution || ''} onChange={event => setFilter('resolution', event.target.value)} aria-label="Filter by resolution"><option value="">All resolutions</option>{data?.facets.resolutions.map(value => <option key={value}>{value}</option>)}</select>
      <select value={query.codec || ''} onChange={event => setFilter('codec', event.target.value)} aria-label="Filter by codec"><option value="">All codecs</option>{data?.facets.codecs.map(value => <option key={value}>{value}</option>)}</select>
      <select value={query.container || ''} onChange={event => setFilter('container', event.target.value)} aria-label="Filter by container"><option value="">All containers</option>{data?.facets.containers.map(value => <option key={value}>{value}</option>)}</select>
      <label className={`filter-toggle ${query.multiple_versions ? 'active' : ''}`}><input type="checkbox" checked={Boolean(query.multiple_versions)} onChange={event => setFilter('multiple_versions', event.target.checked)} />Multiple versions</label>
      <label className={`filter-toggle ${query.missing_poster ? 'active' : ''}`}><input type="checkbox" checked={Boolean(query.missing_poster)} onChange={event => setFilter('missing_poster', event.target.checked)} />Missing posters</label>
      <label className={`filter-toggle ${query.probe_errors ? 'active' : ''}`}><input type="checkbox" checked={Boolean(query.probe_errors)} onChange={event => setFilter('probe_errors', event.target.checked)} />Probe errors</label>
      {activeFilters > 0 && <button className="text-button" onClick={clearFilters}>Clear {activeFilters} filter{activeFilters === 1 ? '' : 's'}</button>}
    </section>

    <div className="result-summary"><span>{data ? `${data.total.toLocaleString()} ${data.total === 1 ? 'movie' : 'movies'}` : 'Loading collection'}</span>{stats && stats.probe_errors > 0 && <span className="warning-copy"><Icon name="warning" size={15}/>{stats.probe_errors} file analysis warning{stats.probe_errors === 1 ? '' : 's'}</span>}</div>

    {loading && <Loading label="Loading movie inventory" />}
    {error && <div className="error-panel"><Icon name="warning"/><div><strong>Could not load the library</strong><p>{error}</p></div></div>}
    {!loading && !error && data?.items.length === 0 && <EmptyState title={sources.length ? 'No matching movies' : 'Connect your first library'} message={sources.length ? 'Try clearing filters or start a new scan.' : 'Add a filesystem, Plex, Jellyfin, or Emby source to create the inventory.'} action={!sources.length ? <button className="button primary" onClick={onGoSources}>Add media source</button> : undefined}/>} 
    {!loading && data && data.items.length > 0 && (view === 'grid' ? <div className="movie-grid">{data.items.map(movie => <MovieCard key={movie.id} movie={movie} onOpen={() => setSelected(movie.id)}/>)}</div> : <MovieTable movies={data.items} onOpen={(movie: MovieListItem) => setSelected(movie.id)}/>)}
    {data && data.total > data.page_size && <nav className="pagination" aria-label="Movie pages"><button className="button secondary" disabled={data.page <= 1} onClick={() => setQuery(current => ({ ...current, page: Math.max(1, (current.page || 1) - 1) }))}>Previous</button><span>Page {data.page} of {Math.ceil(data.total / data.page_size)}</span><button className="button secondary" disabled={data.page * data.page_size >= data.total} onClick={() => setQuery(current => ({ ...current, page: (current.page || 1) + 1 }))}>Next</button></nav>}
    <MovieDetailDrawer movieId={selected} onClose={() => setSelected(null)} />
  </>
}
