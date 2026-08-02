export type SourceType = 'filesystem' | 'plex' | 'jellyfin' | 'emby'

export interface SourceConfig {
  token?: string
  user_id?: string
  verify_ssl?: boolean
  tmdb_token?: string
  follow_symlinks?: boolean
  path_mappings?: Array<{ remote: string; local: string }>
}

export interface Source {
  id: string
  name: string
  type: SourceType
  url_or_path: string
  library_id?: string | null
  config: SourceConfig
  schedule_enabled: boolean
  schedule_minutes: number
  enabled: boolean
  created_at: string
  updated_at: string
  movie_count: number
  last_scan_status?: string | null
  last_scan_at?: string | null
}

export interface MovieListItem {
  id: string
  title: string
  year?: number | null
  runtime_seconds?: number | null
  overview?: string | null
  poster_url?: string | null
  source_id: string
  source_name: string
  source_type: string
  file_count: number
  total_size_bytes: number
  resolutions: string[]
  video_codecs: string[]
  containers: string[]
  has_probe_error: boolean
  updated_at: string
}

export interface MediaFile {
  id: string
  path: string
  filename: string
  size_bytes?: number | null
  modified_ts?: number | null
  edition?: string | null
  container?: string | null
  duration_seconds?: number | null
  video_codec?: string | null
  width?: number | null
  height?: number | null
  resolution_label?: string | null
  video_bitrate?: number | null
  audio_codec?: string | null
  audio_channels?: number | null
  audio_languages?: string | null
  probe_error?: string | null
  probe: Record<string, unknown>
}

export interface MovieDetail extends MovieListItem {
  metadata: Record<string, unknown>
  files: MediaFile[]
}

export interface PaginatedMovies {
  items: MovieListItem[]
  total: number
  page: number
  page_size: number
  facets: {
    resolutions: string[]
    codecs: string[]
    containers: string[]
  }
}

export interface ScanRun {
  id: string
  source_id: string
  source_name?: string | null
  status: 'queued' | 'running' | 'completed' | 'failed'
  discovered_count: number
  analyzed_count: number
  cached_count: number
  error_count: number
  current_item?: string | null
  error_message?: string | null
  started_at: string
  completed_at?: string | null
}

export interface Stats {
  movies: number
  files: number
  total_size_bytes: number
  missing_posters: number
  probe_errors: number
  sources: number
  resolutions: Record<string, number>
}

export interface Diagnostics {
  app: Record<string, unknown>
  system: Record<string, unknown>
  database: Record<string, unknown>
  sources: Array<Record<string, unknown>>
  recent_scans: Array<Record<string, unknown>>
}
