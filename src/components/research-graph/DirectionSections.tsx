import {
  Building2,
  CalendarRange,
  GitFork,
  Sparkles,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import TopicButton from "@/components/research-graph/TopicButton"
import {
  phaseLabel,
  type GraphObjectOpener,
  type PhaseContext,
  type PhaseTopic,
  type ResearchGraphViewModel,
  type Translate,
} from "@/components/research-graph/model"

type DirectionView = Pick<
  ResearchGraphViewModel,
  "phases" | "transitions" | "matrixTopics" | "phaseContext"
>

function LatestPhaseBadge({
  year,
  t,
}: {
  year: number
  t: Translate
}) {
  return (
    <Badge variant="default">
      {year} · {t("research_graph.latest_phase")}
    </Badge>
  )
}

function PhaseCard({
  phase,
  isLatest,
  context,
  onOpen,
  t,
}: {
  phase: ResearchGraphViewModel["phases"][number]
  isLatest: boolean
  context: PhaseContext | undefined
  onOpen: GraphObjectOpener
  t: Translate
}) {
  const hasContext = Boolean(
    context
    && (context.institutions.length || context.newCollaboratorCount),
  )
  return (
    <div className="rounded-xl border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            {isLatest && <LatestPhaseBadge year={phase.endYear} t={t} />}
            <p className="text-sm font-semibold">{phaseLabel(phase)}</p>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {phase.papers.length} {t("research_graph.phase_outputs")}
            {" · "}{phase.citations} {t("candidate.citations")}
            {" · "}{phase.abstractEvidenceCount}{" "}
            {t("research_graph.abstract_evidence_count")}
          </p>
        </div>
        <Badge variant="secondary">{t("research_graph.computed")}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {phase.topics.map((topic) => (
          <TopicButton
            key={topic.id}
            topic={topic}
            showCount
            onOpen={onOpen}
            t={t}
          />
        ))}
      </div>
      {hasContext && context && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
          <span className="text-xs font-medium text-muted-foreground">
            {t("research_graph.phase_context")}：
          </span>
          {context.institutions.map((event) => (
            <button
              key={event.institution_id}
              type="button"
              className="group inline-flex cursor-pointer rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
              aria-label={`${t("research_graph.open_institution")}：${event.title}`}
              title={`${t("research_graph.open_institution")}：${event.title}`}
              onClick={() => void onOpen(
                "institution",
                event.institution_id!,
              )}
            >
              <Badge
                variant="outline"
                className="pointer-events-none transition-shadow group-hover:shadow-md"
              >
                <Building2 className="mr-1 h-3 w-3" />
                {event.title}
              </Badge>
            </button>
          ))}
          {context.newCollaboratorCount > 0 && (
            <Badge variant="secondary">
              {t("research_graph.new_collaborators")}{" "}
              {context.newCollaboratorCount}
            </Badge>
          )}
        </div>
      )}
    </div>
  )
}

function TransitionTopics({
  label,
  topics,
  variant,
  onOpen,
  t,
}: {
  label: string
  topics: PhaseTopic[]
  variant: "default" | "secondary" | "outline"
  onOpen: GraphObjectOpener
  t: Translate
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">
        {t(`research_graph.${label}`)}
      </p>
      <div className="flex flex-wrap gap-1">
        {topics.map((topic) => (
          <TopicButton
            key={topic.id}
            topic={topic}
            variant={variant}
            onOpen={onOpen}
            t={t}
          />
        ))}
        {!topics.length && (
          <span className="text-xs text-muted-foreground">—</span>
        )}
      </div>
    </div>
  )
}

function ResearchPhases({
  view,
  onOpen,
  t,
}: {
  view: DirectionView
  onOpen: GraphObjectOpener
  t: Translate
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CalendarRange className="h-4 w-4" />
          {t("research_graph.phases")}
        </CardTitle>
        <CardDescription>{t("research_graph.phases_desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {view.phases.map((phase, index) => (
          <PhaseCard
            key={phase.key}
            phase={phase}
            isLatest={index === 0}
            context={view.phaseContext.get(phase.key)}
            onOpen={onOpen}
            t={t}
          />
        ))}
        {!view.phases.length && (
          <p className="text-sm text-muted-foreground">
            {t("research_graph.no_phases")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function DirectionTransitions({
  view,
  onOpen,
  t,
}: {
  view: DirectionView
  onOpen: GraphObjectOpener
  t: Translate
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <GitFork className="h-4 w-4" />
          {t("research_graph.transitions")}
        </CardTitle>
        <CardDescription>{t("research_graph.transitions_desc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {view.transitions.map((transition, index) => (
          <div key={transition.key} className="rounded-xl border p-4">
            <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              {index === 0 && (
                <LatestPhaseBadge year={transition.current.endYear} t={t} />
              )}
              <span>{phaseLabel(transition.current)}</span>
              <span className="text-muted-foreground">
                {t("research_graph.compared_with")}
              </span>
              <span>{phaseLabel(transition.previous)}</span>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <TransitionTopics
                label="transition_emerged"
                topics={transition.emerged}
                variant="default"
                onOpen={onOpen}
                t={t}
              />
              <TransitionTopics
                label="transition_continued"
                topics={transition.continued}
                variant="secondary"
                onOpen={onOpen}
                t={t}
              />
              <TransitionTopics
                label="transition_faded"
                topics={transition.faded}
                variant="outline"
                onOpen={onOpen}
                t={t}
              />
            </div>
          </div>
        ))}
        {!view.transitions.length && (
          <p className="text-sm text-muted-foreground">
            {t("research_graph.no_transitions")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function TopicMatrix({
  view,
  onOpen,
  t,
}: {
  view: DirectionView
  onOpen: GraphObjectOpener
  t: Translate
}) {
  const hasMatrix = Boolean(view.matrixTopics.length && view.phases.length)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4" />
          {t("research_graph.topic_matrix")}
        </CardTitle>
        <CardDescription>{t("research_graph.topic_matrix_desc")}</CardDescription>
      </CardHeader>
      <CardContent>
        {hasMatrix ? (
          <div className="overflow-x-auto">
            <div
              className="grid min-w-[42rem] gap-1 text-xs"
              style={{
                gridTemplateColumns: `minmax(12rem, 1.6fr) repeat(${view.phases.length}, minmax(5rem, .7fr))`,
              }}
            >
              <div className="p-2 font-medium text-muted-foreground">
                {t("research_graph.direction")}
              </div>
              {view.phases.map((phase, index) => (
                <div
                  key={phase.key}
                  className="p-2 text-center font-medium"
                >
                  {index === 0 && (
                    <span className="block text-primary">
                      {phase.endYear} · {t("research_graph.latest")}
                    </span>
                  )}
                  <span>{phaseLabel(phase)}</span>
                </div>
              ))}
              {view.matrixTopics.map((topic) => (
                <div key={topic.id} className="contents">
                  <button
                    type="button"
                    className="cursor-pointer truncate rounded-md p-2 text-left font-medium transition-colors hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                    aria-label={`${t("research_graph.open_topic")}：${topic.name}`}
                    title={`${t("research_graph.open_topic")}：${topic.name}`}
                    onClick={() => void onOpen("topic", topic.id)}
                  >
                    {topic.name}
                  </button>
                  {view.phases.map((phase) => {
                    const count = phase.topicCounts.get(topic.id)?.count || 0
                    return (
                      <div
                        key={`${phase.key}:${topic.id}`}
                        className={count
                          ? "rounded-md bg-primary/15 p-2 text-center font-semibold text-primary"
                          : "rounded-md bg-muted/30 p-2 text-center text-muted-foreground"
                        }
                      >
                        {count || "—"}
                      </div>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("research_graph.no_topic_matrix")}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export default function DirectionSections({
  view,
  onOpen,
  t,
}: {
  view: DirectionView
  onOpen: GraphObjectOpener
  t: Translate
}) {
  return (
    <>
      <ResearchPhases view={view} onOpen={onOpen} t={t} />
      <DirectionTransitions view={view} onOpen={onOpen} t={t} />
      <TopicMatrix view={view} onOpen={onOpen} t={t} />
    </>
  )
}
