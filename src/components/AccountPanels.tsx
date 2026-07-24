import { useCallback, useEffect, useState } from "react"
import { AlertCircle, Bell, BookOpen, CheckCircle2, Eye, Loader2, LogIn, RefreshCw, X } from "lucide-react"
import { useAuth } from "@/auth"
import { ApiError, getHistory, getTracking, refreshTracking, removeTracking, type ScholarListItem } from "@/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

function updateTime(value?: string) {
  if (!value) return "—"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "—"
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date)
}

export function AuthDialog({ open, required = false, onClose, t }: {
  open: boolean
  required?: boolean
  onClose: () => void
  t: (key: string) => string
}) {
  const { register, signIn } = useAuth()
  const [mode, setMode] = useState<"login" | "register">("login")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [passwordConfirmation, setPasswordConfirmation] = useState("")
  const [message, setMessage] = useState("")
  const [loading, setLoading] = useState(false)
  const registering = mode === "register"
  const canSubmit = Boolean(
    username.trim()
    && password.length >= 12
    && (!registering || passwordConfirmation.length >= 12),
  )
  if (!open) return null

  const submit = async () => {
    setLoading(true)
    setMessage("")
    if (registering && password !== passwordConfirmation) {
      setMessage(t("auth.password_mismatch"))
      setLoading(false)
      return
    }
    try {
      if (registering) await register(username.trim(), password)
      else await signIn(username.trim(), password)
      setPassword("")
      setPasswordConfirmation("")
      onClose()
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t("auth.failed"))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/40 p-3 sm:p-6">
      <Card className="max-h-[calc(100dvh-1.5rem)] w-full max-w-md overflow-y-auto sm:max-h-[calc(100dvh-3rem)]">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <LogIn className="h-4 w-4" />{t(registering ? "auth.register_title" : "auth.title")}
          </CardTitle>
          {!required && <Button variant="ghost" size="icon" onClick={onClose}><X className="h-4 w-4" /></Button>}
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {t(registering ? "auth.register_desc" : "auth.password_desc")}
          </p>
          <input
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder={t("auth.username_placeholder")}
            className="h-10 w-full rounded-md border bg-background px-3 text-sm"
          />
          <input
            type="password"
            autoComplete={registering ? "new-password" : "current-password"}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !registering && canSubmit) void submit()
            }}
            placeholder={t("auth.password_placeholder")}
            className="h-10 w-full rounded-md border bg-background px-3 text-sm"
          />
          {registering && (
            <input
              type="password"
              autoComplete="new-password"
              value={passwordConfirmation}
              onChange={(event) => setPasswordConfirmation(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && canSubmit) void submit()
              }}
              placeholder={t("auth.password_confirm_placeholder")}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
            />
          )}
          <Button className="w-full" disabled={!canSubmit || loading} onClick={submit}>
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            {t(registering ? "auth.register" : "auth.sign_in")}
          </Button>
          {message && <p className="text-sm text-destructive">{message}</p>}
          <Button variant="ghost" className="w-full" onClick={() => {
            setMode((current) => current === "login" ? "register" : "login")
            setMessage("")
            setPassword("")
            setPasswordConfirmation("")
          }}>
            {t(registering ? "auth.have_account" : "auth.need_account")}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

export function AccountPanel({ mode, onClose, onSelect, t }: {
  mode: "history" | "favorites" | null
  onClose: () => void
  onSelect: (authorId: string, scholarName: string) => void
  t: (key: string) => string
}) {
  const { refreshUser } = useAuth()
  const [items, setItems] = useState<ScholarListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
  const [actingOn, setActingOn] = useState("")

  const loadItems = useCallback(async (silent = false) => {
    if (!mode) return
    if (!silent) setLoading(true)
    setError("")
    try {
      setItems(await (mode === "history" ? getHistory() : getTracking()))
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Request failed")
      if (reason instanceof ApiError && reason.kind === "auth") void refreshUser()
    } finally {
      if (!silent) setLoading(false)
    }
  }, [mode, refreshUser])

  useEffect(() => {
    if (!mode) return
    let active = true
    void Promise.resolve().then(async () => {
      if (active) await loadItems()
    })
    return () => { active = false }
  }, [loadItems, mode])

  useEffect(() => {
    if (mode !== "favorites" || !items.some((item) => item.refresh_status === "queued" || item.refresh_status === "updating")) {
      return
    }
    const timer = window.setTimeout(() => void loadItems(true), 3000)
    return () => window.clearTimeout(timer)
  }, [items, loadItems, mode])

  if (!mode) return null

  const remove = async (item: ScholarListItem) => {
    setActingOn(item.author_id)
    setError("")
    try {
      await removeTracking(item.author_id)
      setItems((current) => current.filter((row) => row.author_id !== item.author_id))
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Request failed")
      if (reason instanceof ApiError && reason.kind === "auth") void refreshUser()
    } finally {
      setActingOn("")
    }
  }

  const refresh = async (item: ScholarListItem) => {
    setActingOn(item.author_id)
    setError("")
    try {
      const result = await refreshTracking(item.author_id)
      setItems((current) => current.map((row) => row.author_id === item.author_id
        ? { ...row, refresh_status: result.status ?? "queued", refresh_error: "" }
        : row))
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Request failed")
      if (reason instanceof ApiError && reason.kind === "auth") void refreshUser()
    } finally {
      setActingOn("")
    }
  }

  return (
    <>
      <button
        type="button"
        aria-label={t("panel.close")}
        className="fixed inset-0 z-40 bg-black/30 lg:hidden"
        onClick={onClose}
      />
      <aside className="fixed right-0 top-0 z-50 flex h-[100dvh] w-full max-w-md flex-col border-l bg-background shadow-xl lg:sticky lg:right-auto lg:top-14 lg:z-20 lg:h-[calc(100dvh-3.5rem)] lg:max-w-none lg:self-start lg:shadow-none">
        <div className="flex shrink-0 items-center justify-between border-b p-5">
          <h2 className="flex items-center gap-2 font-semibold">
            {mode === "history" ? <BookOpen className="h-4 w-4" /> : <Bell className="h-4 w-4" />}
            {t(mode === "history" ? "account.history" : "account.favorites")}
          </h2>
          <Button variant="ghost" size="icon" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {mode === "favorites" && (
            <div className="mb-4 flex gap-3 rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
              <Bell className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <p>{t("tracking.description")}</p>
            </div>
          )}
          {loading && <Loader2 className="mx-auto mt-12 h-6 w-6 animate-spin" />}
          {error && <p className="break-words text-sm text-destructive">{error}</p>}
          {!loading && !items.length && <p className="text-sm text-muted-foreground">{t("account.empty")}</p>}
          <div className="space-y-2">
            {items.map((item) => (
              <Card key={item.author_id}>
                <CardContent className="min-w-0 p-4">
                  <div className="flex min-w-0 items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="break-words text-sm font-medium">{item.name}</p>
                      {mode === "favorites" && item.has_updates && (
                        <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">{t("tracking.new_activity")}</Badge>
                      )}
                    </div>
                    <p className="break-words text-xs text-muted-foreground">{item.institution}</p>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                      <span>{item.total_papers ?? 0} {t("candidate.papers")}</span>
                      {mode === "favorites" && (item.new_papers ?? 0) > 0 && (
                        <span className="font-medium text-emerald-700 dark:text-emerald-400">+{item.new_papers} {t("tracking.papers")}</span>
                      )}
                      {mode === "favorites" && (item.new_citations ?? 0) > 0 && (
                        <span className="font-medium text-emerald-700 dark:text-emerald-400">+{item.new_citations?.toLocaleString()} {t("tracking.citations")}</span>
                      )}
                    </div>
                    {mode === "favorites" && (
                      <>
                        {(item.research_changes?.length ?? 0) > 0 && (
                          <div className="mt-2 rounded-md bg-violet-500/10 px-2.5 py-2 text-xs text-violet-700 dark:text-violet-300">
                            <p className="font-medium">{t("tracking.direction_changes")}</p>
                            <p className="mt-1 break-words">
                              {item.research_changes?.slice(0, 3).map((change) => change.topic).join(" · ")}
                            </p>
                          </div>
                        )}
                        <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                          {item.refresh_status === "queued" || item.refresh_status === "updating" ? (
                            <><RefreshCw className="h-3 w-3 animate-spin" />{t(`tracking.status_${item.refresh_status}`)}</>
                          ) : item.refresh_status === "failed" ? (
                            <><AlertCircle className="h-3 w-3 text-destructive" />{t("tracking.status_failed")}</>
                          ) : (
                            <><CheckCircle2 className="h-3 w-3" />{t("tracking.status_ready")}</>
                          )}
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t("tracking.last_updated")} {updateTime(item.updated_at)}
                        </p>
                        {item.refresh_status === "failed" && item.refresh_error && (
                          <p className="mt-1 break-words text-xs text-destructive">{item.refresh_error}</p>
                        )}
                      </>
                    )}
                  </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => onSelect(item.author_id, item.name)}>
                      <Eye className="h-3.5 w-3.5" />{t("tracking.view_profile")}
                    </Button>
                    {mode === "favorites" && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={actingOn === item.author_id || item.refresh_status === "queued" || item.refresh_status === "updating"}
                          onClick={() => void refresh(item)}
                        >
                          {actingOn === item.author_id
                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            : <RefreshCw className="h-3.5 w-3.5" />}
                          {t(item.refresh_status === "failed" ? "tracking.retry" : "tracking.check_now")}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={actingOn === item.author_id}
                          onClick={() => void remove(item)}
                        >
                          <X className="h-3.5 w-3.5" />{t("tracking.stop")}
                        </Button>
                      </>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </aside>
    </>
  )
}
