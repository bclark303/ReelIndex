import { useEffect, useState } from 'react'
import { Icon } from '../components/Icon'
import { Loading } from '../components/Loading'
import { api } from '../lib/api'
import { formatBytes } from '../lib/format'
import type { Diagnostics } from '../types'

function ValueGrid({ data }: { data: Record<string, unknown> }) {
  return <div className="diagnostic-grid">{Object.entries(data).map(([key, value]) => <div className="diagnostic-value" key={key}><span>{key.replaceAll('_', ' ')}</span><strong>{typeof value === 'number' && key.includes('disk') ? formatBytes(value) : String(value ?? '—')}</strong></div>)}</div>
}

export function DiagnosticsPage() {
  const [data, setData] = useState<Diagnostics | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api.getDiagnostics().then(setData).catch(err => setError(err.message)) }, [])
  return <>
    <section className="page-heading split-heading"><div><span className="eyebrow">Troubleshooting and disclosure</span><h1>Diagnostics</h1><p>Review system capability, source configuration, and recent inventory runs.</p></div><a className="button secondary" href="/api/diagnostics/export" download><Icon name="download" size={17}/>Export JSON</a></section>
    {!data && !error && <Loading label="Collecting diagnostics" />}
    {error && <div className="error-panel"><Icon name="warning"/><p>{error}</p></div>}
    {data && <div className="diagnostics-stack"><section className="diagnostic-card"><div className="section-heading"><div><span className="eyebrow">Runtime</span><h2>System</h2></div><Icon name="activity"/></div><ValueGrid data={data.system}/></section><section className="diagnostic-card"><div className="section-heading"><div><span className="eyebrow">Persistent cache</span><h2>Database</h2></div><Icon name="database"/></div><ValueGrid data={data.database}/></section><section className="diagnostic-card"><div className="section-heading"><div><span className="eyebrow">Recent activity</span><h2>Scan history</h2></div><Icon name="clock"/></div><div className="scan-history">{data.recent_scans.length ? data.recent_scans.map((scan, index) => <div className="history-row" key={String(scan.id || index)}><span className={`status-dot ${String(scan.status)}`}/><div><strong>{String(scan.status)}</strong><span>{String(scan.started_at)}</span></div><div className="history-counts"><span>{String(scan.discovered)} found</span><span>{String(scan.cached)} cached</span><span>{String(scan.errors)} errors</span></div></div>) : <p>No scans have run yet.</p>}</div></section></div>}
  </>
}
