import type { Candidate, ScholarProfile } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'

export type { Candidate, ScholarProfile }

export async function searchAuthors(name: string): Promise<Candidate[]> {
  const res = await fetch(`${API_BASE}/search?name=${encodeURIComponent(name)}`)
  if (!res.ok) throw new Error(`Search failed (${res.status})`)
  const data = await res.json()
  return data.candidates ?? []
}

export async function getProfile(authorId: string): Promise<ScholarProfile> {
  const res = await fetch(`${API_BASE}/profile`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ author_id: authorId }),
  })
  if (!res.ok) throw new Error(`Profile request failed (${res.status})`)
  const data = await res.json()
  if (data.status === 'error') throw new Error(data.errors?.[0] ?? 'Unknown error')
  return data.data
}

interface StreamOptions {
  refresh?: boolean
  signal?: AbortSignal
}

/** NDJSON 流式接口：逐步推送工作流进度，最后返回画像数据 */
export async function streamProfile(
  authorId: string,
  callbacks: {
    onInit: (stages: string[], labels: Record<string, string>) => void
    onStage: (node: string, status: string, label: string) => void
    onProgress?: (progress: number, message: string, node?: string) => void
    onCacheHit?: (updatedAt: string) => void
    onResult: (data: ScholarProfile, meta: { source?: string; updatedAt?: string }) => void
    onError: (err: string) => void
  },
  options: StreamOptions = {},
): Promise<void> {
  const { onInit, onStage, onProgress, onCacheHit, onResult, onError } = callbacks
  try {
    const res = await fetch(`${API_BASE}/profile/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ author_id: authorId, refresh: options.refresh ?? false }),
      signal: options.signal,
    })
    if (!res.ok) {
      onError(`Profile request failed (${res.status})`)
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
          else if (msg.type === 'cache_hit') onCacheHit?.(msg.updated_at)
          else if (msg.type === 'result') onResult(msg.data, { source: msg.source, updatedAt: msg.updated_at })
          else if (msg.type === 'error') onError(msg.message || 'Unknown error')
        } catch { /* skip malformed lines */ }
      }
    }
  } catch (e: unknown) {
    if (e instanceof DOMException && e.name === 'AbortError') return
    onError(e instanceof Error ? e.message : 'Connection failed')
  }
}
