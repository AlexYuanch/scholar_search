export interface EdgePaper {
  title: string
  id?: string
  topics?: string[]
}

export interface ProfessionalIdentity {
  currentInstitution: string
  institutionHistory: Array<{ name: string; years: number[] }>
  currentAffiliationStatements: Array<{ text: string; years: number[] }>
  affiliationStatements: Array<{ text: string; years: number[] }>
  department?: string | null
  laboratory?: string | null
  researchUnit?: string | null
  academicRole?: string | null
  degreeStatus?: string | null
  orcid?: string | null
  sourceLinks: Array<{ label: string; url: string }>
  sources: string[]
}

export interface Candidate {
  id: string
  name: string
  institution: string
  institutions?: string[]
  current_institution?: string
  historical_institutions?: string[]
  works_count: number
  cited_by_count: number
  h_index: number
  orcid?: string | null
  merged_count?: number
  merged_ids?: string[]
  disambiguation?: string
  identity_confidence?: string
  identity_evidence?: Array<{
    type: "orcid" | "current_institution" | "merged_profile" | "published_profile" | "independent_profile"
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
  professionalIdentity?: ProfessionalIdentity
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
