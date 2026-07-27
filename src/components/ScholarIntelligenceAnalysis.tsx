import { useCallback, useEffect, useMemo, useState } from "react"
import {
  AlertCircle,
  ArrowLeftRight,
  BookOpen,
  Building2,
  CheckCircle2,
  GitCompareArrows,
  HelpCircle,
  Loader2,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  Users,
} from "lucide-react"
import {
  ApiError,
  compareScholarIntelligence,
  getScholarIntelligence,
  refreshResearchGraph,
  submitIntelligenceFeedback,
} from "@/api"
import type {
  IntelligenceComparison,
  IntelligenceConfidence,
  IntelligenceDimension,
  IntelligenceEvidence,
  IntelligenceRecommendation,
  IntelligenceTeam,
  IntelligenceWork,
  LocalizedText,
  ScholarIntelligence,
  ScholarProfile,
} from "@/types"
import type { Lang } from "@/i18n"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

type Translate = (key: string) => string

interface Props {
  profile: ScholarProfile
  t: Translate
  lang: Lang
}

function localize(text: LocalizedText | undefined, lang: Lang) {
  if (!text) return ""
  return text[lang] || text.zh || text.en
}

function formatValue(value: IntelligenceEvidence["value"], lang: Lang) {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(3)
  }
  if (typeof value === "boolean") return value ? (lang === "zh" ? "是" : "Yes") : (lang === "zh" ? "否" : "No")
  if (typeof value === "object") {
    if ("zh" in value && "en" in value) return String(value[lang] || value.zh || value.en)
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${item}`)
      .join(" · ")
  }
  return value
}

function evidenceClass(level: string) {
  if (level === "high") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
  if (level === "medium") return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
  if (level === "low") return "border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300"
  return "border-muted-foreground/20 bg-muted text-muted-foreground"
}

function evidenceLabel(confidence: IntelligenceConfidence, lang: Lang) {
  const labels: Record<IntelligenceConfidence["level"], LocalizedText> = {
    high: { zh: "依据充分", en: "Strong evidence" },
    medium: { zh: "依据一般", en: "Moderate evidence" },
    low: { zh: "依据有限", en: "Limited evidence" },
    insufficient: { zh: "依据不足", en: "Insufficient evidence" },
  }
  return localize(labels[confidence.level], lang)
}

function EvidenceBadge({
  confidence,
  lang,
}: {
  confidence: IntelligenceConfidence
  lang: Lang
}) {
  return (
    <Badge variant="outline" className={evidenceClass(confidence.level)}>
      {evidenceLabel(confidence, lang)}
    </Badge>
  )
}

const compactEvidence: Record<string, {
  label: LocalizedText
  kind: "percent" | "count"
  unit?: LocalizedText
}> = {
  field_overlap: {
    label: { zh: "方向重合", en: "Topic overlap" },
    kind: "percent",
  },
  recent_activity: {
    label: { zh: "近四年论文", en: "Recent papers" },
    kind: "count",
    unit: { zh: "篇", en: "" },
  },
  downstream: {
    label: { zh: "后续扩散", en: "Follow-on diffusion" },
    kind: "percent",
  },
  topic_overlap: {
    label: { zh: "方向重合", en: "Topic overlap" },
    kind: "percent",
  },
  temporal_overlap: {
    label: { zh: "活跃时间重合", en: "Active-period overlap" },
    kind: "percent",
  },
  recent_overlap: {
    label: { zh: "近期主题重合", en: "Recent-topic overlap" },
    kind: "percent",
  },
  direct_collaboration: {
    label: { zh: "直接合作", en: "Direct collaborations" },
    kind: "count",
    unit: { zh: "篇", en: "" },
  },
  shared_collaborators: {
    label: { zh: "共同合作者", en: "Shared collaborators" },
    kind: "count",
    unit: { zh: "位", en: "" },
  },
  capability_complementarity: {
    label: { zh: "能力互补", en: "Capability complementarity" },
    kind: "percent",
  },
  problem_similarity: {
    label: { zh: "问题重合", en: "Problem overlap" },
    kind: "percent",
  },
  method_similarity: {
    label: { zh: "方法重合", en: "Method overlap" },
    kind: "percent",
  },
}

const recommendationEvidenceCodes: Record<
  IntelligenceRecommendation["category"],
  string[]
> = {
  north_star: ["field_overlap", "recent_activity", "downstream"],
  peer: ["topic_overlap", "temporal_overlap", "recent_overlap"],
  potential_collaborator: [
    "direct_collaboration",
    "shared_collaborators",
    "capability_complementarity",
  ],
  potential_competitor: [
    "problem_similarity",
    "method_similarity",
    "direct_collaboration",
  ],
}

function recommendationFacts(item: IntelligenceRecommendation, lang: Lang) {
  const evidenceByCode = new Map(item.evidence.map((entry) => [entry.code, entry]))
  return recommendationEvidenceCodes[item.category]
    .map((code) => {
      const definition = compactEvidence[code]
      const entry = evidenceByCode.get(code)
      if (!definition || !entry || typeof entry.value !== "number") return null
      const value = definition.kind === "percent"
        ? `${Math.round(entry.value * 100)}%`
        : `${entry.value.toLocaleString()}${definition.unit?.[lang] ?? ""}`
      return `${localize(definition.label, lang)} ${value}`
    })
    .filter((value): value is string => Boolean(value))
    .slice(0, 3)
}

function representativeReason(paper: IntelligenceWork, lang: Lang) {
  const reasons: LocalizedText[] = []
  if (paper.components.field_relevance >= 0.4) {
    reasons.push({ zh: "与当前方向高度相关", en: "highly relevant to the current field" })
  }
  if (paper.components.contribution_role >= 0.9) {
    reasons.push({ zh: "作者承担主要贡献角色", en: "the scholar holds a leading authorship role" })
  }
  if (paper.components.internal_follow_on > 0) {
    reasons.push({ zh: "有后续工作继续引用", en: "later graph works continue to cite it" })
  }
  if (paper.components.topic_continuation > 0) {
    reasons.push({ zh: "后续仍持续该方向", en: "later work continues the same direction" })
  }
  if (paper.components.field_time_normalized_impact >= 0.65) {
    reasons.push({
      zh: "在同方向相近年份成果中表现较高",
      en: "it stands out among similar-field works from nearby years",
    })
  }
  const selected = reasons.slice(0, 3).map((reason) => localize(reason, lang))
  if (!selected.length) {
    return lang === "zh"
      ? "综合方向相关性、贡献角色和后续影响入选。"
      : "Selected from its combined field relevance, contribution role, and follow-on influence."
  }
  return lang === "zh"
    ? `${selected.join("；")}。`
    : `${selected.join("; ")}.`
}

function qualitativeIndex(value: number | null, lang: Lang) {
  if (value === null) return lang === "zh" ? "依据不足" : "Insufficient"
  if (value >= 70) return lang === "zh" ? "较强" : "Stronger"
  if (value >= 48) return lang === "zh" ? "一般" : "Moderate"
  return lang === "zh" ? "有限" : "Limited"
}

function EvidenceList({
  evidence,
  intelligence,
  lang,
}: {
  evidence: IntelligenceEvidence[]
  intelligence: ScholarIntelligence
  lang: Lang
}) {
  const papers = useMemo(
    () => new Map(intelligence.representative_works.map((paper) => [paper.id, paper])),
    [intelligence.representative_works],
  )
  if (!evidence.length) {
    return (
      <p className="text-xs text-muted-foreground">
        {lang === "zh" ? "当前没有足够的结构化依据。" : "No sufficient structured evidence is available."}
      </p>
    )
  }
  return (
    <div className="space-y-2">
      {evidence.map((item) => {
        const linkedPapers = item.paper_ids.map((id) => papers.get(id)).filter(Boolean)
        return (
          <div key={`${item.code}-${JSON.stringify(item.value)}`} className="rounded-md border bg-background/60 px-3 py-2">
            <div className="flex flex-wrap items-start justify-between gap-2 text-xs">
              <span className="text-muted-foreground">{localize(item.label, lang)}</span>
              <span className="font-medium tabular-nums">{formatValue(item.value, lang)}</span>
            </div>
            {linkedPapers.length > 0 && (
              <div className="mt-2 space-y-1 border-t pt-2">
                {linkedPapers.map((paper) => paper && (
                  <a
                    key={paper.id}
                    href={paper.source_id}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block break-words text-xs text-primary hover:underline"
                  >
                    {paper.title} ({paper.year || "—"})
                  </a>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function FeedbackButtons({
  itemKey,
  selected,
  disabled,
  onSelect,
  lang,
}: {
  itemKey: string
  selected?: "helpful" | "inaccurate"
  disabled: boolean
  onSelect: (itemKey: string, verdict: "helpful" | "inaccurate") => void
  lang: Lang
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-t pt-3">
      <span className="mr-1 text-xs text-muted-foreground">
        {lang === "zh" ? "这个判断：" : "This assessment:"}
      </span>
      <Button
        type="button"
        variant={selected === "helpful" ? "default" : "outline"}
        size="sm"
        className="h-7 gap-1 text-xs"
        disabled={disabled}
        onClick={() => onSelect(itemKey, "helpful")}
      >
        <ThumbsUp className="h-3 w-3" />
        {lang === "zh" ? "有帮助" : "Helpful"}
      </Button>
      <Button
        type="button"
        variant={selected === "inaccurate" ? "destructive" : "outline"}
        size="sm"
        className="h-7 gap-1 text-xs"
        disabled={disabled}
        onClick={() => onSelect(itemKey, "inaccurate")}
      >
        <ThumbsDown className="h-3 w-3" />
        {lang === "zh" ? "不准确" : "Inaccurate"}
      </Button>
      {selected && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}
    </div>
  )
}

function DimensionCard({
  dimension,
  intelligence,
  feedback,
  feedbackBusy,
  onFeedback,
  lang,
}: {
  dimension: IntelligenceDimension
  intelligence: ScholarIntelligence
  feedback?: "helpful" | "inaccurate"
  feedbackBusy: boolean
  onFeedback: (key: string, verdict: "helpful" | "inaccurate") => void
  lang: Lang
}) {
  const titles: Record<IntelligenceDimension["key"], LocalizedText> = {
    academic_quality: { zh: "成果表现", en: "Research output" },
    continuity: { zh: "方向延续", en: "Topic continuity" },
    impact: { zh: "研究影响", en: "Research influence" },
    topic_style: { zh: "选题特征", en: "Topic profile" },
  }
  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle className="text-base">{localize(titles[dimension.key], lang)}</CardTitle>
          <EvidenceBadge confidence={dimension.confidence} lang={lang} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className={`text-sm leading-relaxed ${dimension.status === "insufficient" ? "font-medium text-muted-foreground" : ""}`}>
          {localize(dimension.conclusion, lang)}
        </p>
        <details className="group border-t pt-3">
          <summary className="cursor-pointer list-none text-xs font-medium text-primary hover:underline">
            {lang === "zh" ? "查看依据" : "View evidence"}
          </summary>
          <div className="mt-3 space-y-4">
            {dimension.index !== null && (
              <p className="text-xs text-muted-foreground">
                {lang === "zh" ? "当前图谱相对指数" : "Current graph-relative index"}:{" "}
                <span className="font-semibold text-foreground">{dimension.index.toFixed(1)}</span>/100
              </p>
            )}
            {dimension.axes?.length ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {dimension.axes.map((axis) => (
                  <div key={axis.key} className="rounded-md border p-3">
                    <p className="text-xs text-muted-foreground">{localize(axis.label, lang)}</p>
                    <p className="mt-1 text-sm font-medium">{localize(axis.value, lang)}</p>
                  </div>
                ))}
              </div>
            ) : null}
            <EvidenceList evidence={dimension.evidence} intelligence={intelligence} lang={lang} />
            {dimension.limitations.length > 0 && (
              <p className="text-xs leading-relaxed text-muted-foreground">
                {localize(dimension.limitations[0], lang)}
              </p>
            )}
            <FeedbackButtons
              itemKey={dimension.key}
              selected={feedback}
              disabled={feedbackBusy}
              onSelect={onFeedback}
              lang={lang}
            />
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

function RecommendationCard({
  item,
  intelligence,
  feedback,
  feedbackBusy,
  comparing,
  onFeedback,
  onCompare,
  lang,
}: {
  item: IntelligenceRecommendation
  intelligence: ScholarIntelligence
  feedback?: "helpful" | "inaccurate"
  feedbackBusy: boolean
  comparing: boolean
  onFeedback: (key: string, verdict: "helpful" | "inaccurate") => void
  onCompare: (authorId: string, mode: "scholar" | "team") => void
  lang: Lang
}) {
  const itemKey = `${item.category}|${item.author_id}`
  const facts = recommendationFacts(item, lang)
  return (
    <Card className="min-w-0">
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="min-w-0">
          <a
            href={item.author_id}
            target="_blank"
            rel="noopener noreferrer"
            className="break-words font-semibold text-primary hover:underline"
          >
            {item.name}
          </a>
          <p className="mt-1 break-words text-xs text-muted-foreground">
            {item.institution || (lang === "zh" ? "暂无机构依据" : "No affiliation evidence")}
          </p>
        </div>
        <p className="text-sm leading-relaxed">{localize(item.explanation, lang)}</p>
        {facts.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {facts.map((fact) => (
              <Badge key={fact} variant="secondary" className="font-normal">
                {fact}
              </Badge>
            ))}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1 text-xs"
            disabled={comparing}
            onClick={() => onCompare(item.author_id, "scholar")}
          >
            {comparing ? <Loader2 className="h-3 w-3 animate-spin" /> : <ArrowLeftRight className="h-3 w-3" />}
            {lang === "zh" ? "学者比较" : "Compare scholars"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1 text-xs"
            disabled={comparing}
            onClick={() => onCompare(item.author_id, "team")}
          >
            <Building2 className="h-3 w-3" />
            {lang === "zh" ? "团队对比" : "Compare teams"}
          </Button>
        </div>
        <details className="group border-t pt-3">
          <summary className="cursor-pointer list-none text-xs font-medium text-primary hover:underline">
            {lang === "zh" ? "查看依据" : "View evidence"}
          </summary>
          <div className="mt-3 space-y-4">
            <EvidenceBadge confidence={item.confidence} lang={lang} />
            <EvidenceList evidence={item.evidence} intelligence={intelligence} lang={lang} />
            {item.limitations.length > 0 && (
              <p className="text-xs leading-relaxed text-muted-foreground">
                {localize(item.limitations[0], lang)}
              </p>
            )}
            <FeedbackButtons
              itemKey={itemKey}
              selected={feedback}
              disabled={feedbackBusy}
              onSelect={onFeedback}
              lang={lang}
            />
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

function ComparisonCard({
  comparison,
  lang,
  onClose,
}: {
  comparison: IntelligenceComparison
  lang: Lang
  onClose: () => void
}) {
  const leftName = comparison.left?.name || (lang === "zh" ? "左侧" : "Left")
  const rightName = comparison.right?.name || (lang === "zh" ? "右侧" : "Right")
  const dimensionLabels: Record<string, LocalizedText> = {
    academic_quality: { zh: "成果表现", en: "Research output" },
    continuity: { zh: "方向延续", en: "Topic continuity" },
    impact: { zh: "研究影响", en: "Research influence" },
    covered_members: { zh: "收录作者", en: "Covered scholars" },
    covered_works: { zh: "收录论文", en: "Covered papers" },
    active_years: { zh: "活跃年份", en: "Active years" },
    field_overlap: { zh: "方向覆盖", en: "Field coverage" },
  }
  const displayComparisonValue = (
    value: number | {
      index: number | null
      confidence: IntelligenceConfidence
      evidence: IntelligenceEvidence[]
    },
    key: string,
  ) => {
    if (typeof value !== "number") return qualitativeIndex(value.index, lang)
    if (key === "field_overlap") return `${Math.round(value * 100)}%`
    return value.toLocaleString()
  }
  return (
    <Card className="border-primary/30 bg-primary/[0.025]">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <GitCompareArrows className="h-4 w-4 text-primary" />
              {comparison.mode === "team"
                ? (lang === "zh" ? "团队对比" : "Team comparison")
                : (lang === "zh" ? "学者对比" : "Scholar comparison")}
            </CardTitle>
            <CardDescription className="mt-1">
              {leftName} ↔ {rightName}
            </CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {lang === "zh" ? "关闭" : "Close"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {comparison.status === "insufficient" ? (
          <div className="flex items-start gap-2 rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            <HelpCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {localize(comparison.conclusion, lang)}
          </div>
        ) : (
          <>
            <div className="space-y-2">
              {comparison.dimensions?.map((dimension) => {
                return (
                  <div key={dimension.key} className="grid gap-2 rounded-md border bg-background p-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
                    <p className="font-semibold">
                      {displayComparisonValue(dimension.left, dimension.key)}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {localize(dimension.label || dimensionLabels[dimension.key], lang)
                        || dimension.key.replaceAll("_", " ")}
                    </p>
                    <p className="text-right font-semibold">
                      {displayComparisonValue(dimension.right, dimension.key)}
                    </p>
                    {dimension.conclusion && (
                      <p className="text-xs text-muted-foreground sm:col-span-3">
                        {comparison.mode === "scholar"
                          ? (
                              lang === "zh"
                                ? "差异只用于理解研究轨迹，不代表绝对优劣。"
                                : "Differences describe research trajectories, not absolute superiority."
                            )
                          : localize(dimension.conclusion, lang)}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
            <p className="text-sm leading-relaxed">
              {comparison.mode === "scholar"
                ? (
                    lang === "zh"
                      ? "对比使用同一数据口径，结果用于理解差异，不表示因果或绝对优劣。"
                      : "Both sides use the same data scope; the comparison describes differences without implying causality or absolute superiority."
                  )
                : localize(comparison.conclusion, lang)}
            </p>
          </>
        )}
        {comparison.limitations?.length ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {localize(comparison.limitations[0], lang)}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function TeamCard({ team, lang }: { team: IntelligenceTeam; lang: Lang }) {
  return (
    <Card className="min-w-0">
      <CardContent className="space-y-3 p-4">
        <div className="min-w-0">
          <h4 className="break-words font-semibold">{team.name}</h4>
          <p className="mt-1 text-xs text-muted-foreground">
            {lang === "zh"
              ? `当前收录 ${team.member_count} 位相关作者、${team.covered_work_count} 篇论文`
              : `${team.member_count} related scholars and ${team.covered_work_count} papers currently covered`}
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {team.topics.slice(0, 5).map((topic) => (
            <Badge key={topic.name} variant="secondary" className="font-normal">
              {topic.name} · {topic.works_count}
            </Badge>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {lang === "zh" ? "活跃年份" : "Active years"}: {team.active_years}
        </p>
      </CardContent>
    </Card>
  )
}

export default function ScholarIntelligenceAnalysis({ profile, lang }: Props) {
  const [intelligence, setIntelligence] = useState<ScholarIntelligence | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [feedback, setFeedback] = useState<Record<string, "helpful" | "inaccurate">>({})
  const [feedbackBusy, setFeedbackBusy] = useState("")
  const [comparison, setComparison] = useState<IntelligenceComparison | null>(null)
  const [comparisonBusy, setComparisonBusy] = useState("")

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError("")
    try {
      setIntelligence(await getScholarIntelligence(profile.authorId, signal))
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return
      setError(
        reason instanceof ApiError
          ? reason.message
          : (lang === "zh" ? "研究洞察加载失败" : "Could not load research insights"),
      )
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [lang, profile.authorId])

  useEffect(() => {
    const controller = new AbortController()
    void getScholarIntelligence(profile.authorId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setIntelligence(result)
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return
        if (!controller.signal.aborted) {
          setError(
            reason instanceof ApiError
              ? reason.message
              : (lang === "zh" ? "研究洞察加载失败" : "Could not load research insights"),
          )
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [lang, profile.authorId])

  const handleFeedback = useCallback(async (
    itemKey: string,
    verdict: "helpful" | "inaccurate",
  ) => {
    if (!intelligence) return
    setFeedbackBusy(itemKey)
    const separator = itemKey.indexOf("|")
    const analysisKey = separator >= 0 ? itemKey.slice(0, separator) : itemKey
    const candidateAuthorId = separator >= 0 ? itemKey.slice(separator + 1) : undefined
    try {
      await submitIntelligenceFeedback({
        targetAuthorId: profile.authorId,
        candidateAuthorId,
        analysisKey,
        verdict,
        analysisVersion: intelligence.analysis_version,
        context: {
          graph_version: intelligence.generated_from_graph_version,
        },
      })
      setFeedback((current) => ({ ...current, [itemKey]: verdict }))
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : (lang === "zh" ? "反馈保存失败" : "Could not save feedback"),
      )
    } finally {
      setFeedbackBusy("")
    }
  }, [intelligence, lang, profile.authorId])

  const handleGraphRetry = useCallback(async () => {
    if (intelligence?.graph_status === "failed") {
      setLoading(true)
      setError("")
      try {
        await refreshResearchGraph(profile.authorId, true)
      } catch (reason: unknown) {
        setError(
          reason instanceof Error
            ? reason.message
            : (lang === "zh" ? "图谱重建排队失败" : "Could not queue graph rebuild"),
        )
        setLoading(false)
        return
      }
    }
    await load()
  }, [intelligence?.graph_status, lang, load, profile.authorId])

  const handleCompare = useCallback(async (
    candidateAuthorId: string,
    mode: "scholar" | "team",
  ) => {
    const key = `${candidateAuthorId}:${mode}`
    setComparisonBusy(key)
    setError("")
    try {
      setComparison(await compareScholarIntelligence(
        profile.authorId,
        candidateAuthorId,
        mode,
      ))
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : (lang === "zh" ? "比较加载失败" : "Could not load comparison"),
      )
    } finally {
      setComparisonBusy("")
    }
  }, [lang, profile.authorId])

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          {lang === "zh" ? "正在整理研究洞察…" : "Preparing research insights…"}
        </CardContent>
      </Card>
    )
  }

  if (!intelligence) {
    return (
      <Card className="border-destructive/30">
        <CardContent className="space-y-4 p-6 text-sm">
          <div className="flex items-start gap-2 text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error || (lang === "zh" ? "研究洞察暂不可用" : "Research insights are unavailable")}</span>
          </div>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            {lang === "zh" ? "重试" : "Retry"}
          </Button>
        </CardContent>
      </Card>
    )
  }

  const dimensions = [
    intelligence.dimensions.academic_quality,
    intelligence.dimensions.continuity,
    intelligence.dimensions.impact,
    intelligence.dimensions.topic_style,
  ]
  const recommendationGroups: Array<{
    key: keyof ScholarIntelligence["recommendations"]
    title: LocalizedText
    description: LocalizedText
  }> = [
    {
      key: "north_stars",
      title: { zh: "参考学者", en: "Reference scholars" },
      description: { zh: "可作为当前领域的研究参照，不代表绝对排名。", en: "Useful references in the current field, not an absolute ranking." },
    },
    {
      key: "peers",
      title: { zh: "重点同行", en: "Priority peers" },
      description: { zh: "研究方向和近期研究节奏接近。", en: "Their topics and recent research cadence are close." },
    },
    {
      key: "potential_collaborators",
      title: { zh: "合作线索", en: "Collaboration leads" },
      description: { zh: "存在主题交集和可核验的合作基础。", en: "There is topic overlap and verifiable collaboration context." },
    },
    {
      key: "potential_competitors",
      title: { zh: "研究重合", en: "Research overlap" },
      description: { zh: "近期问题和方法相近，仅表示潜在项目竞争线索。", en: "Recent problems and methods are close; this is only a potential project-competition signal." },
    },
  ]
  const componentLabels: Record<string, LocalizedText> = {
    field_relevance: { zh: "领域相关度", en: "Field relevance" },
    field_time_normalized_impact: { zh: "同领域时间归一化影响", en: "Field- and time-normalized impact" },
    contribution_role: { zh: "作者贡献角色", en: "Contribution role" },
    internal_follow_on: { zh: "图谱内后续带动", en: "Follow-on work in the graph" },
    topic_continuation: { zh: "同方向后续工作", en: "Later work in the same direction" },
  }
  const coverage = intelligence.confidence.coverage
  const coverageEnd = intelligence.field.as_of_year || null
  const coverageStart = coverageEnd && coverage?.year_span
    ? coverageEnd - coverage.year_span + 1
    : null
  const coverageSummary = coverage
    ? (
        lang === "zh"
          ? `基于 ${coverage.works} 篇论文${coverageStart && coverageEnd ? `，覆盖 ${coverageStart}–${coverageEnd}` : ""}`
          : `Based on ${coverage.works} papers${coverageStart && coverageEnd ? ` from ${coverageStart}–${coverageEnd}` : ""}`
      )
    : (
        lang === "zh"
          ? "当前缺少完整的论文覆盖信息"
          : "Complete paper-coverage information is unavailable"
      )
  const overviewCounts = [
    {
      key: "north_stars",
      label: { zh: "参考学者", en: "References" },
      value: intelligence.recommendations.north_stars.length,
    },
    {
      key: "peers",
      label: { zh: "重点同行", en: "Peers" },
      value: intelligence.recommendations.peers.length,
    },
    {
      key: "potential_collaborators",
      label: { zh: "合作线索", en: "Collaboration leads" },
      value: intelligence.recommendations.potential_collaborators.length,
    },
    {
      key: "potential_competitors",
      label: { zh: "研究重合", en: "Research overlaps" },
      value: intelligence.recommendations.potential_competitors.length,
    },
  ]

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <Card className="border-primary/20">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">
                {lang === "zh" ? "结果概览" : "Overview"}
              </CardTitle>
              <CardDescription className="mt-1">{coverageSummary}</CardDescription>
            </div>
            <EvidenceBadge confidence={intelligence.confidence} lang={lang} />
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {overviewCounts.map((item) => (
              <div key={item.key} className="rounded-lg border bg-background px-3 py-3">
                <p className="text-xl font-semibold tabular-nums">{item.value}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {localize(item.label, lang)}
                </p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            {intelligence.field.topics.slice(0, 5).map((topic) => (
              <Badge key={topic.name} variant="secondary">
                {topic.name}
              </Badge>
            ))}
          </div>
          {intelligence.confidence.level === "insufficient" && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed p-3">
              <p className="text-sm font-medium">
                {lang === "zh" ? "当前数据不足：无法可靠判断。" : "Current data is insufficient for a reliable assessment."}
              </p>
              <Button variant="outline" size="sm" onClick={() => void handleGraphRetry()}>
                <RefreshCw className="h-3.5 w-3.5" />
                {intelligence.graph_status === "queued" || intelligence.graph_status === "updating"
                  ? (lang === "zh" ? "图谱更新中，稍后重试" : "Graph updating; retry later")
                  : intelligence.graph_status === "failed"
                    ? (lang === "zh" ? "失败后重建图谱" : "Rebuild failed graph")
                  : (lang === "zh" ? "重新检查图谱" : "Check graph again")}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {recommendationGroups.map((group) => {
        const rows = intelligence.recommendations[group.key]
        return (
          <section key={group.key}>
            <div className="mb-3">
              <h3 className="font-semibold">{localize(group.title, lang)}</h3>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{localize(group.description, lang)}</p>
            </div>
            {rows.length ? (
              <div className="grid gap-4 lg:grid-cols-2">
                {rows.map((item) => {
                  const itemKey = `${item.category}|${item.author_id}`
                  return (
                    <RecommendationCard
                      key={itemKey}
                      item={item}
                      intelligence={intelligence}
                      feedback={feedback[itemKey]}
                      feedbackBusy={feedbackBusy === itemKey}
                      comparing={comparisonBusy.startsWith(item.author_id)}
                      onFeedback={handleFeedback}
                      onCompare={handleCompare}
                      lang={lang}
                    />
                  )
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                {lang === "zh"
                  ? "暂无可靠结果。"
                  : "No reliable result is available."}
              </p>
            )}
          </section>
        )
      })}

      {comparison && (
        <ComparisonCard comparison={comparison} lang={lang} onClose={() => setComparison(null)} />
      )}

      <section>
        <div className="mb-3 flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          <h3 className="font-semibold">{lang === "zh" ? "核心结论" : "Key findings"}</h3>
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {dimensions.map((dimension) => (
            <DimensionCard
              key={dimension.key}
              dimension={dimension}
              intelligence={intelligence}
              feedback={feedback[dimension.key]}
              feedbackBusy={feedbackBusy === dimension.key}
              onFeedback={handleFeedback}
              lang={lang}
            />
          ))}
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{lang === "zh" ? "代表作" : "Representative works"}</CardTitle>
          <CardDescription>
            {lang === "zh"
              ? "综合方向相关性、贡献角色和后续影响选择，不按引用数单排。"
              : "Selected from field relevance, contribution role, and follow-on influence—not citation count alone."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {intelligence.representative_works.map((paper) => (
            <div key={paper.id} className="rounded-lg border p-4">
              <a
                href={paper.source_id}
                target="_blank"
                rel="noopener noreferrer"
                className="break-words text-sm font-medium text-primary hover:underline"
              >
                {paper.title}
              </a>
              <p className="mt-1 text-xs text-muted-foreground">
                {paper.year || "—"} · {paper.venue || "—"} · {paper.citations.toLocaleString()}{" "}
                {lang === "zh" ? "次当前引用" : "current citations"}
              </p>
              <p className="mt-3 text-sm leading-relaxed">
                <span className="font-medium">
                  {lang === "zh" ? "入选原因：" : "Why selected: "}
                </span>
                {representativeReason(paper, lang)}
              </p>
              <details className="group mt-3 border-t pt-3">
                <summary className="cursor-pointer list-none text-xs font-medium text-primary hover:underline">
                  {lang === "zh" ? "为什么入选" : "Why this work"}
                </summary>
                <div className="mt-3 space-y-4">
                  <EvidenceBadge confidence={paper.confidence} lang={lang} />
                  <div className="grid gap-2 text-xs sm:grid-cols-5">
                    {Object.entries(paper.components).map(([key, value]) => (
                      <div key={key} className="rounded bg-muted/50 px-2 py-1.5">
                        <p className="break-words text-muted-foreground">
                          {localize(componentLabels[key], lang) || key.replaceAll("_", " ")}
                        </p>
                        <p className="font-medium">{(value * 100).toFixed(0)}%</p>
                      </div>
                    ))}
                  </div>
                  <EvidenceList evidence={paper.evidence} intelligence={intelligence} lang={lang} />
                </div>
              </details>
            </div>
          ))}
          {!intelligence.representative_works.length && (
            <p className="text-sm text-muted-foreground">
              {lang === "zh" ? "数据不足，无法可靠选择代表作。" : "Insufficient data to select representative works reliably."}
            </p>
          )}
        </CardContent>
      </Card>

      <Separator />

      <section>
        <div className="mb-3 flex items-center gap-2">
          <Users className="h-4 w-4 text-primary" />
          <div>
            <h3 className="font-semibold">{lang === "zh" ? "团队视角" : "Team view"}</h3>
          </div>
        </div>
        {intelligence.teams.field_teams.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {intelligence.teams.field_teams.map((team) => (
              <TeamCard key={team.institution_id || team.name} team={team} lang={lang} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {lang === "zh" ? "当前缺少可聚合的机构团队数据。" : "No institution-team data can be aggregated reliably."}
          </p>
        )}
      </section>

      <details className="group rounded-lg border bg-muted/30">
        <summary className="cursor-pointer list-none px-4 py-3 text-sm font-medium">
          {lang === "zh" ? "数据说明" : "Data and methodology"}
        </summary>
        <div className="space-y-4 border-t px-4 py-4 text-xs leading-relaxed text-muted-foreground">
          <div className="flex flex-wrap items-center gap-2">
            <EvidenceBadge confidence={intelligence.confidence} lang={lang} />
            <span>
              {lang === "zh" ? "图谱版本" : "Graph version"}{" "}
              {intelligence.generated_from_graph_version}
            </span>
          </div>
          <p>{localize(intelligence.methodology.score_source, lang)}</p>
          <p>{localize(intelligence.methodology.ranking_scope, lang)}</p>
          <ul className="space-y-1">
            {intelligence.methodology.principles.map((item) => (
              <li key={item.zh}>• {localize(item, lang)}</li>
            ))}
          </ul>
          {coverage && (
            <p>
              {lang === "zh"
                ? `主题覆盖 ${Math.round(coverage.topic_coverage * 100)}%，摘要覆盖 ${Math.round(coverage.abstract_coverage * 100)}%。`
                : `Topic coverage ${Math.round(coverage.topic_coverage * 100)}%; abstract coverage ${Math.round(coverage.abstract_coverage * 100)}%.`}
            </p>
          )}
          {intelligence.limitations.map((item) => (
            <p key={item.zh}>{localize(item, lang)}</p>
          ))}
        </div>
      </details>
    </div>
  )
}
