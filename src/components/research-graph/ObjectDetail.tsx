import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
