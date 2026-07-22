import type { Candidate, ScholarProfile } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
const SEARCH_TIMEOUT_MS = 30_000

async function errorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    if (typeof payload.detail === 'string') return payload.detail
  } catch {
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
}

export interface WorkPage {
  items: ScholarProfile['topCitedPapers']
  total: number
  next_cursor: string | null
}

export async function searchAuthors(name: string): Promise<Candidate[]> {
  const controller = new AbortController()
  const timeout = globalThis.setTimeout(() => controller.abort(), SEARCH_TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE}/search?name=${encodeURIComponent(name)}`, {
      signal: controller.signal,
      credentials: 'include',
    })
    if (!res.ok) throw new Error(await errorMessage(res, `Search failed (${res.status})`))
    const data = await res.json()
    return data.candidates ?? []
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('Search timed out after 30 seconds', { cause: error })
    }
    throw error
  } finally {
    globalThis.clearTimeout(timeout)
  }
}

export async function getProfile(authorId: string): Promise<ScholarProfile> {
  const res = await fetch(`${API_BASE}/profile`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ author_id: authorId }),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Profile request failed (${res.status})`)
  const data = await res.json()
  if (data.status === 'error') throw new Error(data.errors?.[0] ?? 'Unknown error')
  return data.data
}

interface StreamOptions {
  signal?: AbortSignal
}

/** NDJSON 流式接口：逐步推送工作流进度，最后返回画像数据 */
export async function streamProfile(
  authorId: string,
  callbacks: {
    onInit: (stages: string[], labels: Record<string, string>) => void
    onStage: (node: string, status: string, label: string) => void
    onProgress?: (progress: number, message: string, node?: string) => void
    onResult: (data: ScholarProfile, meta: {
      profileVersion?: number
      refreshStatus?: string
    }) => void
    onError: (err: string) => void
  },
  options: StreamOptions = {},
): Promise<void> {
  const { onInit, onStage, onProgress, onResult, onError } = callbacks
  try {
    const res = await fetch(`${API_BASE}/profile/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author_id: authorId }),
      signal: options.signal,
      credentials: 'include',
    })
    if (!res.ok) {
      onError(await errorMessage(res, `Profile request failed (${res.status})`))
      return
    }
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const msg = JSON.parse(line)
          if (msg.type === 'init') onInit(msg.stages, msg.labels)
          else if (msg.type === 'stage') onStage(msg.node, msg.status, msg.label)
          else if (msg.type === 'progress') onProgress?.(msg.progress, msg.message, msg.node)
          else if (msg.type === 'result') onResult(msg.data, {
            profileVersion: msg.profile_version,
            refreshStatus: msg.refresh_status,
          })
          else if (msg.type === 'error') onError(msg.message || 'Unknown error')
        } catch { /* skip malformed lines */ }
      }
    }
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    onError(e instanceof Error ? e.message : 'Connection failed')
  }
}

async function authenticatedFetch(path: string, init: RequestInit = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
  })
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  return response
}

export async function getHistory(): Promise<ScholarListItem[]> {
  const response = await authenticatedFetch('/history')
  return (await response.json()).items ?? []
}

export async function getFavorites(): Promise<ScholarListItem[]> {
  const response = await authenticatedFetch('/favorites')
  return (await response.json()).items ?? []
}

export async function addFavorite(authorId: string): Promise<void> {
  await authenticatedFetch('/favorites', {
    method: 'POST',
    body: JSON.stringify({ author_id: authorId }),
  })
}

export async function removeFavorite(authorId: string): Promise<void> {
  await authenticatedFetch(`/favorites/${encodeURIComponent(authorId)}`, { method: 'DELETE' })
}

export async function getAuthorWorks(
  authorId: string,
  cursor?: string | null,
  sort: 'citations' | 'year' = 'citations',
): Promise<WorkPage> {
  const params = new URLSearchParams({ limit: '50', sort })
  if (cursor) params.set('cursor', cursor)
  const response = await fetch(`${API_BASE}/authors/${encodeURIComponent(authorId)}/works?${params}`)
  if (!response.ok) throw new Error(`Works request failed (${response.status})`)
  return response.json()
}

export function profileEventsUrl(scholarId: string, version: number): string {
  return `${API_BASE}/profiles/${encodeURIComponent(scholarId)}/events?version=${version}`
}
