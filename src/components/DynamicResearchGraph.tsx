import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react"
import {
  Building2,
  CalendarRange,
  ExternalLink,
  GitFork,
  Loader2,
  Network,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Users,
} from "lucide-react"
import {
  getResearchGraph,
  getResearchGraphObject,
  refreshResearchGraph,
} from "@/api"
import type {
  ResearchGraph,
  ResearchGraphObject,
  ResearchGraphObjectType,
  ScholarProfile,
} from "@/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const ResearchGraphNetwork = lazy(() => import("@/components/ResearchGraphNetwork"))

type Translate = (key: string) => string

function yearRange(first?: number | null, last?: number | null) {
  if (!first && !last) return "—"
  if (!last || first === last) return String(first ?? last)
  return `${first ?? "?"}–${last}`
}

function confidenceLabel(value: number) {
  return `${Math.round(value * 100)}%`
}

function eventObject(event: ResearchGraph["timeline"][number]): {
  type: ResearchGraphObjectType
  id: string
} | null {
  if (event.work_id) return { type: "paper", id: event.work_id }
  if (event.topic_id) return { type: "topic", id: event.topic_id }
  if (event.institution_id) return { type: "institution", id: event.institution_id }
  if (event.collaborator_id) return { type: "author", id: event.collaborator_id }
  return null
}

function ObjectDetail({
  value,
  onClose,
  t,
}: {
  value: ResearchGraphObject
  onClose: () => void
  t: Translate
}) {
  const entries = Object.entries(value.data).filter(([key, field]) => (
    !["raw_json", "abstract"].includes(key)
    && field !== null
    && field !== ""
    && typeof field !== "object"
  ))
  const abstract = typeof value.data.abstract === "string" ? value.data.abstract : ""
  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">{t(`research_graph.object.${value.type}`)}</CardTitle>
            <CardDescription>{value.id}</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>{t("research_graph.close")}</Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map(([key, field]) => (
          <div key={key} className="grid gap-1 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]">
            <span className="text-muted-foreground">{key}</span>
            <span className="break-words">{String(field)}</span>
          </div>
        ))}
        {abstract && (
          <div className="rounded-md border bg-background p-3">
            <Badge variant="outline">{t("research_graph.abstract_basis")}</Badge>
            <p className="mt-2 break-words text-sm leading-relaxed">{abstract}</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function DynamicResearchGraph({
  profile,
  t,
}: {
  profile: ScholarProfile
  t: Translate
}) {
  const [graph, setGraph] = useState<ResearchGraph | null>(null)
  const [detail, setDetail] = useState<ResearchGraphObject | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState("")

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const next = await getResearchGraph(profile.authorId)
      setGraph(next)
      setError("")
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t("research_graph.load_failed"))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [profile.authorId, t])

  useEffect(() => {
    void Promise.resolve().then(() => load())
  }, [load])

  useEffect(() => {
    if (!graph || !["queued", "updating"].includes(graph.status.status)) return
    const timer = window.setInterval(() => void load(true), 3000)
    return () => window.clearInterval(timer)
  }, [graph, load])

  const requestRefresh = async (forceRebuild: boolean) => {
    setRefreshing(true)
    try {
      await refreshResearchGraph(profile.authorId, forceRebuild)
      setGraph((current) => current ? {
        ...current,
        status: { ...current.status, status: "queued", last_error: null },
      } : current)
      setError("")
      await load(true)
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t("research_graph.refresh_failed"))
    } finally {
      setRefreshing(false)
    }
  }

  const openObject = useCallback(async (
    objectType: ResearchGraphObjectType,
    objectId: string,
  ) => {
    try {
      setDetail(await getResearchGraphObject(objectType, objectId))
      setError("")
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : t("research_graph.object_failed"))
    }
  }, [t])

  const statusTone = useMemo(() => {
    if (graph?.status.status === "ready") return "default"
    if (graph?.status.status === "failed") return "destructive"
    return "secondary"
  }, [graph?.status.status])

  if (loading) {
    return (
      <Card>
        <CardContent className="flex min-h-48 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </CardContent>
      </Card>
    )
  }

  if (!graph) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-sm text-destructive">{error || t("research_graph.load_failed")}</p>
          <Button variant="outline" onClick={() => void load()}>{t("error.retry")}</Button>
        </CardContent>
      </Card>
    )
  }

  const graphIsEmpty = graph.status.status === "never" && !graph.papers.length

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <GitFork className="h-4 w-4" />
                {t("research_graph.title")}
              </CardTitle>
              <CardDescription className="mt-1">{t("research_graph.description")}</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusTone}>{t(`research_graph.status.${graph.status.status}`)}</Badge>
              <Button
                variant="outline"
                size="sm"
                disabled={refreshing || ["queued", "updating"].includes(graph.status.status)}
                onClick={() => void requestRefresh(false)}
              >
                {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                {t("research_graph.incremental_refresh")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={refreshing || ["queued", "updating"].includes(graph.status.status)}
                onClick={() => void requestRefresh(true)}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t("research_graph.rebuild")}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {graph.status.last_success_at && (
            <p className="text-xs text-muted-foreground">
              {t("research_graph.last_updated")} {new Date(graph.status.last_success_at).toLocaleString()}
              {" · "}v{graph.status.version}
            </p>
          )}
          {graph.status.last_error && (
            <p className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              {graph.status.last_error}
            </p>
          )}
          {graph.status.warnings.map((warning) => (
            <p key={warning} className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">{warning}</p>
          ))}
          {error && <p className="text-sm text-destructive">{error}</p>}
          {graphIsEmpty && (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              {t("research_graph.empty")}
            </p>
          )}
        </CardContent>
      </Card>

      {detail && <ObjectDetail value={detail} onClose={() => setDetail(null)} t={t} />}

      {graph.local_network.nodes.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Network className="h-4 w-4" />
              {t("research_graph.local_network")}
            </CardTitle>
            <CardDescription>{t("research_graph.local_network_desc")}</CardDescription>
          </CardHeader>
          <CardContent className="p-3 sm:p-6">
            <Suspense fallback={<Loader2 className="mx-auto h-6 w-6 animate-spin" />}>
              <ResearchGraphNetwork graph={graph.local_network} onObjectClick={openObject} />
            </Suspense>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CalendarRange className="h-4 w-4" />
              {t("research_graph.timeline")}
            </CardTitle>
            <CardDescription>{t("research_graph.timeline_desc")}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="max-h-[38rem] space-y-3 overflow-y-auto pr-1">
              {graph.timeline.map((event) => {
                const object = eventObject(event)
                return (
                  <div key={event.event_key} className="grid grid-cols-[4rem_minmax(0,1fr)] gap-3 rounded-lg border p-3">
                    <span className="text-xs font-semibold tabular-nums">{event.event_year ?? "—"}</span>
                    <div className="min-w-0">
                      {object ? (
                        <button
                          type="button"
                          className="break-words text-left text-sm font-medium hover:text-primary hover:underline"
                          onClick={() => void openObject(object.type, object.id)}
                        >
                          {event.title}
                        </button>
                      ) : <p className="break-words text-sm font-medium">{event.title}</p>}
                      <p className="text-xs text-muted-foreground">
                        {t(`research_graph.event.${event.event_type}`)}
                        {event.description ? ` · ${event.description}` : ""}
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {event.source} · {confidenceLabel(event.confidence)}
                      </p>
                    </div>
                  </div>
                )
              })}
              {!graph.timeline.length && <p className="text-sm text-muted-foreground">{t("research_graph.no_timeline")}</p>}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4" />
              {t("research_graph.topic_evolution")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {graph.topic_evolution.slice(0, 16).map((topic) => (
              <button
                key={topic.id}
                type="button"
                className="block w-full rounded-lg border p-3 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
                onClick={() => void openObject("topic", topic.id)}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="break-words text-sm font-medium">{topic.name}</span>
                  <Badge variant="secondary">{topic.works_count}</Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {yearRange(topic.first_year, topic.last_year)} · {topic.source} · {confidenceLabel(topic.confidence)}
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {topic.years.slice(-8).map((value) => {
                    const year = typeof value === "number" ? value : value.year
                    const count = typeof value === "number" ? undefined : value.works_count
                    return <Badge key={year} variant="outline">{year}{count ? ` · ${count}` : ""}</Badge>
                  })}
                </div>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-4 w-4" />
              {t("research_graph.collaboration_evolution")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {graph.collaborations.slice(0, 20).map((collaboration) => (
              <div key={collaboration.author.id} className="rounded-lg border p-3">
                <button
                  type="button"
                  className="text-left text-sm font-medium hover:text-primary hover:underline"
                  onClick={() => void openObject("author", collaboration.author.id)}
                >
                  {collaboration.author.name}
                </button>
                <p className="text-xs text-muted-foreground">
                  {yearRange(collaboration.first_year, collaboration.last_year)}
                  {" · "}{collaboration.works_count} {t("candidate.papers")}
                  {" · "}{collaboration.source} · {confidenceLabel(collaboration.confidence)}
                </p>
                <div className="mt-2 space-y-1">
                  {collaboration.papers.slice(0, 3).map((paper) => (
                    <button
                      key={paper.id}
                      type="button"
                      className="block max-w-full truncate text-left text-xs text-muted-foreground hover:text-primary hover:underline"
                      onClick={() => void openObject("paper", paper.id)}
                    >
                      {paper.year ?? "—"} · {paper.title}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Building2 className="h-4 w-4" />
              {t("research_graph.affiliations")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {graph.affiliations.map((affiliation) => (
              <button
                key={affiliation.id}
                type="button"
                className="block w-full rounded-lg border p-3 text-left hover:border-primary/40 hover:bg-primary/5"
                onClick={() => void openObject("institution", affiliation.id)}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className="break-words text-sm font-medium">{affiliation.name}</span>
                  {affiliation.is_current && <Badge>{t("research_graph.current")}</Badge>}
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {yearRange(affiliation.start_year, affiliation.end_year)}
                  {affiliation.country_code ? ` · ${affiliation.country_code}` : ""}
                  {" · "}{affiliation.source} · {confidenceLabel(affiliation.confidence)}
                </p>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("research_graph.paper_topic_insights")}</CardTitle>
          <CardDescription>{t("research_graph.abstract_rule")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {graph.papers.slice(0, 20).map((paper) => (
            <div key={paper.id} className="rounded-lg border p-4">
              <button
                type="button"
                className="break-words text-left text-sm font-medium hover:text-primary hover:underline"
                onClick={() => void openObject("paper", paper.id)}
              >
                {paper.title}
              </button>
              <p className="mt-1 text-xs text-muted-foreground">
                {paper.year ?? "—"} · {paper.venue || "—"} · {paper.citations} {t("candidate.citations")}
                {" · "}{paper.source.join(" + ")} · {confidenceLabel(paper.confidence)}
              </p>
              <div className="mt-2 flex flex-wrap gap-1">
                {paper.topics.map((topic) => (
                  <button key={topic.id} type="button" onClick={() => void openObject("topic", topic.id)}>
                    <Badge variant={topic.is_primary ? "default" : "secondary"}>{topic.name}</Badge>
                  </button>
                ))}
              </div>
              {paper.insight?.based_on_abstract ? (
                <div className="mt-3 space-y-2 rounded-md bg-muted/50 p-3 text-sm">
                  <Badge variant="outline">{t("research_graph.abstract_basis")}</Badge>
                  {paper.insight.problem && <p><span className="font-medium">{t("research_graph.problem")}：</span>{paper.insight.problem}</p>}
                  {paper.insight.core_method && <p><span className="font-medium">{t("research_graph.method")}：</span>{paper.insight.core_method}</p>}
                  {paper.insight.main_contribution && <p><span className="font-medium">{t("research_graph.contribution")}：</span>{paper.insight.main_contribution}</p>}
                  {paper.insight.topic_relationship && <p><span className="font-medium">{t("research_graph.topic_relation")}：</span>{paper.insight.topic_relationship}</p>}
                  <details>
                    <summary className="cursor-pointer text-xs text-muted-foreground">{t("research_graph.abstract_evidence")}</summary>
                    <div className="mt-2 space-y-1">
                      {paper.insight.abstract_evidence.map((evidence, index) => (
                        <p key={`${evidence.field}-${index}`} className="border-l-2 pl-2 text-xs text-muted-foreground">
                          {evidence.text}
                        </p>
                      ))}
                    </div>
                  </details>
                </div>
              ) : (
                <p className="mt-3 rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
                  {t("research_graph.no_abstract")}
                </p>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("research_graph.citation_evolution")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {graph.citations.slice(0, 80).map((citation) => (
            <div key={`${citation.citing.id}-${citation.cited.source_id}`} className="grid gap-2 rounded-lg border p-3 text-sm md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-center">
              <button
                type="button"
                className="min-w-0 break-words text-left hover:text-primary hover:underline"
                onClick={() => void openObject("paper", citation.citing.id)}
              >
                {citation.citing.title}
              </button>
              <span className="text-xs text-muted-foreground">→ {t("research_graph.cites")} →</span>
              {citation.cited.id ? (
                <button
                  type="button"
                  className="min-w-0 break-words text-left hover:text-primary hover:underline"
                  onClick={() => void openObject("paper", citation.cited.id!)}
                >
                  {citation.cited.title}
                </button>
              ) : (
                <a
                  href={citation.cited.source_id}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex min-w-0 items-start gap-1 break-words hover:text-primary hover:underline"
                >
                  {citation.cited.title}
                  <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                </a>
              )}
            </div>
          ))}
          {!graph.citations.length && <p className="text-sm text-muted-foreground">{t("research_graph.no_citations")}</p>}
        </CardContent>
      </Card>
    </div>
  )
}
