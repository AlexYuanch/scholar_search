import { useEffect, useState } from "react"
import { Bell, BookOpen, CheckCircle2, Heart, Loader2, LogIn, RefreshCw, X } from "lucide-react"
import { useAuth } from "@/auth"
import { getFavorites, getHistory, removeFavorite, type ScholarListItem } from "@/api"
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
  const [items, setItems] = useState<ScholarListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!mode) return
    let active = true
    void Promise.resolve().then(async () => {
      if (!active) return
      setLoading(true)
      setError("")
      try {
        const nextItems = await (mode === "history" ? getHistory() : getFavorites())
        if (active) setItems(nextItems)
      } catch (reason: unknown) {
        if (active) setError(reason instanceof Error ? reason.message : "Request failed")
      } finally {
        if (active) setLoading(false)
      }
    })
    return () => { active = false }
  }, [mode])

  if (!mode) return null

  const remove = async (item: ScholarListItem) => {
    await removeFavorite(item.author_id)
    setItems((current) => current.filter((row) => row.author_id !== item.author_id))
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
            {mode === "history" ? <BookOpen className="h-4 w-4" /> : <Heart className="h-4 w-4" />}
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
              <Card key={item.author_id} className="cursor-pointer hover:bg-muted/50" onClick={() => onSelect(item.author_id, item.name)}>
                <CardContent className="flex min-w-0 items-start justify-between gap-2 p-4">
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
                      <p className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                        {item.refresh_status === "queued" || item.refresh_status === "updating" ? (
                          <><RefreshCw className="h-3 w-3 animate-spin" />{t("tracking.updating")}</>
                        ) : (
                          <><CheckCircle2 className="h-3 w-3" />{t(item.has_updates ? "tracking.updated_at" : "tracking.current")} {updateTime(item.updated_at)}</>
                        )}
                      </p>
                    )}
                  </div>
                  {mode === "favorites" && (
                    <Button className="shrink-0" variant="ghost" size="icon" onClick={(event) => {
                      event.stopPropagation()
                      void remove(item)
                    }}><X className="h-4 w-4" /></Button>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </aside>
    </>
  )
}
