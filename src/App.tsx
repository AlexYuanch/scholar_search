import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import {
  Search, BarChart3, Users,
  ArrowRight, Loader2, AlertCircle, Check, ChevronRight, Sun, Moon, Globe,
  Heart, History, LogIn, LogOut, RefreshCw, ShieldCheck,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { useTranslation } from "./i18n"
import type { Candidate, ScholarProfile } from "./types"
import {
  ApiError,
  addTracking,
  getProfile,
  getTracking,
  markTrackingSeen,
  profileEventsUrl,
  recordPageVisit,
  refreshProfile,
  removeTracking,
  searchAuthors,
  streamProfile,
  type ApiErrorKind,
} from "./api"
import { useAuth } from "./auth"
import SidePanel from "@/components/SidePanel"
import { AccountPanel, AuthDialog } from "@/components/AccountPanels"
import ScholarComparison from "@/components/ScholarComparison"
import ProfileSection from "@/components/ProfileSection"
import AdminDashboard from "@/components/AdminDashboard"
import LandingHero from "@/components/LandingHero"

interface WorkflowStage {
  node: string
  label: string
  status: "pending" | "running" | "completed"
}
type PanelPaper = string | { title: string; id?: string; topics?: string[] }
type CandidateSortKey = "recommended" | "papers" | "citations" | "hIndex" | "latest"
type CandidateIdentityGroup = "high" | "medium" | "review"

const CANDIDATE_GROUP_ORDER: Record<CandidateIdentityGroup, number> = { high: 0, medium: 1, review: 2 }

function candidateGroupFor(candidate: Candidate): CandidateIdentityGroup {
  if (candidate.identity_group) return candidate.identity_group
  if (candidate.identity_confidence === "high") return "high"
  if (candidate.identity_confidence === "medium") return "medium"
  return "review"
}

// ── 候选人列表 ──────────────────────────────────────────────

function CandidateList({ candidates, onSelect, loading, t }: {
  candidates: Candidate[]
  onSelect: (candidate: Candidate) => void
  loading: boolean
  t: (k: string) => string
}) {
  const [sortKey, setSortKey] = useState<CandidateSortKey>("recommended")
  const [institutionQuery, setInstitutionQuery] = useState("")
  const [topicQuery, setTopicQuery] = useState("")
  const [onlyOrcid, setOnlyOrcid] = useState(false)

  const hasTopics = candidates.some((candidate) => (candidate.research_topics ?? []).length > 0)

  const filteredCandidates = useMemo(() => {
    const institutionNeedle = institutionQuery.trim().toLocaleLowerCase()
    const topicNeedle = topicQuery.trim().toLocaleLowerCase()
    const filtered = candidates.filter((candidate) => {
      const institutions = [
        candidate.primary_institution,
        candidate.institution,
        ...(candidate.institutions ?? []),
        ...(candidate.other_institutions ?? []),
      ].filter(Boolean).join(" ").toLocaleLowerCase()
      const topics = (candidate.research_topics ?? []).join(" ").toLocaleLowerCase()
      return (
        (!institutionNeedle || institutions.includes(institutionNeedle))
        && (!topicNeedle || topics.includes(topicNeedle))
        && (!onlyOrcid || Boolean(candidate.orcid))
      )
    })
    return filtered
      .map((candidate, index) => ({ candidate, index }))
      .sort((left, right) => {
        const leftGroup = CANDIDATE_GROUP_ORDER[candidateGroupFor(left.candidate)]
        const rightGroup = CANDIDATE_GROUP_ORDER[candidateGroupFor(right.candidate)]
        if (leftGroup !== rightGroup) return leftGroup - rightGroup
        if (sortKey === "papers") return right.candidate.works_count - left.candidate.works_count || left.index - right.index
        if (sortKey === "citations") return right.candidate.cited_by_count - left.candidate.cited_by_count || left.index - right.index
        if (sortKey === "hIndex") return right.candidate.h_index - left.candidate.h_index || left.index - right.index
        if (sortKey === "latest") return (right.candidate.latest_publication_year ?? 0) - (left.candidate.latest_publication_year ?? 0) || left.index - right.index
        return (
          (right.candidate.identity_score ?? 0) - (left.candidate.identity_score ?? 0)
          || Number(Boolean(right.candidate.orcid)) - Number(Boolean(left.candidate.orcid))
          || (right.candidate.match_reasons?.length ?? 0) - (left.candidate.match_reasons?.length ?? 0)
          || left.index - right.index
        )
      })
      .map(({ candidate }) => candidate)
  }, [candidates, institutionQuery, onlyOrcid, sortKey, topicQuery])

  const clearFilters = () => {
    setSortKey("recommended")
    setInstitutionQuery("")
    setTopicQuery("")
    setOnlyOrcid(false)
  }

  return (
    <section className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <h2 className="text-lg font-semibold">
        {t("candidate.result_count").replace("{count}", String(candidates.length))}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {t("candidate.confirm_prompt")}
      </p>
      {candidates.length > 1 && (
        <div className="my-5 space-y-3 rounded-2xl border bg-card/70 p-3 shadow-sm sm:p-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              value={institutionQuery}
              onChange={(event) => setInstitutionQuery(event.target.value)}
              placeholder={t("candidate.filter_institution")}
              className="h-9 rounded-md border bg-background px-3 text-sm"
            />
            {hasTopics && (
              <input
                value={topicQuery}
                onChange={(event) => setTopicQuery(event.target.value)}
                placeholder={t("candidate.filter_topic")}
                className="h-9 rounded-md border bg-background px-3 text-sm"
              />
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-2 text-muted-foreground">
              <input type="checkbox" checked={onlyOrcid} onChange={(event) => setOnlyOrcid(event.target.checked)} />
              {t("candidate.only_orcid")}
            </label>
            <label className="flex items-center gap-2 text-muted-foreground">
              <span>{t("candidate.sort_label")}</span>
              <select value={sortKey} onChange={(event) => setSortKey(event.target.value as CandidateSortKey)} className="h-9 rounded-md border bg-background px-2 text-sm text-foreground">
                <option value="recommended">{t("candidate.sort_recommended")}</option>
                <option value="papers">{t("candidate.sort_papers")}</option>
                <option value="citations">{t("candidate.sort_citations")}</option>
                <option value="hIndex">{t("candidate.sort_hindex")}</option>
                <option value="latest">{t("candidate.sort_latest")}</option>
              </select>
            </label>
            {(institutionQuery || topicQuery || onlyOrcid || sortKey !== "recommended") && (
              <Button variant="ghost" size="sm" onClick={clearFilters}>{t("candidate.clear_filters")}</Button>
            )}
            <span className="ml-auto text-xs text-muted-foreground">
              {t("candidate.filtered_count").replace("{visible}", String(filteredCandidates.length)).replace("{total}", String(candidates.length))}
            </span>
          </div>
        </div>
      )}
      {filteredCandidates.length === 0 && (
        <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          <p>{t("candidate.no_filtered")}</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={clearFilters}>{t("candidate.clear_filters")}</Button>
        </div>
      )}
      <div className="mt-5 space-y-3">
        {filteredCandidates.map((c) => (
          <Card key={c.id}
            className="overflow-hidden transition-all hover:-translate-y-0.5 hover:border-primary/35"
          >
            <CardContent className="min-w-0 p-5">
              <div className="flex min-w-0 items-start gap-4">
                <Avatar className="h-12 w-12 shrink-0">
                  <AvatarFallback className="bg-primary/10 text-sm text-primary">
                    {c.name.split(" ").map(n => n[0]).join("")}
                  </AvatarFallback>
                </Avatar>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-base font-semibold">{c.name}</p>
                    {c.orcid && <Badge variant="outline">{t("candidate.orcid_available")}</Badge>}
                  </div>
                  <p className="mt-1 max-w-2xl break-words text-sm text-muted-foreground">
                    {c.primary_institution || c.institution || t("candidate.unknown_inst")}
                  </p>
                  {c.other_institutions?.length ? (
                    <p className="mt-0.5 max-w-2xl break-words text-xs text-muted-foreground">
                      {c.other_institutions.slice(0, 3).join(" · ")}
                    </p>
                  ) : null}
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
                    <span>{c.works_count} {t("candidate.papers")}</span>
                    <span>{c.cited_by_count.toLocaleString()} {t("candidate.citations")}</span>
                    <span>h-index {c.h_index}</span>
                    {c.latest_publication_year && (
                      <span>{t("candidate.latest_publication").replace("{year}", String(c.latest_publication_year))}</span>
                    )}
                  </div>
                  {c.research_topics?.length ? (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {c.research_topics.slice(0, 4).map((topic) => (
                        <Badge key={topic} variant="secondary" className="font-normal">{topic}</Badge>
                      ))}
                    </div>
                  ) : null}
                  {c.orcid ? (
                    <a
                      href={c.orcid.startsWith("http") ? c.orcid : `https://orcid.org/${c.orcid}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-3 inline-flex text-xs text-primary hover:underline"
                    >
                      ORCID {c.orcid.replace("https://orcid.org/", "")}
                    </a>
                  ) : (
                    <p className="mt-3 text-xs text-muted-foreground">{t("candidate.verify_hint")}</p>
                  )}
                </div>
              </div>
              <Button className="mt-4 w-full sm:w-auto" size="sm" onClick={() => onSelect(c)}>
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


// ── 主应用 ─────────────────────────────────────────────────

export default function App() {
  const { t, lang, setLang } = useTranslation()
  const { user, refreshUser, signOut } = useAuth()

  // 搜索状态
  const [query, setQuery] = useState("")
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [candidateRevision, setCandidateRevision] = useState(0)
  const [profile, setProfile] = useState<ScholarProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorKind, setErrorKind] = useState<ApiErrorKind | null>(null)
  const [noResults, setNoResults] = useState(false)
  const [searched, setSearched] = useState(false)
  const [authDialogOpen, setAuthDialogOpen] = useState(false)
  const [pendingSearch, setPendingSearch] = useState<string | null>(null)
  const [accountMode, setAccountMode] = useState<"history" | "favorites" | null>(null)
  const [adminOpen, setAdminOpen] = useState(false)
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
    setError(lang === "en" ? t(`error.detail.${kind}`) : message)
    setErrorKind(kind)
    if (kind === "auth") void refreshUser()
  }, [lang, refreshUser, t])

  // 主题状态
  const [dark, setDark] = useState(() => localStorage.getItem("dark") !== "false")
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
    void recordPageVisit().catch(() => undefined)
  }, [])

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
      onInit: (stages) => {
        if (!isCurrent()) return
        setWorkflowStages(stages.map((s, i) => ({
          node: s, label: t(`progress.stage.${s}`),
          status: i === 0 ? 'running' as const : 'pending' as const,
        })))
        setWorkflowProgress(1)
        setWorkflowMessage(t(`progress.message.${stages[0]}`))
      },
      onStage: (node, status) => {
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
        setWorkflowMessage(t(`progress.message.${node}`))
      },
      onProgress: (progress, _message, node, messageCode) => {
        if (!isCurrent()) return
        setWorkflowProgress(prev => Math.max(prev, Math.min(progress, 100)))
        setWorkflowMessage(t(`progress.message.${messageCode ?? node ?? "default"}`))
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
  }, [reportError, t])

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
        const nextVersion = next.version ?? 0
        if (nextVersion < currentVersion) return
        if (nextVersion === currentVersion) {
          if (next.status && ["ready", "queued", "updating", "failed"].includes(next.status)) {
            setProfile((current) => current?.scholarId === scholarId
              ? {
                  ...current,
                  refreshStatus: next.status as ScholarProfile["refreshStatus"],
                }
              : current
            )
          }
          return
        }
        if (next.status !== "ready") return
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

  const handleRefreshProfile = useCallback(async () => {
    if (!profile || !user) return
    try {
      const result = await refreshProfile(profile.authorId)
      setProfile((current) => current?.authorId === profile.authorId
        ? { ...current, refreshStatus: result.status }
        : current
      )
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.kind === "auth") void refreshUser()
      reportError(
        reason instanceof Error ? reason.message : t("profile.refresh_failed"),
        reason instanceof ApiError ? reason.kind : "worker",
      )
    }
  }, [profile, refreshUser, reportError, t, user])

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

  const executeSearch = useCallback(async (q: string) => {
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
        setCandidateRevision((value) => value + 1)
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
  }, [reportError, t])

  // 搜索
  const handleSearch = useCallback(async () => {
    const q = query.trim()
    if (!q) return
    if (!user) {
      setPendingSearch(q)
      setAuthDialogOpen(true)
      return
    }
    await executeSearch(q)
  }, [executeSearch, query, user])

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
    setAdminOpen(false)
    setPanel(null)
    setAccountMode(mode)
  }, [])

  const toggleAdminDashboard = useCallback(() => {
    if (adminOpen) {
      setAdminOpen(false)
      return
    }
    setPanel(null)
    setAccountMode(null)
    setComparisonOpen(false)
    setAdminOpen(true)
  }, [adminOpen])

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
    setAdminOpen(false)
    setComparisonOpen(false)
  }, [])

  useEffect(() => {
    return () => abortRef.current?.abort()
  }, [])

  const sidePanelOpen = Boolean((panel || accountMode) && !graphFullscreen)
  const showLanding = !profile
    && !searched
    && !loading
    && !error
    && !candidates.length
    && workflowStages.length === 0

  return (
    <div className="scholar-app min-h-screen bg-background">

      {/* Navbar */}
      <header className={`scholar-header sticky top-0 z-30 border-b ${graphFullscreen ? "hidden" : ""}`}>
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-2 px-3 sm:px-6">
          <button type="button" className="scholar-brand" onClick={handleReset}>
            <BarChart3 className="h-5 w-5" />
            <span className={user ? "hidden sm:inline" : ""}>ScholarSearch</span>
            <small className="hidden sm:inline">{lang === "zh" ? "科研助手" : "Research assistant"}</small>
          </button>

          <div className="scholar-nav-actions flex items-center gap-1">
            {/* 暗色模式 */}
            <Button
              variant="ghost"
              size="icon"
              className="scholar-theme-button hidden h-8 w-8 sm:inline-flex"
              onClick={() => setDark(!dark)}
              title={t(dark ? "theme.light" : "theme.dark")}
            >
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
                {user.can_view_admin && (
                  <Button
                    variant={adminOpen ? "secondary" : "ghost"}
                    size="sm"
                    className="h-8 gap-1 px-2 text-xs"
                    title={t("admin.nav")}
                    onClick={toggleAdminDashboard}
                  >
                    <ShieldCheck className="h-4 w-4" />
                    <span className="hidden lg:inline">{t("admin.nav")}</span>
                  </Button>
                )}
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
                  setAdminOpen(false)
                  void signOut()
                }}>
                  <LogOut className="h-3.5 w-3.5" /><span className="hidden md:inline">{t("auth.sign_out")}</span>
                </Button>
              </>
            ) : (
              <Button variant="outline" size="sm" className="h-8 gap-1 text-xs" onClick={() => setAuthDialogOpen(true)}>
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
      {!graphFullscreen && (
        showLanding ? (
          <LandingHero
            query={query}
            loading={loading}
            lang={lang}
            onQueryChange={setQuery}
            onSearch={() => void handleSearch()}
            t={t}
          />
        ) : (
          <section className="scholar-search-strip border-b">
            <div className="mx-auto flex max-w-4xl flex-col gap-2 px-4 py-6 sm:flex-row sm:px-6">
              <div className="relative flex-1">
                <Search className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <input
                  type="text"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && void handleSearch()}
                  placeholder={t("search.placeholder")}
                  className="h-12 w-full rounded-xl border bg-background pl-11 pr-4 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/15"
                />
              </div>
              <Button size="lg" className="h-12 w-full rounded-xl px-6 sm:w-auto" onClick={() => void handleSearch()} disabled={!query.trim()}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
                {loading ? t("search.loading") : t("search.button")}
              </Button>
            </div>
          </section>
        )
      )}

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
                <RefreshCw className="h-3.5 w-3.5" />
                {t(errorKind === "auth" ? "auth.sign_in" : "error.retry")}
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
        <CandidateList
          key={candidateRevision}
          candidates={candidates}
          onSelect={handleCandidateSelect}
          loading={loading}
          t={t}
        />
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
          onRefresh={() => void handleRefreshProfile()}
          onEdgeClick={handleEdgeClick}
          onNodeClick={handleNodeClick}
          onFullscreenChange={setGraphFullscreen}
          t={t}
          lang={lang}
        />
      )}

      {profile && comparisonOpen && (
        <ScholarComparison profile={profile} onClose={() => setComparisonOpen(false)} t={t} />
      )}

      {/* 空状态 */}
      {user && !showLanding && !searched && !loading && !error && !profile && !candidates.length && (
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
        lang={lang}
      />
      </div>
      <AuthDialog
        open={authDialogOpen}
        onAuthenticated={() => {
          if (!pendingSearch) return
          const nextQuery = pendingSearch
          setPendingSearch(null)
          setQuery(nextQuery)
          void executeSearch(nextQuery)
        }}
        onClose={() => {
          setAuthDialogOpen(false)
          setPendingSearch(null)
        }}
        t={t}
      />
      {user?.can_view_admin && (
        <AdminDashboard
          open={adminOpen}
          onClose={() => setAdminOpen(false)}
          user={user}
          t={t}
          lang={lang}
        />
      )}
    </div>
  )
}
