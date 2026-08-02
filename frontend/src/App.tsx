import { useCallback, useEffect, useState } from 'react'
import { Icon } from './components/Icon'
import { ScanPanel } from './components/ScanPanel'
import { api } from './lib/api'
import { DiagnosticsPage } from './pages/DiagnosticsPage'
import { LibraryPage } from './pages/LibraryPage'
import { SourcesPage } from './pages/SourcesPage'
import type { ScanRun, Source } from './types'

type Page = 'library' | 'sources' | 'diagnostics'

export default function App() {
  const [page, setPage] = useState<Page>(() => (window.location.hash.slice(1) as Page) || 'library')
  const [sources, setSources] = useState<Source[]>([])
  const [scans, setScans] = useState<ScanRun[]>([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [sourceError, setSourceError] = useState('')

  const refreshSources = useCallback(async () => {
    try { setSources(await api.listSources()); setSourceError('') } catch (error) { setSourceError(error instanceof Error ? error.message : 'Could not load sources') }
  }, [])

  const refreshScans = useCallback(async () => {
    try {
      const next = await api.listScans()
      setScans(next)
      const recentlyFinished = next.some(scan => scan.completed_at && Date.now() - new Date(scan.completed_at).getTime() < 5000)
      if (recentlyFinished) { setRefreshKey(key => key + 1); void refreshSources() }
    } catch { /* a transient polling failure should not replace the main UI */ }
  }, [refreshSources])

  useEffect(() => { void refreshSources(); void refreshScans() }, [refreshSources, refreshScans])
  useEffect(() => {
    const hasActive = scans.some(scan => scan.status === 'queued' || scan.status === 'running')
    const interval = window.setInterval(() => void refreshScans(), hasActive ? 1500 : 12000)
    return () => window.clearInterval(interval)
  }, [scans, refreshScans])

  useEffect(() => {
    const onHash = () => setPage((window.location.hash.slice(1) as Page) || 'library')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const navigate = (next: Page) => { window.location.hash = next; setPage(next) }
  const startScan = async (source: Source) => { await api.startScan(source.id); await refreshScans() }

  return <div className="app-shell">
    <header className="topbar">
      <button className="brand" onClick={() => navigate('library')} aria-label="ReelIndex home"><span className="brand-mark"><Icon name="film"/></span><span><strong>ReelIndex</strong><small>Movie inventory</small></span></button>
      <nav aria-label="Primary navigation"><button className={page === 'library' ? 'active' : ''} onClick={() => navigate('library')}><Icon name="grid" size={18}/>Library</button><button className={page === 'sources' ? 'active' : ''} onClick={() => navigate('sources')}><Icon name="server" size={18}/>Sources</button><button className={page === 'diagnostics' ? 'active' : ''} onClick={() => navigate('diagnostics')}><Icon name="activity" size={18}/>Diagnostics</button></nav>
      <div className="topbar-status"><span className="read-only-dot"/><span>Read only</span></div>
    </header>
    <ScanPanel scans={scans}/>
    {sourceError && <div className="global-error"><Icon name="warning" size={17}/><span>{sourceError}</span></div>}
    <main>
      {page === 'library' && <LibraryPage sources={sources} refreshKey={refreshKey} onGoSources={() => navigate('sources')}/>} 
      {page === 'sources' && <SourcesPage sources={sources} onRefresh={refreshSources} onScan={startScan}/>} 
      {page === 'diagnostics' && <DiagnosticsPage/>}
    </main>
    <footer><span>ReelIndex 1.0</span><span>AI-assisted, read-only inventory</span></footer>
  </div>
}
