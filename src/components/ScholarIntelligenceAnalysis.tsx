import { useCallback, useEffect, useMemo, useState } from "react"
import {
  AlertCircle,
  ArrowLeftRight,
  Building2,
  CheckCircle2,
  Compass,
  Eye,
  Heart,
  Loader2,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react"
import {
  ApiError,
  addTracking,
  compareInstitutions,
  discoverScholarField,
  getScholarIntelligence,
  getTracking,
  refreshResearchGraph,
  submitIntelligenceFeedback,
} from "@/api"
import type {
  IntelligenceComparison,
  IntelligenceEvidence,
  IntelligenceInstitution,
  IntelligenceRecommendation,
  LocalizedText,
  ScholarIntelligence,
  ScholarProfile,
} from "@/types"
import type { Lang } from "@/i18n"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"

type DiscoveryFilter = "all" | IntelligenceRecommendation["category"]

interface Props {
  profile: ScholarProfile
  lang: Lang
  onViewProfile: (authorId: string, scholarName: string) => void
  onCompare: (authorId: string) => void
  onTrackingChange?: () => void
}

const CATEGORY_ORDER: IntelligenceRecommendation["category"][] = [
  "north_star",
  "peer",
  "potential_collaborator",
  "potential_competitor",
]

const CATEGORY_LABELS: Record<IntelligenceRecommendation["category"], LocalizedText> = {
  north_star: { zh: "学习参考", en: "Research reference" },
  peer: { zh: "同行动态", en: "Peer activity" },
  potential_collaborator: { zh: "合作人选", en: "Potential collaborator" },
  potential_competitor: { zh: "选题重合", en: "Topic overlap" },
}

const FILTER_LABELS: Record<DiscoveryFilter, LocalizedText> = {
  all: { zh: "全部", en: "All" },
  ...CATEGORY_LABELS,
}

const FILTER_DESCRIPTIONS: Record<DiscoveryFilter, LocalizedText> = {
  all: {
    zh: "按用途查看：学习其研究路线、跟进同行动态、寻找合作人选，或提前核对选题重合。",
    en: "Browse by purpose: learn from research paths, follow peers, find collaborators, or check topic overlap early.",
  },
  north_star: {
    zh: "适合查看其代表成果和长期研究路线，作为研究参考；不表示“最好学者”。",
    en: "Useful for reviewing representative work and long-term research paths; this does not mean “best scholar.”",
  },
  peer: {
    zh: "研究方向和活跃时间相近，适合持续跟进近期成果。",
    en: "Similar research focus and active period; useful for following recent work.",
  },
  potential_collaborator: {
    zh: "存在研究交集或能力互补，且尚未形成稳定合作，可进一步核对合作可能。",
    en: "Research overlap or complementary strengths without an established collaboration; worth reviewing as a possible collaborator.",
  },
  potential_competitor: {
    zh: "近期研究问题和方法相近，适合提前核对选题是否重合；不代表实际竞争关系。",
    en: "Recent research questions and methods are similar; useful for checking topic overlap, not proof of competition.",
  },
}

const FACT_CODES: Record<IntelligenceRecommendation["category"], string[]> = {
  north_star: ["shared_topics", "recent_activity", "downstream"],
  peer: ["shared_topics", "temporal_overlap", "recent_overlap"],
  potential_collaborator: [
    "shared_topics",
    "direct_collaboration",
    "shared_collaborators",
  ],
  potential_competitor: [
    "shared_topics",
    "problem_similarity",
    "method_similarity",
  ],
}

const FACT_LABELS: Record<string, LocalizedText> = {
  shared_topics: { zh: "共同方向", en: "Shared topics" },
  field_overlap: { zh: "研究交集", en: "Research overlap" },
  recent_activity: { zh: "近四年收录", en: "Recent records" },
  downstream: { zh: "有后续研究跟进", en: "Followed by later work" },
  topic_overlap: { zh: "研究交集", en: "Research overlap" },
  temporal_overlap: { zh: "活跃时期相近", en: "Similar active period" },
  recent_overlap: { zh: "近期方向相近", en: "Similar recent focus" },
  direct_collaboration: { zh: "合作论文", en: "Shared papers" },
  shared_collaborators: { zh: "共同合作者", en: "Shared collaborators" },
  capability_complementarity: { zh: "研究能力互补", en: "Complementary capabilities" },
  problem_similarity: { zh: "研究问题相近", en: "Similar research questions" },
  method_similarity: { zh: "方法路线相近", en: "Similar methods" },
}

function localize(text: LocalizedText | undefined, lang: Lang) {
  if (!text) return ""
  return text[lang] || text.zh || text.en
}

function formatEvidence(value: IntelligenceEvidence["value"], lang: Lang) {
  if (value === null || value === undefined || value === "") return "—"
  if (typeof value === "number") {
    if (!Number.isInteger(value) && value >= 0 && value <= 1) {
      return `${Math.round(value * 100)}%`
    }
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2)
  }
  if (typeof value === "boolean") {
    return value ? (lang === "zh" ? "是" : "Yes") : (lang === "zh" ? "否" : "No")
  }
  if (typeof value === "object") {
    if ("zh" in value && "en" in value) {
      return String(value[lang] || value.zh || value.en)
    }
    return Object.entries(value).map(([key, item]) => `${key}: ${item}`).join(" · ")
  }
  return value
}

function statusLabel(status: ScholarIntelligence["discovery"]["status"], lang: Lang) {
  const labels: Record<ScholarIntelligence["discovery"]["status"], LocalizedText> = {
    never: { zh: "尚未开始", en: "Not started" },
    queued: { zh: "等待分析", en: "Waiting" },
    discovering: { zh: "寻找相关学者", en: "Finding scholars" },
    enriching: { zh: "补充资料中", en: "Adding evidence" },
    ready: { zh: "分析完成", en: "Complete" },
    partial: { zh: "已有部分结果", en: "Partial results" },
    failed: { zh: "分析失败", en: "Analysis failed" },
  }
  return localize(labels[status], lang)
}

function recommendationFacts(item: IntelligenceRecommendation, lang: Lang) {
  const evidence = new Map(item.evidence.map((row) => [row.code, row]))
  return FACT_CODES[item.category]
    .map((code) => {
      const row = evidence.get(code)
      if (!row) return null
      const value = (
        code === "recent_activity"
        && typeof row.value === "number"
        && row.value >= 300
      )
        ? "≥300"
        : formatEvidence(row.value, lang)
      return `${localize(FACT_LABELS[code], lang)} ${value}`
    })
    .filter((row): row is string => Boolean(row))
    .slice(0, 3)
}

function EvidenceList({
  evidence,
  lang,
}: {
  evidence: IntelligenceEvidence[]
  lang: Lang
}) {
  return (
    <div className="space-y-2">
      {evidence.map((row) => (
        <div
          key={`${row.code}-${JSON.stringify(row.value)}`}
          className="flex min-w-0 flex-wrap items-start justify-between gap-2 rounded-md border bg-background/70 px-3 py-2 text-xs"
        >
          <span className="min-w-0 break-words text-muted-foreground">
            {localize(row.label, lang)}
          </span>
          <span className="shrink-0 font-medium tabular-nums">
            {formatEvidence(row.value, lang)}
          </span>
        </div>
      ))}
    </div>
  )
}

function FeedbackButtons({
  itemKey,
  selected,
  busy,
  onFeedback,
  lang,
}: {
  itemKey: string
  selected?: "helpful" | "inaccurate"
  busy: boolean
  onFeedback: (itemKey: string, verdict: "helpful" | "inaccurate") => void
  lang: Lang
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-t pt-3">
      <span className="text-xs text-muted-foreground">
        {lang === "zh" ? "这个判断：" : "This assessment:"}
      </span>
      <Button
        variant={selected === "helpful" ? "default" : "outline"}
        size="sm"
        className="h-7 gap-1 text-xs"
        disabled={busy}
        onClick={() => onFeedback(itemKey, "helpful")}
      >
        <ThumbsUp className="h-3 w-3" />
        {lang === "zh" ? "有帮助" : "Helpful"}
      </Button>
      <Button
        variant={selected === "inaccurate" ? "destructive" : "outline"}
        size="sm"
        className="h-7 gap-1 text-xs"
        disabled={busy}
        onClick={() => onFeedback(itemKey, "inaccurate")}
      >
        <ThumbsDown className="h-3 w-3" />
        {lang === "zh" ? "不准确" : "Inaccurate"}
      </Button>
      {selected && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}
    </div>
  )
}

interface MergedRecommendation {
  author_id: string
  name: string
  institution?: string | null
  categories: IntelligenceRecommendation["category"][]
  byCategory: Partial<Record<IntelligenceRecommendation["category"], IntelligenceRecommendation>>
}

function strongestRecommendationCategory(
  row: MergedRecommendation,
): IntelligenceRecommendation["category"] {
  return CATEGORY_ORDER.reduce<IntelligenceRecommendation["category"] | null>(
    (strongest, category) => {
      const candidate = row.byCategory[category]
      if (!candidate) return strongest
      if (!strongest) return category
      const current = row.byCategory[strongest]
      return !current || candidate.index > current.index ? category : strongest
    },
    null,
  ) as IntelligenceRecommendation["category"]
}

function mergeRecommendations(
  intelligence: ScholarIntelligence,
): MergedRecommendation[] {
  const merged = new Map<string, MergedRecommendation>()
  const groups: Array<[IntelligenceRecommendation["category"], IntelligenceRecommendation[]]> = [
    ["north_star", intelligence.recommendations.north_stars],
    ["peer", intelligence.recommendations.peers],
    ["potential_collaborator", intelligence.recommendations.potential_collaborators],
    ["potential_competitor", intelligence.recommendations.potential_competitors],
  ]
  for (const [category, rows] of groups) {
    for (const row of rows) {
      const current = merged.get(row.author_id) || {
        author_id: row.author_id,
        name: row.name,
        institution: row.institution,
        categories: [],
        byCategory: {},
      }
      if (!current.categories.includes(category)) current.categories.push(category)
      current.byCategory[category] = row
      merged.set(row.author_id, current)
    }
  }
  return [...merged.values()].sort((left, right) => {
    const leftIndex = Math.max(...Object.values(left.byCategory).map((row) => row?.index ?? 0))
    const rightIndex = Math.max(...Object.values(right.byCategory).map((row) => row?.index ?? 0))
    return rightIndex - leftIndex || left.author_id.localeCompare(right.author_id)
  })
}

function ScholarCard({
  row,
  filter,
  tracked,
  trackingBusy,
  feedback,
  feedbackBusy,
  onViewProfile,
  onCompare,
  onTrack,
  onFeedback,
  lang,
}: {
  row: MergedRecommendation
  filter: DiscoveryFilter
  tracked: boolean
  trackingBusy: boolean
  feedback: Record<string, "helpful" | "inaccurate">
  feedbackBusy: string
  onViewProfile: (authorId: string, scholarName: string) => void
  onCompare: (authorId: string) => void
  onTrack: (authorId: string) => void
  onFeedback: (itemKey: string, verdict: "helpful" | "inaccurate") => void
  lang: Lang
}) {
  const selectedCategory = (
    filter !== "all" && row.byCategory[filter]
      ? filter
      : strongestRecommendationCategory(row)
  ) as IntelligenceRecommendation["category"]
  const selected = row.byCategory[selectedCategory] as IntelligenceRecommendation
  const facts = recommendationFacts(selected, lang)
  return (
    <Card className="min-w-0">
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h4 className="break-words font-semibold">{row.name}</h4>
              <p className="mt-1 break-words text-xs text-muted-foreground">
                {row.institution || (lang === "zh" ? "机构信息不足" : "Institution unavailable")}
              </p>
            </div>
            <div className="flex flex-wrap justify-end gap-1">
              {row.categories.map((category) => (
                <Badge key={category} variant="secondary" className="font-normal">
                  {localize(CATEGORY_LABELS[category], lang)}
                </Badge>
              ))}
            </div>
          </div>
          <p className="mt-3 text-sm leading-relaxed">
            {localize(selected.explanation, lang)}
          </p>
        </div>
        {facts.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {facts.map((fact) => (
              <span key={fact} className="rounded-md bg-muted px-2 py-1 text-xs">
                {fact}
              </span>
            ))}
          </div>
        )}
        {selectedCategory === "potential_competitor" && (
          <p className="text-xs font-medium text-amber-700 dark:text-amber-300">
            {lang === "zh"
              ? "近期问题和方法相近，建议关注对方进展；不代表实际竞争关系。"
              : "Recent questions and methods are similar; follow their progress, but do not treat this as proof of competition."}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onViewProfile(row.author_id, row.name)}
          >
            <Eye className="h-3.5 w-3.5" />
            {lang === "zh" ? "查看画像" : "View profile"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onCompare(row.author_id)}
          >
            <ArrowLeftRight className="h-3.5 w-3.5" />
            {lang === "zh" ? "加入对比" : "Compare"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={tracked || trackingBusy}
            onClick={() => onTrack(row.author_id)}
          >
            {trackingBusy
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <Heart className={`h-3.5 w-3.5 ${tracked ? "fill-current text-red-500" : ""}`} />}
            {tracked
              ? (lang === "zh" ? "追踪中" : "Tracked")
              : (lang === "zh" ? "追踪" : "Track")}
          </Button>
        </div>
        <details className="group border-t pt-3">
          <summary className="cursor-pointer list-none text-xs font-medium text-primary hover:underline">
            {lang === "zh" ? "为什么推荐" : "Why this suggestion"}
          </summary>
          <div className="mt-3 space-y-3">
            <EvidenceList evidence={selected.evidence} lang={lang} />
            {selected.limitations.map((item) => (
              <p key={item.zh} className="text-xs leading-relaxed text-muted-foreground">
                {localize(item, lang)}
              </p>
            ))}
            <FeedbackButtons
              itemKey={`${selected.category}|${selected.author_id}`}
              selected={feedback[`${selected.category}|${selected.author_id}`]}
              busy={feedbackBusy === `${selected.category}|${selected.author_id}`}
              onFeedback={onFeedback}
              lang={lang}
            />
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

function institutionSummary(
  institution: IntelligenceInstitution,
  lang: Lang,
) {
  const topicNames = institution.topics.slice(0, 2).map((topic) => topic.name)
  const topicText = topicNames.length
    ? (lang === "zh" ? topicNames.join("、") : topicNames.join(" and "))
    : (lang === "zh" ? "相关方向" : "related topics")
  if (institution.is_focus_institution) {
    return lang === "zh"
      ? `${institution.name} 是当前学者的主要关联机构，下面的数据用于和其他机构核对研究方向与合作联系。`
      : `${institution.name} is the current scholar's primary affiliation. The figures below provide a baseline for comparing topics and collaboration links.`
  }
  if (institution.analyzed_member_count === 0) {
    return lang === "zh"
      ? `${institution.name} 近四年在 ${topicText} 上有持续论文活动；当前尚无已分析的相关学者可供查看。`
      : `${institution.name} has recent publication activity in ${topicText}; no analyzed relevant scholar is currently available to view.`
  }
  if (institution.current_collaboration_count === 0) {
    return lang === "zh"
      ? `${institution.name} 近四年在 ${topicText} 上有较多论文，目前未找到与当前学者合著的论文；可查看 ${institution.analyzed_member_count} 位已分析的相关学者。`
      : `${institution.name} has published frequently in ${topicText} over the past four years. No coauthored paper with the current scholar was found; ${institution.analyzed_member_count} analyzed relevant scholar${institution.analyzed_member_count === 1 ? "" : "s"} can be viewed.`
  }
  if (institution.current_collaboration_count === 1) {
    return lang === "zh"
      ? `${institution.name} 近四年在 ${topicText} 上有论文活动，并找到 1 篇与当前学者合著的论文；可从已有合作关系查看相关学者。`
      : `${institution.name} has recent publications in ${topicText} and one coauthored paper with the current scholar; related scholars can be explored through this existing collaboration.`
  }
  return lang === "zh"
    ? `${institution.name} 近四年在 ${topicText} 上有论文活动，并找到 ${institution.current_collaboration_count} 篇与当前学者合著的论文；可从已有合作关系查看相关学者。`
    : `${institution.name} has recent publications in ${topicText} and ${institution.current_collaboration_count} coauthored papers with the current scholar; related scholars can be explored through these collaborations.`
}

function InstitutionCard({
  institution,
  comparing,
  onCompare,
  feedback,
  feedbackBusy,
  onFeedback,
  lang,
}: {
  institution: IntelligenceInstitution
  comparing: boolean
  onCompare: (institutionId: string) => void
  feedback?: "helpful" | "inaccurate"
  feedbackBusy: boolean
  onFeedback: (itemKey: string, verdict: "helpful" | "inaccurate") => void
  lang: Lang
}) {
  const itemKey = `institution_radar|${institution.institution_id}`
  return (
    <Card className="min-w-0">
      <CardContent className="space-y-3 p-4">
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h4 className="break-words font-semibold">{institution.name}</h4>
            {institution.country_code && (
              <p className="mt-1 text-xs text-muted-foreground">
                {institution.country_code}
              </p>
            )}
          </div>
          <div className="flex flex-wrap justify-end gap-1">
            {institution.is_focus_institution && (
              <Badge variant="outline">
                {lang === "zh" ? "当前机构" : "Current institution"}
              </Badge>
            )}
          </div>
        </div>
        <p className="text-sm leading-relaxed">
          {institutionSummary(institution, lang)}
        </p>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <div className="rounded-md bg-muted/60 p-2">
            <p className="text-muted-foreground">{lang === "zh" ? "方向论文" : "Topic works"}</p>
            <p className="mt-1 font-semibold tabular-nums">{institution.historical_works}</p>
          </div>
          <div className="rounded-md bg-muted/60 p-2">
            <p className="text-muted-foreground">{lang === "zh" ? "近四年论文" : "Works in 4 years"}</p>
            <p className="mt-1 font-semibold tabular-nums">{institution.recent_works}</p>
          </div>
          <div className="rounded-md bg-muted/60 p-2">
            <p className="text-muted-foreground">{lang === "zh" ? "与该学者合著" : "Coauthored works"}</p>
            <p className="mt-1 font-semibold tabular-nums">{institution.current_collaboration_count}</p>
          </div>
          <div className="rounded-md bg-muted/60 p-2">
            <p className="text-muted-foreground">{lang === "zh" ? "可查看学者" : "Viewable scholars"}</p>
            <p className="mt-1 font-semibold tabular-nums">{institution.analyzed_member_count}</p>
          </div>
        </div>
        {!institution.is_focus_institution && (
          <Button
            size="sm"
            variant="outline"
            disabled={comparing}
            onClick={() => onCompare(institution.institution_id)}
          >
            {comparing
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <ArrowLeftRight className="h-3.5 w-3.5" />}
            {lang === "zh" ? "与我的机构比较" : "Compare with current institution"}
          </Button>
        )}
        <details className="group border-t pt-3">
          <summary className="cursor-pointer list-none text-xs font-medium text-primary hover:underline">
            {lang === "zh" ? "数据范围" : "Data coverage"}
          </summary>
          <div className="mt-3 space-y-3">
            <p className="text-xs leading-relaxed text-muted-foreground">
              {lang === "zh"
                ? "论文活动来自所选主题的 OpenAlex 分组；已分析作者只计算当前动态图谱覆盖，不代表机构完整名册或质量。"
                : "Work activity comes from OpenAlex groupings for the selected topics. Analyzed scholars only reflect current dynamic-graph coverage, not a complete roster or quality."}
            </p>
            <FeedbackButtons
              itemKey={itemKey}
              selected={feedback}
              busy={feedbackBusy}
              onFeedback={onFeedback}
              lang={lang}
            />
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

function InstitutionComparison({
  comparison,
  onClose,
  lang,
}: {
  comparison: IntelligenceComparison
  onClose: () => void
  lang: Lang
}) {
  return (
    <Card className="border-primary/30">
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle className="text-base">
              {lang === "zh" ? "机构对比" : "Institution comparison"}
            </CardTitle>
            <CardDescription className="mt-1">
              {localize(comparison.conclusion, lang)}
            </CardDescription>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose}>
            {lang === "zh" ? "关闭" : "Close"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-start gap-3 border-b pb-2 text-xs font-medium">
          <span>{lang === "zh" ? "维度" : "Dimension"}</span>
          <span className="max-w-28 break-words text-right">
            {comparison.left?.name || (lang === "zh" ? "当前机构" : "Current")}
          </span>
          <span className="max-w-28 break-words text-right">
            {comparison.right?.name || (lang === "zh" ? "候选机构" : "Candidate")}
          </span>
        </div>
        {comparison.status === "available" && comparison.dimensions?.map((row) => (
          <div
            key={row.key}
            className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 border-b py-2 text-xs last:border-b-0"
          >
            <span className="min-w-0 break-words text-muted-foreground">
              {localize(row.label, lang)}
            </span>
            <span className="font-medium tabular-nums">
              {typeof row.left === "number" ? row.left.toLocaleString() : "—"}
            </span>
            <span className="font-medium tabular-nums">
              {typeof row.right === "number" ? row.right.toLocaleString() : "—"}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

export default function ScholarIntelligenceAnalysis({
  profile,
  lang,
  onViewProfile,
  onCompare,
  onTrackingChange,
}: Props) {
  const [intelligence, setIntelligence] = useState<ScholarIntelligence | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [filter, setFilter] = useState<DiscoveryFilter>("all")
  const [actionBusy, setActionBusy] = useState(false)
  const [tracked, setTracked] = useState<Set<string>>(new Set())
  const [trackingBusy, setTrackingBusy] = useState("")
  const [feedback, setFeedback] = useState<Record<string, "helpful" | "inaccurate">>({})
  const [feedbackBusy, setFeedbackBusy] = useState("")
  const [institutionComparison, setInstitutionComparison] = useState<IntelligenceComparison | null>(null)
  const [institutionComparing, setInstitutionComparing] = useState("")

  const load = useCallback(async (signal?: AbortSignal, background = false) => {
    if (!background) setLoading(true)
    try {
      const result = await getScholarIntelligence(profile.authorId, signal)
      if (!signal?.aborted) {
        setIntelligence(result)
        setError("")
      }
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return
      if (!signal?.aborted) {
        setError(
          reason instanceof ApiError
            ? reason.message
            : (lang === "zh" ? "学术视野加载失败" : "Could not load the academic landscape"),
        )
      }
    } finally {
      if (!signal?.aborted && !background) setLoading(false)
    }
  }, [lang, profile.authorId])

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      void load(controller.signal)
      void getTracking().then((rows) => {
        if (!controller.signal.aborted) {
          setTracked(new Set(rows.map((row) => row.author_id)))
        }
      }).catch(() => undefined)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [load])

  useEffect(() => {
    if (!intelligence || !["queued", "discovering", "enriching"].includes(intelligence.discovery.status)) {
      return
    }
    const timer = window.setInterval(() => {
      void load(undefined, true)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [intelligence, load])

  const handleDiscover = useCallback(async () => {
    setActionBusy(true)
    setError("")
    try {
      if (intelligence?.graph_status === "failed") {
        await refreshResearchGraph(profile.authorId, true)
      } else {
        await discoverScholarField(
          profile.authorId,
          intelligence?.discovery.status === "failed",
        )
      }
      await load(undefined, true)
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : (lang === "zh" ? "领域样本任务提交失败" : "Could not queue field discovery"),
      )
    } finally {
      setActionBusy(false)
    }
  }, [intelligence, lang, load, profile.authorId])

  const handleTrack = useCallback(async (authorId: string) => {
    setTrackingBusy(authorId)
    try {
      await addTracking(authorId)
      setTracked((current) => new Set(current).add(authorId))
      onTrackingChange?.()
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : (lang === "zh" ? "追踪操作失败" : "Could not track scholar"),
      )
    } finally {
      setTrackingBusy("")
    }
  }, [lang, onTrackingChange])

  const handleFeedback = useCallback(async (
    itemKey: string,
    verdict: "helpful" | "inaccurate",
  ) => {
    if (!intelligence) return
    setFeedbackBusy(itemKey)
    const separator = itemKey.indexOf("|")
    const analysisKey = separator >= 0 ? itemKey.slice(0, separator) : itemKey
    const candidateId = separator >= 0 ? itemKey.slice(separator + 1) : undefined
    try {
      await submitIntelligenceFeedback({
        targetAuthorId: profile.authorId,
        candidateAuthorId: candidateId,
        analysisKey,
        verdict,
        analysisVersion: intelligence.analysis_version,
        context: {
          graph_version: intelligence.generated_from_graph_version,
          field_discovery_version: intelligence.discovery.version,
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

  const handleInstitutionCompare = useCallback(async (institutionId: string) => {
    setInstitutionComparing(institutionId)
    setError("")
    try {
      setInstitutionComparison(await compareInstitutions(
        profile.authorId,
        institutionId,
      ))
    } catch (reason: unknown) {
      setError(
        reason instanceof Error
          ? reason.message
          : (lang === "zh" ? "机构对比加载失败" : "Could not compare institutions"),
      )
    } finally {
      setInstitutionComparing("")
    }
  }, [lang, profile.authorId])

  const merged = useMemo(
    () => intelligence && intelligence.discovery.discovered_count > 0
      ? mergeRecommendations(intelligence)
      : [],
    [intelligence],
  )
  const availableFilters = useMemo(
    () => ([
      "all",
      ...CATEGORY_ORDER.filter((category) => (
        merged.some((row) => row.categories.includes(category))
      )),
    ] as DiscoveryFilter[]),
    [merged],
  )
  const effectiveFilter = availableFilters.includes(filter) ? filter : "all"
  const visible = useMemo(
    () => effectiveFilter === "all"
      ? merged
      : merged.filter((row) => row.categories.includes(effectiveFilter)),
    [effectiveFilter, merged],
  )
  const mergedInstitutions = useMemo(() => {
    if (!intelligence) return []
    const rows = new Map<string, IntelligenceInstitution>()
    for (const institutions of [
      intelligence.institutions.active,
      intelligence.institutions.opportunities,
    ]) {
      for (const institution of institutions) {
        if (!rows.has(institution.institution_id)) {
          rows.set(institution.institution_id, institution)
        }
      }
    }
    return [...rows.values()].sort((left, right) => (
      Number(right.is_focus_institution) - Number(left.is_focus_institution)
      || right.analyzed_member_count - left.analyzed_member_count
      || right.current_collaboration_count - left.current_collaboration_count
      || right.recent_works - left.recent_works
      || left.name.localeCompare(right.name)
    ))
  }, [intelligence])

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin" />
          {lang === "zh" ? "正在整理学术视野…" : "Preparing the academic landscape…"}
        </CardContent>
      </Card>
    )
  }

  if (!intelligence) {
    return (
      <Card className="border-destructive/30">
        <CardContent className="space-y-4 p-6 text-sm">
          <p className="flex items-start gap-2 text-destructive">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            {error || (lang === "zh" ? "学术视野暂不可用" : "The academic landscape is unavailable")}
          </p>
          <Button size="sm" variant="outline" onClick={() => void load()}>
            <RefreshCw className="h-3.5 w-3.5" />
            {lang === "zh" ? "重试" : "Retry"}
          </Button>
        </CardContent>
      </Card>
    )
  }

  const discovery = intelligence.discovery
  const progressMaximum = Math.max(discovery.target_count, 1)
  const progressValue = Math.min(
    100,
    Math.round(discovery.analyzed_count / progressMaximum * 100),
  )
  const discoveryActive = ["queued", "discovering", "enriching"].includes(discovery.status)
  const anyRecommendations = merged.length > 0

  return (
    <div className="space-y-6">
      {error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      <Card className="border-primary/20">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Compass className="h-4 w-4 text-primary" />
                {lang === "zh" ? "分析进度" : "Analysis progress"}
              </CardTitle>
              <CardDescription className="mt-1">
                {lang === "zh"
                  ? `已发现 ${discovery.discovered_count} 位候选，已分析 ${discovery.analyzed_count}/${discovery.target_count} 位`
                  : `${discovery.discovered_count} candidates found; ${discovery.analyzed_count}/${discovery.target_count} analyzed`}
              </CardDescription>
            </div>
            <Badge variant="outline">{statusLabel(discovery.status, lang)}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {discovery.target_count > 0 && (
            <div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.max(discovery.analyzed_count ? 4 : 0, progressValue)}%` }}
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>
                  {lang === "zh" ? "排队中" : "Queued"} {discovery.queued_count}
                </span>
                {discovery.failed_count > 0 && (
                  <span>
                    {lang === "zh" ? "失败" : "Failed"} {discovery.failed_count}
                  </span>
                )}
              </div>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {(discovery.selected_topics.length
              ? discovery.selected_topics
              : intelligence.field.topics
            ).slice(0, 6).map((topic) => (
              <Badge key={topic.name} variant="secondary">
                {topic.name}
              </Badge>
            ))}
          </div>
          {(discovery.status === "never" || discovery.status === "failed" || intelligence.graph_status === "failed") && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed p-3">
              <p className="text-sm text-muted-foreground">
                {discovery.last_error || (
                  lang === "zh"
                    ? "当前领域样本尚未完成，现有图谱结论仍可查看。"
                    : "The field sample is incomplete; existing graph results remain available."
                )}
              </p>
              <Button size="sm" variant="outline" disabled={actionBusy} onClick={() => void handleDiscover()}>
                {actionBusy
                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  : <RefreshCw className="h-3.5 w-3.5" />}
                {lang === "zh" ? "重新补全" : "Retry discovery"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h3 className="font-semibold">{lang === "zh" ? "相关学者" : "Relevant scholars"}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {localize(FILTER_DESCRIPTIONS[effectiveFilter], lang)}
            </p>
          </div>
          <div className="flex max-w-full flex-wrap gap-1 rounded-lg border bg-muted/30 p-1">
            {availableFilters.map((key) => (
              <Button
                key={key}
                size="sm"
                variant={effectiveFilter === key ? "default" : "ghost"}
                className="h-7 px-2.5 text-xs"
                onClick={() => setFilter(key)}
              >
                {localize(FILTER_LABELS[key], lang)}
              </Button>
            ))}
          </div>
        </div>
        {visible.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {visible.map((row) => (
              <ScholarCard
                key={row.author_id}
                row={row}
                filter={effectiveFilter}
                tracked={tracked.has(row.author_id)}
                trackingBusy={trackingBusy === row.author_id}
                feedback={feedback}
                feedbackBusy={feedbackBusy}
                onViewProfile={onViewProfile}
                onCompare={onCompare}
                onTrack={(authorId) => void handleTrack(authorId)}
                onFeedback={handleFeedback}
                lang={lang}
              />
            ))}
          </div>
        ) : (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            {discoveryActive
              ? (
                  lang === "zh"
                    ? `候选图谱仍在补全（${discovery.analyzed_count}/${discovery.target_count}），可靠结果会逐步出现。`
                    : `Candidate graphs are still being enriched (${discovery.analyzed_count}/${discovery.target_count}); reliable results will appear progressively.`
                )
              : effectiveFilter === "all" && !anyRecommendations
                ? (
                    lang === "zh"
                      ? "当前样本未同时满足方向、时间、贡献与关系证据门槛，暂无可靠学者建议。"
                      : "The current sample does not jointly meet topic, time, contribution, and relationship thresholds."
                  )
                : (
                    lang === "zh"
                      ? "当前筛选下没有满足多项证据门槛的结果。"
                      : "No result under this filter meets the multi-evidence thresholds."
                  )}
          </p>
        )}
      </section>

      <Separator />

      <section>
        <div className="mb-3">
          <h3 className="flex items-center gap-2 font-semibold">
            <Building2 className="h-4 w-4 text-primary" />
            {lang === "zh" ? "相关机构" : "Relevant institutions"}
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {lang === "zh"
              ? "查看相同方向上的论文活动、与当前学者的合著记录，以及可以继续查看的相关学者。"
              : "Review publication activity in related topics, coauthorship with the current scholar, and relevant scholars available to view."}
          </p>
        </div>

        {mergedInstitutions.length > 0 && (
          <div className="grid gap-3 lg:grid-cols-2">
            {mergedInstitutions.map((institution) => (
              <InstitutionCard
                key={institution.institution_id}
                institution={institution}
                comparing={institutionComparing === institution.institution_id}
                onCompare={(institutionId) => void handleInstitutionCompare(institutionId)}
                feedback={feedback[`institution_radar|${institution.institution_id}`]}
                feedbackBusy={feedbackBusy === `institution_radar|${institution.institution_id}`}
                onFeedback={handleFeedback}
                lang={lang}
              />
            ))}
          </div>
        )}

        {!mergedInstitutions.length && (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            {discoveryActive
              ? (lang === "zh" ? "机构样本正在发现中。" : "Institution discovery is in progress.")
              : (lang === "zh" ? "当前缺少可核验的机构主题活动数据。" : "No verifiable institution topic-activity data is available.")}
          </p>
        )}
      </section>

      {institutionComparison && (
        <InstitutionComparison
          comparison={institutionComparison}
          onClose={() => setInstitutionComparison(null)}
          lang={lang}
        />
      )}
    </div>
  )
}
