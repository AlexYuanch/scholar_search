import { useCallback, useEffect, useMemo, useState } from "react"
import {
  GitFork,
  Loader2,
  RefreshCw,
  RotateCcw,
} from "lucide-react"
import {
  getResearchGraphObject,
  refreshResearchGraph,
} from "@/api"
import {
  getCachedResearchGraph,
  loadResearchGraphCached,
} from "@/profileAnalysisCache"
import { useAdaptivePolling } from "@/hooks/useAdaptivePolling"
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
import DirectionSections from "@/components/research-graph/DirectionSections"
import EvidenceSections from "@/components/research-graph/EvidenceSections"
import ObjectDetail from "@/components/research-graph/ObjectDetail"
import {
  buildResearchGraphViewModel,
  type Translate,
} from "@/components/research-graph/model"

function GraphStatusCard({
  graph,
  profile,
  refreshing,
  error,
  graphIsEmpty,
  successfulButEmpty,
  waitingForFirstVersion,
  firstVersionFailed,
  onRefresh,
  t,
}: {
  graph: ResearchGraph
  profile: ScholarProfile
  refreshing: boolean
  error: string
  graphIsEmpty: boolean
  successfulButEmpty: boolean
  waitingForFirstVersion: boolean
  firstVersionFailed: boolean
  onRefresh: (forceRebuild: boolean) => void | Promise<void>
  t: Translate
}) {
  const statusTone = graph.status.status === "ready"
    ? "default"
    : graph.status.status === "failed"
      ? "destructive"
      : "secondary"
  const taskActive = ["queued", "updating"].includes(graph.status.status)
  const years = graph.papers
    .map((paper) => paper.year)
    .filter((year): year is number => typeof year === "number")
  const yearRange = years.length
    ? `${Math.min(...years)}–${Math.max(...years)}`
    : "—"
  const abstractEvidenceCount = graph.papers.filter(
    (paper) => paper.insight?.based_on_abstract,
  ).length
  const identityAudit = profile.identityAudit
  const identityNeedsAttention = Boolean(
    identityAudit?.possibleConflatedIdentity
    || (identityAudit?.excludedWorks ?? 0) > 0,
  )
  const identityEvidenceLimited = (
    identityAudit?.resolutionMethod === "insufficient_evidence"
  )

  return (
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
              disabled={refreshing || taskActive}
              onClick={() => void onRefresh(false)}
            >
              {refreshing
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <RefreshCw className="h-3.5 w-3.5" />
              }
              {t("research_graph.incremental_refresh")}
            </Button>
            {graph.status.status === "failed" && (
              <Button
                variant="ghost"
                size="sm"
                disabled={refreshing || taskActive}
                onClick={() => void onRefresh(true)}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t("research_graph.rebuild")}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("research_graph.coverage_papers")}</p>
            <p className="mt-1 text-lg font-bold tabular-nums">{graph.papers.length}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("research_graph.coverage_years")}</p>
            <p className="mt-1 text-lg font-bold tabular-nums">{yearRange}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("research_graph.coverage_abstracts")}</p>
            <p className="mt-1 text-lg font-bold tabular-nums">{abstractEvidenceCount}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("research_graph.coverage_citations")}</p>
            <p className="mt-1 text-lg font-bold tabular-nums">{graph.citations.length}</p>
          </div>
        </div>
        {graph.status.last_success_at && (
          <p className="text-xs text-muted-foreground">
            {t("research_graph.last_updated")}{" "}
            {new Date(graph.status.last_success_at).toLocaleString()}
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
                onClick={() => void onRefresh(false)}
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
        {identityNeedsAttention && (
          <p className="rounded-md border border-amber-300/70 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-700/70 dark:bg-amber-950/30 dark:text-amber-300">
            {t("research_graph.identity_attention")
              .replace("{excluded}", String(identityAudit?.excludedWorks ?? 0))
              .replace("{orcid}", String(identityAudit?.orcidMatchedWorks ?? 0))}
          </p>
        )}
        {!identityNeedsAttention && identityEvidenceLimited && (
          <p className="rounded-md border bg-muted/40 p-3 text-xs text-muted-foreground">
            {t("research_graph.identity_limited")}
          </p>
        )}
        {graphIsEmpty && (
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            {t("research_graph.empty")}
          </p>
        )}
        {successfulButEmpty && (
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            {t("research_graph.success_empty")}
          </p>
        )}
        {waitingForFirstVersion && (
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            {t("research_graph.first_sync_pending")}
          </p>
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
  const cachedGraph = getCachedResearchGraph(
    profile.authorId,
    profile.profileVersion,
  )
  const [graph, setGraph] = useState<ResearchGraph | null>(cachedGraph ?? null)
  const [detail, setDetail] = useState<ResearchGraphObject | null>(null)
  const [loading, setLoading] = useState(!cachedGraph)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState("")
  const viewModel = useMemo(
    () => graph ? buildResearchGraphViewModel(graph) : null,
    [graph],
  )

  const load = useCallback(async (silent = false, force = false) => {
    if (!silent) setLoading(true)
    try {
      const next = await loadResearchGraphCached(
        profile.authorId,
        profile.profileVersion,
        force,
      )
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
  }, [profile.authorId, profile.profileVersion, t])

  useEffect(() => {
    void Promise.resolve().then(() => {
      setDetail(null)
      const cached = getCachedResearchGraph(
        profile.authorId,
        profile.profileVersion,
      )
      setGraph(cached ?? null)
      return load(Boolean(cached))
    })
  }, [load, profile.authorId, profile.profileVersion])

  const poll = useCallback(() => load(true, true), [load])
  useAdaptivePolling(
    Boolean(graph && ["queued", "updating"].includes(graph.status.status)),
    poll,
  )

  const requestRefresh = async (forceRebuild: boolean) => {
    setRefreshing(true)
    try {
      const result = await refreshResearchGraph(profile.authorId, forceRebuild)
      if (result.status === "queued") {
        setGraph((current) => current ? {
          ...current,
          status: { ...current.status, status: "queued", last_error: null },
        } : current)
      }
      setError("")
      await load(true, true)
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

  if (!graph || !viewModel) {
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
  const successfulButEmpty = hasSuccessfulVersion && graph.papers.length === 0

  return (
    <div className="space-y-6">
      <GraphStatusCard
        graph={graph}
        profile={profile}
        refreshing={refreshing}
        error={error}
        graphIsEmpty={graphIsEmpty}
        successfulButEmpty={successfulButEmpty}
        waitingForFirstVersion={waitingForFirstVersion}
        firstVersionFailed={firstVersionFailed}
        onRefresh={requestRefresh}
        t={t}
      />

      {detail && (
        <ObjectDetail value={detail} onClose={() => setDetail(null)} t={t} />
      )}

      {hasSuccessfulVersion && (
        <>
          <DirectionSections view={viewModel} onOpen={openObject} t={t} />
          <EvidenceSections view={viewModel} onOpen={openObject} t={t} />
        </>
      )}
    </div>
  )
}
