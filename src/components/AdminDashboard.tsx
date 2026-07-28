import { useCallback, useEffect, useMemo, useState } from "react"
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Clock3,
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

export default function AdminDashboard({
  open,
  onClose,
  user,
  t,
  lang,
}: {
  open: boolean
  onClose: () => void
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

  const summaryCards = data ? [
    {
      label: t("admin.online"),
      value: data.summary.online_authenticated + data.summary.online_anonymous,
      note: `${data.summary.online_authenticated} ${t("admin.members")} · ${data.summary.online_anonymous} ${t("admin.guests")}`,
      icon: Activity,
    },
    {
      label: t("admin.today_visits"),
      value: data.summary.today_page_views,
      note: `${data.summary.today_active_users} ${t("admin.active_members")}`,
      icon: BarChart3,
    },
    {
      label: t("admin.total_users"),
      value: data.summary.total_users,
      note: `${data.summary.new_users} ${t("admin.new_in_range")}`,
      icon: Users,
    },
    {
      label: t("admin.searches"),
      value: data.summary.searches,
      note: `${data.summary.profile_views} ${t("admin.profile_views")}`,
      icon: Search,
    },
  ] : []

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-background">
      <header className="sticky top-0 z-10 border-b bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-primary" />
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold sm:text-base">{t("admin.title")}</h1>
              <p className="hidden text-xs text-muted-foreground sm:block">{t("admin.subtitle")}</p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1"
              onClick={() => void loadDashboard()}
              disabled={loading}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">{t("admin.refresh")}</span>
            </Button>
            <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </header>

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
          {summaryCards.map(({ label, value, note, icon: Icon }) => (
            <Card key={label}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  <span>{label}</span>
                  <Icon className="h-4 w-4" />
                </div>
                <p className="mt-3 text-3xl font-semibold tabular-nums">{value}</p>
                <p className="mt-1 text-xs text-muted-foreground">{note}</p>
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
              <div className="flex h-52 items-end gap-1 overflow-hidden">
                {(data?.trends ?? []).map((item, index) => (
                  <div key={item.bucket} className="group flex min-w-0 flex-1 items-end justify-center gap-px" title={`${formatTime(item.bucket)} · ${item.page_views}/${item.searches}`}>
                    <div
                      className="w-1/2 min-w-0 rounded-t bg-primary/30 transition-colors group-hover:bg-primary/50"
                      style={{ height: `${Math.max(2, item.page_views / maxTrend * 100)}%` }}
                    />
                    <div
                      className="w-1/2 min-w-0 rounded-t bg-primary"
                      style={{ height: `${Math.max(2, item.searches / maxTrend * 100)}%` }}
                    />
                    {index === (data?.trends.length ?? 0) - 1 && (
                      <span className="sr-only">{formatTime(item.bucket)}</span>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 sm:p-5">
              <h3 className="font-semibold">{t("admin.online_users")}</h3>
              <div className="mt-4 space-y-2">
                {(data?.online_users ?? []).map((item) => (
                  <div key={item.id} className="flex items-center justify-between gap-3 rounded-lg bg-muted/50 px-3 py-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <UserRoundCheck className="h-4 w-4 shrink-0 text-emerald-600" />
                      <span className="truncate text-sm font-medium">{item.username}</span>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground">{formatTime(item.last_seen_at)}</span>
                  </div>
                ))}
                {!loading && !data?.online_users.length && (
                  <p className="py-8 text-center text-sm text-muted-foreground">{t("admin.no_online_users")}</p>
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
    </div>
  )
}
