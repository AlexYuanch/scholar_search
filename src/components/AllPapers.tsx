import { useCallback, useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"
import { ApiError, getAuthorWorks } from "@/api"
import { useAuth } from "@/auth"
import type { ScholarProfile } from "@/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { TimelinePaperFilter } from "@/components/ResearchTimeline"

export default function AllPapers({ profile, filter, onClearFilter, t }: {
  profile: ScholarProfile
  filter?: TimelinePaperFilter | null
  onClearFilter?: () => void
  t: (key: string) => string
}) {
  const { refreshUser } = useAuth()
  const [papers, setPapers] = useState<ScholarProfile["topCitedPapers"]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [total, setTotal] = useState(profile.totalPapers)
  const [sort, setSort] = useState<"citations" | "year">("citations")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const abortRef = useRef<AbortController | null>(null)
  const filterYear = filter?.year
  const filterTopic = filter?.topic

  const load = useCallback(async (nextCursor?: string | null, replace = false) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    setError("")
    if (replace) {
      setPapers([])
      setCursor(null)
      if (filterYear !== undefined || filterTopic) setTotal(0)
    }
    try {
      const page = await getAuthorWorks(profile.authorId, nextCursor, sort, {
        signal: controller.signal,
        year: filterYear,
        topic: filterTopic,
      })
      if (abortRef.current !== controller) return
      setPapers((current) => replace ? page.items : [...current, ...page.items])
      setCursor(page.next_cursor)
      setTotal(page.total)
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return
      if (abortRef.current !== controller) return
      setError(reason instanceof Error ? reason.message : "Works request failed")
      if (reason instanceof ApiError && reason.kind === "auth") void refreshUser()
    } finally {
      if (abortRef.current === controller) setLoading(false)
    }
  }, [filterTopic, filterYear, profile.authorId, refreshUser, sort])

  useEffect(() => {
    void Promise.resolve().then(() => load(null, true))
    return () => abortRef.current?.abort()
  }, [load])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="text-sm text-muted-foreground">{total} {t("candidate.papers")}</span>
          {filter && (
            <p className="mt-1 text-xs font-medium text-primary">
              {t("papers.filter_prefix")}：{filter.year} · {filter.topic}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {filter && onClearFilter && (
            <Button variant="ghost" size="sm" onClick={onClearFilter}>
              {t("papers.clear_filter")}
            </Button>
          )}
          <select
            value={sort}
            aria-label={t("papers.sort_label")}
            onChange={(event) => setSort(event.target.value as "citations" | "year")}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="citations">{t("papers.sort_citations")}</option>
            <option value="year">{t("papers.sort_year")}</option>
          </select>
        </div>
      </div>
      {papers.map((paper, index) => (
        <Card key={paper.id ?? `${paper.title}-${index}`}>
          <CardContent className="flex gap-3 p-4">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-xs">{index + 1}</div>
            <div className="min-w-0 flex-1">
              {paper.id ? <a href={paper.id} target="_blank" rel="noreferrer" className="break-words text-sm font-medium hover:underline">{paper.title}</a>
                : <p className="break-words text-sm font-medium">{paper.title}</p>}
              <p className="break-words text-xs text-muted-foreground">{paper.year} · {paper.journal} · {paper.citations} {t("candidate.citations")}</p>
            </div>
          </CardContent>
        </Card>
      ))}
      {error && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3">
          <p className="break-words text-sm text-destructive">{error}</p>
          <Button size="sm" variant="outline" onClick={() => void load(null, true)}>{t("error.retry")}</Button>
        </div>
      )}
      {loading && <Loader2 className="mx-auto h-5 w-5 animate-spin" />}
      {!loading && !error && !papers.length && (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">{t("papers.empty")}</p>
      )}
      {cursor && !loading && <Button variant="outline" className="w-full" onClick={() => void load(cursor)}>{t("papers.load_more")}</Button>}
    </div>
  )
}
