import { Activity, Clock3, Eye, Link2 } from "lucide-react"

import type { Lang } from "@/i18n"
import type {
  IntelligenceComparison,
  IntelligenceInstitution,
  LocalizedText,
} from "@/types"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

interface Props {
  comparison: IntelligenceComparison
  onClose: () => void
  onViewScholar: (authorId: string, scholarName: string) => void
  focusScholarName: string
  lang: Lang
}

function localize(text: LocalizedText | undefined, lang: Lang) {
  if (!text) return ""
  return text[lang] || text.zh || text.en
}

function isInstitution(value: IntelligenceComparison["left"]): value is IntelligenceInstitution {
  return Boolean(value && "institution_id" in value)
}

function recentShare(institution: IntelligenceInstitution) {
  if (institution.historical_works <= 0) return null
  return Math.min(1, institution.recent_works / institution.historical_works)
}

function formatPercent(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`
}

function activityDifference(
  left: IntelligenceInstitution,
  right: IntelligenceInstitution,
  lang: Lang,
) {
  if (left.recent_works === right.recent_works) {
    return lang === "zh" ? "近四年样本量相同" : "Same four-year sample size"
  }
  if (left.recent_works === 0) {
    return lang === "zh"
      ? "仅对比机构有近期样本"
      : "Only the compared institution has a recent sample"
  }
  if (right.recent_works === 0) {
    return lang === "zh"
      ? "仅本机构有近期样本"
      : "Only the current institution has a recent sample"
  }
  const ratio = right.recent_works / left.recent_works
  if (ratio > 1) {
    return lang === "zh"
      ? `对比机构约为本机构的 ${ratio.toFixed(1)} 倍`
      : `Compared institution is about ${ratio.toFixed(1)}× the current institution`
  }
  return lang === "zh"
    ? `本机构约为对比机构的 ${(1 / ratio).toFixed(1)} 倍`
    : `Current institution is about ${(1 / ratio).toFixed(1)}× the compared institution`
}

function shareDifference(
  leftShare: number | null,
  rightShare: number | null,
  lang: Lang,
) {
  if (leftShare === null || rightShare === null) {
    return lang === "zh" ? "历史样本不足" : "Insufficient historical sample"
  }
  const points = Math.round(Math.abs(rightShare - leftShare) * 100)
  if (points === 0) {
    return lang === "zh" ? "近期占比相同" : "Same recent share"
  }
  if (rightShare > leftShare) {
    return lang === "zh"
      ? `对比机构高 ${points} 个百分点`
      : `Compared institution is ${points} points higher`
  }
  return lang === "zh"
    ? `本机构高 ${points} 个百分点`
    : `Current institution is ${points} points higher`
}

function InstitutionHeader({
  institution,
  current,
  lang,
}: {
  institution: IntelligenceInstitution
  current: boolean
  lang: Lang
}) {
  return (
    <div className="min-w-0 rounded-lg border bg-muted/20 p-3">
      <p className="text-xs font-medium text-muted-foreground">
        {current
          ? (lang === "zh" ? "本机构" : "Current institution")
          : (lang === "zh" ? "对比机构" : "Compared institution")}
      </p>
      <p className="mt-1 break-words text-sm font-semibold">{institution.name}</p>
      {institution.country_code && (
        <p className="mt-1 text-xs text-muted-foreground">{institution.country_code}</p>
      )}
    </div>
  )
}

function ActivityBar({
  value,
  maximum,
  highlight,
}: {
  value: number
  maximum: number
  highlight: boolean
}) {
  const width = maximum > 0 && value > 0
    ? Math.max(2, (value / maximum) * 100)
    : 0
  return (
    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
      <div
        className={highlight ? "h-full rounded-full bg-primary" : "h-full rounded-full bg-muted-foreground/35"}
        style={{ width: `${width}%` }}
      />
    </div>
  )
}

function InstitutionMetric({
  label,
  value,
  barValue,
  barMaximum,
  highlight,
}: {
  label: string
  value: string
  barValue?: number
  barMaximum?: number
  highlight?: boolean
}) {
  return (
    <div className="min-w-0 rounded-md bg-muted/40 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold tabular-nums">{value}</p>
      {barValue !== undefined && barMaximum !== undefined && (
        <ActivityBar
          value={barValue}
          maximum={barMaximum}
          highlight={Boolean(highlight)}
        />
      )}
    </div>
  )
}

export default function InstitutionComparison({
  comparison,
  onClose,
  onViewScholar,
  focusScholarName,
  lang,
}: Props) {
  const left = isInstitution(comparison.left) ? comparison.left : null
  const right = isInstitution(comparison.right) ? comparison.right : null

  if (comparison.status !== "available" || !left || !right) {
    return (
      <Card className="border-primary/30">
        <CardHeader>
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <CardTitle className="text-base">
                {lang === "zh" ? "与本机构的差异" : "Difference from current institution"}
              </CardTitle>
              <CardDescription className="mt-1">
                {localize(comparison.conclusion, lang)}
              </CardDescription>
            </div>
            <Button
              size="sm"
              variant="ghost"
              className="shrink-0"
              onClick={onClose}
            >
              {lang === "zh" ? "关闭" : "Close"}
            </Button>
          </div>
        </CardHeader>
      </Card>
    )
  }

  const leftShare = recentShare(left)
  const rightShare = recentShare(right)
  const maximumRecentWorks = Math.max(left.recent_works, right.recent_works)

  return (
    <Card className="border-primary/30">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <CardTitle className="text-base">
              {lang === "zh" ? "与本机构的差异" : "Difference from current institution"}
            </CardTitle>
            <CardDescription className="mt-1 max-w-3xl leading-relaxed">
              {localize(comparison.conclusion, lang)}
            </CardDescription>
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="shrink-0"
            onClick={onClose}
          >
            {lang === "zh" ? "关闭" : "Close"}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          <InstitutionHeader institution={left} current lang={lang} />
          <InstitutionHeader institution={right} current={false} lang={lang} />
        </div>

        <section className="rounded-lg border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="flex items-center gap-2 text-sm font-semibold">
              <Activity className="h-4 w-4 text-primary" />
              {lang === "zh" ? "近期论文活动" : "Recent publication activity"}
            </h4>
            <Badge variant="secondary">
              {activityDifference(left, right, lang)}
            </Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <InstitutionMetric
              label={lang === "zh" ? "本机构 · 近四年" : "Current · four years"}
              value={left.recent_works.toLocaleString()}
              barValue={left.recent_works}
              barMaximum={maximumRecentWorks}
            />
            <InstitutionMetric
              label={lang === "zh" ? "对比机构 · 近四年" : "Compared · four years"}
              value={right.recent_works.toLocaleString()}
              barValue={right.recent_works}
              barMaximum={maximumRecentWorks}
              highlight
            />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {lang === "zh"
              ? "只比较当前所选研究方向下的 OpenAlex 收录量，不代表论文质量或机构实力。"
              : "This compares OpenAlex coverage in the selected topics only; it does not represent paper quality or institutional strength."}
          </p>
        </section>

        <section className="rounded-lg border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="flex items-center gap-2 text-sm font-semibold">
              <Clock3 className="h-4 w-4 text-primary" />
              {lang === "zh" ? "时间分布" : "Time distribution"}
            </h4>
            <Badge variant="secondary">
              {shareDifference(leftShare, rightShare, lang)}
            </Badge>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <InstitutionMetric
              label={lang === "zh" ? "本机构 · 近四年占比" : "Current · recent share"}
              value={formatPercent(leftShare)}
            />
            <InstitutionMetric
              label={lang === "zh" ? "对比机构 · 近四年占比" : "Compared · recent share"}
              value={formatPercent(rightShare)}
            />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {lang === "zh"
              ? "占比是“近四年论文 ÷ 所选方向历史论文”，用于观察时间分布，不是增长率。"
              : "Share means four-year works divided by historical works in the selected topics; it describes time distribution, not growth."}
          </p>
        </section>

        <section className="rounded-lg border p-4">
          <h4 className="flex items-center gap-2 text-sm font-semibold">
            <Link2 className="h-4 w-4 text-primary" />
            {lang === "zh" ? "当前图谱联系" : "Links in the current graph"}
          </h4>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            <div className="grid grid-cols-2 gap-2">
              <InstitutionMetric
                label={lang === "zh"
                  ? `本机构 · 与 ${focusScholarName} 合著`
                  : `Current · coauthored with ${focusScholarName}`}
                value={left.current_collaboration_count.toLocaleString()}
              />
              <InstitutionMetric
                label={lang === "zh" ? "已分析学者" : "Analyzed scholars"}
                value={left.analyzed_member_count.toLocaleString()}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <InstitutionMetric
                label={lang === "zh"
                  ? `对比机构 · 与 ${focusScholarName} 合著`
                  : `Compared · coauthored with ${focusScholarName}`}
                value={right.current_collaboration_count.toLocaleString()}
              />
              <InstitutionMetric
                label={lang === "zh" ? "已分析学者" : "Analyzed scholars"}
                value={right.analyzed_member_count.toLocaleString()}
              />
            </div>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {lang === "zh"
              ? "零表示当前已分析范围内没有记录，不代表现实中一定没有合作。"
              : "Zero means no record within current analyzed coverage; it does not prove that no real-world collaboration exists."}
          </p>
          {right.analyzed_members && right.analyzed_members.length > 0 && (
            <div className="mt-3 border-t pt-3">
              <p className="text-xs font-medium text-muted-foreground">
                {lang === "zh"
                  ? `可查看的相关学者（${right.analyzed_members.length}）`
                  : `Relevant scholars available to view (${right.analyzed_members.length})`}
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {right.analyzed_members.map((member) => (
                  <Button
                    key={member.author_id}
                    size="sm"
                    variant="outline"
                    className="h-auto min-w-0 whitespace-normal py-1.5 text-left"
                    onClick={() => onViewScholar(member.author_id, member.name)}
                  >
                    <Eye className="h-3.5 w-3.5 shrink-0" />
                    <span className="break-words">{member.name}</span>
                    <span className="text-muted-foreground">
                      {lang === "zh" ? "查看画像" : "View profile"}
                    </span>
                  </Button>
                ))}
              </div>
            </div>
          )}
        </section>

        {comparison.next_step && (
          <div className="rounded-lg border border-primary/20 bg-primary/5 p-4">
            <p className="text-xs font-semibold text-primary">
              {lang === "zh" ? "建议怎么用" : "How to use this"}
            </p>
            <p className="mt-1 text-sm leading-relaxed">
              {localize(comparison.next_step, lang)}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
