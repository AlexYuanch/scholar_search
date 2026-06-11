export interface EdgePaper {
  title: string
  id?: string
  topics?: string[]
}

export interface Candidate {
  id: string
  name: string
  institution: string
  works_count: number
  cited_by_count: number
  h_index: number
}

export interface ScholarProfile {
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
    topics: Array<{ topic: string; score: number }>
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
  coauthors: Array<{ name: string; papers: number }>
  graphNodes: Array<{ id: string; name: string; type: string }>
  graphEdges: Array<{ source: string; target: string; weight: number; papers?: EdgePaper[] }>
  profileSummary: string
}
