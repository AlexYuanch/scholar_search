export interface EdgePaper {
  title: string
  id?: string
  topics?: string[]
}

export interface AffiliationEvidence {
  primaryAffiliation: string
  openAlexAffiliationHistory: Array<{ name: string; years: number[] }>
  publicationAffiliationStatements: Array<{ text: string; years: number[] }>
  verifiedEmployment?: {
    institution: string
    unit?: string | null
    role?: string | null
    sourceLabel: string
    sourceUrl?: string | null
  } | null
  verifiedEducation?: Array<{
    institution: string
    unit?: string | null
    degree?: string | null
    sourceLabel: string
    sourceUrl?: string | null
  }>
  orcid?: string | null
  sourceLinks: Array<{ label: string; url: string }>
  sources: string[]
}

export interface Candidate {
  id: string
  name: string
  institution: string
  institutions?: string[]
  primary_institution?: string
  other_institutions?: string[]
  works_count: number
  cited_by_count: number
  h_index: number
  orcid?: string | null
  merged_count?: number
  merged_ids?: string[]
  disambiguation?: string
  identity_confidence?: string
  identity_evidence?: Array<{
    type: "orcid" | "primary_institution" | "merged_profile" | "published_profile" | "independent_profile"
    value?: string
    reason?: string
    shared_works?: number
    shared_coauthors?: number
    shared_topics?: number
    shared_institutions?: number
    sampled_works?: number
    coauthor_count?: number
    topic_count?: number
    merged_count?: number
  }>
}

export interface ScholarProfile {
  authorId: string
  scholarId: string
  profileVersion: number
  refreshStatus: "ready" | "queued" | "updating" | "failed"
  updatedAt?: string
  name: string
  institution: string
  institutions?: string[]
  orcid?: string | null
  department: string
  affiliationEvidence?: AffiliationEvidence
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
    sources?: string[]
  }>
  topCitedPapers: Array<{
    title: string
    year: number
    citations: number
    journal: string
    id?: string
    doi?: string
    topics?: string[]
    sources?: string[]
    verificationStatus?: string
  }>
  coauthors: Array<{ id?: string; name: string; institution?: string; papers: number }>
  graphNodes: Array<{ id: string; name: string; institution?: string; type: string }>
  graphEdges: Array<{ source: string; target: string; weight: number; papers?: EdgePaper[] }>
  profileSummary: string
  profileSummaryI18n?: { zh?: string; en?: string }
  profileEvidence: Array<{
    id: string
    type: "metric" | "paper" | "topic" | "coauthor"
    text: string
    url?: string
    sources?: string[]
    confidence?: "high" | "medium" | "low"
  }>
  dataAudit?: {
    status: "sufficient" | "partial" | "attention"
    sources: string[]
    openalexExpected: number
    openalexFetched: number
    collectedWorks: number
    worksWithDoi: number
    crossrefRequested: number
    crossrefVerified: number
    crossrefMissing: number
    crossrefFailed: number
    crossrefLimited: boolean
    unverifiedWorks: number
    duplicateRecordsMerged: number
    conflictCount: number
    worksComplete: boolean
    verifiedRatio: number
    retrievedAt: string
  }
  evidenceReview?: {
    approvedEvidenceIds: string[]
    rejectedEvidenceIds: string[]
    flags: string[]
    publishable: boolean
    summaryConfidence: "high" | "medium" | "low"
    agentReviewed?: boolean
    agentConfidence?: "high" | "medium" | "low" | ""
    agentFlags?: string[]
  }
  agentAnalysis?: {
    status: "completed" | "partial" | "fallback" | "disabled"
    plan: {
      topic_tier?: "fast" | "strong"
      trajectory_tier?: "fast" | "strong"
      report_tier?: "fast" | "strong"
      review_tier?: "fast" | "strong"
      rationale?: string
    }
    runs: Array<{
      agent: string
      status: string
      model: string
      tier: string
      plannedTier: string
      attemptedModels: string[]
      escalated: boolean
      reasons: string[]
    }>
    trajectory?: {
      summaryZh?: string
      summaryEn?: string
      emerging?: string[]
      rising?: string[]
      steady?: string[]
      falling?: string[]
      confidence?: "high" | "medium" | "low"
      previousWindow?: { start: number; end: number }
      currentWindow?: { start: number; end: number }
    }
    review?: {
      summarySupported?: boolean
      approvedEvidenceIds?: string[]
      flags?: string[]
      confidence?: "high" | "medium" | "low"
      noteZh?: string
      noteEn?: string
    }
  }
  identityAudit?: {
    primaryAuthorId: string
    requestedAuthorIds: string[]
    mergedAuthorIds: string[]
    rejectedAuthorIds: string[]
    mergedCount: number
    collectedWorks?: number
    excludedWorks?: number
    excludedWorkIds?: string[]
    largeConflictWorks?: number
    possibleConflatedIdentity?: boolean
  }
}
