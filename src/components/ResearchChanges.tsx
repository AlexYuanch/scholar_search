import { ArrowDownRight, ArrowUpRight, CircleMinus, Sparkles } from "lucide-react"
import type { ScholarProfile } from "@/types"
import type { Lang } from "@/i18n"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

interface Props {
  profile: ScholarProfile
  t: (key: string) => string
  lang: Lang
}

type DirectionKind = "emerging" | "rising" | "steady" | "falling"

interface DirectionChange {
  topic: string
  previousCount: number
  currentCount: number
  previousShare: number
  currentShare: number
  change: number
  kind: DirectionKind
}

interface ChangeAnalysis {
  latestYear: number
  previousStart: number
  previousEnd: number
  currentStart: number
  currentEnd: number
  previousPapers: number
  currentPapers: number
  previousAssignments: number
  currentAssignments: number
  currentTopicCount: number
  directions: DirectionChange[]
  matrixTopics: string[]
  matrixYears: number[]
  countsByYear: Map<number, Map<string, number>>
}

const WINDOW_YEARS = 3

function sumPapers(profile: ScholarProfile, start: number, end: number) {
  return profile.yearlyTrend
    .filter((item) => item.year >= start && item.year <= end)
    .reduce((total, item) => total + item.papers, 0)
}

function analyzeChanges(profile: ScholarProfile): ChangeAnalysis | null {
  const usableTimeline = profile.interestTimeline.filter((item) => item.topics.length > 0)
  const publicationYears = profile.yearlyTrend
    .filter((item) => item.papers > 0)
    .map((item) => item.year)
  const timelineYears = usableTimeline.map((item) => item.year)
  const allYears = [...publicationYears, ...timelineYears]
  if (!allYears.length) return null

  const latestYear = Math.max(...allYears)
  const currentStart = latestYear - WINDOW_YEARS + 1
  const currentEnd = latestYear
  const previousStart = currentStart - WINDOW_YEARS
  const previousEnd = currentStart - 1
  const countsByYear = new Map<number, Map<string, number>>()

  for (const item of usableTimeline) {
    const topicCounts = new Map<string, number>()
    for (const topic of item.topics) {
      if (!topic.topic.trim() || topic.count <= 0) continue
      topicCounts.set(topic.topic, (topicCounts.get(topic.topic) ?? 0) + topic.count)
    }
    countsByYear.set(item.year, topicCounts)
  }

  const previous = new Map<string, number>()
  const current = new Map<string, number>()
  for (const [year, topicCounts] of countsByYear) {
    const target = year >= currentStart && year <= currentEnd
      ? current
      : year >= previousStart && year <= previousEnd
        ? previous
        : null
    if (!target) continue
    for (const [topic, count] of topicCounts) {
      target.set(topic, (target.get(topic) ?? 0) + count)
    }
  }

  const previousAssignments = [...previous.values()].reduce((total, count) => total + count, 0)
  const currentAssignments = [...current.values()].reduce((total, count) => total + count, 0)
  const topics = new Set([...previous.keys(), ...current.keys()])
  const directions = [...topics].map((topic): DirectionChange => {
    const previousCount = previous.get(topic) ?? 0
    const currentCount = current.get(topic) ?? 0
    const previousShare = previousAssignments ? previousCount / previousAssignments : 0
    const currentShare = currentAssignments ? currentCount / currentAssignments : 0
    const change = currentShare - previousShare
    let kind: DirectionKind = "steady"
    if (currentCount > 0 && previousCount === 0) kind = "emerging"
    else if (change >= 0.04 || (change >= 0.02 && currentShare >= previousShare * 1.5)) kind = "rising"
    else if (change <= -0.04 || (change <= -0.02 && previousShare >= currentShare * 1.5)) kind = "falling"
    return { topic, previousCount, currentCount, previousShare, currentShare, change, kind }
  }).sort((left, right) => Math.max(right.currentShare, right.previousShare) - Math.max(left.currentShare, left.previousShare))

  const matrixYears = Array.from({ length: WINDOW_YEARS * 2 }, (_, index) => previousStart + index)
  const matrixTopics = [...directions]
    .sort((left, right) => (right.currentCount + right.previousCount) - (left.currentCount + left.previousCount))
    .slice(0, 6)
    .map((item) => item.topic)

  return {
    latestYear,
    previousStart,
    previousEnd,
    currentStart,
    currentEnd,
    previousPapers: sumPapers(profile, previousStart, previousEnd),
    currentPapers: sumPapers(profile, currentStart, currentEnd),
    previousAssignments,
    currentAssignments,
    currentTopicCount: [...current.values()].filter((count) => count > 0).length,
    directions,
    matrixTopics,
    matrixYears,
    countsByYear,
  }
}

function formatPaperChange(previous: number, current: number) {
  if (!previous) return "—"
  const percentage = Math.round((current - previous) / previous * 100)
  return `${percentage > 0 ? "+" : ""}${percentage}%`
}

function DirectionGroup({
  kind,
  directions,
  t,
}: {
  kind: DirectionKind
  directions: DirectionChange[]
  t: (key: string) => string
}) {
  const config = {
    emerging: { icon: Sparkles, className: "text-violet-600", background: "bg-violet-500/10" },
    rising: { icon: ArrowUpRight, className: "text-emerald-600", background: "bg-emerald-500/10" },
    steady: { icon: CircleMinus, className: "text-blue-600", background: "bg-blue-500/10" },
    falling: { icon: ArrowDownRight, className: "text-amber-600", background: "bg-amber-500/10" },
  }[kind]
  const Icon = config.icon
  const items = directions.filter((item) => item.kind === kind).slice(0, 4)

  return (
    <div className="min-w-0 rounded-lg border p-4">
      <div className="mb-3 flex items-center gap-2">
        <span className={`rounded-md p-1.5 ${config.background}`}>
          <Icon className={`h-4 w-4 ${config.className}`} />
        </span>
        <h4 className="text-sm font-medium">{t(`changes.${kind}`)}</h4>
      </div>
      {items.length ? (
        <div className="space-y-2">
          {items.map((item) => (
            <div key={item.topic} className="flex min-w-0 flex-col gap-1 rounded-md bg-muted/50 px-3 py-2 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
              <span className="min-w-0 break-words text-sm">{item.topic}</span>
              <span className="shrink-0 whitespace-nowrap text-xs tabular-nums text-muted-foreground sm:text-right">
                {item.previousCount} → {item.currentCount} {t("changes.related_papers")}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("changes.none")}</p>
      )}
    </div>
  )
}

function ActivityMatrix({ analysis, t }: { analysis: ChangeAnalysis; t: (key: string) => string }) {
  const maximum = Math.max(
    1,
    ...analysis.matrixTopics.flatMap((topic) => analysis.matrixYears.map((year) => analysis.countsByYear.get(year)?.get(topic) ?? 0)),
  )

  if (!analysis.matrixTopics.length) return null

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">{t("changes.timeline")}</h4>
        <span className="text-xs text-muted-foreground">{t("changes.darker_more")}</span>
      </div>
      <div className="space-y-2">
        <div className="grid grid-cols-[minmax(4rem,1fr)_repeat(6,minmax(0,1fr))] items-center gap-1 text-center text-[10px] text-muted-foreground sm:grid-cols-[minmax(12rem,1fr)_repeat(6,2.5rem)] sm:gap-2 sm:text-xs">
          <span />
          {analysis.matrixYears.map((year) => (
            <span key={year}>
              <span className="sm:hidden">{String(year).slice(-2)}</span>
              <span className="hidden sm:inline">{year}</span>
            </span>
          ))}
        </div>
        {analysis.matrixTopics.map((topic) => (
          <div key={topic} className="grid grid-cols-[minmax(4rem,1fr)_repeat(6,minmax(0,1fr))] items-center gap-1 sm:grid-cols-[minmax(12rem,1fr)_repeat(6,2.5rem)] sm:gap-2">
            <span className="truncate pr-1 text-xs sm:pr-2 sm:text-sm" title={topic}>{topic}</span>
            {analysis.matrixYears.map((year) => {
              const count = analysis.countsByYear.get(year)?.get(topic) ?? 0
              return (
                <div
                  key={year}
                  className="flex h-7 items-center justify-center rounded bg-primary text-[10px] font-medium text-primary-foreground sm:h-8 sm:rounded-md sm:text-xs"
                  style={{ opacity: count ? 0.2 + count / maximum * 0.8 : 0.05 }}
                  title={`${year} · ${topic} · ${count} ${t("changes.related_papers")}`}
                  aria-label={`${year} ${topic} ${count} ${t("changes.related_papers")}`}
                >
                  {count || ""}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ResearchChanges({ profile, t, lang }: Props) {
  const analysis = analyzeChanges(profile)
  if (!analysis) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">{t("changes.title")}</CardTitle></CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t("changes.insufficient_history")}</p>
        </CardContent>
      </Card>
    )
  }

  const comparable = analysis.previousAssignments > 0 && analysis.currentAssignments > 0
  const directionGroups: DirectionKind[] = ["emerging", "rising", "steady", "falling"]
  const agentSummary = (
    lang === "zh"
      ? profile.agentAnalysis?.trajectory?.summaryZh
      : profile.agentAnalysis?.trajectory?.summaryEn
  )?.trim()

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="text-base">{t("changes.title")}</CardTitle>
            <CardDescription className="mt-1 break-words">
              {analysis.previousStart}–{analysis.previousEnd} {t("changes.compared_with")} {analysis.currentStart}–{analysis.currentEnd}
            </CardDescription>
          </div>
          <Badge variant="outline">{t("changes.latest_year")} {analysis.latestYear}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg bg-muted/60 p-4">
            <p className="text-xs text-muted-foreground">{t("changes.recent_output")}</p>
            <p className="mt-1 text-2xl font-bold tabular-nums">{analysis.currentPapers}</p>
            <p className="text-xs text-muted-foreground">{analysis.currentStart}–{analysis.currentEnd} · {t("changes.period_total")}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-4">
            <p className="text-xs text-muted-foreground">{t("changes.output_change")}</p>
            <p className="mt-1 text-2xl font-bold tabular-nums">{formatPaperChange(analysis.previousPapers, analysis.currentPapers)}</p>
            <p className="text-xs text-muted-foreground">{t("changes.previous_period")} {analysis.previousPapers} {t("changes.papers")}</p>
          </div>
          <div className="rounded-lg bg-muted/60 p-4">
            <p className="text-xs text-muted-foreground">{t("changes.active_directions")}</p>
            <p className="mt-1 text-2xl font-bold tabular-nums">{analysis.currentTopicCount}</p>
            <p className="text-xs text-muted-foreground">{t("changes.in_recent_window")}</p>
          </div>
        </div>

        {agentSummary && (
          <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Sparkles className="h-4 w-4 text-primary" />
              {t("agent.trajectory_insight")}
            </div>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{agentSummary}</p>
          </div>
        )}

        {comparable ? (
          <div className="grid gap-3 md:grid-cols-2">
            {directionGroups.map((kind) => (
              <DirectionGroup key={kind} kind={kind} directions={analysis.directions} t={t} />
            ))}
          </div>
        ) : (
          <p className="rounded-lg border bg-muted/40 p-4 text-sm text-muted-foreground">
            {t("changes.insufficient_history")}
          </p>
        )}

        <ActivityMatrix analysis={analysis} t={t} />

        <p className="text-xs leading-relaxed text-muted-foreground">
          {t("changes.caution")}
        </p>
      </CardContent>
    </Card>
  )
}
