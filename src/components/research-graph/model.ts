import type { ResearchGraph, ResearchGraphObjectType } from "@/types"

export type Translate = (key: string) => string
export type GraphObjectOpener = (
  objectType: ResearchGraphObjectType,
  objectId: string,
) => void | Promise<void>
export type GraphPaper = ResearchGraph["papers"][number]
export type TimelineEvent = ResearchGraph["timeline"][number]

export type PhaseTopic = {
  id: string
  name: string
  count: number
}

export type ResearchPhase = {
  key: string
  startYear: number
  endYear: number
  papers: GraphPaper[]
  topics: PhaseTopic[]
  topicCounts: Map<string, PhaseTopic>
  citations: number
  abstractEvidenceCount: number
}

export type ResearchTransition = {
  key: string
  previous: ResearchPhase
  current: ResearchPhase
  emerged: PhaseTopic[]
  continued: PhaseTopic[]
  faded: PhaseTopic[]
}

export type PhaseContext = {
  institutions: TimelineEvent[]
  newCollaboratorCount: number
}

export type ResearchGraphViewModel = {
  phases: ResearchPhase[]
  transitions: ResearchTransition[]
  matrixTopics: PhaseTopic[]
  phaseContext: Map<string, PhaseContext>
  insightPapers: GraphPaper[]
  internalCitations: ResearchGraph["citations"]
}

const MAX_PHASES = 5
const MAX_TOPICS_PER_PHASE = 5
const MAX_MATRIX_TOPICS = 10
const MAX_INSIGHTS_PER_PHASE = 2
const MAX_INTERNAL_CITATIONS = 12
const MAX_CITATIONS_PER_SOURCE_PAPER = 2

function buildChronologicalPhases(papers: GraphPaper[]): ResearchPhase[] {
  const dated = papers.filter((paper): paper is GraphPaper & { year: number } => (
    typeof paper.year === "number"
  ))
  if (!dated.length) return []

  const years = dated.map((paper) => paper.year)
  const minimumYear = Math.min(...years)
  const maximumYear = Math.max(...years)
  const windowSize = Math.max(
    3,
    Math.ceil((maximumYear - minimumYear + 1) / MAX_PHASES),
  )
  const buckets = new Map<number, GraphPaper[]>()

  dated.forEach((paper) => {
    const index = Math.floor((paper.year - minimumYear) / windowSize)
    const bucket = buckets.get(index)
    if (bucket) bucket.push(paper)
    else buckets.set(index, [paper])
  })

  return [...buckets.entries()]
    .sort(([left], [right]) => left - right)
    .map(([index, phasePapers]) => {
      const startYear = minimumYear + index * windowSize
      const endYear = Math.min(maximumYear, startYear + windowSize - 1)
      const topicCounts = new Map<string, PhaseTopic>()

      phasePapers.forEach((paper) => {
        paper.topics.forEach((topic) => {
          const current = topicCounts.get(topic.id)
          topicCounts.set(topic.id, {
            id: topic.id,
            name: topic.name,
            count: (current?.count || 0) + 1,
          })
        })
      })

      return {
        key: `${startYear}-${endYear}`,
        startYear,
        endYear,
        papers: [...phasePapers].sort(
          (left, right) => right.citations - left.citations,
        ),
        topics: [...topicCounts.values()]
          .sort(
            (left, right) => (
              right.count - left.count || left.name.localeCompare(right.name)
            ),
          )
          .slice(0, MAX_TOPICS_PER_PHASE),
        topicCounts,
        citations: phasePapers.reduce(
          (total, paper) => total + paper.citations,
          0,
        ),
        abstractEvidenceCount: phasePapers.filter(
          (paper) => paper.insight?.based_on_abstract,
        ).length,
      }
    })
}

function buildTransitions(
  chronologicalPhases: ResearchPhase[],
): ResearchTransition[] {
  return chronologicalPhases.slice(1).map((current, index) => {
    const previous = chronologicalPhases[index]
    const previousIds = new Set(previous.topics.map((topic) => topic.id))
    const currentIds = new Set(current.topics.map((topic) => topic.id))
    return {
      key: `${previous.key}:${current.key}`,
      previous,
      current,
      emerged: current.topics.filter((topic) => !previousIds.has(topic.id)),
      continued: current.topics.filter((topic) => previousIds.has(topic.id)),
      faded: previous.topics.filter((topic) => !currentIds.has(topic.id)),
    }
  }).reverse()
}

function buildMatrixTopics(
  chronologicalPhases: ResearchPhase[],
): PhaseTopic[] {
  const totals = new Map<string, PhaseTopic>()
  chronologicalPhases.forEach((phase) => {
    phase.topicCounts.forEach((topic, id) => {
      totals.set(id, {
        ...topic,
        count: (totals.get(id)?.count || 0) + topic.count,
      })
    })
  })
  return [...totals.values()]
    .sort(
      (left, right) => (
        right.count - left.count || left.name.localeCompare(right.name)
      ),
    )
    .slice(0, MAX_MATRIX_TOPICS)
}

function buildPhaseContext(
  chronologicalPhases: ResearchPhase[],
  timeline: ResearchGraph["timeline"],
): Map<string, PhaseContext> {
  return new Map(chronologicalPhases.map((phase) => {
    const events = timeline.filter((event) => (
      typeof event.event_year === "number"
      && event.event_year >= phase.startYear
      && event.event_year <= phase.endYear
    ))
    const institutions = [...events.reduce((values, event) => {
      if (
        event.event_type.startsWith("institution")
        && event.institution_id
      ) {
        values.set(event.institution_id, event)
      }
      return values
    }, new Map<string, TimelineEvent>()).values()].slice(0, 2)

    return [
      phase.key,
      {
        institutions,
        newCollaboratorCount: events.filter(
          (event) => event.event_type === "collaboration_started",
        ).length,
      },
    ]
  }))
}

function selectInternalCitations(
  citations: ResearchGraph["citations"],
): ResearchGraph["citations"] {
  const selected: ResearchGraph["citations"] = []
  const selectedPerSource = new Map<string, number>()

  for (const citation of citations) {
    if (!citation.cited.id) continue
    const count = selectedPerSource.get(citation.citing.id) || 0
    if (count >= MAX_CITATIONS_PER_SOURCE_PAPER) continue
    selected.push(citation)
    selectedPerSource.set(citation.citing.id, count + 1)
    if (selected.length >= MAX_INTERNAL_CITATIONS) break
  }
  return selected
}

export function phaseLabel(phase: ResearchPhase): string {
  return phase.startYear === phase.endYear
    ? String(phase.startYear)
    : `${phase.startYear}–${phase.endYear}`
}

export function buildResearchGraphViewModel(
  graph: ResearchGraph,
): ResearchGraphViewModel {
  const chronologicalPhases = buildChronologicalPhases(graph.papers)
  return {
    phases: [...chronologicalPhases].reverse(),
    transitions: buildTransitions(chronologicalPhases),
    matrixTopics: buildMatrixTopics(chronologicalPhases),
    phaseContext: buildPhaseContext(chronologicalPhases, graph.timeline),
    insightPapers: chronologicalPhases
      .flatMap((phase) => phase.papers
        .filter((paper) => paper.insight?.based_on_abstract)
        .slice(0, MAX_INSIGHTS_PER_PHASE))
      .sort(
        (left, right) => (
          (right.year || 0) - (left.year || 0)
          || right.citations - left.citations
        ),
      ),
    internalCitations: selectInternalCitations(graph.citations),
  }
}
