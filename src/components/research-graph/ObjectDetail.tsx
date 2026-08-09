import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ExternalLink } from "lucide-react"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { ResearchGraphObject } from "@/types"
import type { Translate } from "@/components/research-graph/model"

export default function ObjectDetail({
  value,
  onClose,
  t,
}: {
  value: ResearchGraphObject
  onClose: () => void
  t: Translate
}) {
  if (value.type === "topic") {
    const name = typeof value.data.display_name === "string"
      ? value.data.display_name.trim()
      : ""
    const description = typeof value.data.description === "string"
      ? value.data.description.trim()
      : ""
    const sourceUrl = typeof value.data.source_topic_id === "string"
      && /^https?:\/\//.test(value.data.source_topic_id)
      ? value.data.source_topic_id
      : ""

    return (
      <Card className="border-primary/30 bg-primary/5">
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 space-y-2">
              <Badge variant="outline">{t("research_graph.direction")}</Badge>
              <CardTitle className="break-words text-xl">
                {name || t("research_graph.topic_unknown")}
              </CardTitle>
              <CardDescription className="max-w-3xl leading-relaxed">
                {description || t("research_graph.topic_detail_desc")}
              </CardDescription>
            </div>
            <Button variant="ghost" size="sm" onClick={onClose}>
              {t("research_graph.close")}
            </Button>
          </div>
        </CardHeader>
        {sourceUrl && (
          <CardContent>
            <Button asChild variant="outline" size="sm">
              <a href={sourceUrl} target="_blank" rel="noreferrer">
                {t("research_graph.topic_source")}
                <ExternalLink className="h-4 w-4" />
              </a>
            </Button>
          </CardContent>
        )}
      </Card>
    )
  }

  const entries = Object.entries(value.data).filter(([key, field]) => (
    !["raw_json", "abstract"].includes(key)
    && field !== null
    && field !== ""
    && typeof field !== "object"
  ))
  const abstract = typeof value.data.abstract === "string"
    ? value.data.abstract
    : ""

  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">
              {t(`research_graph.object.${value.type}`)}
            </CardTitle>
            <CardDescription>{value.id}</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t("research_graph.close")}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.map(([key, field]) => (
          <div
            key={key}
            className="grid gap-1 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]"
          >
            <span className="text-muted-foreground">{key}</span>
            <span className="break-words">{String(field)}</span>
          </div>
        ))}
        {abstract && (
          <div className="rounded-md border bg-background p-3">
            <Badge variant="outline">
              {t("research_graph.abstract_basis")}
            </Badge>
            <p className="mt-2 break-words text-sm leading-relaxed">
              {abstract}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
