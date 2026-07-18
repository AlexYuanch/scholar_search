export interface EdgePaper {
  title: string
  id?: string
  topics?: string[]
}

export interface Candidate {
  id: string
  name: string
  institution: string
  institutions?: string[]
  works_count: number
  cited_by_count: number
  h_index: number
  orcid?: string | null
  merged_count?: number
  merged_ids?: string[]
  disambiguation?: string
}

export interface ScholarProfile {
  authorId: string
  scholarId: string
  profileVersion: number
  refreshStatus: "ready" | "queued" | "updating" | "failed"
  name: string
  institution: string
  department: string
  totalPapers: number
  totalCitations: number
  hIndex: number
  topics: string[]
  yearlyTrend: Array<{ year: number; papers: number; citations: number }>
  topicDistribution: Array<{ name: string; value: number }>
  interestTimeline: Array<{
    year: number
    topics: Array<{ topic: string; count: number }>
  }>
  representativePapers: Array<{
    title: string
    year: number
    citations: number
    journal: string
    id?: string
  }>
  topCitedPapers: Array<{
    title: string
    year: number
    citations: number
    journal: string
    id?: string
  }>
  coauthors: Array<{ name: string; institution?: string; papers: number }>
  graphNodes: Array<{ id: string; name: string; institution?: string; type: string }>
  graphEdges: Array<{ source: string; target: string; weight: number; papers?: EdgePaper[] }>
  profileSummary: string
  profileEvidence: Array<{
    id: string
    type: "metric" | "paper" | "topic" | "coauthor"
    text: string
    url?: string
  }>
}
