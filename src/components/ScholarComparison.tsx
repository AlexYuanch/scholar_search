import { useEffect, useMemo, useRef, useState } from "react"
import { ArrowLeftRight, BookOpen, ChevronRight, Loader2, Search, X } from "lucide-react"
import { searchAuthors, streamProfile } from "@/api"
import type { Candidate, ScholarProfile } from "@/types"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

interface Props {
  profile: ScholarProfile
  onClose: () => void
  t: (key: string) => string
}

interface RecentSummary {
  papers: number
  citations: number
  activeYears: number
}

function initials(name: string) {
  return name.split(" ").filter(Boolean).map((part) => part[0]).join("").slice(0, 3)
}

function recentSummary(profile: ScholarProfile, startYear: number): RecentSummary {
  const rows = profile.yearlyTrend.filter((item) => item.year >= startYear)
  return {
    papers: rows.reduce((sum, item) => sum + item.papers, 0),
    citations: rows.reduce((sum, item) => sum + item.citations, 0),
    activeYears: rows.filter((item) => item.papers > 0).length,
  }
}

function normalizedTopics(profile: ScholarProfile) {
  return new Map(profile.topics.map((topic) => [topic.trim().toLocaleLowerCase(), topic]))
}

function ScholarIdentity({ profile, label }: { profile: ScholarProfile; label: string }) {
  return (
    <Card className="min-w-0">
      <CardContent className="flex min-w-0 items-center gap-3 p-4 sm:p-5">
        <Avatar className="h-12 w-12 shrink-0 border">
          <AvatarFallback className="bg-primary/10 text-sm font-semibold text-primary">
            {initials(profile.name)}
          </AvatarFallback>
        </Avatar>
        <div className="min-w-0">
          <Badge variant="outline" className="mb-1">{label}</Badge>
          <h3 className="break-words font-semibold">{profile.name}</h3>
          <p className="break-words text-xs text-muted-foreground">{profile.institution || "—"}</p>
        </div>
      </CardContent>
    </Card>
  )
}

function ComparisonRow({
  label,
  left,
  right,
}: {
  label: string
  left: number
  right: number
}) {
  const maximum = Math.max(left, right, 1)
  return (
    <div className="grid gap-2 border-b py-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_10rem_minmax(0,1fr)] sm:items-center">
      <div className="min-w-0 text-left">
        <p className="text-xl font-bold tabular-nums">{left.toLocaleString()}</p>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${left ? Math.max(4, left / maximum * 100) : 0}%` }} />
        </div>
      </div>
      <p className="order-first text-center text-sm text-muted-foreground sm:order-none">{label}</p>
      <div className="min-w-0 text-right">
        <p className="text-xl font-bold tabular-nums">{right.toLocaleString()}</p>
        <div className="mt-2 flex h-1.5 justify-end overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${right ? Math.max(4, right / maximum * 100) : 0}%` }} />
        </div>
      </div>
    </div>
  )
}

function TopicGroup({ title, topics, empty }: { title: string; topics: string[]; empty: string }) {
  return (
    <div className="min-w-0 rounded-lg border p-4">
      <h4 className="mb-3 text-sm font-medium">{title}</h4>
      {topics.length ? (
        <div className="flex flex-wrap gap-2">
          {topics.map((topic) => <Badge key={topic} variant="secondary" className="break-words">{topic}</Badge>)}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{empty}</p>
      )}
    </div>
  )
}

function PaperList({ profile, empty }: { profile: ScholarProfile; empty: string }) {
  const papers = profile.representativePapers.length
    ? profile.representativePapers.slice(0, 3)
    : profile.topCitedPapers.slice(0, 3)
  if (!papers.length) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <div className="space-y-2">
      {papers.map((paper) => (
        <a
          key={paper.id || `${paper.title}-${paper.year}`}
          href={paper.id || undefined}
          target={paper.id ? "_blank" : undefined}
          rel={paper.id ? "noopener noreferrer" : undefined}
          className="block rounded-lg border p-3 transition-colors hover:bg-muted/50"
        >
          <p className="break-words text-sm font-medium leading-snug">{paper.title}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {paper.year || "—"} · {paper.citations.toLocaleString()}
          </p>
        </a>
      ))}
    </div>
  )
}

function ComparisonResult({ left, right, t }: { left: ScholarProfile; right: ScholarProfile; t: (key: string) => string }) {
  const startYear = new Date().getFullYear() - 4
  const leftRecent = recentSummary(left, startYear)
  const rightRecent = recentSummary(right, startYear)
  const leftTopics = normalizedTopics(left)
  const rightTopics = normalizedTopics(right)
  const shared = [...leftTopics.entries()]
    .filter(([key]) => rightTopics.has(key))
    .map(([, topic]) => topic)
  const leftOnly = [...leftTopics.entries()]
    .filter(([key]) => !rightTopics.has(key))
    .map(([, topic]) => topic)
  const rightOnly = [...rightTopics.entries()]
    .filter(([key]) => !leftTopics.has(key))
    .map(([, topic]) => topic)

  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-2">
        <ScholarIdentity profile={left} label={t("compare.scholar_a")} />
        <ScholarIdentity profile={right} label={t("compare.scholar_b")} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("compare.scale_title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <ComparisonRow label={t("metric.total_papers")} left={left.totalPapers} right={right.totalPapers} />
          <ComparisonRow label={t("metric.total_citations")} left={left.totalCitations} right={right.totalCitations} />
          <ComparisonRow label={t("metric.h_index")} left={left.hIndex} right={right.hIndex} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{startYear}–{new Date().getFullYear()} {t("compare.recent_title")}</CardTitle>
        </CardHeader>
        <CardContent>
          <ComparisonRow label={t("compare.recent_papers")} left={leftRecent.papers} right={rightRecent.papers} />
          <ComparisonRow label={t("compare.recent_citations")} left={leftRecent.citations} right={rightRecent.citations} />
          <ComparisonRow label={t("compare.active_years")} left={leftRecent.activeYears} right={rightRecent.activeYears} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("compare.topic_title")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 lg:grid-cols-3">
          <TopicGroup title={t("compare.shared_topics")} topics={shared} empty={t("compare.no_shared_topics")} />
          <TopicGroup title={`${left.name} ${t("compare.distinct_topics")}`} topics={leftOnly} empty={t("compare.no_distinct_topics")} />
          <TopicGroup title={`${right.name} ${t("compare.distinct_topics")}`} topics={rightOnly} empty={t("compare.no_distinct_topics")} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="break-words text-base">{left.name} · {t("section.repr_papers")}</CardTitle></CardHeader>
          <CardContent><PaperList profile={left} empty={t("compare.no_papers")} /></CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="break-words text-base">{right.name} · {t("section.repr_papers")}</CardTitle></CardHeader>
          <CardContent><PaperList profile={right} empty={t("compare.no_papers")} /></CardContent>
        </Card>
      </div>

      <p className="rounded-lg bg-muted/60 p-4 text-xs leading-relaxed text-muted-foreground">
        {t("compare.caution")}
      </p>
    </div>
  )
}

export default function ScholarComparison({ profile, onClose, t }: Props) {
  const [query, setQuery] = useState("")
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [comparedProfile, setComparedProfile] = useState<ScholarProfile | null>(null)
  const [loading, setLoading] = useState<"search" | "profile" | null>(null)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState("")
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", closeOnEscape)
    return () => window.removeEventListener("keydown", closeOnEscape)
  }, [onClose])

  const institutionById = useMemo(
    () => new Map(candidates.map((candidate) => [candidate.id, candidate.institutions?.filter(Boolean).join(" · ") || candidate.institution])),
    [candidates],
  )

  const loadCandidate = async (candidate: Candidate) => {
    if (candidate.id === profile.authorId) {
      setError(t("compare.same_scholar"))
      return
    }
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setComparedProfile(null)
    setCandidates([])
    setError("")
    setLoading("profile")
    setProgress(1)
    await streamProfile(candidate.id, {
      onInit: () => undefined,
      onStage: () => undefined,
      onProgress: (value) => setProgress((current) => Math.max(current, value)),
      onResult: (data) => {
        setComparedProfile(data)
        setLoading(null)
        setProgress(100)
      },
      onError: (message) => {
        setError(message)
        setLoading(null)
      },
    }, { signal: controller.signal })
  }

  const search = async () => {
    const name = query.trim()
    if (!name) return
    abortRef.current?.abort()
    setCandidates([])
    setComparedProfile(null)
    setError("")
    setLoading("search")
    setProgress(0)
    try {
      const results = await searchAuthors(name)
      const alternatives = results.filter((candidate) => candidate.id !== profile.authorId)
      if (!alternatives.length) {
        setError(results.length ? t("compare.same_scholar") : t("compare.no_candidates"))
      } else if (alternatives.length === 1) {
        await loadCandidate(alternatives[0])
      } else {
        setCandidates(alternatives)
      }
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t("search.error"))
    } finally {
      setLoading((current) => current === "search" ? null : current)
    }
  }

  const resetComparison = () => {
    abortRef.current?.abort()
    setQuery("")
    setCandidates([])
    setComparedProfile(null)
    setLoading(null)
    setProgress(0)
    setError("")
  }

  return (
    <div className="fixed inset-0 z-[90] bg-black/40 sm:p-4">
      <section role="dialog" aria-modal="true" aria-label={t("compare.title")} className="mx-auto flex h-[100dvh] w-full max-w-6xl flex-col overflow-hidden bg-background sm:h-[calc(100dvh-2rem)] sm:rounded-xl sm:border sm:shadow-2xl">
        <header className="flex shrink-0 items-start justify-between gap-3 border-b px-4 py-4 sm:px-6">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 break-words text-lg font-semibold">
              <ArrowLeftRight className="h-5 w-5 shrink-0 text-primary" />
              {t("compare.title")}
            </h2>
            <p className="mt-1 break-words text-sm text-muted-foreground">{t("compare.description")}</p>
          </div>
          <Button variant="ghost" size="icon" className="shrink-0" onClick={onClose} aria-label={t("panel.close")}>
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {!comparedProfile && (
            <div className="mx-auto max-w-3xl space-y-5">
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{t("compare.choose_title")}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <div className="relative min-w-0 flex-1">
                      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        onKeyDown={(event) => event.key === "Enter" && void search()}
                        placeholder={t("compare.placeholder")}
                        className="h-10 w-full rounded-md border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring"
                        autoFocus
                      />
                    </div>
                    <Button onClick={() => void search()} disabled={!query.trim() || loading !== null}>
                      {loading === "search" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                      {t("compare.search")}
                    </Button>
                  </div>
                </CardContent>
              </Card>

              {error && <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">{error}</p>}

              {loading === "profile" && (
                <Card>
                  <CardContent className="p-6">
                    <div className="flex items-center gap-3">
                      <Loader2 className="h-5 w-5 animate-spin text-primary" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2 text-sm">
                          <span>{t("compare.loading_profile")}</span>
                          <span className="tabular-nums text-muted-foreground">{Math.round(progress)}%</span>
                        </div>
                        <div className="mt-2 h-2 overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.max(2, progress)}%` }} />
                        </div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {candidates.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">{candidates.length} {t("candidate.title")}</p>
                  {candidates.map((candidate) => (
                    <Card key={candidate.id} className="cursor-pointer transition-colors hover:bg-muted/50" onClick={() => void loadCandidate(candidate)}>
                      <CardContent className="flex min-w-0 items-center justify-between gap-3 p-4">
                        <div className="flex min-w-0 items-center gap-3">
                          <Avatar className="h-10 w-10 shrink-0">
                            <AvatarFallback className="bg-primary/10 text-xs text-primary">{initials(candidate.name)}</AvatarFallback>
                          </Avatar>
                          <div className="min-w-0">
                            <p className="break-words text-sm font-medium">{candidate.name}</p>
                            <p className="break-words text-xs text-muted-foreground">{institutionById.get(candidate.id) || t("candidate.unknown_inst")}</p>
                            <p className="mt-1 text-xs text-muted-foreground">
                              {candidate.works_count} {t("candidate.papers")} · {candidate.cited_by_count.toLocaleString()} {t("candidate.citations")}
                            </p>
                          </div>
                        </div>
                        <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground" />
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
            </div>
          )}

          {comparedProfile && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <BookOpen className="h-4 w-4" />{t("compare.result_ready")}
                </p>
                <Button variant="outline" size="sm" onClick={resetComparison}>{t("compare.change")}</Button>
              </div>
              <ComparisonResult left={profile} right={comparedProfile} t={t} />
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
