import {
  getResearchGraph,
  getScholarIntelligence,
} from "@/api"
import type { ResearchGraph, ScholarIntelligence } from "@/types"

type CacheEntry<T> = {
  value?: T
  promise?: Promise<T>
  updatedAt: number
}

const CACHE_MAX_AGE_MS = 60_000
const MAX_ENTRIES = 24
const graphCache = new Map<string, CacheEntry<ResearchGraph>>()
const intelligenceCache = new Map<string, CacheEntry<ScholarIntelligence>>()

function cacheKey(authorId: string, profileVersion: number) {
  return `${authorId}|${profileVersion}`
}

function trimCache<T>(cache: Map<string, CacheEntry<T>>) {
  while (cache.size > MAX_ENTRIES) {
    const oldestKey = cache.keys().next().value
    if (!oldestKey) return
    cache.delete(oldestKey)
  }
}

function readEntry<T>(
  cache: Map<string, CacheEntry<T>>,
  key: string,
): T | undefined {
  const entry = cache.get(key)
  if (!entry?.value) return undefined
  cache.delete(key)
  cache.set(key, entry)
  return entry.value
}

async function loadEntry<T>(
  cache: Map<string, CacheEntry<T>>,
  key: string,
  loader: () => Promise<T>,
  force: boolean,
): Promise<T> {
  const current = cache.get(key)
  if (current?.promise) return current.promise
  if (
    !force
    && current?.value
    && Date.now() - current.updatedAt < CACHE_MAX_AGE_MS
  ) {
    return current.value
  }

  const promise = loader()
    .then((value) => {
      cache.delete(key)
      cache.set(key, { value, updatedAt: Date.now() })
      trimCache(cache)
      return value
    })
    .catch((error) => {
      const previous = cache.get(key)
      if (previous?.value) {
        cache.set(key, {
          value: previous.value,
          updatedAt: previous.updatedAt,
        })
      } else {
        cache.delete(key)
      }
      throw error
    })

  cache.set(key, {
    value: current?.value,
    updatedAt: current?.updatedAt ?? 0,
    promise,
  })
  return promise
}

export function getCachedResearchGraph(
  authorId: string,
  profileVersion: number,
) {
  return readEntry(graphCache, cacheKey(authorId, profileVersion))
}

export function loadResearchGraphCached(
  authorId: string,
  profileVersion: number,
  force = false,
) {
  return loadEntry(
    graphCache,
    cacheKey(authorId, profileVersion),
    () => getResearchGraph(authorId),
    force,
  )
}

export function getCachedScholarIntelligence(
  authorId: string,
  profileVersion: number,
) {
  return readEntry(intelligenceCache, cacheKey(authorId, profileVersion))
}

export function loadScholarIntelligenceCached(
  authorId: string,
  profileVersion: number,
  force = false,
) {
  return loadEntry(
    intelligenceCache,
    cacheKey(authorId, profileVersion),
    () => getScholarIntelligence(authorId),
    force,
  )
}

export function prefetchProfileAnalysis(
  authorId: string,
  profileVersion: number,
) {
  void loadResearchGraphCached(authorId, profileVersion).catch(() => undefined)
  void loadScholarIntelligenceCached(authorId, profileVersion).catch(() => undefined)
}
