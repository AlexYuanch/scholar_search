import { useCallback, useEffect, useMemo, useState } from "react"
import {
  ArrowRight,
  BookOpen,
  Building2,
  CalendarRange,
  GitFork,
  Loader2,
  Quote,
  RefreshCw,
  RotateCcw,
  Sparkles,
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
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

type Translate = (key: string) => string
type GraphPaper = ResearchGraph["papers"][number]

type PhaseTopic = {
  id: string
  name: string
  count: number
}

type ResearchPhase = {
  key: string
  startYear: number
  endYear: number
  papers: GraphPaper[]
  topics: PhaseTopic[]
  topicCounts: Map<string, PhaseTopic>
  citations: number
  abstractEvidenceCount: number
}

function buildResearchPhases(papers: GraphPaper[]): ResearchPhase[] {
  const dated = papers.filter((paper): paper is GraphPaper & { year: number } => (
    typeof paper.year === "number"
  ))
  if (!dated.length) return []
  const years = dated.map((paper) => paper.year)
  const minimumYear = Math.min(...years)
  const maximumYear = Math.max(...years)
  const windowSize = Math.max(
    3,
    Math.ceil((maximumYear - minimumYear + 1) / 5),
  )
  const buckets = new Map<number, GraphPaper[]>()
  dated.forEach((paper) => {
    const index = Math.floor((paper.year - minimumYear) / windowSize)
    buckets.set(index, [...(buckets.get(index) || []), paper])
  })
  return [...buckets.entries()]
    .sort(([left], [right]) => left - right)
    .map(([index, phasePapers]) => {
      const startYear = minimumYear + index * windowSize
      const endYear = Math.min(maximumYear, startYear + windowSize - 1)
      const topicCounts = new Map<string, PhaseTopic>()
      phasePapers.forEach((paper) => {
        paper.topics.forEach((topic) => {
          const current = topicCounts.get(topic.id)
          topicCounts.set(topic.id, {
            id: topic.id,
            name: topic.name,
            count: (current?.count || 0) + 1,
          })
        })
      })
      return {
        key: `${startYear}-${endYear}`,
        startYear,
        endYear,
        papers: [...phasePapers].sort(
          (left, right) => right.citations - left.citations,
        ),
        topics: [...topicCounts.values()]
          .sort(
            (left, right) => (
              right.count - left.count || left.name.localeCompare(right.name)
            ),
          )
          .slice(0, 5),
        topicCounts,
        citations: phasePapers.reduce(
          (total, paper) => total + paper.citations,
          0,
        ),
        abstractEvidenceCount: phasePapers.filter(
          (paper) => paper.insight?.based_on_abstract,
        ).length,
      }
    })
}

function phaseLabel(phase: ResearchPhase) {
  return phase.startYear === phase.endYear
    ? String(phase.startYear)
    : `${phase.startYear}–${phase.endYear}`
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
  const abstract = typeof value.data.abstract === "string"
    ? value.data.abstract
    : ""
  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">
              {t(`research_graph.object.${value.type}`)}
            </CardTitle>
            <CardDescription>{value.id}</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("research_graph.close")}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map(([key, field]) => (
          <div
            key={key}
            className="grid gap-1 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]"
          >
            <span className="text-muted-foreground">{key}</span>
            <span className="break-words">{String(field)}</span>
          </div>
        ))}
        {abstract && (
          <div className="rounded-md border bg-background p-3">
            <Badge variant="outline">
              {t("research_graph.abstract_basis")}
            </Badge>
            <p className="mt-2 break-words text-sm leading-relaxed">
              {abstract}
            </p>
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
      setError(
        reason instanceof Error
          ? reason.message
          : t("research_graph.load_failed"),
      )
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
      setError(
        reason instanceof Error
          ? reason.message
          : t("research_graph.refresh_failed"),
      )
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
      setError(
        reason instanceof Error
          ? reason.message
          : t("research_graph.object_failed"),
      )
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
        <CardContent className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          {t("research_graph.loading")}
        </CardContent>
      </Card>
    )
  }

  if (!graph) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-sm text-destructive">
            {error || t("research_graph.load_failed")}
          </p>
          <Button variant="outline" onClick={() => void load()}>
            {t("error.retry")}
          </Button>
        </CardContent>
      </Card>
    )
  }

  const hasSuccessfulVersion = Boolean(graph.status.last_success_at)
  const graphIsEmpty = graph.status.status === "never" && !hasSuccessfulVersion
  const waitingForFirstVersion = (
    !hasSuccessfulVersion
    && ["queued", "updating"].includes(graph.status.status)
  )
  const firstVersionFailed = (
    !hasSuccessfulVersion && graph.status.status === "failed"
  )
  const phases = buildResearchPhases(graph.papers)
  const transitions = phases.slice(1).map((phase, index) => {
    const previous = phases[index]
    const previousIds = new Set(previous.topics.map((topic) => topic.id))
    const currentIds = new Set(phase.topics.map((topic) => topic.id))
    return {
      key: `${previous.key}:${phase.key}`,
      previous,
      current: phase,
      emerged: phase.topics.filter((topic) => !previousIds.has(topic.id)),
      continued: phase.topics.filter((topic) => previousIds.has(topic.id)),
      faded: previous.topics.filter((topic) => !currentIds.has(topic.id)),
    }
  })
  const matrixTopics = [...phases.reduce((topics, phase) => {
    phase.topicCounts.forEach((topic, id) => {
      const current = topics.get(id)
      topics.set(id, {
        ...topic,
        count: (current?.count || 0) + topic.count,
      })
    })
    return topics
  }, new Map<string, PhaseTopic>()).values()]
    .sort(
      (left, right) => (
        right.count - left.count || left.name.localeCompare(right.name)
      ),
    )
    .slice(0, 10)
  const insightPapers = phases
    .flatMap((phase) => phase.papers
      .filter((paper) => paper.insight?.based_on_abstract)
      .slice(0, 2))
    .sort(
      (left, right) => (
        (left.year || 0) - (right.year || 0)
        || right.citations - left.citations
      ),
    )
  const phaseContext = new Map(phases.map((phase) => {
    const events = graph.timeline.filter((event) => (
      typeof event.event_year === "number"
      && event.event_year >= phase.startYear
      && event.event_year <= phase.endYear
    ))
    const institutions = [...events.reduce((values, event) => {
      if (
        !event.event_type.startsWith("institution")
        || !event.institution_id
      ) return values
      values.set(event.institution_id, event)
      return values
    }, new Map<string, ResearchGraph["timeline"][number]>()).values()]
      .slice(0, 2)
    const newCollaboratorCount = events.filter(
      (event) => event.event_type === "collaboration_started",
    ).length
    return [
      phase.key,
      { institutions, newCollaboratorCount },
    ] as const
  }))
  const internalCitations = graph.citations
    .filter((citation) => Boolean(citation.cited.id))
    .reduce<ResearchGraph["citations"]>((selected, citation) => {
      if (selected.length >= 12) return selected
      const fromSamePaper = selected.filter(
        (item) => item.citing.id === citation.citing.id,
      ).length
      return fromSamePaper < 2 ? [...selected, citation] : selected
    }, [])

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
              <CardDescription className="mt-1">
                {t("research_graph.description")}
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={statusTone}>
                {t(`research_graph.status.${graph.status.status}`)}
              </Badge>
              <Button
                variant="outline"
                size="sm"
                disabled={
                  refreshing
                  || ["queued", "updating"].includes(graph.status.status)
                }
                onClick={() => void requestRefresh(false)}
              >
                {refreshing
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  : <RefreshCw className="h-3.5 w-3.5" />
                }
                {t("research_graph.incremental_refresh")}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                disabled={
                  refreshing
                  || ["queued", "updating"].includes(graph.status.status)
                }
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
              {t("research_graph.last_updated")}{" "}
              {new Date(graph.status.last_success_at).toLocaleString()}
              {" · "}v{graph.status.version}
            </p>
          )}
          {graph.status.last_error && (
            <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-3">
              <p className="text-sm text-destructive">
                {graph.status.last_error}
              </p>
              {firstVersionFailed && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={refreshing}
                  onClick={() => void requestRefresh(false)}
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  {t("error.retry")}
                </Button>
              )}
            </div>
          )}
          {graph.status.warnings.map((warning) => (
            <p
              key={warning}
              className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground"
            >
              {warning}
            </p>
          ))}
          {error && <p className="text-sm text-destructive">{error}</p>}
          {graphIsEmpty && (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              {t("research_graph.empty")}
            </p>
          )}
          {waitingForFirstVersion && (
            <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              {t("research_graph.first_sync_pending")}
            </p>
          )}
        </CardContent>
      </Card>

      {detail && (
        <ObjectDetail value={detail} onClose={() => setDetail(null)} t={t} />
      )}

      {hasSuccessfulVersion && (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <CalendarRange className="h-4 w-4" />
                {t("research_graph.phases")}
              </CardTitle>
              <CardDescription>
                {t("research_graph.phases_desc")}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {phases.map((phase) => (
                <div key={phase.key} className="rounded-xl border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold">
                        {phaseLabel(phase)}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {phase.papers.length}{" "}
                        {t("research_graph.phase_outputs")}
                        {" · "}{phase.citations} {t("candidate.citations")}
                        {" · "}{phase.abstractEvidenceCount}{" "}
                        {t("research_graph.abstract_evidence_count")}
                      </p>
                    </div>
                    <Badge variant="secondary">
                      {t("research_graph.computed")}
                    </Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {phase.topics.map((topic) => (
                      <button
                        key={topic.id}
                        type="button"
                        onClick={() => void openObject("topic", topic.id)}
                      >
                        <Badge variant="outline">
                          {topic.name} · {topic.count}
                        </Badge>
                      </button>
                    ))}
                  </div>
                  {(() => {
                    const context = phaseContext.get(phase.key)
                    if (
                      !context
                      || (
                        !context.institutions.length
                        && !context.newCollaboratorCount
                      )
                    ) return null
                    return (
                      <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
                        <span className="text-xs font-medium text-muted-foreground">
                          {t("research_graph.phase_context")}：
                        </span>
                        {context.institutions.map((event) => (
                          <button
                            key={event.institution_id}
                            type="button"
                            onClick={() => void openObject(
                              "institution",
                              event.institution_id!,
                            )}
                          >
                            <Badge variant="outline">
                              <Building2 className="mr-1 h-3 w-3" />
                              {event.title}
                            </Badge>
                          </button>
                        ))}
                        {context.newCollaboratorCount > 0 && (
                          <Badge variant="secondary">
                            {t("research_graph.new_collaborators")}{" "}
                            {context.newCollaboratorCount}
                          </Badge>
                        )}
                      </div>
                    )
                  })()}
                </div>
              ))}
              {!phases.length && (
                <p className="text-sm text-muted-foreground">
                  {t("research_graph.no_phases")}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <GitFork className="h-4 w-4" />
                {t("research_graph.transitions")}
              </CardTitle>
              <CardDescription>
                {t("research_graph.transitions_desc")}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {transitions.map((transition) => (
                <div key={transition.key} className="rounded-xl border p-4">
                  <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
                    <span>{phaseLabel(transition.previous)}</span>
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                    <span>{phaseLabel(transition.current)}</span>
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-3">
                    {[
                      ["transition_emerged", transition.emerged, "default"],
                      ["transition_continued", transition.continued, "secondary"],
                      ["transition_faded", transition.faded, "outline"],
                    ].map(([label, topics, variant]) => (
                      <div key={String(label)}>
                        <p className="mb-1 text-xs font-medium text-muted-foreground">
                          {t(`research_graph.${String(label)}`)}
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {(topics as PhaseTopic[]).map((topic) => (
                            <button
                              key={topic.id}
                              type="button"
                              onClick={() => void openObject("topic", topic.id)}
                            >
                              <Badge variant={variant as "default" | "secondary" | "outline"}>
                                {topic.name}
                              </Badge>
                            </button>
                          ))}
                          {!(topics as PhaseTopic[]).length && (
                            <span className="text-xs text-muted-foreground">
                              —
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {!transitions.length && (
                <p className="text-sm text-muted-foreground">
                  {t("research_graph.no_transitions")}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Sparkles className="h-4 w-4" />
                {t("research_graph.topic_matrix")}
              </CardTitle>
              <CardDescription>
                {t("research_graph.topic_matrix_desc")}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {matrixTopics.length && phases.length ? (
                <div className="overflow-x-auto">
                  <div
                    className="grid min-w-[42rem] gap-1 text-xs"
                    style={{
                      gridTemplateColumns: `minmax(12rem, 1.6fr) repeat(${phases.length}, minmax(5rem, .7fr))`,
                    }}
                  >
                    <div className="p-2 font-medium text-muted-foreground">
                      {t("research_graph.direction")}
                    </div>
                    {phases.map((phase) => (
                      <div
                        key={phase.key}
                        className="p-2 text-center font-medium"
                      >
                        {phaseLabel(phase)}
                      </div>
                    ))}
                    {matrixTopics.map((topic) => (
                      <div key={topic.id} className="contents">
                        <button
                          type="button"
                          className="truncate rounded-md p-2 text-left font-medium hover:bg-muted"
                          onClick={() => void openObject("topic", topic.id)}
                        >
                          {topic.name}
                        </button>
                        {phases.map((phase) => {
                          const count = (
                            phase.topicCounts.get(topic.id)?.count || 0
                          )
                          return (
                            <div
                              key={`${phase.key}:${topic.id}`}
                              className={count
                                ? "rounded-md bg-primary/15 p-2 text-center font-semibold text-primary"
                                : "rounded-md bg-muted/30 p-2 text-center text-muted-foreground"
                              }
                            >
                              {count || "—"}
                            </div>
                          )
                        })}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("research_graph.no_topic_matrix")}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <BookOpen className="h-4 w-4" />
                {t("research_graph.abstract_evolution")}
              </CardTitle>
              <CardDescription>
                {t("research_graph.abstract_evolution_desc")}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {insightPapers.map((paper) => (
                <div
                  key={paper.id}
                  className="grid gap-3 rounded-xl border p-4 md:grid-cols-[5rem_minmax(0,1fr)]"
                >
                  <div>
                    <p className="text-sm font-semibold tabular-nums">
                      {paper.year ?? "—"}
                    </p>
                    <Badge variant="outline" className="mt-2">
                      {t("research_graph.abstract_basis")}
                    </Badge>
                  </div>
                  <div className="min-w-0 space-y-2 text-sm">
                    {paper.insight?.problem && (
                      <p>
                        <span className="font-medium">
                          {t("research_graph.problem")}：
                        </span>
                        {paper.insight.problem}
                      </p>
                    )}
                    {paper.insight?.core_method && (
                      <p>
                        <span className="font-medium">
                          {t("research_graph.method")}：
                        </span>
                        {paper.insight.core_method}
                      </p>
                    )}
                    {paper.insight?.main_contribution && (
                      <p>
                        <span className="font-medium">
                          {t("research_graph.contribution")}：
                        </span>
                        {paper.insight.main_contribution}
                      </p>
                    )}
                    {paper.insight?.topic_relationship && (
                      <p>
                        <span className="font-medium">
                          {t("research_graph.topic_relation")}：
                        </span>
                        {paper.insight.topic_relationship}
                      </p>
                    )}
                    <button
                      type="button"
                      className="block max-w-full truncate text-left text-xs text-muted-foreground hover:text-primary hover:underline"
                      onClick={() => void openObject("paper", paper.id)}
                    >
                      {t("research_graph.evidence_source")}：{paper.title}
                    </button>
                  </div>
                </div>
              ))}
              {!insightPapers.length && (
                <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                  {t("research_graph.no_abstract_evolution")}
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Quote className="h-4 w-4" />
                {t("research_graph.citation_evolution")}
              </CardTitle>
              <CardDescription>
                {t("research_graph.citation_desc")}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {internalCitations.map((citation) => (
                <div
                  key={`${citation.citing.id}-${citation.cited.source_id}`}
                  className="grid gap-2 rounded-lg border p-3 text-sm md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-center"
                >
                  <button
                    type="button"
                    className="min-w-0 break-words text-left hover:text-primary hover:underline"
                    onClick={() => void openObject(
                      "paper",
                      citation.citing.id,
                    )}
                  >
                    {citation.citing.title}
                  </button>
                  <span className="text-xs text-muted-foreground">
                    → {t("research_graph.cites")} →
                  </span>
                  <button
                    type="button"
                    className="min-w-0 break-words text-left hover:text-primary hover:underline"
                    onClick={() => void openObject(
                      "paper",
                      citation.cited.id!,
                    )}
                  >
                    {citation.cited.title}
                  </button>
                </div>
              ))}
              {!internalCitations.length && (
                <p className="text-sm text-muted-foreground">
                  {t("research_graph.no_citations")}
                </p>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
