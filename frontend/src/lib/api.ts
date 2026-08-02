import type { Diagnostics, MovieDetail, PaginatedMovies, ScanRun, Source, SourceConfig, SourceType, Stats } from '../types'

const API = '/api'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }))
    throw new ApiError(payload.detail || 'Request failed', response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export interface MovieQuery {
  search?: string
  source_id?: string
  resolution?: string
  codec?: string
  container?: string
  missing_poster?: boolean
  multiple_versions?: boolean
  probe_errors?: boolean
  sort?: string
  direction?: string
  page?: number
  page_size?: number
}

export const api = {
  listMovies: (query: MovieQuery = {}) => {
    const params = new URLSearchParams()
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== '' && value !== false) params.set(key, String(value))
    })
    return request<PaginatedMovies>(`/movies?${params}`)
  },
  getMovie: (id: string) => request<MovieDetail>(`/movies/${id}`),
  getStats: () => request<Stats>('/stats'),
  listSources: () => request<Source[]>('/sources'),
  createSource: (payload: {
    name: string
    type: SourceType
    url_or_path: string
    library_id?: string | null
    config: SourceConfig
    schedule_enabled: boolean
    schedule_minutes: number
    enabled: boolean
  }) => request<Source>('/sources', { method: 'POST', body: JSON.stringify(payload) }),
  updateSource: (id: string, payload: Partial<Source>) => request<Source>(`/sources/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  deleteSource: (id: string) => request<void>(`/sources/${id}`, { method: 'DELETE' }),
  testConnection: (payload: { type: SourceType; url_or_path: string; library_id?: string | null; config: SourceConfig }) =>
    request<{ ok: boolean; message: string; libraries: Array<{ id: string; name: string }>; details: Record<string, unknown> }>('/sources/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  startScan: (sourceId: string) => request<ScanRun>(`/scans/${sourceId}`, { method: 'POST' }),
  listScans: () => request<ScanRun[]>('/scans'),
  getScan: (id: string) => request<ScanRun>(`/scans/${id}`),
  getDiagnostics: () => request<Diagnostics>('/diagnostics'),
}
