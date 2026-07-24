import { useEffect, useState } from "react"
import { ExternalLink, KeyRound, Loader2, ShieldCheck, Trash2, X } from "lucide-react"
import {
  deleteOpenAlexSettings,
  getOpenAlexSettings,
  saveOpenAlexSettings,
  type OpenAlexSettings,
} from "@/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function OpenAlexSettingsDialog({
  open,
  onClose,
  onChange,
  t,
}: {
  open: boolean
  onClose: () => void
  onChange: (settings: OpenAlexSettings) => void
  t: (key: string) => string
}) {
  const [settings, setSettings] = useState<OpenAlexSettings | null>(null)
  const [apiKey, setApiKey] = useState("")
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")

  useEffect(() => {
    if (!open) return
    let active = true
    void getOpenAlexSettings()
      .then((value) => {
        if (active) setSettings(value)
      })
      .catch((reason: unknown) => {
        if (active) setMessage(reason instanceof Error ? reason.message : t("api_key.load_failed"))
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => { active = false }
  }, [open, t])

  if (!open) return null

  const save = async () => {
    setLoading(true)
    setMessage("")
    try {
      const value = await saveOpenAlexSettings(apiKey)
      setSettings(value)
      setApiKey("")
      setMessage(t("api_key.saved"))
      onChange(value)
    } catch (reason: unknown) {
      setMessage(reason instanceof Error ? reason.message : t("api_key.save_failed"))
    } finally {
      setLoading(false)
    }
  }

  const remove = async () => {
    setLoading(true)
    setMessage("")
    try {
      await deleteOpenAlexSettings()
      const value: OpenAlexSettings = {
        configured: false,
        key_hint: null,
        validated_at: null,
        updated_at: null,
      }
      setSettings(value)
      onChange(value)
      setMessage(t("api_key.removed"))
    } catch (reason: unknown) {
      setMessage(reason instanceof Error ? reason.message : t("api_key.remove_failed"))
    } finally {
      setLoading(false)
    }
  }

  const remaining = settings?.usage?.daily_remaining_usd

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center overflow-y-auto bg-black/40 p-3 sm:p-6">
      <Card className="max-h-[calc(100dvh-1.5rem)] w-full max-w-lg overflow-y-auto sm:max-h-[calc(100dvh-3rem)]">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <KeyRound className="h-4 w-4" />{t("api_key.title")}
          </CardTitle>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={t("panel.close")}>
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="rounded-lg border bg-muted/40 p-3 text-sm">
            <p className="font-medium">{t("api_key.why_title")}</p>
            <p className="mt-1 text-muted-foreground">{t("api_key.why_desc")}</p>
          </div>

          <a
            href="https://openalex.org/settings/api"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium text-primary hover:bg-muted"
          >
            {t("api_key.register")}<ExternalLink className="h-3.5 w-3.5" />
          </a>

          {settings?.configured && (
            <div className="flex items-center justify-between rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 text-sm">
              <span className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-emerald-600" />
                {t("api_key.configured")} {settings.key_hint}
              </span>
              {typeof remaining === "number" && (
                <span className="text-xs text-muted-foreground">
                  {t("api_key.remaining")} ${remaining.toFixed(4)}
                </span>
              )}
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="openalex-api-key">
              {settings?.configured ? t("api_key.replace") : t("api_key.input_label")}
            </label>
            <input
              id="openalex-api-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && apiKey.trim().length >= 8 && !loading) void save()
              }}
              placeholder={t("api_key.placeholder")}
              className="h-10 w-full rounded-md border bg-background px-3 text-sm"
            />
            <p className="text-xs text-muted-foreground">{t("api_key.privacy")}</p>
          </div>

          <Button className="w-full" disabled={apiKey.trim().length < 8 || loading} onClick={save}>
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("api_key.validate_save")}
          </Button>

          {settings?.configured && (
            <Button
              variant="outline"
              className="w-full text-destructive hover:text-destructive"
              disabled={loading}
              onClick={remove}
            >
              <Trash2 className="h-4 w-4" />{t("api_key.remove")}
            </Button>
          )}

          {message && (
            <p className={`text-sm ${
              message === t("api_key.saved") || message === t("api_key.removed")
                ? "text-emerald-600"
                : "text-destructive"
            }`}>
              {message}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
