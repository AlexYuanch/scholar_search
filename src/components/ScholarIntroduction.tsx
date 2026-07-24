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

function formatYears(years: number[]) {
  if (!years.length) return ""
  if (years.length === 1) return String(years[0])
  return `${Math.min(...years)}–${Math.max(...years)}`
}

function evidenceId(profile: ScholarProfile, type: ScholarProfile["profileEvidence"][number]["type"]) {
  return profile.profileEvidence.find((item) => item.type === type)?.id
}

function citation(id?: string) {
  return id ? ` [${id}]` : ""
}

function localizedIntroduction(profile: ScholarProfile, lang: Lang, t: Translate) {
  const identity = profile.professionalIdentity
  const institution = identity?.currentInstitution || profile.institution
  const unit = identity?.researchUnit || identity?.department || identity?.laboratory
  const role = identity?.academicRole || identity?.degreeStatus
  const firstSentence = role
    ? fill(t(unit ? "intro.identity_with_role" : "intro.identity_with_role_only"), {
        name: profile.name,
        role,
        unit: unit || "",
        institution,
      })
    : unit
      ? fill(t("intro.identity_with_unit"), {
          name: profile.name,
          unit,
          institution,
        })
      : fill(t("intro.identity_basic"), {
          name: profile.name,
          institution,
        })

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
      institution: profile.professionalIdentity?.currentInstitution || profile.institution,
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
  const identity = profile.professionalIdentity
  const currentInstitution = identity?.currentInstitution || profile.institution
  const currentAffiliation = identity?.currentAffiliationStatements?.[0]
  const history = identity?.institutionHistory?.length
    ? identity.institutionHistory
    : (profile.institutions || []).map((name) => ({ name, years: [] }))
  const pastInstitutions = history.filter((item) => item.name !== currentInstitution)
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
          {currentInstitution && (
            <IdentityField label={t("identity.current_institution")}>
              {currentInstitution}
            </IdentityField>
          )}
          {currentAffiliation?.text && (
            <IdentityField label={t("identity.current_affiliation")}>
              {currentAffiliation.text}
              {currentAffiliation.years.length > 0 && (
                <span className="ml-1 text-xs text-muted-foreground">
                  ({formatYears(currentAffiliation.years)})
                </span>
              )}
            </IdentityField>
          )}
          {identity?.researchUnit && (
            <IdentityField label={t("identity.research_unit")}>
              {identity.researchUnit}
            </IdentityField>
          )}
          {identity?.department && (
            <IdentityField label={t("identity.department")}>
              {identity.department}
            </IdentityField>
          )}
          {identity?.laboratory && (
            <IdentityField label={t("identity.laboratory")}>
              {identity.laboratory}
            </IdentityField>
          )}
          {identity?.academicRole && (
            <IdentityField label={t("identity.academic_role")}>
              {identity.academicRole}
            </IdentityField>
          )}
          {identity?.degreeStatus && (
            <IdentityField label={t("identity.degree_status")}>
              {identity.degreeStatus}
            </IdentityField>
          )}
          {pastInstitutions.length > 0 && (
            <IdentityField label={t("identity.institution_history")}>
              <ul className="space-y-1">
                {pastInstitutions.map((item) => (
                  <li key={item.name}>
                    {item.name}
                    {item.years.length > 0 && (
                      <span className="ml-1 text-xs text-muted-foreground">
                        ({formatYears(item.years)})
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </IdentityField>
          )}
          {profile.authorId && (
            <IdentityField label={t("identity.public_identifiers")}>
              <div className="flex flex-wrap gap-2">
                {(identity?.sourceLinks?.length
                  ? identity.sourceLinks
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
        <p className="text-xs text-muted-foreground">{t("identity.source_note")}</p>

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
