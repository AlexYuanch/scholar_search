import type {
  Candidate,
  ResearchGraph,
  ResearchGraphObject,
  ResearchGraphObjectType,
  ScholarProfile,
} from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const SEARCH_TIMEOUT_MS = 30_000
const PROFILE_IDLE_TIMEOUT_MS = 120_000

export type ApiErrorKind =
  | 'network'
  | 'timeout'
  | 'rate_limit'
  | 'auth'
  | 'api_key'
  | 'not_found'
  | 'worker'
  | 'server'

export class ApiError extends Error {
  kind: ApiErrorKind
  status?: number
  retryAfter?: number

  constructor(message: string, kind: ApiErrorKind, status?: number, retryAfter?: number) {
    super(message)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.retryAfter = retryAfter
  }
}

function responseKind(status: number): ApiErrorKind {
  if (status === 401) return 'auth'
  if (status === 428) return 'api_key'
  if (status === 404) return 'not_found'
  if (status === 429) return 'rate_limit'
  return 'server'
}

async function responseError(response: Response, fallback: string): Promise<ApiError> {
  const message = await errorMessage(response, fallback)
  const retryAfter = Number(response.headers.get('Retry-After') || 0) || undefined
  return new ApiError(message, responseKind(response.status), response.status, retryAfter)
}

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    if (typeof payload.detail === 'string') return payload.detail
  } catch {
    return fallback
  }
  return fallback
}

export type { Candidate, ScholarProfile }

export interface ScholarListItem {
  author_id: string
  scholar_id: string
  name: string
  institution?: string
  total_papers?: number
  total_citations?: number
  h_index?: number
  updated_at?: string
  created_at?: string
  last_viewed_at?: string
  view_count?: number
  profile_version?: number
  last_seen_profile_version?: number
  last_seen_at?: string
  refresh_status?: "ready" | "queued" | "updating" | "failed"
  new_papers?: number
  new_citations?: number
  research_changes?: Array<{
    topic: string
    kind: "emerging" | "rising" | "falling"
    previous_count: number
    current_count: number
  }>
  has_research_changes?: boolean
  has_updates?: boolean
  refresh_error?: string
}

export interface WorkPage {
  items: ScholarProfile['topCitedPapers']
  total: number
  next_cursor: string | null
}

export interface OpenAlexSettings {
  configured: boolean
  key_hint: string | null
  validated_at: string | null
  updated_at: string | null
  usage?: {
    daily_budget_usd?: number | null
    daily_used_usd?: number | null
    daily_remaining_usd?: number | null
    prepaid_remaining_usd?: number | null
    resets_at?: string | null
  }
}

export async function searchAuthors(name: string, options: { signal?: AbortSignal } = {}): Promise<Candidate[]> {
  const controller = new AbortController()
  let timedOut = false
  const abortFromCaller = () => controller.abort()
  if (options.signal?.aborted) controller.abort()
  else options.signal?.addEventListener('abort', abortFromCaller, { once: true })
  const timeout = globalThis.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, SEARCH_TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE}/search?name=${encodeURIComponent(name)}`, {
      signal: controller.signal,
      credentials: 'include',
    })
    if (!res.ok) throw await responseError(res, `Search failed (${res.status})`)
    const data = await res.json()
    return data.candidates ?? []
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (timedOut) throw new ApiError('Search timed out after 30 seconds', 'timeout')
      throw error
    }
    if (error instanceof TypeError) throw new ApiError(error.message || 'Network request failed', 'network')
    throw error
  } finally {
    options.signal?.removeEventListener('abort', abortFromCaller)
    globalThis.clearTimeout(timeout)
  }
}

export async function getProfile(authorId: string, options: { signal?: AbortSignal } = {}): Promise<ScholarProfile> {
  const res = await fetch(`${API_BASE}/profile`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ author_id: authorId }),
    credentials: 'include',
    signal: options.signal,
  })
  if (!res.ok) throw await responseError(res, `Profile request failed (${res.status})`)
  const data = await res.json()
  if (data.status === 'error') throw new Error(data.errors?.[0] ?? 'Unknown error')
  return data.data
}

export async function refreshProfile(authorId: string): Promise<{
  status: ScholarProfile["refreshStatus"]
  job_id: string
  profile_version: number
}> {
  const response = await authenticatedFetch(
    `/authors/${encodeURIComponent(authorId)}/profile/refresh`,
    { method: 'POST' },
  )
  return response.json()
}

interface StreamOptions {
  signal?: AbortSignal
  authorIds?: string[]
}

/** NDJSON 流式接口：逐步推送工作流进度，最后返回画像数据 */
export async function streamProfile(
  authorId: string,
  callbacks: {
    onInit: (stages: string[], labels: Record<string, string>) => void
    onStage: (node: string, status: string, label: string) => void
    onProgress?: (
      progress: number,
      message: string,
      node?: string,
      messageCode?: string,
    ) => void
    onResult: (data: ScholarProfile, meta: {
      profileVersion?: number
      refreshStatus?: string
    }) => void
    onError: (err: string, kind?: ApiErrorKind) => void
  },
  options: StreamOptions = {},
): Promise<void> {
  const { onInit, onStage, onProgress, onResult, onError } = callbacks
  const controller = new AbortController()
  let timedOut = false
  let idleTimer = 0
  const abortFromCaller = () => controller.abort()
  if (options.signal?.aborted) controller.abort()
  else options.signal?.addEventListener('abort', abortFromCaller, { once: true })
  const resetIdleTimeout = () => {
    globalThis.clearTimeout(idleTimer)
    idleTimer = globalThis.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, PROFILE_IDLE_TIMEOUT_MS)
  }
  resetIdleTimeout()
  try {
    const res = await fetch(`${API_BASE}/profile/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author_id: authorId, author_ids: options.authorIds ?? [authorId] }),
      signal: controller.signal,
      credentials: 'include',
    })
    if (!res.ok) {
      const error = await responseError(res, `Profile request failed (${res.status})`)
      onError(error.message, error.kind)
      return
    }
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let completed = false

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      resetIdleTimeout()
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const msg = JSON.parse(line)
          if (msg.type === 'init') onInit(msg.stages, msg.labels)
          else if (msg.type === 'stage') onStage(msg.node, msg.status, msg.label)
          else if (msg.type === 'progress') {
            onProgress?.(msg.progress, msg.message, msg.node, msg.message_code)
          }
          else if (msg.type === 'result') {
            completed = true
            onResult(msg.data, {
              profileVersion: msg.profile_version,
              refreshStatus: msg.refresh_status,
            })
          } else if (msg.type === 'error') {
            completed = true
            onError(
              msg.message || 'Unknown error',
              msg.code === 'rate_limit'
                ? 'rate_limit'
                : msg.code === 'timeout'
                  ? 'timeout'
                  : msg.code === 'network_error'
                    ? 'network'
                    : 'worker',
            )
          }
        } catch { /* skip malformed lines */ }
      }
    }
    if (!completed && !controller.signal.aborted) {
      onError('Profile stream ended before a result was received', 'network')
    }
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      if (timedOut) onError('Profile stream timed out', 'timeout')
      return
    }
    onError(e instanceof Error ? e.message : 'Connection failed', e instanceof TypeError ? 'network' : 'server')
  } finally {
    globalThis.clearTimeout(idleTimer)
    options.signal?.removeEventListener('abort', abortFromCaller)
  }
}

async function authenticatedFetch(path: string, init: RequestInit = {}) {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    })
    if (!response.ok) throw await responseError(response, `Request failed (${response.status})`)
    return response
  } catch (error: unknown) {
    if (error instanceof ApiError) throw error
    if (error instanceof TypeError) throw new ApiError(error.message || 'Network request failed', 'network')
    throw error
  }
}

export async function getOpenAlexSettings(): Promise<OpenAlexSettings> {
  const response = await authenticatedFetch('/settings/openalex')
  return response.json()
}

export async function saveOpenAlexSettings(apiKey: string): Promise<OpenAlexSettings> {
  const response = await authenticatedFetch('/settings/openalex', {
    method: 'PUT',
    body: JSON.stringify({ api_key: apiKey }),
  })
  return response.json()
}

export async function deleteOpenAlexSettings(): Promise<void> {
  await authenticatedFetch('/settings/openalex', { method: 'DELETE' })
}

export async function getHistory(): Promise<ScholarListItem[]> {
  const response = await authenticatedFetch('/history')
  return (await response.json()).items ?? []
}

export async function getTracking(): Promise<ScholarListItem[]> {
  const response = await authenticatedFetch('/tracking')
  return (await response.json()).items ?? []
}

export async function addTracking(authorId: string): Promise<void> {
  await authenticatedFetch('/tracking', {
    method: 'POST',
    body: JSON.stringify({ author_id: authorId }),
  })
}

export async function removeTracking(authorId: string): Promise<void> {
  await authenticatedFetch(`/tracking/${encodeURIComponent(authorId)}`, { method: 'DELETE' })
}

export async function markTrackingSeen(authorId: string, profileVersion: number): Promise<void> {
  await authenticatedFetch('/tracking/seen', {
    method: 'POST',
    body: JSON.stringify({ author_id: authorId, profile_version: profileVersion }),
  })
}

export async function refreshTracking(authorId: string): Promise<{ status: ScholarListItem["refresh_status"]; job_id: string }> {
  const response = await authenticatedFetch(`/tracking/${encodeURIComponent(authorId)}/refresh`, {
    method: 'POST',
  })
  return response.json()
}

export async function getAuthorWorks(
  authorId: string,
  cursor?: string | null,
  sort: 'citations' | 'year' = 'citations',
  options: { signal?: AbortSignal; year?: number; topic?: string } = {},
): Promise<WorkPage> {
  const params = new URLSearchParams({ limit: '50', sort })
  if (cursor) params.set('cursor', cursor)
  if (options.year !== undefined) params.set('year', String(options.year))
  if (options.topic) params.set('topic', options.topic)
  const response = await fetch(`${API_BASE}/authors/${encodeURIComponent(authorId)}/works?${params}`, {
    credentials: 'include',
    signal: options.signal,
  })
  if (!response.ok) throw await responseError(response, `Works request failed (${response.status})`)
  return response.json()
}

export function profileEventsUrl(scholarId: string, version: number): string {
  return `${API_BASE}/profiles/${encodeURIComponent(scholarId)}/events?version=${version}`
}

export async function getResearchGraph(
  authorId: string,
  signal?: AbortSignal,
): Promise<ResearchGraph> {
  const response = await authenticatedFetch(
    `/authors/${encodeURIComponent(authorId)}/research-graph`,
    { signal },
  )
  return response.json()
}

export async function refreshResearchGraph(
  authorId: string,
  forceRebuild = false,
): Promise<{
  status: "ready" | "queued" | "updating"
  job_id: string | null
  force_rebuild: boolean
}> {
  const response = await authenticatedFetch(
    `/authors/${encodeURIComponent(authorId)}/research-graph/refresh`,
    {
      method: 'POST',
      body: JSON.stringify({ force_rebuild: forceRebuild }),
    },
  )
  return response.json()
}

export async function getResearchGraphObject(
  objectType: ResearchGraphObjectType,
  objectId: string,
): Promise<ResearchGraphObject> {
  const response = await authenticatedFetch(
    `/research-graph/objects/${objectType}/${encodeURIComponent(objectId)}`,
  )
  return response.json()
}
