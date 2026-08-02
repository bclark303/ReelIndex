export function formatBytes(bytes?: number | null): string {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const power = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / Math.pow(1024, power)
  return `${value.toFixed(value >= 10 || power === 0 ? 0 : 1)} ${units[power]}`
}

export function formatRuntime(seconds?: number | null): string {
  if (!seconds) return '—'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`
}

export function formatBitrate(value?: number | null): string {
  if (!value) return '—'
  return `${(value / 1_000_000).toFixed(1)} Mbps`
}

export function formatDate(value?: string | null): string {
  if (!value) return 'Never'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}
