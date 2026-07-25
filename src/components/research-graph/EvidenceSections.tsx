import { BookOpen, Quote } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type {
  GraphObjectOpener,
  ResearchGraphViewModel,
  Translate,
} from "@/components/research-graph/model"

type EvidenceView = Pick<
  ResearchGraphViewModel,
  "insightPapers" | "internalCitations"
>

function AbstractEvolution({
  view,
  onOpen,
  t,
}: {
  view: EvidenceView
  onOpen: GraphObjectOpener
  t: Translate
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <BookOpen className="h-4 w-4" />
          {t("research_graph.abstract_evolution")}
        </CardTitle>
        <CardDescription>
          {t("research_graph.abstract_evolution_desc")}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {view.insightPapers.map((paper) => (
          <div
            key={paper.id}
            className="grid gap-3 rounded-xl border p-4 md:grid-cols-[5rem_minmax(0,1fr)]"
          >
            <div>
              <p className="text-sm font-semibold tabular-nums">
                {paper.year ?? "—"}
              </p>
              <Badge variant="outline" className="mt-2">
                {t("research_graph.abstract_basis")}
              </Badge>
            </div>
            <div className="min-w-0 space-y-2 text-sm">
              {paper.insight?.problem && (
                <p>
                  <span className="font-medium">
                    {t("research_graph.problem")}：
                  </span>
                  {paper.insight.problem}
                </p>
              )}
              {paper.insight?.core_method && (
                <p>
                  <span className="font-medium">
                    {t("research_graph.method")}：
                  </span>
                  {paper.insight.core_method}
                </p>
              )}
              {paper.insight?.main_contribution && (
                <p>
                  <span className="font-medium">
                    {t("research_graph.contribution")}：
                  </span>
                  {paper.insight.main_contribution}
                </p>
              )}
              {paper.insight?.topic_relationship && (
                <p>
                  <span className="font-medium">
                    {t("research_graph.topic_relation")}：
                  </span>
                  {paper.insight.topic_relationship}
                </p>
              )}
              <button
                type="button"
                className="block max-w-full cursor-pointer truncate text-left text-xs text-muted-foreground hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                aria-label={`${t("research_graph.open_paper")}：${paper.title}`}
                title={`${t("research_graph.open_paper")}：${paper.title}`}
                onClick={() => void onOpen("paper", paper.id)}
              >
                {t("research_graph.evidence_source")}：{paper.title}
              </button>
            </div>
          </div>
        ))}
        {!view.insightPapers.length && (
          <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            {t("research_graph.no_abstract_evolution")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function CitationLineage({
  view,
  onOpen,
  t,
}: {
  view: EvidenceView
  onOpen: GraphObjectOpener
  t: Translate
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Quote className="h-4 w-4" />
          {t("research_graph.citation_evolution")}
        </CardTitle>
        <CardDescription>{t("research_graph.citation_desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {view.internalCitations.map((citation) => (
          <div
            key={`${citation.citing.id}-${citation.cited.source_id}`}
            className="grid gap-2 rounded-lg border p-3 text-sm md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:items-center"
          >
            <button
              type="button"
              className="min-w-0 cursor-pointer break-words text-left hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              aria-label={`${t("research_graph.open_paper")}：${citation.citing.title}`}
              title={`${t("research_graph.open_paper")}：${citation.citing.title}`}
              onClick={() => void onOpen("paper", citation.citing.id)}
            >
              {citation.citing.title}
            </button>
            <span className="text-xs text-muted-foreground">
              → {t("research_graph.cites")} →
            </span>
            <button
              type="button"
              className="min-w-0 cursor-pointer break-words text-left hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              aria-label={`${t("research_graph.open_paper")}：${citation.cited.title}`}
              title={`${t("research_graph.open_paper")}：${citation.cited.title}`}
              onClick={() => void onOpen("paper", citation.cited.id!)}
            >
              {citation.cited.title}
            </button>
          </div>
        ))}
        {!view.internalCitations.length && (
          <p className="text-sm text-muted-foreground">
            {t("research_graph.no_citations")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export default function EvidenceSections({
  view,
  onOpen,
  t,
}: {
  view: EvidenceView
  onOpen: GraphObjectOpener
  t: Translate
}) {
  return (
    <>
      <AbstractEvolution view={view} onOpen={onOpen} t={t} />
      <CitationLineage view={view} onOpen={onOpen} t={t} />
    </>
  )
}
