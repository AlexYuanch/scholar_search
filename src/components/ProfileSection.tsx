import { lazy, Suspense, useEffect, useRef, useState, type ComponentType } from "react"
import {
  ArrowLeftRight,
  BarChart3,
  BookOpen,
  ExternalLink,
  Heart,
  Loader2,
  Quote,
} from "lucide-react"
import AllPapers from "@/components/AllPapers"
import DataVerification from "@/components/DataVerification"
import DynamicResearchGraph from "@/components/DynamicResearchGraph"
import ResearchChanges from "@/components/ResearchChanges"
import ResearchTimeline, { type TimelinePaperFilter } from "@/components/ResearchTimeline"
import ScholarIntroduction from "@/components/ScholarIntroduction"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import type { Lang } from "@/i18n"
import type { EdgePaper, ScholarProfile } from "@/types"

const CollaborationGraph = lazy(() => import("@/components/CollaborationGraph"))

type Translate = (key: string) => string

interface Props {
  profile: ScholarProfile
  favorite: boolean
  onToggleFavorite: () => void
  onCompare: () => void
  onEdgeClick?: (data: {
    sourceName: string
    targetName: string
    papers: EdgePaper[]
    weight: number
  }) => void
  onNodeClick?: (data: {
    id: string
    name: string
    type: string
    papers: EdgePaper[]
    weight: number
  }) => void
  onFullscreenChange?: (fullscreen: boolean) => void
  t: Translate
  lang: Lang
}

type ProfileTab = "overview" | "papers" | "network" | "research-graph"

function MetricCard({
  icon: Icon,
  label,
  value,
}: {
  icon: ComponentType<{ className?: string }>
  label: string
  value: string | number
}) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-primary/10 p-2">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div className="flex flex-col">
            <span className="text-sm text-muted-foreground">{label}</span>
            <span className="text-2xl font-bold">{value}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function TopicsSection({ topics }: { topics: string[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {topics.map((topic) => (
        <Badge key={topic} variant="secondary" className="px-3 py-1 text-sm">
          {topic}
        </Badge>
      ))}
    </div>
  )
}

export default function ProfileSection({
  profile,
  favorite,
  onToggleFavorite,
  onCompare,
  onEdgeClick,
  onNodeClick,
  onFullscreenChange,
  t,
  lang,
}: Props) {
  const [activeTab, setActiveTab] = useState<ProfileTab>("overview")
  const [paperFilter, setPaperFilter] = useState<TimelinePaperFilter | null>(null)
  const papersSectionRef = useRef<HTMLDivElement>(null)
  const analysisUpdating = profile.refreshStatus === "queued" || profile.refreshStatus === "updating"

  const handleTimelineTopicClick = (filter: TimelinePaperFilter) => {
    if (analysisUpdating) return
    setPaperFilter(filter)
    setActiveTab("papers")
  }

  useEffect(() => {
    if (activeTab !== "papers" || !paperFilter) return
    const frame = requestAnimationFrame(() => {
      papersSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
    })
    return () => cancelAnimationFrame(frame)
  }, [activeTab, paperFilter])

  const collaboratorId = (name: string, institution?: string, id?: string) => {
    if (id) return id
    return profile.graphNodes.find((node) =>
      node.type === "coauthor"
      && node.name === name
      && (!institution || !node.institution || node.institution === institution)
    )?.id
  }

  const showCollaboratorDetails = (authorId: string, scholarName: string, fallbackWeight: number) => {
    const edge = profile.graphEdges.find((item) => item.target === authorId)
    onNodeClick?.({
      id: authorId,
      name: scholarName,
      type: "coauthor",
      papers: edge?.papers ?? [],
      weight: edge?.weight ?? fallbackWeight,
    })
  }

  return (
    <section className="mx-auto max-w-5xl px-6 py-10">
      <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-4">
          <Avatar className="h-16 w-16 shrink-0 border-2 sm:h-20 sm:w-20">
            <AvatarFallback className="bg-primary/10 text-2xl font-semibold text-primary">
              {profile.name.split(" ").map((name) => name[0]).join("")}
            </AvatarFallback>
          </Avatar>
          <div className="min-w-0">
            <a
              href={profile.authorId}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-start gap-1 break-words text-xl font-bold hover:text-primary hover:underline sm:text-2xl"
              title={t("graph.open_alex")}
            >
              {profile.name}
              <ExternalLink className="mt-1 h-4 w-4 shrink-0" />
            </a>
            {profile.affiliationEvidence?.verifiedEmployment ? (
              <p className="break-words text-sm text-muted-foreground">
                {[
                  profile.affiliationEvidence.verifiedEmployment.role,
                  profile.affiliationEvidence.verifiedEmployment.unit,
                  profile.affiliationEvidence.verifiedEmployment.institution,
                ].filter(Boolean).join(lang === "zh" ? "，" : ", ")}
              </p>
            ) : profile.institution ? (
              <p className="break-words text-sm text-muted-foreground">
                {t("identity.primary_affiliation")}: {profile.institution}
              </p>
            ) : null}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          <Button variant="outline" size="sm" className="h-8 gap-1" onClick={onCompare}>
            <ArrowLeftRight className="h-3.5 w-3.5" />
            {t("compare.action")}
          </Button>
          <Button variant="outline" size="sm" className="h-8 gap-1" onClick={onToggleFavorite}>
            <Heart className={`h-3.5 w-3.5 ${favorite ? "fill-current text-red-500" : ""}`} />
            {t(favorite ? "favorite.remove" : "favorite.add")}
          </Button>
        </div>
      </div>

      <Separator className="my-6" />

      <Tabs
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as ProfileTab)}
      >
        <TabsList className="grid w-full grid-cols-2 sm:inline-flex sm:w-auto">
          <TabsTrigger value="overview">{t("tab.overview")}</TabsTrigger>
          <TabsTrigger value="papers">{t("tab.papers")}</TabsTrigger>
          <TabsTrigger value="network">{t("tab.network")}</TabsTrigger>
          <TabsTrigger value="research-graph">{t("tab.research_graph")}</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-6">
          <ScholarIntroduction profile={profile} lang={lang} t={t} />

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("section.research_directions")}</CardTitle>
              <CardDescription>{t("section.research_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="p-3 sm:p-6">
              <TopicsSection topics={profile.topics} />
            </CardContent>
          </Card>

          <ResearchTimeline
            profile={profile}
            onTopicClick={handleTimelineTopicClick}
            updating={analysisUpdating}
            t={t}
          />
          <ResearchChanges profile={profile} t={t} lang={lang} />

          <div className="grid gap-4 sm:grid-cols-3">
            <MetricCard icon={BookOpen} label={t("metric.total_papers")} value={profile.totalPapers} />
            <MetricCard
              icon={Quote}
              label={t("metric.total_citations")}
              value={profile.totalCitations.toLocaleString()}
            />
            <MetricCard icon={BarChart3} label={t("metric.h_index")} value={profile.hIndex} />
          </div>

          <DataVerification profile={profile} t={t} lang={lang} />
        </TabsContent>

        <TabsContent value="papers" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("section.repr_papers")}</CardTitle>
              <CardDescription>{t("section.repr_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {(profile.representativePapers.length
                ? profile.representativePapers
                : profile.topCitedPapers.slice(0, 5)
              ).map((paper) => (
                <div key={paper.id || `${paper.title}-${paper.year}`} className="rounded-lg border p-4">
                  {paper.id ? (
                    <a
                      href={paper.id}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-start gap-1 break-words text-sm font-medium text-primary hover:underline"
                    >
                      {paper.title}
                      <ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    </a>
                  ) : (
                    <p className="break-words text-sm font-medium">{paper.title}</p>
                  )}
                  <p className="mt-1 text-xs text-muted-foreground">
                    {paper.year || "—"} · {paper.journal || "—"} ·{" "}
                    {paper.citations.toLocaleString()} {t("candidate.citations")}
                  </p>
                </div>
              ))}
              {!profile.representativePapers.length && !profile.topCitedPapers.length && (
                <p className="text-sm text-muted-foreground">{t("compare.no_papers")}</p>
              )}
            </CardContent>
          </Card>

          <div ref={papersSectionRef} className="scroll-mt-20">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{t("section.all_papers")}</CardTitle>
                <CardDescription>{t("papers.pagination_desc")}</CardDescription>
              </CardHeader>
              <CardContent>
                <AllPapers
                  profile={profile}
                  filter={paperFilter}
                  onClearFilter={() => setPaperFilter(null)}
                  t={t}
                />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="network" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("section.collab_network")}</CardTitle>
              <CardDescription>{t("section.collab_desc")}</CardDescription>
            </CardHeader>
            <CardContent className="p-3 sm:p-6">
              <div className="mb-5 flex flex-wrap gap-2">
                {profile.coauthors.slice(0, 8).map((coauthor) => {
                  const authorId = collaboratorId(coauthor.name, coauthor.institution, coauthor.id)
                  if (!authorId) {
                    return (
                      <Badge
                        key={`${coauthor.name}-${coauthor.institution || ""}`}
                        variant="secondary"
                        className="whitespace-normal"
                      >
                        {coauthor.name} · {coauthor.papers}
                      </Badge>
                    )
                  }
                  return (
                    <button
                      key={`${authorId}-${coauthor.name}`}
                      type="button"
                      className="inline-flex items-center rounded-md bg-secondary px-2.5 py-0.5 text-xs font-semibold text-secondary-foreground transition-colors hover:bg-primary hover:text-primary-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      title={`${t("graph.click_node")}: ${coauthor.name}`}
                      onClick={() => showCollaboratorDetails(authorId, coauthor.name, coauthor.papers)}
                    >
                      {coauthor.name} · {coauthor.papers}
                    </button>
                  )
                })}
              </div>
              <Suspense
                fallback={(
                  <div className="flex h-[520px] items-center justify-center text-muted-foreground">
                    <Loader2 className="h-6 w-6 animate-spin" />
                  </div>
                )}
              >
                <CollaborationGraph
                  name={profile.name}
                  graphNodes={profile.graphNodes}
                  graphEdges={profile.graphEdges}
                  onEdgeClick={onEdgeClick}
                  onNodeClick={onNodeClick}
                  onFullscreenChange={onFullscreenChange}
                  t={t}
                />
              </Suspense>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="research-graph" className="space-y-4">
          {analysisUpdating ? (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">
                {t("timeline.updating")}
              </CardContent>
            </Card>
          ) : (
            <DynamicResearchGraph profile={profile} t={t} />
          )}
        </TabsContent>
      </Tabs>
    </section>
  )
}
