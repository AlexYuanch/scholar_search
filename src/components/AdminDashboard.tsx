import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Activity,
  AlertTriangle,
  BarChart3,
  ChevronRight,
  Clock3,
  Globe2,
  RefreshCw,
  Search,
  ShieldCheck,
  UserRoundCheck,
  Users,
  X,
} from "lucide-react"
import {
  getAdminDashboard,
  getAdminUsers,
  updateAdminRole,
  type AdminDashboardData,
  type AdminUser,
} from "@/api"
import type { AuthUser } from "@/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

type RangeName = "24h" | "7d" | "30d"
type DetailView = "online" | "visits" | "users" | "searches"

export default function AdminDashboard({
  open,
  user,
  t,
  lang,
}: {
  open: boolean
  user: AuthUser
  t: (key: string) => string
  lang: "zh" | "en"
}) {
  const [range, setRange] = useState<RangeName>("7d")
  const [data, setData] = useState<AdminDashboardData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [query, setQuery] = useState("")
  const [users, setUsers] = useState<AdminUser[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [changingUserId, setChangingUserId] = useState("")
  const [detailView, setDetailView] = useState<DetailView | null>(null)
  const [onlineTab, setOnlineTab] = useState<"users" | "visitors">("users")
  const [searchTab, setSearchTab] = useState<"searches" | "profiles">("searches")

  const loadDashboard = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      setData(await getAdminDashboard(range))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("admin.load_failed"))
    } finally {
      setLoading(false)
    }
  }, [range, t])

  const loadUsers = useCallback(async (search = "") => {
    if (!user.can_manage_admins) return
    setUsersLoading(true)
    try {
      const result = await getAdminUsers(search)
      setUsers(result.items)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("admin.users_failed"))
    } finally {
      setUsersLoading(false)
    }
  }, [t, user.can_manage_admins])

  useEffect(() => {
    if (!open) return
    const timer = globalThis.setTimeout(() => {
      void loadDashboard()
    }, 0)
    return () => globalThis.clearTimeout(timer)
  }, [loadDashboard, open])

  useEffect(() => {
    if (!open || !user.can_manage_admins) return
    const timer = globalThis.setTimeout(() => {
      void loadUsers(query)
    }, 250)
    return () => globalThis.clearTimeout(timer)
  }, [loadUsers, open, query, user.can_manage_admins])

  const maxTrend = useMemo(
    () => Math.max(
      1,
      ...(data?.trends ?? []).map((item) => Math.max(item.page_views, item.searches)),
    ),
    [data],
  )
  const trendLabelIndexes = useMemo(() => {
    const count = data?.trends.length ?? 0
    if (!count) return new Set<number>()
    return new Set([0, Math.floor((count - 1) / 2), count - 1])
  }, [data?.trends.length])

  const changeRole = async (target: AdminUser) => {
    setChangingUserId(target.id)
    setError("")
    try {
      const updated = await updateAdminRole(
        target.id,
        target.role === "admin" ? "user" : "admin",
      )
      setUsers((current) => current.map((item) => (
        item.id === updated.id ? updated : item
      )))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("admin.role_failed"))
    } finally {
      setChangingUserId("")
    }
  }

  if (!open) return null

  const formatTime = (value: string) => new Intl.DateTimeFormat(
    lang === "zh" ? "zh-CN" : "en-US",
    { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" },
  ).format(new Date(value))
  const formatBucket = (value: string) => new Intl.DateTimeFormat(
    lang === "zh" ? "zh-CN" : "en-US",
    range === "24h"
      ? { hour: "2-digit" }
      : { month: "numeric", day: "numeric" },
  ).format(new Date(value))
  const activityLabel = (value: string | null) => {
    const known = new Set([
      "page_view",
      "search",
      "profile_view",
      "profile_refresh",
      "login_success",
      "register_success",
    ])
    return t(`admin.activity.${value && known.has(value) ? value : "active"}`)
  }
  const visitorLabel = (username: string | null, visitorId: string) => (
    username || `${t("admin.anonymous_visitor")} ${visitorId}`
  )
  const onlinePreview = [
    ...(data?.online_users ?? []).map((item) => ({
      key: `user-${item.id}`,
      label: item.username,
      lastSeenAt: item.last_seen_at,
      type: "user" as const,
    })),
    ...(data?.online_visitors ?? []).map((item) => ({
      key: `visitor-${item.id}`,
      label: `${t("admin.anonymous_visitor")} ${item.id}`,
      lastSeenAt: item.last_seen_at,
      type: "visitor" as const,
    })),
  ].sort((left, right) => right.lastSeenAt.localeCompare(left.lastSeenAt)).slice(0, 4)

  const summaryCards = data ? [
    {
      label: t("admin.online"),
      value: data.summary.online_authenticated + data.summary.online_anonymous,
      note: `${data.summary.online_authenticated} ${t("admin.members")} · ${data.summary.online_anonymous} ${t("admin.guests")}`,
      icon: Activity,
      detailView: "online" as const,
    },
    {
      label: t("admin.today_visits"),
      value: data.summary.today_page_views,
      note: `${data.summary.today_active_users} ${t("admin.active_members")}`,
      icon: BarChart3,
      detailView: "visits" as const,
    },
    {
      label: t("admin.total_users"),
      value: data.summary.total_users,
      note: `${data.summary.new_users} ${t("admin.new_in_range")}`,
      icon: Users,
      detailView: "users" as const,
    },
    {
      label: t("admin.searches"),
      value: data.summary.searches,
      note: `${data.summary.profile_views} ${t("admin.profile_views")}`,
      icon: Search,
      detailView: "searches" as const,
    },
  ] : []

  return (
    <section className="scholar-admin-page min-h-[calc(100vh-3.5rem)] bg-background">
      <div className="border-b bg-background/95">
        <div className="mx-auto flex min-h-20 max-w-6xl items-center justify-between gap-3 px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <div className="min-w-0">
              <h1 className="text-lg font-semibold sm:text-xl">{t("admin.title")}</h1>
              <p className="mt-0.5 text-xs text-muted-foreground sm:text-sm">{t("admin.subtitle")}</p>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-9 gap-1.5"
            onClick={() => void loadDashboard()}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>{t("admin.refresh")}</span>
          </Button>
        </div>
      </div>

      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{t("admin.overview")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t("admin.online_definition")}</p>
          </div>
          <div className="flex rounded-lg border bg-muted/40 p-1">
            {(["24h", "7d", "30d"] as RangeName[]).map((item) => (
              <Button
                key={item}
                variant={range === item ? "default" : "ghost"}
                size="sm"
                className="h-7 px-3 text-xs"
                onClick={() => setRange(item)}
              >
                {t(`admin.range.${item}`)}
              </Button>
            ))}
          </div>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {summaryCards.map(({ label, value, note, icon: Icon, detailView: cardDetailView }) => (
            <Card
              key={label}
              className="cursor-pointer transition-colors hover:border-primary/40 hover:bg-muted/20"
              role="button"
              tabIndex={0}
              onClick={() => setDetailView(cardDetailView)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault()
                  setDetailView(cardDetailView)
                }
              }}
            >
              <CardContent className="p-4">
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  <span>{label}</span>
                  <Icon className="h-4 w-4" />
                </div>
                <p className="mt-3 text-3xl font-semibold tabular-nums">{value}</p>
                <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>{note}</span>
                  <span className="flex items-center gap-0.5 text-primary">
                    {t("admin.view_online")}
                    <ChevronRight className="h-3 w-3" />
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(18rem,1fr)]">
          <Card>
            <CardContent className="p-4 sm:p-5">
              <div className="mb-5">
                <h3 className="font-semibold">{t("admin.traffic_trend")}</h3>
                <p className="text-xs text-muted-foreground">{t("admin.traffic_legend")}</p>
              </div>
              <div className="relative h-52 border-b border-l border-border/70">
                <div className="pointer-events-none absolute inset-0 grid grid-rows-4">
                  {[0, 1, 2, 3].map((line) => (
                    <div key={line} className="border-t border-dashed border-border/60" />
                  ))}
                </div>
                <div className="absolute inset-x-2 bottom-0 top-2 flex items-end gap-1">
                  {(data?.trends ?? []).map((item) => {
                    const title = `${formatTime(item.bucket)} · ${t("admin.visits")} ${item.page_views} · ${t("admin.searches")} ${item.searches}`
                    return (
                      <div
                        key={item.bucket}
                        className="group flex h-full min-w-0 flex-1 items-end justify-center gap-px"
                        title={title}
                        aria-label={title}
                      >
                        <div
                          className="w-1/2 min-w-[2px] rounded-t bg-primary/30 transition-colors group-hover:bg-primary/50"
                          style={{
                            height: item.page_views
                              ? `${Math.max(6, item.page_views / maxTrend * 100)}%`
                              : 0,
                          }}
                        />
                        <div
                          className="w-1/2 min-w-[2px] rounded-t bg-primary transition-colors group-hover:bg-primary/80"
                          style={{
                            height: item.searches
                              ? `${Math.max(6, item.searches / maxTrend * 100)}%`
                              : 0,
                          }}
                        />
                      </div>
                    )
                  })}
                </div>
                <span className="absolute -left-1 top-0 -translate-x-full text-[10px] text-muted-foreground">
                  {maxTrend}
                </span>
                <span className="absolute -bottom-1 -left-1 -translate-x-full translate-y-full text-[10px] text-muted-foreground">
                  0
                </span>
              </div>
              <div className="mt-2 flex justify-between pl-2 text-[10px] text-muted-foreground">
                {(data?.trends ?? []).map((item, index) => (
                  trendLabelIndexes.has(index)
                    ? <span key={item.bucket}>{formatBucket(item.bucket)}</span>
                    : null
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 sm:p-5">
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-semibold">{t("admin.online_details")}</h3>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1 px-2 text-xs text-primary"
                  onClick={() => setDetailView("online")}
                >
                  {t("admin.view_all")}
                  <ChevronRight className="h-3 w-3" />
                </Button>
              </div>
              <div className="mt-4 space-y-2">
                {onlinePreview.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className="flex w-full items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2 text-left transition-colors hover:bg-muted"
                    onClick={() => {
                      setOnlineTab(item.type === "user" ? "users" : "visitors")
                      setDetailView("online")
                    }}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      {item.type === "user"
                        ? <UserRoundCheck className="h-4 w-4 shrink-0 text-emerald-600" />
                        : <Globe2 className="h-4 w-4 shrink-0 text-sky-600" />}
                      <span className="truncate text-sm font-medium">{item.label}</span>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">{formatTime(item.lastSeenAt)}</span>
                  </button>
                ))}
                {!loading && !onlinePreview.length && (
                  <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_online")}</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <CardContent className="p-4 sm:p-5">
              <h3 className="font-semibold">{t("admin.popular_scholars")}</h3>
              <div className="mt-4 space-y-2">
                {(data?.popular_scholars ?? []).map((item, index) => (
                  <div key={item.scholar_id} className="flex items-center gap-3 text-sm">
                    <span className="w-5 text-muted-foreground">{index + 1}</span>
                    <span className="min-w-0 flex-1 truncate">{item.name || t("admin.unknown_scholar")}</span>
                    <span className="tabular-nums text-muted-foreground">{item.views}</span>
                  </div>
                ))}
                {!data?.popular_scholars.length && (
                  <p className="py-6 text-center text-sm text-muted-foreground">{t("admin.no_data")}</p>
                )}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 sm:p-5">
              <h3 className="font-semibold">{t("admin.jobs")}</h3>
              <div className="mt-4 grid grid-cols-2 gap-2">
                {(["queued", "running", "succeeded", "failed"] as const).map((status) => (
                  <div key={status} className="rounded-lg bg-muted/50 p-3">
                    <p className="text-xs text-muted-foreground">{t(`admin.job.${status}`)}</p>
                    <p className="mt-1 text-xl font-semibold tabular-nums">{data?.jobs[status] ?? 0}</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 sm:p-5">
              <h3 className="font-semibold">{t("admin.anomalies")}</h3>
              <div className="mt-4 space-y-2">
                {(data?.anomalies ?? []).map((item) => (
                  <div key={item.type} className="flex items-center justify-between gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm">
                    <span>{t(`admin.anomaly.${item.type}`)}</span>
                    <Badge variant="outline">{item.count}</Badge>
                  </div>
                ))}
                {!data?.anomalies.length && (
                  <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
                    <Clock3 className="h-4 w-4" />
                    {t("admin.no_anomalies")}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {user.can_manage_admins && (
          <Card>
            <CardContent className="p-4 sm:p-5">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
                <div>
                  <h3 className="font-semibold">{t("admin.permissions")}</h3>
                  <p className="mt-1 text-xs text-muted-foreground">{t("admin.permissions_desc")}</p>
                </div>
                <div className="relative w-full sm:w-72">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={t("admin.search_users")}
                    className="h-9 w-full rounded-md border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
              <div className="mt-4 divide-y rounded-lg border">
                {users.map((item) => (
                  <div key={item.id} className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">{item.username}</span>
                        <Badge variant="outline">{t(`admin.role.${item.role}`)}</Badge>
                      </div>
                      {!item.is_active && <p className="text-xs text-muted-foreground">{t("admin.inactive")}</p>}
                    </div>
                    <Button
                      variant={item.role === "admin" ? "outline" : "default"}
                      size="sm"
                      className="w-full sm:w-auto"
                      disabled={item.role === "super_admin" || changingUserId === item.id}
                      onClick={() => void changeRole(item)}
                    >
                      {item.role === "admin" ? t("admin.revoke") : item.role === "super_admin" ? t("admin.protected") : t("admin.grant")}
                    </Button>
                  </div>
                ))}
                {!usersLoading && !users.length && (
                  <p className="p-6 text-center text-sm text-muted-foreground">{t("admin.no_users")}</p>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </main>

      {detailView && (
        <div
          className="fixed inset-x-0 bottom-0 top-14 z-40 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4"
          role="presentation"
          onClick={() => setDetailView(null)}
        >
          <div
            className="max-h-[calc(100vh-4.5rem)] w-full overflow-hidden rounded-t-2xl border bg-background shadow-2xl sm:max-w-2xl sm:rounded-2xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="online-details-title"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b px-4 py-4 sm:px-5">
              <div>
                <h2 id="online-details-title" className="font-semibold">
                  {t(`admin.details.${detailView}.title`)}
                </h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t(`admin.details.${detailView}.desc`)}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => setDetailView(null)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            {detailView === "online" && (
              <div className="flex gap-1 border-b px-4 pt-3 sm:px-5">
              {([
                ["users", `${t("admin.signed_in_users")} (${data?.online_users.length ?? 0})`],
                ["visitors", `${t("admin.anonymous_visitors")} (${data?.online_visitors.length ?? 0})`],
              ] as const).map(([tab, label]) => (
                <Button
                  key={tab}
                  variant="ghost"
                  size="sm"
                  className={`rounded-b-none border-b-2 px-3 ${
                    onlineTab === tab
                      ? "border-primary text-foreground"
                      : "border-transparent text-muted-foreground"
                  }`}
                  onClick={() => setOnlineTab(tab)}
                >
                  {label}
                </Button>
              ))}
              </div>
            )}

            {detailView === "searches" && (
              <div className="flex gap-1 border-b px-4 pt-3 sm:px-5">
                {([
                  ["searches", `${t("admin.search_records")} (${data?.recent_searches.length ?? 0})`],
                  ["profiles", `${t("admin.profile_records")} (${data?.recent_profile_views.length ?? 0})`],
                ] as const).map(([tab, label]) => (
                  <Button
                    key={tab}
                    variant="ghost"
                    size="sm"
                    className={`rounded-b-none border-b-2 px-3 ${
                      searchTab === tab
                        ? "border-primary text-foreground"
                        : "border-transparent text-muted-foreground"
                    }`}
                    onClick={() => setSearchTab(tab)}
                  >
                    {label}
                  </Button>
                ))}
              </div>
            )}

            <div className="max-h-[60vh] space-y-2 overflow-y-auto p-4 sm:p-5">
              {detailView === "online" && onlineTab === "users" && (data?.online_users ?? []).map((item) => (
                <div key={item.id} className="rounded-xl border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <UserRoundCheck className="h-4 w-4 shrink-0 text-emerald-600" />
                      <span className="truncate text-sm font-semibold">{item.username}</span>
                      <Badge variant="outline">{t("admin.signed_in")}</Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {activityLabel(item.last_activity)}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                    <span>{t("admin.first_seen")}：{formatTime(item.first_seen_at)}</span>
                    <span>{t("admin.last_seen")}：{formatTime(item.last_seen_at)}</span>
                    <span>{t("admin.recent_actions")}：{item.activity_count}</span>
                    <span>{t("admin.online_sessions")}：{item.session_count}</span>
                  </div>
                </div>
              ))}

              {detailView === "online" && onlineTab === "visitors" && (data?.online_visitors ?? []).map((item) => (
                <div key={item.id} className="rounded-xl border p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <Globe2 className="h-4 w-4 shrink-0 text-sky-600" />
                      <span className="text-sm font-semibold">{t("admin.anonymous_visitor")} {item.id}</span>
                      <Badge variant="outline">{t("admin.not_signed_in")}</Badge>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {activityLabel(item.last_activity)}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                    <span>{t("admin.first_seen")}：{formatTime(item.first_seen_at)}</span>
                    <span>{t("admin.last_seen")}：{formatTime(item.last_seen_at)}</span>
                    <span>{t("admin.recent_actions")}：{item.activity_count}</span>
                  </div>
                </div>
              ))}

              {detailView === "visits" && (data?.recent_visits ?? []).map((item, index) => (
                <div key={`${item.visitor_id}-${item.occurred_at}-${index}`} className="flex items-center justify-between gap-3 rounded-xl border p-3">
                  <div className="flex min-w-0 items-center gap-2">
                    {item.username
                      ? <UserRoundCheck className="h-4 w-4 shrink-0 text-emerald-600" />
                      : <Globe2 className="h-4 w-4 shrink-0 text-sky-600" />}
                    <span className="truncate text-sm font-medium">
                      {visitorLabel(item.username, item.visitor_id)}
                    </span>
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatTime(item.occurred_at)}
                  </span>
                </div>
              ))}

              {detailView === "users" && (data?.recent_users ?? []).map((item) => (
                <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <Users className="h-4 w-4 shrink-0 text-primary" />
                    <span className="truncate text-sm font-semibold">{item.username}</span>
                    <Badge variant="outline">{t(`admin.role.${item.role}`)}</Badge>
                    {!item.is_active && <Badge variant="outline">{t("admin.inactive")}</Badge>}
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {formatTime(item.created_at)}
                  </span>
                </div>
              ))}

              {detailView === "searches" && searchTab === "searches" && (data?.recent_searches ?? []).map((item, index) => (
                <div key={`${item.visitor_id}-${item.occurred_at}-${index}`} className="rounded-xl border p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="break-words text-sm font-semibold">
                        {item.query || t("admin.query_unavailable")}
                      </p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {visitorLabel(item.username, item.visitor_id)}
                      </p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatTime(item.occurred_at)}
                    </span>
                  </div>
                </div>
              ))}

              {detailView === "searches" && searchTab === "profiles" && (data?.recent_profile_views ?? []).map((item, index) => (
                <div key={`${item.visitor_id}-${item.occurred_at}-${index}`} className="rounded-xl border p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="break-words text-sm font-semibold">
                        {item.name || t("admin.unknown_scholar")}
                      </p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {visitorLabel(item.username, item.visitor_id)}
                      </p>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatTime(item.occurred_at)}
                    </span>
                  </div>
                </div>
              ))}

              {detailView === "online" && onlineTab === "users" && !data?.online_users.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_online_users")}</p>
              )}
              {detailView === "online" && onlineTab === "visitors" && !data?.online_visitors.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_online_visitors")}</p>
              )}
              {detailView === "visits" && !data?.recent_visits.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_visits")}</p>
              )}
              {detailView === "users" && !data?.recent_users.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_recent_users")}</p>
              )}
              {detailView === "searches" && searchTab === "searches" && !data?.recent_searches.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_searches")}</p>
              )}
              {detailView === "searches" && searchTab === "profiles" && !data?.recent_profile_views.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_profile_views")}</p>
              )}
            </div>

            {detailView === "online" && onlineTab === "visitors" && (
              <p className="border-t bg-muted/30 px-4 py-3 text-xs leading-relaxed text-muted-foreground sm:px-5">
                {t("admin.visitor_privacy")}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
