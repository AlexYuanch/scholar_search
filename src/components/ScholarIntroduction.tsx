import type { ReactNode } from "react"
import { ExternalLink } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { Lang } from "@/i18n"
import type { ScholarProfile } from "@/types"

type Translate = (key: string) => string

function fill(template: string, values: Record<string, string | number>) {
  return Object.entries(values).reduce(
    (text, [key, value]) => text.replaceAll(`{${key}}`, String(value)),
    template,
  )
}

function list(values: string[], lang: Lang) {
  return values.join(lang === "zh" ? "、" : ", ")
}

function evidenceId(profile: ScholarProfile, type: ScholarProfile["profileEvidence"][number]["type"]) {
  return profile.profileEvidence.find((item) => item.type === type)?.id
}

function citation(id?: string) {
  return id ? ` [${id}]` : ""
}

function localizedIntroduction(profile: ScholarProfile, lang: Lang, t: Translate) {
  const agentSummary = profile.profileSummaryI18n?.[lang]?.trim()
  if (agentSummary) {
    return agentSummary
      .split(/\n+/)
      .map((paragraph) => paragraph.trim())
      .filter(Boolean)
  }

  const employment = profile.affiliationEvidence?.verifiedEmployment
  const firstSentence = employment
    ? fill(t("intro.verified_employment"), {
        name: profile.name,
        details: [employment.role, employment.unit, employment.institution]
          .filter(Boolean)
          .join(lang === "zh" ? "，" : ", "),
      })
    : fill(t("intro.publication_profile_only"), { name: profile.name })

  const numberFormat = new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en-US")
  const paragraphs = [
    firstSentence,
    fill(t("intro.metrics"), {
      papers: numberFormat.format(profile.totalPapers),
      citations: numberFormat.format(profile.totalCitations),
      hindex: numberFormat.format(profile.hIndex),
      citation: citation(evidenceId(profile, "metric")),
    }),
  ]
  if (profile.topics.length) {
    paragraphs.push(fill(t("intro.research"), {
      topics: list(profile.topics.slice(0, 5), lang),
      citation: citation(evidenceId(profile, "topic")),
    }))
  }
  const representative = (
    profile.representativePapers.length
      ? profile.representativePapers
      : profile.topCitedPapers
  ).slice(0, 2)
  if (representative.length) {
    const paperEvidence = profile.profileEvidence.filter((item) => item.type === "paper")
    paragraphs.push(fill(t("intro.representative"), {
      papers: list(
        representative.map((paper) => `“${paper.title}” (${paper.year || "—"})`),
        lang,
      ),
      citation: paperEvidence.slice(0, 2).map((item) => `[${item.id}]`).join(""),
    }))
  }
  if (profile.coauthors.length) {
    paragraphs.push(fill(t("intro.collaboration"), {
      coauthors: list(
        profile.coauthors.slice(0, 3).map((item) => `${item.name} (${item.papers})`),
        lang,
      ),
      citation: citation(evidenceId(profile, "coauthor")),
    }))
  }
  return paragraphs
}

function localizedEvidence(
  profile: ScholarProfile,
  item: ScholarProfile["profileEvidence"][number],
  paperIndex: number,
  lang: Lang,
  t: Translate,
) {
  const numberFormat = new Intl.NumberFormat(lang === "zh" ? "zh-CN" : "en-US")
  if (item.type === "metric") {
    return fill(t("evidence.metric"), {
      papers: numberFormat.format(profile.totalPapers),
      citations: numberFormat.format(profile.totalCitations),
      hindex: numberFormat.format(profile.hIndex),
      verified: numberFormat.format(profile.dataAudit?.crossrefVerified ?? 0),
    })
  }
  if (item.type === "topic") {
    return fill(t("evidence.topic"), {
      topics: list(profile.topics.slice(0, 5), lang),
    })
  }
  if (item.type === "paper") {
    const papers = profile.representativePapers.length
      ? profile.representativePapers
      : profile.topCitedPapers
    const paper = papers.find((candidate) => candidate.id === item.url) || papers[paperIndex]
    if (paper) {
      return fill(t("evidence.paper"), {
        title: paper.title,
        year: paper.year || "—",
        citations: numberFormat.format(paper.citations),
      })
    }
  }
  if (item.type === "coauthor") {
    return fill(t("evidence.coauthor"), {
      coauthors: list(
        profile.coauthors.slice(0, 3).map((coauthor) =>
          `${coauthor.name} (${numberFormat.format(coauthor.papers)})`
        ),
        lang,
      ),
    })
  }
  return t("evidence.unavailable")
}

function IdentityField({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-words text-sm">{children}</dd>
    </div>
  )
}

export default function ScholarIntroduction({
  profile,
  lang,
  t,
}: {
  profile: ScholarProfile
  lang: Lang
  t: Translate
}) {
  const affiliationEvidence = profile.affiliationEvidence
  const employment = affiliationEvidence?.verifiedEmployment
  const education = affiliationEvidence?.verifiedEducation || []
  const paragraphs = localizedIntroduction(profile, lang, t)
  const paperEvidenceIndexById = new Map(
    profile.profileEvidence
      .filter((item) => item.type === "paper")
      .map((item, index) => [item.id, index]),
  )

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("section.profile_summary")}</CardTitle>
        <CardDescription>{t("section.profile_summary_desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2 text-sm leading-relaxed text-muted-foreground">
          {paragraphs.length
            ? paragraphs.map((paragraph, index) => <p key={`${paragraph}-${index}`}>{paragraph}</p>)
            : <p>{t("section.summary_empty")}</p>}
        </div>

        <dl className="grid gap-3 sm:grid-cols-2">
          {employment && (
            <IdentityField label={t("identity.verified_employment")}>
              <p>
                {[employment.role, employment.unit, employment.institution]
                  .filter(Boolean)
                  .join(lang === "zh" ? "，" : ", ")}
              </p>
              {employment.sourceUrl ? (
                <a
                  href={employment.sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  {employment.sourceLabel}<ExternalLink className="h-3 w-3" />
                </a>
              ) : (
                <p className="mt-1 text-xs text-muted-foreground">{employment.sourceLabel}</p>
              )}
            </IdentityField>
          )}
          {education.length > 0 && (
            <IdentityField label={t("identity.verified_education")}>
              <ul className="space-y-1">
                {education.map((item, index) => (
                  <li key={`${item.institution}-${index}`}>
                    {[item.degree, item.unit, item.institution].filter(Boolean).join(lang === "zh" ? "，" : ", ")}
                  </li>
                ))}
              </ul>
            </IdentityField>
          )}
          {profile.authorId && (
            <IdentityField label={t("identity.public_identifiers")}>
              <div className="flex flex-wrap gap-2">
                {(affiliationEvidence?.sourceLinks?.length
                  ? affiliationEvidence.sourceLinks
                  : [
                      { label: "OpenAlex", url: profile.authorId },
                      ...(profile.orcid ? [{ label: "ORCID", url: profile.orcid }] : []),
                    ]
                ).map((source) => (
                  <a
                    key={`${source.label}-${source.url}`}
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    {source.label}<ExternalLink className="h-3 w-3" />
                  </a>
                ))}
              </div>
            </IdentityField>
          )}
        </dl>
        {profile.profileEvidence.length > 0 && (
          <div className="space-y-2 border-t pt-4">
            <h4 className="text-xs font-medium text-muted-foreground">{t("section.evidence")}</h4>
            {profile.profileEvidence.map((item) => {
              const currentPaperIndex = paperEvidenceIndexById.get(item.id) ?? 0
              const text = localizedEvidence(profile, item, currentPaperIndex, lang, t)
              return (
                <div key={item.id} className="flex items-start gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline" className="h-5 shrink-0 px-1.5 text-[10px]">
                    [{item.id}]
                  </Badge>
                  {item.url ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-start gap-1 text-primary hover:underline"
                    >
                      <span>{text}</span>
                      <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
                    </a>
                  ) : (
                    <span>{text}</span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
