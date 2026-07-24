import { CalendarRange } from "lucide-react"
import type { ScholarProfile } from "@/types"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export default function ResearchTimeline({ profile, t }: {
  profile: ScholarProfile
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
                    <Badge key={`${item.year}-${topic.topic}`} variant="secondary" className="max-w-full whitespace-normal">
                      {topic.topic} · {topic.count}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{t("timeline.empty")}</p>
        )}
        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">{t("timeline.evidence")}</p>
      </CardContent>
    </Card>
  )
}
