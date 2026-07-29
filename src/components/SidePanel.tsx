import { ExternalLink, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import type { EdgePaper } from "@/types"

interface PanelData {
  type: "edge" | "coauthor" | "center"
  sourceName?: string
  targetName: string
  papers: Array<EdgePaper | string>
  weight: number
  targetId?: string
}

interface Props {
  data: PanelData | null
  onClose: () => void
  onViewProfile: (authorId: string, scholarName: string) => void
  t: (key: string) => string
  fullscreen?: boolean
}

function paperTitle(paper: EdgePaper | string) {
  return typeof paper === "string" ? paper : paper.title
}

function paperId(paper: EdgePaper | string) {
  return typeof paper === "string" ? "" : paper.id
}

export default function SidePanel({ data, onClose, onViewProfile, t, fullscreen }: Props) {
  if (!data) return null

  const title = data.type === "edge"
    ? `${data.sourceName ?? ""} ${t("panel.papers_with")} ${data.targetName}`
    : data.targetName

  return (
    <>
      {!fullscreen && (
        <button
          type="button"
          aria-label={t("panel.close")}
          className="scholar-panel-backdrop"
          onClick={onClose}
        />
      )}
      <aside
        className={`scholar-side-panel ${
          fullscreen
            ? "scholar-side-panel--fullscreen"
            : "scholar-side-panel--responsive"
        }`}
      >
      <div className="scholar-panel-surface flex h-full flex-col">
        <div className="flex items-start justify-between gap-3 border-b p-4">
          <div className="min-w-0">
            <h3 className="break-words text-base font-semibold leading-tight">{title}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {data.weight} {t("graph.papers_coauthored")}
            </p>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {data.type !== "edge" && data.targetId && data.type !== "center" && (
            <Button
              className="mb-4 w-full"
              variant="outline"
              onClick={() => onViewProfile(data.targetId!, data.targetName)}
            >
              {t("graph.view_profile")}
            </Button>
          )}

          <h4 className="mb-3 text-sm font-medium">
            {data.type === "edge" ? t("panel.coauthored_papers") : t("graph.coauthor_papers")}
          </h4>

          {data.papers.length ? (
            <div className="space-y-2">
              {data.papers.map((paper, index) => {
                const id = paperId(paper)
                return (
                  <Card key={`${paperTitle(paper)}-${index}`}>
                    <CardContent className="p-3">
                      {id ? (
                        <a
                          href={id}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex min-w-0 items-start gap-1 break-words text-sm font-medium leading-snug text-primary hover:underline"
                        >
                          {paperTitle(paper)}
                          <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
                        </a>
                      ) : (
                        <p className="break-words text-sm font-medium leading-snug">{paperTitle(paper)}</p>
                      )}
                      {typeof paper !== "string" && (paper.topics?.length ?? 0) > 0 && (
                        <p className="mt-2 break-words text-xs text-muted-foreground">
                          {paper.topics?.slice(0, 3).join(" / ")}
                        </p>
                      )}
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("panel.no_papers")}</p>
          )}
        </div>
      </div>
      </aside>
    </>
  )
}
