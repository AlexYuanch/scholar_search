import { AlertTriangle, CheckCircle2, Clock3, Database, FileCheck2, ShieldCheck } from "lucide-react"
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

  const verifiedPercent = audit.collectedWorks
    ? Math.round(audit.crossrefVerified / audit.collectedWorks * 100)
    : 0
  const statusKey = `verification.status_${audit.status}`
  const StatusIcon = audit.status === "sufficient" ? CheckCircle2 : AlertTriangle
  const detail = t("verification.detail")
    .replace("{expected}", String(audit.openalexExpected))
    .replace("{fetched}", String(audit.openalexFetched))
    .replace("{merged}", String(audit.duplicateRecordsMerged))
    .replace("{conflicts}", String(audit.conflictCount))
  const failureDetail = t("verification.failed").replace("{count}", String(audit.crossrefFailed))
  const identityDetail = t("verification.identity_merged").replace(
    "{count}",
    String(profile.identityAudit?.mergedCount ?? 1),
  )
  const identityExcludedDetail = t("verification.identity_excluded").replace(
    "{count}",
    String(profile.identityAudit?.excludedWorks ?? 0),
  )
  const identityConflictDetail = t("verification.identity_conflict").replace(
    "{count}",
    String(profile.identityAudit?.largeConflictWorks ?? 0),
  )
  const updatedAt = profile.updatedAt || audit.retrievedAt
  const updatedLabel = updatedAt && !Number.isNaN(new Date(updatedAt).getTime())
    ? new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(updatedAt))
    : "—"
  const confidence = profile.evidenceReview?.summaryConfidence || "low"

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="h-4 w-4" />
              {t("verification.title")}
            </CardTitle>
            <CardDescription className="mt-1">{t("verification.description")}</CardDescription>
          </div>
          <Badge variant="outline" className="gap-1">
            <StatusIcon className="h-3.5 w-3.5" />
            {t(statusKey)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("verification.collected")}</p>
            <p className="mt-1 text-xl font-bold tabular-nums">{audit.collectedWorks}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("verification.with_doi")}</p>
            <p className="mt-1 text-xl font-bold tabular-nums">{audit.worksWithDoi}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("verification.crossref_verified")}</p>
            <p className="mt-1 text-xl font-bold tabular-nums">{audit.crossrefVerified}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{t("verification.pending")}</p>
            <p className="mt-1 text-xl font-bold tabular-nums">{audit.unverifiedWorks}</p>
          </div>
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <span>{t("verification.rate")}</span>
            <span className="tabular-nums">{verifiedPercent}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${verifiedPercent}%` }} />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <FileCheck2 className="h-4 w-4 shrink-0 text-primary" />
          <span>{t("verification.sources")}</span>
          {audit.sources.map((source) => <Badge key={source} variant="secondary">{source}</Badge>)}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex items-start gap-2 rounded-lg border p-3 text-xs text-muted-foreground">
            <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div>
              <p className="font-medium text-foreground">{t("verification.updated_at")}</p>
              <p className="mt-1">{updatedLabel}</p>
            </div>
          </div>
          <div className="flex items-start gap-2 rounded-lg border p-3 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div>
              <p className="font-medium text-foreground">{t("verification.confidence")}</p>
              <p className="mt-1">{t(`verification.confidence_${confidence}`)}</p>
            </div>
          </div>
        </div>

        {(profile.identityAudit?.mergedCount ?? 1) > 1 && (
          <p className="text-xs leading-relaxed text-primary">{identityDetail}</p>
        )}
        {(profile.identityAudit?.excludedWorks ?? 0) > 0 && (
          <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-400">{identityExcludedDetail}</p>
        )}
        {(profile.identityAudit?.largeConflictWorks ?? 0) > 0 && (
          <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-400">{identityConflictDetail}</p>
        )}

        <p className="text-xs leading-relaxed text-muted-foreground">
          {detail}
        </p>
        {audit.crossrefLimited && (
          <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-400">
            {t("verification.limited")}
          </p>
        )}
        {audit.crossrefFailed > 0 && (
          <p className="text-xs leading-relaxed text-amber-700 dark:text-amber-400">
            {failureDetail}
          </p>
        )}
        <div className="rounded-lg border bg-muted/40 p-4">
          <p className="text-xs font-medium">{t("verification.limitations")}</p>
          <ul className="mt-2 space-y-1 text-xs leading-relaxed text-muted-foreground">
            <li>· {t("verification.limit_openalex")}</li>
            <li>· {t("verification.limit_citations")}</li>
            <li>· {t("verification.limit_identity")}</li>
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}
