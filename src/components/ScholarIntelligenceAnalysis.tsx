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
  ShieldCheck,
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
  IntelligenceDimension,
  IntelligenceEvidence,
  IntelligenceRecommendation,
  IntelligenceTeam,
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

function confidenceClass(level: string) {
  if (level === "high") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
  if (level === "medium") return "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
  if (level === "low") return "border-orange-500/30 bg-orange-500/10 text-orange-700 dark:text-orange-300"
  return "border-muted-foreground/20 bg-muted text-muted-foreground"
}

function ConfidenceBadge({
  confidence,
  lang,
}: {
  confidence: IntelligenceDimension["confidence"]
  lang: Lang
}) {
  return (
    <Badge variant="outline" className={confidenceClass(confidence.level)}>
      {lang === "zh" ? "置信度" : "Confidence"}: {localize(confidence.label, lang)}
    </Badge>
  )
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
    academic_quality: { zh: "学术质量", en: "Academic quality" },
    continuity: { zh: "研究延续性", en: "Research continuity" },
    impact: { zh: "学术影响力", en: "Academic impact" },
    topic_style: { zh: "科研选题风格", en: "Research topic style" },
  }
  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle className="text-base">{localize(titles[dimension.key], lang)}</CardTitle>
          <ConfidenceBadge confidence={dimension.confidence} lang={lang} />
        </div>
        {dimension.index !== null && (
          <CardDescription>
            {lang === "zh" ? "当前图谱相对指数" : "Current graph-relative index"}:{" "}
            <span className="font-semibold text-foreground">{dimension.index.toFixed(1)}</span>/100
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <p className={`text-sm leading-relaxed ${dimension.status === "insufficient" ? "font-medium text-muted-foreground" : ""}`}>
          {localize(dimension.conclusion, lang)}
        </p>
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
  return (
    <Card className="min-w-0">
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
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
              {item.institution || (lang === "zh" ? "暂无机构证据" : "No affiliation evidence")}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary">
              {lang === "zh" ? "相对指数" : "Relative index"} {item.index.toFixed(1)}
            </Badge>
            <ConfidenceBadge confidence={item.confidence} lang={lang} />
          </div>
        </div>
        <p className="text-sm leading-relaxed">{localize(item.explanation, lang)}</p>
        <EvidenceList evidence={item.evidence} intelligence={intelligence} lang={lang} />
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
            {lang === "zh" ? "团队比较" : "Compare teams"}
          </Button>
        </div>
        <FeedbackButtons
          itemKey={itemKey}
          selected={feedback}
          disabled={feedbackBusy}
          onSelect={onFeedback}
          lang={lang}
        />
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
    academic_quality: { zh: "学术质量", en: "Academic quality" },
    continuity: { zh: "研究延续性", en: "Research continuity" },
    impact: { zh: "学术影响力", en: "Academic impact" },
    covered_members: { zh: "本地图谱覆盖成员", en: "Locally covered members" },
    covered_works: { zh: "去重后的图谱论文", en: "Distinct graph papers" },
    active_years: { zh: "有论文的年份数", en: "Years with publications" },
    field_overlap: { zh: "目标领域覆盖", en: "Target-field coverage" },
  }
  return (
    <Card className="border-primary/30 bg-primary/[0.025]">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <GitCompareArrows className="h-4 w-4 text-primary" />
              {comparison.mode === "team"
                ? (lang === "zh" ? "团队与机构比较" : "Team and institution comparison")
                : (lang === "zh" ? "学者智能比较" : "Scholar intelligence comparison")}
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
                const left = typeof dimension.left === "number" ? dimension.left : dimension.left.index
                const right = typeof dimension.right === "number" ? dimension.right : dimension.right.index
                return (
                  <div key={dimension.key} className="grid gap-2 rounded-md border bg-background p-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
                    <p className="font-semibold tabular-nums">{left ?? "—"}</p>
                    <p className="text-xs text-muted-foreground">
                      {localize(dimension.label || dimensionLabels[dimension.key], lang)
                        || dimension.key.replaceAll("_", " ")}
                    </p>
                    <p className="text-right font-semibold tabular-nums">{right ?? "—"}</p>
                    {dimension.conclusion && (
                      <p className="text-xs text-muted-foreground sm:col-span-3">
                        {localize(dimension.conclusion, lang)}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
            <p className="text-sm leading-relaxed">{localize(comparison.conclusion, lang)}</p>
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
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h4 className="break-words font-semibold">{team.name}</h4>
            <p className="mt-1 text-xs text-muted-foreground">
              {lang === "zh"
                ? `本地图谱覆盖 ${team.member_count} 位成员、${team.covered_work_count} 篇去重论文`
                : `${team.member_count} locally covered members and ${team.covered_work_count} distinct papers`}
            </p>
          </div>
          <ConfidenceBadge confidence={team.confidence} lang={lang} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {team.topics.slice(0, 5).map((topic) => (
            <Badge key={topic.name} variant="secondary" className="font-normal">
              {topic.name} · {topic.works_count}
            </Badge>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          {lang === "zh" ? "目标领域覆盖" : "Target-field coverage"}: {(team.field_overlap * 100).toFixed(1)}% ·{" "}
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
          : (lang === "zh" ? "智能分析加载失败" : "Could not load intelligence analysis"),
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
              : (lang === "zh" ? "智能分析加载失败" : "Could not load intelligence analysis"),
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
          {lang === "zh" ? "正在从动态研究图谱计算可解释分析…" : "Computing explainable analysis from the dynamic research graph…"}
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
            <span>{error || (lang === "zh" ? "智能分析暂不可用" : "Intelligence analysis is unavailable")}</span>
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
      title: { zh: "领域北极星参照学者", en: "Field north-star reference scholars" },
      description: { zh: "综合领域相关度、代表作、持续贡献、归一化影响与近期活跃度；不是绝对“最好学者”排名。", en: "Combines field relevance, representative work, sustained contribution, normalized impact, and recent activity; not an absolute best-scholar ranking." },
    },
    {
      key: "peers",
      title: { zh: "重点同行", en: "Priority peers" },
      description: { zh: "方向、活跃年份与近期论文主题同时存在重合。", en: "Research directions, active years, and recent paper topics overlap." },
    },
    {
      key: "potential_collaborators",
      title: { zh: "潜在合作者", en: "Potential collaborators" },
      description: { zh: "要求主题交集，并有重复合作或共同合作者证据；单次合作不够。", en: "Requires topic overlap plus repeated collaboration or shared-collaborator evidence; one-off collaboration is insufficient." },
    },
    {
      key: "potential_competitors",
      title: { zh: "潜在项目竞争者", en: "Potential project competitors" },
      description: { zh: "必须同时满足近期问题、方法、时间重合和低合作门槛；仅表示潜在线索。", en: "Requires simultaneous recent problem, method, time, and low-collaboration thresholds; it is only a potential signal." },
    },
  ]
  const componentLabels: Record<string, LocalizedText> = {
    field_relevance: { zh: "领域相关度", en: "Field relevance" },
    field_time_normalized_impact: { zh: "同领域时间归一化影响", en: "Field- and time-normalized impact" },
    contribution_role: { zh: "作者贡献角色", en: "Contribution role" },
    internal_follow_on: { zh: "图谱内后续带动", en: "Follow-on work in the graph" },
    topic_continuation: { zh: "同方向后续工作", en: "Later work in the same direction" },
  }

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
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldCheck className="h-4 w-4 text-primary" />
                {lang === "zh" ? "可解释分析口径" : "Explainable analysis scope"}
              </CardTitle>
              <CardDescription className="mt-1">
                {localize(intelligence.methodology.score_source, lang)}
              </CardDescription>
            </div>
            <div className="flex flex-wrap gap-2">
              <ConfidenceBadge confidence={intelligence.confidence} lang={lang} />
              <Badge variant="outline">
                {lang === "zh" ? "图谱版本" : "Graph version"} {intelligence.generated_from_graph_version}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {intelligence.field.topics.map((topic) => (
              <Badge key={topic.name} variant="secondary">
                {topic.name} · {topic.works_count}
              </Badge>
            ))}
          </div>
          <ul className="space-y-1 text-xs leading-relaxed text-muted-foreground">
            {intelligence.methodology.principles.map((item) => (
              <li key={item.zh}>• {localize(item, lang)}</li>
            ))}
          </ul>
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

      <section>
        <div className="mb-3 flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-primary" />
          <h3 className="font-semibold">{lang === "zh" ? "学者分析" : "Scholar analysis"}</h3>
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
              ? "综合领域相关度、时间归一化影响、贡献角色、后续扩散与方向延续；不按引用数单排。"
              : "Combines field relevance, time-normalized impact, contribution role, follow-on diffusion, and topic continuation; not citation-only sorting."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {intelligence.representative_works.map((paper) => (
            <div key={paper.id} className="rounded-lg border p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <a href={paper.source_id} target="_blank" rel="noopener noreferrer" className="min-w-0 break-words text-sm font-medium text-primary hover:underline">
                  {paper.title}
                </a>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{lang === "zh" ? "综合" : "Composite"} {paper.index.toFixed(1)}</Badge>
                  <ConfidenceBadge confidence={paper.confidence} lang={lang} />
                </div>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {paper.year || "—"} · {paper.venue || "—"} · {paper.citations.toLocaleString()}{" "}
                {lang === "zh" ? "次当前引用" : "current citations"}
              </p>
              <div className="mt-3 grid gap-2 text-xs sm:grid-cols-5">
                {Object.entries(paper.components).map(([key, value]) => (
                  <div key={key} className="rounded bg-muted/50 px-2 py-1.5">
                    <p className="break-words text-muted-foreground">
                      {localize(componentLabels[key], lang) || key.replaceAll("_", " ")}
                    </p>
                    <p className="font-medium">{(value * 100).toFixed(0)}%</p>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {!intelligence.representative_works.length && (
            <p className="text-sm text-muted-foreground">
              {lang === "zh" ? "数据不足，无法可靠选择代表作。" : "Insufficient data to select representative works reliably."}
            </p>
          )}
        </CardContent>
      </Card>

      {comparison && (
        <ComparisonCard comparison={comparison} lang={lang} onClose={() => setComparison(null)} />
      )}

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
              <div className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
                {lang === "zh"
                  ? "当前图谱没有满足该类别全部门槛的对象，未强行给出推荐。"
                  : "No scholar meets every threshold for this category; no recommendation is forced."}
              </div>
            )}
          </section>
        )
      })}

      <Separator />

      <section>
        <div className="mb-3 flex items-center gap-2">
          <Users className="h-4 w-4 text-primary" />
          <div>
            <h3 className="font-semibold">{lang === "zh" ? "团队与机构视角" : "Team and institution view"}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {localize(intelligence.teams.limitations[0], lang)}
            </p>
          </div>
        </div>
        {intelligence.teams.field_teams.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {intelligence.teams.field_teams.map((team) => (
              <TeamCard key={team.institution_id || team.name} team={team} lang={lang} />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">
            {lang === "zh" ? "当前缺少可聚合的机构团队数据。" : "No institution-team data can be aggregated reliably."}
          </div>
        )}
      </section>

      <p className="rounded-lg bg-muted/60 p-4 text-xs leading-relaxed text-muted-foreground">
        {localize(intelligence.limitations[0], lang)} {localize(intelligence.limitations[1], lang)}
      </p>
    </div>
  )
}
