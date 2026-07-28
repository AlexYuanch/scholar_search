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
  identity_group?: "high" | "medium" | "review"
  identity_score?: number
  match_reasons?: Array<{
    code: string
    label?: string
    value?: string | number
    details?: Record<string, number>
  }>
  latest_publication_year?: number | null
  research_topics?: string[]
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
      insights?: Array<{
        direction: string
        changeKind: "emerging" | "rising" | "steady" | "falling"
        interpretationZh: string
        interpretationEn: string
        confidence: "high" | "medium" | "low"
        evidencePapers: Array<{
          id: string
          title: string
          year?: number
          url: string
        }>
      }>
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
    resolutionMethod?: "orcid_anchor" | "institution_collaborator_cluster" | "insufficient_evidence"
    orcidMatchedWorks?: number
    orcidStatus?: "available" | "unavailable"
    excludedClusters?: Array<{
      workCount: number
      yearStart?: number
      yearEnd?: number
      topTopics: string[]
    }>
  }
  analysisVersion?: number
}

export type ResearchGraphObjectType = "author" | "paper" | "institution" | "topic"

export interface ResearchGraphObject {
  type: ResearchGraphObjectType
  id: string
  data: Record<string, unknown>
}

export interface ResearchGraph {
  author: {
    id?: string
    source_id: string
    name: string
    detail_url?: string
  }
  status: {
    status: "never" | "queued" | "updating" | "ready" | "failed"
    version: number
    last_success_at?: string | null
    last_error?: string | null
    warnings: string[]
  }
  timeline: Array<{
    id: string
    event_key: string
    event_type: "paper_published" | "topic_started" | "collaboration_started" | "institution_started" | "institution_ended"
    event_year?: number | null
    event_date?: string | null
    title: string
    description: string
    work_id?: string | null
    topic_id?: string | null
    institution_id?: string | null
    collaborator_id?: string | null
    source: string
    confidence: number
  }>
  topic_evolution: Array<{
    id: string
    name: string
    first_year?: number | null
    last_year?: number | null
    works_count: number
    years: Array<number | { year: number; works_count: number }>
    source: string
    confidence: number
  }>
  collaborations: Array<{
    author: { id: string; source_id: string; name: string }
    first_year?: number | null
    last_year?: number | null
    works_count: number
    papers: Array<{ id: string; source_id?: string; title: string; year?: number | null }>
    source: string
    confidence: number
  }>
  affiliations: Array<{
    id: string
    source_id?: string
    name: string
    country_code?: string | null
    start_year?: number | null
    end_year?: number | null
    years: number[]
    is_current: boolean
    is_last_known?: boolean
    source: string
    confidence: number
  }>
  papers: Array<{
    id: string
    source_id: string
    title: string
    year?: number | null
    publication_date?: string | null
    citations: number
    doi?: string | null
    venue?: string | null
    has_abstract: boolean
    topics: Array<{
      id: string
      name: string
      is_primary: boolean
      source: string
      confidence: number
    }>
    insight?: {
      problem?: string | null
      core_method?: string | null
      main_contribution?: string | null
      topic_relationship?: string | null
      abstract_evidence: Array<{ field: string; text: string }>
      based_on_abstract: boolean
      analyzer_version?: string | null
      source?: string | null
      confidence: number
    } | null
    source: string[]
    confidence: number
  }>
  citations: Array<{
    citing: { id: string; title: string }
    cited: { id?: string | null; source_id: string; title: string }
    source: string
    confidence: number
  }>
  local_network: {
    nodes: Array<{
      id: string
      object_id: string
      object_type: ResearchGraphObjectType
      label: string
      group: "author" | "collaborator" | "paper" | "topic" | "institution"
      detail_url: string
    }>
    edges: Array<{
      from: string
      to: string
      type: "collaborates" | "authored" | "has_topic" | "affiliated"
      label: string
    }>
  }
}

export interface LocalizedText {
  zh: string
  en: string
}

export interface IntelligenceConfidence {
  level: "high" | "medium" | "low" | "insufficient"
  score: number
  label: LocalizedText
  coverage?: {
    works: number
    year_span: number
    topic_coverage: number
    abstract_coverage: number
    graph_ready: boolean
  }
}

export interface IntelligenceEvidence {
  code: string
  label: LocalizedText
  value: string | number | boolean | null | Record<string, number | string>
  paper_ids: string[]
}

export interface IntelligenceScholar {
  author_id: string
  scholar_id: string
  name: string
  orcid?: string | null
  institution?: string | null
  graph_ready: boolean
  graph_version: number
}

export interface IntelligenceDimension {
  key: "academic_quality" | "continuity" | "impact" | "topic_style"
  status: "available" | "insufficient"
  index: number | null
  confidence: IntelligenceConfidence
  conclusion: LocalizedText
  evidence: IntelligenceEvidence[]
  limitations: LocalizedText[]
  axes?: Array<{
    key: string
    label: LocalizedText
    value: LocalizedText
  }>
}

export interface IntelligenceWork {
  id: string
  source_id: string
  title: string
  year?: number | null
  citations: number
  venue?: string | null
  topics: string[]
  index: number
  confidence: IntelligenceConfidence
  components: {
    field_relevance: number
    field_time_normalized_impact: number
    contribution_role: number
    internal_follow_on: number
    topic_continuation: number
  }
  evidence: IntelligenceEvidence[]
}

export interface IntelligenceRecommendation extends IntelligenceScholar {
  category: "north_star" | "peer" | "potential_collaborator" | "potential_competitor"
  index: number
  confidence: IntelligenceConfidence
  explanation: LocalizedText
  evidence: IntelligenceEvidence[]
  limitations: LocalizedText[]
}

export interface IntelligenceTeam {
  institution_id?: string | null
  name: string
  member_count: number
  covered_work_count: number
  active_years: number
  field_overlap: number
  topics: Array<{ name: string; works_count: number }>
  confidence: IntelligenceConfidence
  representative_members: IntelligenceScholar[]
  evidence: IntelligenceEvidence[]
}

export interface FieldDiscoveryStatus {
  status: "never" | "queued" | "discovering" | "enriching" | "ready" | "partial" | "failed"
  selected_topics: Array<{
    source_id: string
    name: string
    works_count: number
    active_years: number
    recent_works: number
    long_term: boolean
    recent: boolean
  }>
  discovered_count: number
  analyzed_count: number
  attempted_count: number
  target_count: number
  queued_count: number
  failed_count: number
  last_success_at?: string | null
  next_refresh_at?: string | null
  retry_after_at?: string | null
  last_error?: string | null
  version: number
}

export interface IntelligenceInstitution {
  institution_id: string
  name: string
  country_code?: string | null
  historical_works: number
  recent_works: number
  current_collaboration_count: number
  analyzed_member_count: number
  analyzed_members?: Array<{
    author_id: string
    name: string
  }>
  topics: Array<{ name: string }>
  is_focus_institution: boolean
  coverage: {
    source: "openalex_grouping"
    analyzed_members: number
  }
}

export interface ScholarIntelligence {
  analysis_version: string
  source: "dynamic_research_graph"
  generated_from_graph_version: number
  graph_status: "never" | "queued" | "updating" | "ready" | "failed"
  explanation_mode: "deterministic_templates"
  subject: IntelligenceScholar
  field: {
    topics: Array<{ name: string; works_count: number; active_years: number }>
    as_of_year?: number | null
    candidate_count: number
    scope: LocalizedText
  }
  methodology: {
    score_source: LocalizedText
    ranking_scope: LocalizedText
    principles: LocalizedText[]
  }
  confidence: IntelligenceConfidence
  dimensions: {
    academic_quality: IntelligenceDimension
    continuity: IntelligenceDimension
    impact: IntelligenceDimension
    topic_style: IntelligenceDimension
  }
  representative_works: IntelligenceWork[]
  recommendations: {
    north_stars: IntelligenceRecommendation[]
    peers: IntelligenceRecommendation[]
    potential_collaborators: IntelligenceRecommendation[]
    potential_competitors: IntelligenceRecommendation[]
  }
  field_reference_list: {
    label: LocalizedText
    is_absolute_ranking: false
    items: IntelligenceRecommendation[]
  }
  teams: {
    focus_team?: IntelligenceTeam | null
    field_teams: IntelligenceTeam[]
    limitations: LocalizedText[]
  }
  discovery: FieldDiscoveryStatus
  institutions: {
    active: IntelligenceInstitution[]
    opportunities: IntelligenceInstitution[]
    focus_institution_id?: string | null
    limitations: LocalizedText[]
  }
  limitations: LocalizedText[]
}

export interface IntelligenceComparison {
  analysis_version: string
  mode: "scholar" | "team" | "institution"
  status: "available" | "insufficient"
  left?: IntelligenceScholar | IntelligenceTeam | IntelligenceInstitution | null
  right?: IntelligenceScholar | IntelligenceTeam | IntelligenceInstitution | null
  dimensions?: Array<{
    key: string
    status?: "available" | "insufficient"
    label?: LocalizedText
    left: number | {
      index: number | null
      confidence: IntelligenceConfidence
      evidence: IntelligenceEvidence[]
    }
    right: number | {
      index: number | null
      confidence: IntelligenceConfidence
      evidence: IntelligenceEvidence[]
    }
    conclusion?: LocalizedText
  }>
  topic_overlap?: number
  representative_works?: {
    left: IntelligenceWork[]
    right: IntelligenceWork[]
  }
  conclusion: LocalizedText
  next_step?: LocalizedText
  limitations?: LocalizedText[]
}
