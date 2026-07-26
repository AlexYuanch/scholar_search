import { CalendarRange } from "lucide-react"
import type { ScholarProfile } from "@/types"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export interface TimelinePaperFilter {
  year: number
  topic: string
}

export default function ResearchTimeline({ profile, onTopicClick, updating = false, t }: {
  profile: ScholarProfile
  onTopicClick: (filter: TimelinePaperFilter) => void
  updating?: boolean
  t: (key: string) => string
}) {
  const timeline = [...profile.interestTimeline]
    .filter((item) => item.topics.length > 0)
    .sort((left, right) => right.year - left.year)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarRange className="h-4 w-4" />
          {t("timeline.title")}
        </CardTitle>
        <CardDescription>{t("timeline.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {timeline.length ? (
          <div className="relative space-y-5 before:absolute before:bottom-2 before:left-[2.2rem] before:top-2 before:w-px before:bg-border">
            {timeline.map((item) => (
              <div key={item.year} className="relative grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3">
                <div className="z-10 flex h-8 items-center justify-center rounded-full border bg-background text-xs font-semibold tabular-nums">
                  {item.year}
                </div>
                <div className="flex min-w-0 flex-wrap gap-2 pt-1">
                  {item.topics.slice(0, 6).map((topic) => (
                    <button
                      key={`${item.year}-${topic.topic}`}
                      type="button"
                      className="max-w-full whitespace-normal rounded-md border border-transparent bg-secondary px-2.5 py-0.5 text-left text-xs font-semibold text-secondary-foreground transition-colors hover:border-primary/30 hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      title={`${t("timeline.open_papers")}: ${item.year} · ${topic.topic}`}
                      aria-label={`${t("timeline.open_papers")}: ${item.year} · ${topic.topic} · ${topic.count}`}
                      disabled={updating}
                      onClick={() => onTopicClick({ year: item.year, topic: topic.topic })}
                    >
                      {topic.topic} · {topic.count}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("timeline.empty")}</p>
        )}
        {updating && (
          <p className="mt-4 rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
            {t("timeline.updating")}
          </p>
        )}
        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">{t("timeline.evidence")}</p>
      </CardContent>
    </Card>
  )
}
