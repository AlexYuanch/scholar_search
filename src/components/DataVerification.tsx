import { AlertTriangle, Clock3, Database, ShieldCheck } from "lucide-react"
import type { ScholarProfile } from "@/types"
import type { Lang } from "@/i18n"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function DataVerification({ profile, t, lang }: {
  profile: ScholarProfile
  t: (key: string) => string
  lang: Lang
}) {
  const audit = profile.dataAudit
  if (!audit) return null

  const updatedAt = profile.updatedAt || audit.retrievedAt
  const updatedLabel = updatedAt && !Number.isNaN(new Date(updatedAt).getTime())
    ? new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(updatedAt))
    : "—"
  const confidence = profile.evidenceReview?.summaryConfidence || "low"
  const excludedWorks = profile.identityAudit?.excludedWorks ?? 0
  const hasAttention = audit.status !== "sufficient" || excludedWorks > 0 || audit.crossrefFailed > 0
  const detail = t("verification.detail")
    .replace("{expected}", String(audit.openalexExpected))
    .replace("{fetched}", String(audit.openalexFetched))
    .replace("{merged}", String(audit.duplicateRecordsMerged))
    .replace("{conflicts}", String(audit.conflictCount))

  return (
    <Card className="bg-muted/15">
      <CardHeader className="pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="h-4 w-4" />
              {t("verification.title")}
            </CardTitle>
            <CardDescription className="mt-1">{t("verification.description")}</CardDescription>
          </div>
          <Badge variant="outline" className="gap-1">
            {hasAttention
              ? <AlertTriangle className="h-3.5 w-3.5" />
              : <ShieldCheck className="h-3.5 w-3.5" />
            }
            {t(`verification.status_${hasAttention ? "partial" : "sufficient"}`)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-background/80 p-3">
            <p className="text-xs text-muted-foreground">{t("verification.collected")}</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">
              {profile.totalPapers} {t("candidate.papers")}
            </p>
          </div>
          <div className="rounded-lg bg-background/80 p-3">
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <Clock3 className="h-3.5 w-3.5" />
              {t("verification.updated_at")}
            </p>
            <p className="mt-1 text-sm font-medium">{updatedLabel}</p>
          </div>
          <div className="rounded-lg bg-background/80 p-3">
            <p className="text-xs text-muted-foreground">{t("verification.sources")}</p>
            <div className="mt-2 flex flex-wrap gap-1">
              {audit.sources.map((source) => <Badge key={source} variant="secondary">{source}</Badge>)}
            </div>
          </div>
        </div>

        {excludedWorks > 0 && (
          <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300">
            {t("verification.identity_excluded").replace("{count}", String(excludedWorks))}
          </p>
        )}

        <details className="group rounded-lg border bg-background/60">
          <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium">
            {t("verification.more")}
          </summary>
          <div className="space-y-3 border-t px-4 py-3 text-xs leading-relaxed text-muted-foreground">
            <p>{detail}</p>
            <p>
              {t("verification.confidence")}: {t(`verification.confidence_${confidence}`)}
            </p>
            {audit.crossrefLimited && <p>{t("verification.limited")}</p>}
            {audit.crossrefFailed > 0 && (
              <p>{t("verification.failed").replace("{count}", String(audit.crossrefFailed))}</p>
            )}
            <ul className="space-y-1">
              <li>· {t("verification.limit_openalex")}</li>
              <li>· {t("verification.limit_citations")}</li>
              <li>· {t("verification.limit_identity")}</li>
            </ul>
          </div>
        </details>
      </CardContent>
    </Card>
  )
}
