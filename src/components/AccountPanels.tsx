import { useEffect, useState } from "react"
import { BookOpen, Heart, Loader2, LogIn, X } from "lucide-react"
import { useAuth } from "@/auth"
import { getFavorites, getHistory, removeFavorite, type ScholarListItem } from "@/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function AuthDialog({ open, onClose, t }: {
  open: boolean
  onClose: () => void
  t: (key: string) => string
}) {
  const { configured, signInWithEmail } = useAuth()
  const [email, setEmail] = useState("")
  const [message, setMessage] = useState("")
  const [devMagicLink, setDevMagicLink] = useState("")
  const [loading, setLoading] = useState(false)
  if (!open) return null

  const submit = async () => {
    setLoading(true)
    setMessage("")
    setDevMagicLink("")
    try {
      const result = await signInWithEmail(email.trim())
      setMessage(t("auth.email_sent"))
      setDevMagicLink(result.devMagicLink ?? "")
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : t("auth.failed"))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base"><LogIn className="h-4 w-4" />{t("auth.title")}</CardTitle>
          <Button variant="ghost" size="icon" onClick={onClose}><X className="h-4 w-4" /></Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{t("auth.magic_link_desc")}</p>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder={t("auth.email_placeholder")}
            className="h-10 w-full rounded-md border bg-background px-3 text-sm"
          />
          <Button className="w-full" disabled={!configured || !email.trim() || loading} onClick={submit}>
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}{t("auth.send_link")}
          </Button>
          {!configured && <p className="text-xs text-destructive">{t("auth.not_configured")}</p>}
          {message && <p className="text-sm text-muted-foreground">{message}</p>}
          {devMagicLink && (
            <a className="block break-all text-xs text-primary underline" href={devMagicLink}>
              {devMagicLink}
            </a>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export function AccountPanel({ mode, onClose, onSelect, t }: {
  mode: "history" | "favorites" | null
  onClose: () => void
  onSelect: (authorId: string) => void
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
    <div className="fixed inset-0 z-40 bg-black/20" onClick={onClose}>
      <aside className="ml-auto h-full w-full max-w-md overflow-y-auto border-l bg-background p-5 shadow-xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 font-semibold">
            {mode === "history" ? <BookOpen className="h-4 w-4" /> : <Heart className="h-4 w-4" />}
            {t(mode === "history" ? "account.history" : "account.favorites")}
          </h2>
          <Button variant="ghost" size="icon" onClick={onClose}><X className="h-4 w-4" /></Button>
        </div>
        {loading && <Loader2 className="mx-auto mt-12 h-6 w-6 animate-spin" />}
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!loading && !items.length && <p className="text-sm text-muted-foreground">{t("account.empty")}</p>}
        <div className="space-y-2">
          {items.map((item) => (
            <Card key={item.author_id} className="cursor-pointer hover:bg-muted/50" onClick={() => onSelect(item.author_id)}>
              <CardContent className="flex items-start justify-between p-4">
                <div>
                  <p className="text-sm font-medium">{item.name}</p>
                  <p className="text-xs text-muted-foreground">{item.institution}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{item.total_papers ?? 0} {t("candidate.papers")}</p>
                </div>
                {mode === "favorites" && (
                  <Button variant="ghost" size="icon" onClick={(event) => {
                    event.stopPropagation()
                    void remove(item)
                  }}><X className="h-4 w-4" /></Button>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      </aside>
    </div>
  )
}
