/** Shared API types. Field names mirror the backend's camelCase contract. */

export type Language = 'en' | 'el'
export type Classification = 'restricted' | 'confidential' | 'shareable'
export type ArtifactState =
  | 'draft' | 'in_review' | 'approved' | 'rejected' | 'superseded' | 'archived'
export type ItemType = 'epic' | 'feature' | 'story' | 'task'
export type Severity = 'critical' | 'major' | 'minor' | 'info'
export type Priority = 'critical' | 'high' | 'medium' | 'low'
export type ExecutionStatus =
  | 'not_started' | 'ready' | 'in_progress' | 'blocked' | 'in_review' | 'done' | 'cancelled'

export interface Money {
  amount: string
  currency: string
}

export interface PublicUser {
  id: string
  email: string
  displayName: string
  globalRoles: string[]
  isClient: boolean
  locale: Language
  active: boolean
}

export interface ProjectHealth {
  projectId: string
  key: string
  name: string
  clientName?: string | null
  deliveryMethod: string
  openCriticalQuestions: number
  pendingApprovals: number
  unresolvedFindings: number
  stories: number
  approvedStories: number
  estimatedHours: number
  actualHours: number
  budget?: Money | null
  forecastCost?: Money | null
  nextMilestone?: string | null
  connectorHealth: string
  localOnly: boolean
}

export interface AIPolicy {
  cloudEnabled: boolean
  localOnly: boolean
  maxCloudClassification: Classification
  sanitizePayloads: boolean
  permittedDisclosureNote?: string | null
  localTranscription: boolean
  localOcr: boolean
  localEmbeddings: boolean
}

export interface WorkingCalendar {
  timezone: string
  workingDays: number[]
  hoursPerPersonDay: number
  holidays: string[]
  focusFactor: number
  allocationIncludesFocus: boolean
}

export interface QualityGates {
  requireAcceptanceCriteria: boolean
  requireTestsForStories: boolean
  blockOnCriticalFindings: boolean
  blockOnUnresolvedCriticalQuestions: boolean
  requireClientAcceptance: boolean
  maxCorrectionCycles: number
}

export type AnalystRole =
  | 'business_analyst' | 'ux_analyst' | 'data_analyst' | 'technical_analyst' | 'qa_analyst'

export interface Project {
  id: string
  key: string
  name: string
  clientName?: string | null
  description?: string | null
  languages: Language[]
  outputLanguage: Language
  deliveryMethod: 'scrum' | 'kanban'
  defaultClassification: Classification
  calendar: WorkingCalendar
  aiPolicy: AIPolicy
  qualityGates: QualityGates
  currency: string
  enabledAnalysts: AnalystRole[]
  archived: boolean
  primaryIntegrationId?: string | null
}

export interface Member {
  id: string
  userId: string
  email: string
  displayName: string
  roles: string[]
  deliveryRole?: string | null
  allocationPercent: number
  acceptanceAuthority: boolean
  revokedAt?: string | null
}

export interface DomainWarning {
  code: string
  message: string
  details?: Record<string, unknown> | null
}

export interface SourceView {
  id: string
  projectId: string
  title: string
  kind: string
  classification: string
  authority: string
  status: string
  currentVersion: number
  currentVersionId?: string | null
  excluded: boolean
  sizeBytes: number
  filename?: string | null
  warnings: DomainWarning[]
  chunkCount: number
  createdAt?: string | null
  accessRestricted: boolean
}

export interface SourceChunk {
  id: string
  ordinal: number
  text: string
  locatorKind: string
  locatorValue: string
  page?: number | null
  startMs?: number | null
  speaker?: string | null
  lowConfidence: boolean
}

export interface TranscriptSegment {
  id: string
  startMs: number
  endMs: number
  speaker?: string | null
  text: string
  confidence: number
  corrected: boolean
}

export interface AnalysisStage {
  role: AnalystRole
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'blocked'
  startedAt?: string | null
  finishedAt?: string | null
  outputSummary: Record<string, number>
  usage?: {
    modelId: string
    deployment: string
    promptTemplateVersion?: string | null
    promptTokens: number
    completionTokens: number
    latencyMs: number
  } | null
  error?: string | null
}

export interface AnalysisJob {
  id: string
  projectId: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'partial' | 'paused'
  stages: AnalysisStage[]
  progress: number
  message?: string | null
  createdCounts: Record<string, number>
  warnings: { stage: string; message: string }[]
  createdAt: string
  finishedAt?: string | null
}

export interface ReviewFinding {
  id: string
  role: string
  severity: Severity
  category: string
  title: string
  rationale: string
  recommendation?: string | null
  targetId?: string | null
  status: 'open' | 'resolved' | 'waived' | 'escalated'
  blocking: boolean
}

export interface Question {
  id: string
  stableId: string
  kind: string
  severity: Severity
  title: string
  detail: string
  proposedClarification?: string | null
  status: 'open' | 'answered' | 'deferred' | 'wont_resolve'
  answer?: string | null
  clientVisible: boolean
}

export interface Requirement {
  id: string
  stableId: string
  type: string
  title: string
  statement: string
  priority: Priority
  provenance: string
  confidence: number
  state: ArtifactState
  citations: Citation[]
}

export interface EvidenceLocator {
  sourceVersionId: string
  kind: string
  value: string
  startMs?: number | null
  speaker?: string | null
  page?: number | null
}

export interface Citation {
  locator: EvidenceLocator
  quote?: string | null
  note?: string | null
}

export interface GlossaryTerm {
  id: string
  term: string
  definition: string
  language: string
  translations: Record<string, string>
  approved: boolean
}

export interface EvidenceLink {
  id: string
  sourceVersionId?: string | null
  locator?: { kind: string; value: string } | null
  targetType: string
  targetId: string
  linkType: string
  rationale?: string | null
  createdBy?: string | null
}

export interface BacklogNode {
  id: string
  stableId: string
  type: ItemType
  parentId?: string | null
  title: string
  state: ArtifactState
  executionStatus: ExecutionStatus
  priority: Priority
  currentVersion: number
  approvedVersion?: number | null
  requiresReapproval: boolean
  stale: boolean
  storyPoints?: number | null
  effortHours: number
  rollupHours: number
  criteriaCount: number
  testCount: number
  openQuestionCount: number
  children: BacklogNode[]
}

export interface AcceptanceCriterion {
  id: string
  text: string
  outcomeLevel: boolean
  provenance: string
}

export interface ArtifactVersion {
  id: string
  itemId: string
  version: number
  state: ArtifactState
  title: string
  actor?: string | null
  need?: string | null
  benefit?: string | null
  description?: string | null
  acceptanceCriteria: AcceptanceCriterion[]
  businessRules: string[]
  assumptions: string[]
  functionalNotes?: string | null
  technicalNotes?: string | null
  nfrNotes?: string | null
  riskDrivers: string[]
  citations: Citation[]
  provenance: string
  generatedByRole?: string | null
  modelId?: string | null
  changeNote?: string | null
  approvedAt?: string | null
  approvalEventId?: string | null
  inheritedFromEventId?: string | null
}

export interface EstimateRollup {
  itemId: string
  unit: string
  hoursPerPersonDay: number
  ownHours: number
  ownOverheadHours: number
  childrenHours: number
  detailedHours: number
  roughParentHours?: number | null
  lowHours: number
  highHours: number
  personDays: number
  storyPoints?: number | null
  storyPointsComparable: boolean
  estimatedCost?: Money | null
  roleBreakdown: Record<string, number>
  warnings: string[]
  childrenEstimated: number
  childrenTotal: number
}

export interface ItemDetail {
  item: {
    id: string
    stableId: string
    type: ItemType
    title: string
    state: ArtifactState
    executionStatus: ExecutionStatus
    priority: Priority
    currentVersion: number
    approvedVersion?: number | null
    requiresReapproval: boolean
    stale: boolean
    rev: number
    parentId?: string | null
  }
  version: ArtifactVersion
  history: {
    id: string
    version: number
    state: string
    createdAt: string
    changeNote?: string | null
    generatedByRole?: string | null
    modelId?: string | null
    approvalEventId?: string | null
    inheritedFromEventId?: string | null
  }[]
  estimate?: {
    id: string
    method: string
    storyPoints?: number | null
    roleEfforts: { role: string; hours: number }[]
    overheadHours: number
    lowHours?: number | null
    highHours?: number | null
    confidenceLabel: string
    assumptions: string[]
  } | null
  roughParentEstimate?: { likelyHours?: number | null } | null
  estimateWarnings: string[]
  rollup: EstimateRollup
  tests: { id: string; stableId: string; title: string; testType: string; state: string; reviewState: string }[]
  dependencies: { id: string; toId: string; kind: string }[]
}

export interface ManifestEntry {
  itemId: string
  stableId: string
  itemType: string
  title: string
  version: number
  versionId: string
  state: string
  inherited: boolean
  referenceOnly: boolean
  previousApprovedVersion?: number | null
  changed: boolean
}

export interface Blocker {
  kind: string
  severity: Severity
  message: string
  targetId?: string | null
  targetTitle?: string | null
  waivable: boolean
}

export interface ApprovalManifest {
  id: string
  rootId: string
  rootType: string
  rootTitle: string
  rootVersion: number
  entries: ManifestEntry[]
  counts: Record<string, number>
  blockers: Blocker[]
  diff?: {
    added: ManifestEntry[]
    removed: ManifestEntry[]
    changed: ManifestEntry[]
    unchangedCount: number
  } | null
  estimateTotals: Record<string, number | string | null>
  clientVisibleEntries: string[]
  manifestHash: string
  generatedAt: string
}

export interface ApprovalEvent {
  id: string
  rootId: string
  rootType: string
  decision: 'approve' | 'reject'
  decidedBy: string
  decidedAt: string
  note?: string | null
  entries: ManifestEntry[]
  waivers: { blockerKind: string; rationale: string; waivedBy: string }[]
  committed: boolean
  revoked: boolean
  publishedTargets: string[]
}

export interface ChartSeries {
  key: string
  label: string
  points: { x?: string; category?: string; value: number | string; label?: string }[]
}

export interface ChartResponse {
  chart: string
  title: string
  unit: string
  asOf: string
  dataFreshness: string
  definition: string
  series: ChartSeries[]
  categories: string[]
  warnings: string[]
  insufficientData: boolean
  filters: Record<string, unknown>
}

export interface CoverageMatrix {
  rows: {
    criterionId: string
    criterionText: string
    itemStableId: string
    itemTitle: string
    testIds: string[]
    covered: boolean
  }[]
  uncoveredCriteria: number
  unlinkedTests: { stableId: string; title: string; reason: string }[]
  coveredPercent: number
  totalCriteria: number
  totalTests: number
}

export interface TestCase {
  id: string
  stableId: string
  title: string
  objective?: string | null
  storyId?: string | null
  criterionIds: string[]
  testType: string
  priority: Priority
  preconditions: string[]
  steps: { ordinal: number; action: string; expected?: string | null }[]
  expectedResults: string[]
  state: ArtifactState
  reviewState: string
  tags: string[]
  gherkin?: unknown
}

export interface Integration {
  id: string
  provider: 'jira' | 'azure_devops' | 'asana'
  name: string
  baseUrl?: string | null
  externalProjectKey?: string | null
  enabled: boolean
  isPrimary: boolean
  mappingApproved: boolean
  health: string
  lastSyncAt?: string | null
  typeMappings: { canonicalType: string; externalType?: string | null; strategy: string; note?: string | null }[]
  fieldRules: {
    canonicalField: string
    externalField?: string | null
    ownership: string
    direction: string
    supported: boolean
    note?: string | null
  }[]
  capabilityReport?: {
    provider: string
    discoveredAt: string
    projects: Record<string, unknown>[]
    itemTypes: Record<string, unknown>[]
    fields: Record<string, unknown>[]
    hierarchyLevels: string[]
    supportsWorklogs: boolean
    supportsWebhooks: boolean
    limitations: string[]
  } | null
}

export interface PublicationPreview {
  integrationId: string
  provider: string
  rows: {
    internalId: string
    stableId: string
    title: string
    canonicalType: string
    externalType?: string | null
    action: string
    mappedFields: Record<string, unknown>
    unsupportedFields: string[]
    warnings: string[]
  }[]
  blocked: { stableId: string; reason: string }[]
  hierarchyNote?: string | null
  informationLoss: boolean
  total: number
}

export interface ReportPreview {
  dataset: string
  columns: { key: string; label: string; type: string; clientSafe: boolean }[]
  rows: Record<string, unknown>[]
  totalRows: number
  truncated: boolean
  snapshotId: string
  generatedAt: string
  appliedPermissions: string[]
  warnings: string[]
  totals: Record<string, unknown>
}

export interface ShareGrant {
  id: string
  audienceEmail: string
  label?: string | null
  versions: { itemId: string; stableId: string; version: number; draft: boolean }[]
  allowAcceptance: boolean
  allowDownload: boolean
  includeDrafts: boolean
  expiresAt?: string | null
  revokedAt?: string | null
}

export interface ClientWorkspace {
  projectId: string
  items: {
    id: string
    stableId: string
    type: string
    title: string
    description?: string | null
    version: number
    state: string
    isDraft: boolean
    acceptanceCriteria: { id: string; text: string }[]
    businessRules: string[]
    assumptions: string[]
    clientAccepted: boolean
  }[]
  questions: { id: string; stableId: string; title: string; detail: string; severity: string; status: string }[]
  tests: { id: string; stableId: string; title: string; testType: string; state: string }[]
  specifications: { id: string; title: string; kind: string; body?: string | null; diagramSource?: string | null }[]
  allowAcceptance: boolean
  allowDownload: boolean
  includesDrafts: boolean
  note: string
}

export interface Specification {
  id: string
  kind: string
  title: string
  version: number
  state: ArtifactState
  body?: string | null
  diagramSource?: string | null
  structured: Record<string, unknown>
  generatedByRole?: string | null
  modelId?: string | null
  validation: Record<string, unknown>
}

export interface Iteration {
  id: string
  name: string
  goal?: string | null
  startDate: string
  endDate: string
  state: string
  team: string
  capacityHours: number
}

export interface CapacityRow {
  userId: string
  displayName: string
  role?: string | null
  scheduledHours: number
  leaveHours: number
  allocationPercent: number
  focusFactor: number
  availableHours: number
}

export interface BoardState {
  columns: {
    key: string
    name: string
    wipLimit?: number | null
    mapsToStatus?: string
    count: number
    overLimit: boolean
    items: {
      id: string
      stableId: string
      title: string
      rev: number
      executionStatus: string
      priority: Priority
      blockedReason?: string | null
      state: string
      approvedVersion?: number | null
    }[]
  }[]
  note: string
}
