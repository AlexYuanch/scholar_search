import { useCallback, useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import { getAuthorWorks } from "@/api"
import type { ScholarProfile } from "@/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

export default function AllPapers({ profile, t }: {
  profile: ScholarProfile
  t: (key: string) => string
}) {
  const [papers, setPapers] = useState<ScholarProfile["topCitedPapers"]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [total, setTotal] = useState(profile.totalPapers)
  const [sort, setSort] = useState<"citations" | "year">("citations")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const load = useCallback(async (nextCursor?: string | null, replace = false) => {
    setLoading(true)
    setError("")
    try {
      const page = await getAuthorWorks(profile.authorId, nextCursor, sort)
      setPapers((current) => replace ? page.items : [...current, ...page.items])
      setCursor(page.next_cursor)
      setTotal(page.total)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Works request failed")
    } finally {
      setLoading(false)
    }
  }, [profile.authorId, sort])

  useEffect(() => {
    void Promise.resolve().then(() => load(null, true))
  }, [load])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{total} {t("candidate.papers")}</span>
        <select value={sort} onChange={(event) => setSort(event.target.value as "citations" | "year")}
          className="h-8 rounded-md border bg-background px-2 text-xs">
          <option value="citations">{t("papers.sort_citations")}</option>
          <option value="year">{t("papers.sort_year")}</option>
        </select>
      </div>
      {papers.map((paper, index) => (
        <Card key={paper.id ?? `${paper.title}-${index}`}>
          <CardContent className="flex gap-3 p-4">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-xs">{index + 1}</div>
            <div className="min-w-0 flex-1">
              {paper.id ? <a href={paper.id} target="_blank" rel="noreferrer" className="text-sm font-medium hover:underline">{paper.title}</a>
                : <p className="text-sm font-medium">{paper.title}</p>}
              <p className="text-xs text-muted-foreground">{paper.year} · {paper.journal} · {paper.citations} {t("candidate.citations")}</p>
            </div>
          </CardContent>
        </Card>
      ))}
      {error && <p className="text-sm text-destructive">{error}</p>}
      {loading && <Loader2 className="mx-auto h-5 w-5 animate-spin" />}
      {cursor && !loading && <Button variant="outline" className="w-full" onClick={() => void load(cursor)}>{t("papers.load_more")}</Button>}
    </div>
  )
}
