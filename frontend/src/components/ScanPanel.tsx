import type { ScanRun } from '../types'
import { Icon } from './Icon'

export function ScanPanel({ scans }: { scans: ScanRun[] }) {
  const active = scans.filter(scan => scan.status === 'queued' || scan.status === 'running')
  if (!active.length) return null
  return <div className="scan-panel" role="status" aria-live="polite">
    {active.map(scan => {
      const complete = scan.analyzed_count + scan.cached_count + scan.error_count
      const progress = scan.discovered_count ? Math.min(100, Math.round((complete / scan.discovered_count) * 100)) : 3
      return <div className="scan-row" key={scan.id}>
        <div className="scan-icon"><Icon name="refresh" className="spin"/></div>
        <div className="scan-content"><div className="scan-copy"><strong>Scanning {scan.source_name || 'library'}</strong><span>{scan.current_item || 'Discovering files…'}</span></div><div className="progress-track"><span style={{ width: `${progress}%` }}/></div><div className="scan-counts"><span>{scan.discovered_count} found</span><span>{scan.analyzed_count} analyzed</span><span>{scan.cached_count} cached</span>{scan.error_count > 0 && <span>{scan.error_count} errors</span>}</div></div>
      </div>
    })}
  </div>
}
