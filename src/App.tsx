import { Suspense, lazy, useState, useEffect, useCallback, useRef, type ComponentType } from "react"
import {
  Search, BookOpen, Quote, BarChart3, Users,
  ArrowRight, Loader2, AlertCircle, Check, ChevronRight, Sun, Moon, Globe, ExternalLink,
  Heart, History, LogIn, LogOut, ArrowLeftRight, RefreshCw,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Separator } from "@/components/ui/separator"
import { useTranslation } from "./i18n"
import type { Candidate, ScholarProfile } from "./types"
import {
  ApiError,
  addTracking,
  getProfile,
  getTracking,
  markTrackingSeen,
  profileEventsUrl,
  removeTracking,
  searchAuthors,
  streamProfile,
  type ApiErrorKind,
} from "./api"
import { useAuth } from "./auth"
import SidePanel from "@/components/SidePanel"
import AllPapers from "@/components/AllPapers"
import { AccountPanel, AuthDialog } from "@/components/AccountPanels"
import ScholarComparison from "@/components/ScholarComparison"
import ResearchChanges from "@/components/ResearchChanges"
import DataVerification from "@/components/DataVerification"
import ResearchTimeline, { type TimelinePaperFilter } from "@/components/ResearchTimeline"

const CollaborationGraph = lazy(() => import("@/components/CollaborationGraph"))

interface WorkflowStage {
  node: string
  label: string
  status: "pending" | "running" | "completed"
}
type Accent = "blue" | "green" | "purple" | "orange"
type PanelPaper = string | { title: string; id?: string; topics?: string[] }

// ── 指标卡片 ──────────────────────────────────────────────

function MetricCard({ icon: Icon, label, value, sub }: {
  icon: ComponentType<{ className?: string }>; label: string; value: string | number; sub?: string
}) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-primary/10 p-2">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <span className="text-sm text-muted-foreground">{label}</span>
            <span className="text-2xl font-bold">{value}</span>
            {sub && <span className="text-xs text-muted-foreground">{sub}</span>}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function TopicsSection({ topics }: { topics: string[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {topics.map((t) => (
        <Badge key={t} variant="secondary" className="px-3 py-1 text-sm">{t}</Badge>
      ))}
    </div>
  )
}

function EvidenceList({ evidence, t }: { evidence: ScholarProfile["profileEvidence"]; t: (k: string) => string }) {
  if (!evidence?.length) return null
  return (
    <div className="mt-4 space-y-2 border-t pt-4">
      <h4 className="text-xs font-medium text-muted-foreground">{t("section.evidence")}</h4>
      <div className="space-y-2">
        {evidence.map((item) => (
          <div key={item.id} className="flex items-start gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="h-5 shrink-0 px-1.5 text-[10px]">[{item.id}]</Badge>
            {item.url ? (
              <a href={item.url} target="_blank" rel="noopener noreferrer" className="flex items-start gap-1 text-primary hover:underline">
                <span>{item.text}</span>
                <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
              </a>
            ) : (
              <span>{item.text}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}


// ── 候选人列表 ──────────────────────────────────────────────

function CandidateList({ candidates, onSelect, loading, t }: {
  candidates: Candidate[]
  onSelect: (candidate: Candidate) => void
  loading: boolean
  t: (k: string) => string
}) {
  const evidenceLabel = (evidence: NonNullable<Candidate["identity_evidence"]>[number]) => {
    if (evidence.type === "orcid") return `ORCID ${String(evidence.value || "").replace("https://orcid.org/", "")}`
    if (evidence.type === "current_institution") return `${t("candidate.current_inst")}: ${evidence.value}`
    if (evidence.type === "merged_profile") {
      return t("candidate.merge_evidence")
        .replace("{works}", String(evidence.shared_works ?? 0))
        .replace("{coauthors}", String(evidence.shared_coauthors ?? 0))
        .replace("{topics}", String(evidence.shared_topics ?? 0))
        .replace("{institutions}", String(evidence.shared_institutions ?? 0))
    }
    if (evidence.type === "published_profile") {
      return t("candidate.published_profile_evidence")
        .replace("{count}", String(evidence.merged_count ?? 1))
    }
    return t("candidate.independent_evidence")
      .replace("{works}", String(evidence.sampled_works ?? 0))
      .replace("{coauthors}", String(evidence.coauthor_count ?? 0))
      .replace("{topics}", String(evidence.topic_count ?? 0))
  }

  return (
    <section className="mx-auto max-w-3xl px-6 py-6">
      <h3 className="mb-4 text-sm font-medium text-muted-foreground">
        {candidates.length} {t("candidate.title")}
      </h3>
      <p className="mb-4 rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
        {t("candidate.confirm_prompt")}
      </p>
      <div className="space-y-2">
        {candidates.map((c) => (
          <Card key={c.id}
            className="transition-colors hover:bg-muted/30"
          >
            <CardContent className="min-w-0 p-4">
              <div className="flex min-w-0 items-start gap-3">
                <Avatar className="h-10 w-10 shrink-0">
                  <AvatarFallback className="text-xs bg-primary/10 text-primary">
                    {c.name.split(" ").map(n => n[0]).join("")}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-medium text-sm">{c.name}</p>
                    <Badge variant={c.identity_confidence === "high" ? "default" : "outline"}>
                      {t(`candidate.confidence_${c.identity_confidence || "single"}`)}
                    </Badge>
                  </div>
                  <p className="mt-1 max-w-xl break-words text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{t("candidate.current_inst")}:</span>{" "}
                    {c.current_institution || c.institution || t("candidate.unknown_inst")}
                  </p>
                  <p className="mt-0.5 max-w-xl break-words text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{t("candidate.history_inst")}:</span>{" "}
                    {c.historical_institutions?.length
                      ? c.historical_institutions.join(" · ")
                      : t("candidate.no_history_inst")}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    ORCID {c.orcid ? c.orcid.replace("https://orcid.org/", "") : t("candidate.orcid_missing")}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <span>{c.works_count} {t("candidate.papers")}</span>
                    <span>{c.cited_by_count.toLocaleString()} {t("candidate.citations")}</span>
                    <span>h-index {c.h_index}</span>
                    <span>{t("candidate.merged_count").replace("{count}", String(c.merged_count ?? 1))}</span>
                  </div>
                  {(c.merged_count ?? 1) > 1 && (
                    <p className="mt-1 text-xs text-primary">{t("candidate.merged_hint")}</p>
                  )}
                  <div className="mt-3 rounded-md bg-muted/60 p-2.5">
                    <p className="text-xs font-medium">{t("candidate.identity_basis")}</p>
                    <ul className="mt-1 space-y-1 text-xs text-muted-foreground">
                      {(c.identity_evidence ?? []).map((evidence, index) => (
                        <li key={`${evidence.type}-${index}`}>· {evidenceLabel(evidence)}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
              <Button className="mt-3 w-full sm:w-auto" size="sm" onClick={() => onSelect(c)}>
                {t("candidate.confirm")}<ChevronRight className="h-4 w-4" />
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
      {loading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}
    </section>
  )
}


// ── 学者画像内容 ────────────────────────────────────────────

function ProfileSection({
  profile,
  favorite,
  onToggleFavorite,
  onCompare,
  onEdgeClick,
  onNodeClick,
  onFullscreenChange,
  t,
}: {
  profile: ScholarProfile
  favorite: boolean
  onToggleFavorite: () => void
  onCompare: () => void
  onEdgeClick?: (data: { sourceName: string; targetName: string; papers: PanelPaper[]; weight: number }) => void
  onNodeClick?: (data: { id: string; name: string; type: string; papers: PanelPaper[]; weight: number }) => void
  onFullscreenChange?: (fs: boolean) => void
  t: (k: string) => string
}) {
  const [paperFilter, setPaperFilter] = useState<TimelinePaperFilter | null>(null)
  const papersSectionRef = useRef<HTMLDivElement>(null)

  const handleTimelineTopicClick = (filter: TimelinePaperFilter) => {
    setPaperFilter(filter)
    papersSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <section className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <Avatar className="h-16 w-16 shrink-0 border-2 sm:h-20 sm:w-20">
            <AvatarFallback className="text-2xl font-semibold bg-primary/10 text-primary">
              {profile.name.split(" ").map(n => n[0]).join("")}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <h2 className="break-words text-xl font-bold sm:text-2xl">{profile.name}</h2>
            {profile.department && <p className="break-words text-muted-foreground">{profile.department}</p>}
            <p className="break-words text-sm text-muted-foreground">{profile.institution}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          <Button variant="outline" size="sm" className="h-8 gap-1" onClick={onCompare}>
            <ArrowLeftRight className="h-3.5 w-3.5" />
            {t("compare.action")}
          </Button>
          <Button variant="outline" size="sm" className="h-8 gap-1" onClick={onToggleFavorite}>
            <Heart className={`h-3.5 w-3.5 ${favorite ? "fill-current text-red-500" : ""}`} />
            {t(favorite ? "favorite.remove" : "favorite.add")}
          </Button>
        </div>
      </div>

      <Separator className="my-6" />

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("section.profile_summary")}</CardTitle>
            <CardDescription>{t("section.profile_summary_desc")}</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {profile.profileSummary || t("section.summary_empty")}
            </p>
            <EvidenceList evidence={profile.profileEvidence} t={t} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("section.research_directions")}</CardTitle>
            <CardDescription>{t("section.research_desc")}</CardDescription>
          </CardHeader>
          <CardContent className="p-3 sm:p-6">
            <TopicsSection topics={profile.topics} />
          </CardContent>
        </Card>

        <ResearchTimeline profile={profile} onTopicClick={handleTimelineTopicClick} t={t} />

        <ResearchChanges profile={profile} t={t} />

        <div className="grid gap-4 sm:grid-cols-3">
          <MetricCard icon={BookOpen} label={t("metric.total_papers")} value={profile.totalPapers} />
          <MetricCard icon={Quote} label={t("metric.total_citations")} value={profile.totalCitations.toLocaleString()} />
          <MetricCard icon={BarChart3} label={t("metric.h_index")} value={profile.hIndex} />
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("section.repr_papers")}</CardTitle>
            <CardDescription>{t("section.repr_desc")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {(profile.representativePapers.length
              ? profile.representativePapers
              : profile.topCitedPapers.slice(0, 5)
            ).map((paper) => (
              <div key={paper.id || `${paper.title}-${paper.year}`} className="rounded-lg border p-4">
                {paper.id ? (
                  <a href={paper.id} target="_blank" rel="noopener noreferrer" className="flex items-start gap-1 break-words text-sm font-medium text-primary hover:underline">
                    {paper.title}<ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  </a>
                ) : (
                  <p className="break-words text-sm font-medium">{paper.title}</p>
                )}
                <p className="mt-1 text-xs text-muted-foreground">
                  {paper.year || "—"} · {paper.journal || "—"} · {paper.citations.toLocaleString()} {t("candidate.citations")}
                </p>
              </div>
            ))}
            {!profile.representativePapers.length && !profile.topCitedPapers.length && (
              <p className="text-sm text-muted-foreground">{t("compare.no_papers")}</p>
            )}
          </CardContent>
        </Card>

        <div ref={papersSectionRef} className="scroll-mt-20">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("section.all_papers")}</CardTitle>
              <CardDescription>{t("papers.pagination_desc")}</CardDescription>
            </CardHeader>
            <CardContent>
              <AllPapers
                profile={profile}
                filter={paperFilter}
                onClearFilter={() => setPaperFilter(null)}
                t={t}
              />
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("section.collab_network")}</CardTitle>
            <CardDescription>{t("section.collab_desc")}</CardDescription>
          </CardHeader>
          <CardContent className="p-3 sm:p-6">
            <div className="mb-5 flex flex-wrap gap-2">
              {profile.coauthors.slice(0, 8).map((coauthor) => (
                <Badge key={`${coauthor.name}-${coauthor.institution || ""}`} variant="secondary" className="whitespace-normal">
                  {coauthor.name} · {coauthor.papers}
                </Badge>
              ))}
            </div>
            <Suspense fallback={<div className="flex h-[520px] items-center justify-center text-muted-foreground"><Loader2 className="h-6 w-6 animate-spin" /></div>}>
              <CollaborationGraph
                name={profile.name}
                coauthors={profile.coauthors}
                graphNodes={profile.graphNodes}
                graphEdges={profile.graphEdges}
                topics={profile.topics}
                onEdgeClick={onEdgeClick}
                onNodeClick={onNodeClick}
                onFullscreenChange={onFullscreenChange}
                t={t}
              />
            </Suspense>
          </CardContent>
        </Card>

        <DataVerification profile={profile} t={t} />
      </div>
    </section>
  )
}


// ── 主应用 ─────────────────────────────────────────────────

export default function App() {
  const { t, lang, setLang } = useTranslation()
  const { user, loading: authLoading, refreshUser, signOut } = useAuth()

  // 搜索状态
  const [query, setQuery] = useState("")
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [profile, setProfile] = useState<ScholarProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorKind, setErrorKind] = useState<ApiErrorKind | null>(null)
  const [noResults, setNoResults] = useState(false)
  const [searched, setSearched] = useState(false)
  const [authDialogOpen, setAuthDialogOpen] = useState(false)
  const [accountMode, setAccountMode] = useState<"history" | "favorites" | null>(null)
  const [favorite, setFavorite] = useState(false)
  const [liveUpdateMessage, setLiveUpdateMessage] = useState("")

  // 图谱全屏状态
  const [graphFullscreen, setGraphFullscreen] = useState(false)
  const [comparisonOpen, setComparisonOpen] = useState(false)
  const [workflowStages, setWorkflowStages] = useState<WorkflowStage[]>([])
  const [workflowProgress, setWorkflowProgress] = useState(0)
  const [workflowMessage, setWorkflowMessage] = useState("")
  const [trackingRevision, setTrackingRevision] = useState(0)
  const abortRef = useRef<AbortController | null>(null)
  const requestSeqRef = useRef(0)

  const reportError = useCallback((message: string, kind: ApiErrorKind = "server") => {
    setError(message)
    setErrorKind(kind)
    if (kind === "auth") void refreshUser()
  }, [refreshUser])

  // 主题状态
  const [dark, setDark] = useState(() => localStorage.getItem("dark") === "true")
  const [accent, setAccent] = useState<Accent>(() =>
    (localStorage.getItem("accent") as Accent) ?? "blue"
  )

  // 侧面板状态
  const [panel, setPanel] = useState<{
    type: "edge" | "coauthor" | "center"
    sourceName?: string
    targetName: string
    papers: PanelPaper[]
    weight: number
    targetId?: string
  } | null>(null)

  // 应用主题到 <html>
  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle("dark", dark)
    localStorage.setItem("dark", String(dark))
  }, [dark])

  useEffect(() => {
    const root = document.documentElement
    root.className = root.className.replace(/theme-\w+/g, "").trim()
    if (accent !== "blue") root.classList.add(`theme-${accent}`)
    localStorage.setItem("accent", accent)
  }, [accent])

  const loadProfile = useCallback(async (authorId: string, authorIds?: string[]) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const requestId = requestSeqRef.current + 1
    requestSeqRef.current = requestId
    const isCurrent = () => requestSeqRef.current === requestId && !controller.signal.aborted
    setPanel(null)
    setAccountMode(null)
    setComparisonOpen(false)
    setLoading(true)
    setError(null)
    setErrorKind(null)
    setNoResults(false)
    setProfile(null)
    setFavorite(false)
    setCandidates([])
    setWorkflowStages([])
    setWorkflowProgress(0)
    setWorkflowMessage("")
    await streamProfile(authorId, {
      onInit: (stages, labels) => {
        if (!isCurrent()) return
        setWorkflowStages(stages.map((s, i) => ({
          node: s, label: labels[s],
          status: i === 0 ? 'running' as const : 'pending' as const,
        })))
        setWorkflowProgress(1)
        setWorkflowMessage(labels[stages[0]])
      },
      onStage: (node, status, label) => {
        if (!isCurrent()) return
        setWorkflowStages(prev => {
          const idx = prev.findIndex(s => s.node === node)
          if (idx < 0) return prev
          const next = prev.map(s => ({ ...s }))
          next[idx] = { ...next[idx], status: status === 'running' ? 'running' : 'completed' }
          if (status === 'completed' && idx + 1 < next.length && next[idx + 1].status === 'pending') {
            next[idx + 1] = { ...next[idx + 1], status: 'running' }
          }
          return next
        })
        setWorkflowMessage(label)
      },
      onProgress: (progress, message, node) => {
        if (!isCurrent()) return
        setWorkflowProgress(prev => Math.max(prev, Math.min(progress, 100)))
        setWorkflowMessage(message)
        if (node) {
          setWorkflowStages(prev => prev.map(stage =>
            stage.node === node && stage.status === "pending"
              ? { ...stage, status: "running" }
              : stage
          ))
        }
      },
      onResult: (data, meta) => {
        if (!isCurrent()) return
        setProfile({
          ...data,
          profileVersion: meta.profileVersion ?? data.profileVersion,
          refreshStatus: (meta.refreshStatus as ScholarProfile["refreshStatus"]) ?? data.refreshStatus,
        })
        setLoading(false)
        setTimeout(() => setWorkflowStages([]), 600)
      },
      onError: (err, kind) => {
        if (!isCurrent()) return
        reportError(err, kind ?? "worker")
        setLoading(false)
        setWorkflowMessage("")
      },
    }, { signal: controller.signal, authorIds })
  }, [reportError])

  useEffect(() => {
    if (!user || !profile) return
    let active = true
    void getTracking().then((items) => {
      if (!active) return
      const tracked = items.find((item) => item.author_id === profile.authorId)
      setFavorite(Boolean(tracked))
      if (tracked && profile.profileVersion > 0) {
        void markTrackingSeen(profile.authorId, profile.profileVersion).catch(() => undefined)
      }
    }).catch((reason: unknown) => {
      if (active) {
        setFavorite(false)
        if (reason instanceof ApiError && reason.kind === "auth") reportError(reason.message, "auth")
      }
    })
    return () => { active = false }
  }, [profile, reportError, user])

  useEffect(() => {
    if (!user || !profile?.scholarId) return
    const scholarId = profile.scholarId
    const currentVersion = profile.profileVersion
    const controller = new AbortController()
    const eventSource = new EventSource(profileEventsUrl(scholarId, currentVersion))
    const onProfile = (event: MessageEvent) => {
      try {
        const next = JSON.parse(event.data) as { version?: number; status?: string }
        if ((next.version ?? 0) <= currentVersion || next.status !== "ready") return
        void getProfile(profile.authorId, { signal: controller.signal }).then((latest) => {
          setProfile(latest)
          setLiveUpdateMessage(t("realtime.updated"))
          window.setTimeout(() => setLiveUpdateMessage(""), 5000)
        }).catch((reason: unknown) => {
          if (reason instanceof DOMException && reason.name === "AbortError") return
          if (reason instanceof ApiError && reason.kind === "auth") reportError(reason.message, "auth")
        })
      } catch {
        // Ignore malformed event payloads; EventSource will keep the connection alive.
      }
    }
    eventSource.addEventListener("profile", onProfile as EventListener)
    return () => {
      controller.abort()
      eventSource.close()
    }
  }, [profile?.authorId, profile?.profileVersion, profile?.scholarId, reportError, t, user])

  const handleToggleFavorite = useCallback(async () => {
    if (!profile) return
    if (!user) {
      setAuthDialogOpen(true)
      return
    }
    try {
      if (favorite) await removeTracking(profile.authorId)
      else await addTracking(profile.authorId)
      setFavorite((value) => !value)
      setTrackingRevision((value) => value + 1)
    } catch (reason: unknown) {
      reportError(
        reason instanceof Error ? reason.message : t("favorite.failed"),
        reason instanceof ApiError ? reason.kind : "server",
      )
    }
  }, [favorite, profile, reportError, t, user])

  // 搜索
  const handleSearch = useCallback(async () => {
    if (!user) {
      setAuthDialogOpen(true)
      return
    }
    const q = query.trim()
    if (!q) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const requestId = requestSeqRef.current + 1
    requestSeqRef.current = requestId
    const isCurrent = () => requestSeqRef.current === requestId && !controller.signal.aborted
    setLoading(true)
    setError(null)
    setErrorKind(null)
    setNoResults(false)
    setProfile(null)
    setCandidates([])
    setPanel(null)
    setAccountMode(null)
    setComparisonOpen(false)
    setSearched(true)
    try {
      const results = await searchAuthors(q, { signal: controller.signal })
      if (!isCurrent()) return
      if (!results.length) {
        setNoResults(true)
      } else {
        setCandidates(results)
      }
    } catch (e: unknown) {
      if (e instanceof DOMException && e.name === "AbortError") return
      if (!isCurrent()) return
      reportError(
        e instanceof Error ? e.message : t("search.error"),
        e instanceof ApiError ? e.kind : "network",
      )
    } finally {
      if (isCurrent()) setLoading(false)
    }
  }, [query, reportError, t, user])

  // 图谱交互
  const handleEdgeClick = useCallback((data: {
    sourceName: string; targetName: string; papers: PanelPaper[]; weight: number
  }) => {
    setAccountMode(null)
    setPanel({ ...data, type: "edge" })
  }, [])

  const handleNodeClick = useCallback((data: {
    id: string; name: string; type: string; papers: PanelPaper[]; weight: number
  }) => {
    setAccountMode(null)
    setPanel({
      type: data.type === "center" ? "center" : "coauthor",
      targetName: data.name,
      papers: data.papers,
      weight: data.weight,
      targetId: data.id,
    })
  }, [])

  const handleCandidateSelect = useCallback((candidate: Candidate) => {
    setQuery(candidate.name)
    void loadProfile(candidate.id, candidate.merged_ids)
  }, [loadProfile])

  const handleViewProfile = useCallback(async (authorId: string, scholarName: string) => {
    setQuery(scholarName)
    await loadProfile(authorId)
  }, [loadProfile])

  const handleAccountSelect = useCallback((authorId: string, scholarName: string) => {
    setAccountMode(null)
    setQuery(scholarName)
    void loadProfile(authorId)
  }, [loadProfile])

  const openAccountPanel = useCallback((mode: "history" | "favorites") => {
    setPanel(null)
    setAccountMode(mode)
  }, [])

  const handleReset = useCallback(() => {
    abortRef.current?.abort()
    requestSeqRef.current += 1
    setQuery("")
    setCandidates([])
    setProfile(null)
    setError(null)
    setErrorKind(null)
    setNoResults(false)
    setLoading(false)
    setWorkflowStages([])
    setWorkflowProgress(0)
    setWorkflowMessage("")
    setSearched(false)
    setPanel(null)
    setAccountMode(null)
    setComparisonOpen(false)
  }, [])

  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const accents: { key: Accent; label: string; color: string }[] = [
    { key: "blue", label: t("theme.blue"), color: "bg-[#3b82f6]" },
    { key: "green", label: t("theme.green"), color: "bg-[#22c55e]" },
    { key: "purple", label: t("theme.purple"), color: "bg-[#a855f7]" },
    { key: "orange", label: t("theme.orange"), color: "bg-[#f97316]" },
  ]
  const sidePanelOpen = Boolean((panel || accountMode) && !graphFullscreen)

  return (
    <div className="min-h-screen bg-background">

      {/* Navbar */}
      <header className={`sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 ${graphFullscreen ? "hidden" : ""}`}>
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-2 px-3 sm:px-6">
          <div className="flex items-center gap-2 font-semibold cursor-pointer" onClick={handleReset}>
            <BarChart3 className="h-5 w-5 text-primary" />
            <span className="hidden sm:inline">ScholarProfile</span>
          </div>

          <div className="flex items-center gap-1">
            {/* 强调色切换 */}
            <div className="mr-1 hidden items-center gap-0.5 rounded-md border p-0.5 xl:flex">
              {accents.map(a => (
                <button
                  key={a.key}
                  onClick={() => setAccent(a.key)}
                  className={`h-5 w-5 rounded-sm ${a.color} transition-transform hover:scale-125 ${
                    accent === a.key ? "ring-2 ring-ring ring-offset-1" : "opacity-50"
                  }`}
                  title={a.label}
                />
              ))}
            </div>

            {/* 暗色模式 */}
            <Button variant="ghost" size="icon" className="hidden h-8 w-8 sm:inline-flex" onClick={() => setDark(!dark)}>
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>

            {/* 语言切换 */}
            <Button variant="ghost" size="sm" className="hidden h-8 gap-1 text-xs sm:inline-flex"
              onClick={() => setLang(lang === "zh" ? "en" : "zh")}
            >
              <Globe className="h-3.5 w-3.5" />
              {lang === "zh" ? "EN" : "中"}
            </Button>

            {user ? (
              <>
                <span
                  className="hidden max-w-24 truncate rounded-md bg-muted px-2 py-1 text-xs font-medium text-foreground sm:inline"
                  title={user.username}
                >
                  {user.username}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 gap-1 px-2 text-xs"
                  title={t("account.history")}
                  aria-label={t("account.history")}
                  onClick={() => openAccountPanel("history")}
                >
                  <History className="h-4 w-4" />
                  <span>{t("account.history")}</span>
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 gap-1 px-2 text-xs"
                  title={t("account.favorites")}
                  aria-label={t("account.favorites")}
                  onClick={() => openAccountPanel("favorites")}
                >
                  <Heart className="h-4 w-4" />
                  <span>{t("account.favorites")}</span>
                </Button>
                <Button variant="ghost" size="sm" className="h-8 gap-1 text-xs" onClick={() => {
                  setFavorite(false)
                  void signOut()
                }}>
                  <LogOut className="h-3.5 w-3.5" /><span className="hidden md:inline">{t("auth.sign_out")}</span>
                </Button>
              </>
            ) : (
              <Button variant="ghost" size="sm" className="h-8 gap-1 text-xs" onClick={() => setAuthDialogOpen(true)}>
                <LogIn className="h-3.5 w-3.5" />{t("auth.sign_in")}
              </Button>
            )}

            {profile && (
              <Button variant="ghost" size="sm" className="h-8 ml-1" onClick={handleReset}>
                <Search className="h-4 w-4 mr-1" />
                <span className="hidden md:inline">{t("nav.new_search")}</span>
              </Button>
            )}
          </div>
        </div>
      </header>

      <div className={sidePanelOpen ? "lg:grid lg:grid-cols-[minmax(0,1fr)_clamp(22rem,32vw,30rem)]" : ""}>
        <main className="min-w-0">

      {/* 搜索区 */}
      <section className={`relative overflow-hidden border-b bg-gradient-to-b from-background to-muted/30 ${graphFullscreen ? "hidden" : ""}`}>
        <div className="mx-auto max-w-3xl px-4 py-10 text-center sm:px-6 sm:py-16">
          {!profile && (
            <>
              <h1 className="mb-4 text-3xl font-bold tracking-tight sm:text-5xl">
                {t("app.title")}
              </h1>
              <p className="mx-auto mb-8 max-w-2xl text-base text-muted-foreground sm:text-lg">
                {t("app.subtitle")}
              </p>
            </>
          )}
          <div className="mx-auto flex max-w-xl flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder={t("search.placeholder")}
                className="h-11 w-full rounded-md border bg-background pl-9 pr-4 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              />
            </div>
            <Button size="lg" className="h-11 w-full sm:w-auto" onClick={handleSearch} disabled={!query.trim()}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
              {loading ? t("search.loading") : t("search.button")}
            </Button>
          </div>
        </div>
      </section>

      {/* 错误提示 */}
      {error && (
        <div className="mx-auto max-w-3xl px-4 pt-6 sm:px-6">
          <Card className="border-destructive/50 bg-destructive/5">
            <CardContent className="flex flex-wrap items-center gap-3 p-4">
              <AlertCircle className="h-5 w-5 text-destructive shrink-0" />
              <div className="min-w-0 flex-1 text-sm">
                <p className="font-medium">{t(`error.${errorKind ?? "server"}`)}</p>
                <p className="break-words text-muted-foreground">{error}</p>
              </div>
              <Button variant="outline" size="sm" className="ml-auto" onClick={() => {
                if (errorKind === "auth") setAuthDialogOpen(true)
                else void handleSearch()
              }}>
                <RefreshCw className="h-3.5 w-3.5" />{t(errorKind === "auth" ? "auth.sign_in" : "error.retry")}
              </Button>
            </CardContent>
          </Card>
        </div>
      )}

      {liveUpdateMessage && (
        <div className="fixed bottom-4 left-1/2 z-[80] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 rounded-md border bg-background px-4 py-3 text-center text-sm shadow-lg sm:bottom-5">
          {liveUpdateMessage}
        </div>
      )}

      {/* 用户可理解的四阶段画像进度 */}
      {workflowStages.length > 0 && !profile && !error && (
        <div className="mx-auto max-w-xl px-6 py-8">
          <div className="rounded-xl border bg-card shadow-sm overflow-hidden">
            {/* Header */}
            <div className="border-b px-5 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  <span>{t("progress.title")}</span>
                </div>
                <span className="text-xs tabular-nums text-muted-foreground">
                  {Math.round(workflowProgress)}%
                </span>
              </div>
              <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
                  style={{ width: `${workflowProgress}%` }}
                />
              </div>
              {workflowMessage && (
                <p className="mt-2 text-xs text-muted-foreground">{workflowMessage}</p>
              )}
            </div>

            <div className="grid gap-2 p-4 text-sm sm:grid-cols-4">
              {workflowStages.map((stage, index) => (
                <div
                  key={stage.node}
                  className={`flex items-center gap-2 rounded-lg border px-3 py-3 ${
                    stage.status === "running"
                      ? "border-primary bg-primary/5 font-medium"
                      : stage.status === "completed"
                        ? "bg-muted/50 text-muted-foreground"
                        : "text-muted-foreground/50"
                  }`}
                >
                  {stage.status === "completed" ? (
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/10 text-emerald-600">
                      <Check className="h-3 w-3" />
                    </span>
                  ) : stage.status === "running" ? (
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
                  ) : (
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px]">
                      {index + 1}
                    </span>
                  )}
                  <span>{stage.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {/* 加载中（搜索阶段） */}
      {loading && !candidates.length && !profile && !error && workflowStages.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="h-8 w-8 animate-spin mb-4" />
          <p className="text-sm">{t("search.candidate_loading")}</p>
        </div>
      )}

      {/* 候选人 */}
      {candidates.length > 0 && (
        <CandidateList candidates={candidates} onSelect={handleCandidateSelect} loading={loading} t={t} />
      )}

      {noResults && !loading && !error && (
        <div className="mx-auto max-w-xl px-6 py-16 text-center text-muted-foreground">
          <Users className="mx-auto mb-4 h-12 w-12 opacity-30" />
          <p className="font-medium text-foreground">{t("search.no_results")}</p>
          <p className="mt-2 text-sm">{t("search.no_results_hint")}</p>
        </div>
      )}

      {/* 画像 */}
      {profile && (
        <ProfileSection
          key={profile.authorId}
          profile={profile}
          favorite={Boolean(user) && favorite}
          onToggleFavorite={() => void handleToggleFavorite()}
          onCompare={() => setComparisonOpen(true)}
          onEdgeClick={handleEdgeClick}
          onNodeClick={handleNodeClick}
          onFullscreenChange={setGraphFullscreen}
          t={t}
        />
      )}

      {profile && comparisonOpen && (
        <ScholarComparison profile={profile} onClose={() => setComparisonOpen(false)} t={t} />
      )}

      {/* 空状态 */}
      {!searched && !loading && !error && !profile && !candidates.length && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <Users className="h-12 w-12 mb-4 opacity-30" />
          <p className="text-sm">{t("search.empty")}</p>
        </div>
      )}

        </main>

      {/* 侧面板 */}
      <SidePanel
        data={panel}
        onClose={() => setPanel(null)}
        onViewProfile={handleViewProfile}
        t={t}
        fullscreen={graphFullscreen}
      />
      <AccountPanel
        mode={accountMode}
        onClose={() => setAccountMode(null)}
        onSelect={handleAccountSelect}
        onTrackingChange={(authorId, tracked) => {
          if (profile?.authorId === authorId) setFavorite(tracked)
          setTrackingRevision((value) => value + 1)
        }}
        trackingRevision={trackingRevision}
        t={t}
      />
      </div>
      <AuthDialog
        open={authDialogOpen || (!authLoading && !user)}
        required={!user}
        onClose={() => setAuthDialogOpen(false)}
        t={t}
      />
    </div>
  )
}
