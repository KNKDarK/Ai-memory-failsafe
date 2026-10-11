// Types mirror the JSON shapes returned by the FastAPI backend
// (see backend/api/serializers.py and the domain models). Kept in one place so
// the UI can never silently drift from the API contract.

export type OutcomeType =
  | "success"
  | "task_failure"
  | "tool_failure"
  | "timeout"
  | "invalid_output";

export type FailureCategory =
  | "missing_configuration"
  | "missing_dependency"
  | "invalid_api_response"
  | "tool_timeout"
  | "incorrect_assumption"
  | "permission_denied"
  | "resource_exhausted"
  | "unknown";

export type CauseStatus = "confirmed" | "hypothesis";
export type MemoryStatus = "active" | "outdated" | "incorrect" | "archived";
export type FeedbackVerdict = "useful" | "unhelpful" | "outdated" | "incorrect";
export type ExecutionMode = "baseline" | "naive" | "memory";
export type RetrievalMode =
  | "hashing_embedding"
  | "tfidf_fallback"
  | "neural_embedding"
  | "bm25_lexical"
  | "hybrid_lexical_embedding";

export interface HealthResponse {
  status: "ok" | "degraded";
  memory_database_available: boolean;
  error: string | null;
  environment: string;
  memory_count?: number;
  active_memory_count?: number;
}

export interface LifecycleConfig {
  stale_after_days: number;
  retire_after_days: number;
  obsolete_failure_ratio: number;
  min_uses_for_obsolete: number;
}

export interface LifecycleCounts {
  fresh: number;
  stale: number;
  obsolete: number;
  expired: number;
}

export interface LifecycleSummary {
  policy: LifecycleConfig;
  counts: LifecycleCounts;
  total: number;
  active: number;
  stale: number;
  obsolete: number;
  expired: number;
  planned_transitions: Array<Record<string, unknown>>;
}

export interface ConfigResponse {
  environment: string;
  offline: boolean;
  llm: { provider: string; real_model: boolean };
  embedding: { provider: string; dim: number };
  retrieval: {
    limit: number;
    min_score: number;
    min_similarity: number;
    method: string;
  };
  weights: {
    similarity: number;
    confidence: number;
    recency: number;
    feedback: number;
  };
  min_confidence_to_apply: number;
  lifecycle: LifecycleConfig;
  default_max_attempts: number;
  redact_secrets: boolean;
}

export interface ScenarioExpected {
  baseline_success: boolean;
  memory_success: boolean;
  prevention_expected: boolean;
}

export interface ScenarioSummary {
  id: string;
  name: string;
  category: string;
  task: string;
  description: string;
  max_attempts: number;
  simulated: boolean;
  notes: string;
  seed_memory_count: number;
  expected: ScenarioExpected;
}

export interface ToolResult {
  tool: string;
  ok: boolean;
  outcome_type: OutcomeType;
  output: unknown;
  error: string | null;
  error_code: string | null;
  evidence: string[];
  duration_ms: number;
  metadata: Record<string, unknown>;
}

export interface PlanStep {
  id: string;
  tool: string;
  description: string;
  args: Record<string, unknown>;
  is_prevention: boolean;
  prevention_source: string | null;
  optional: boolean;
}

export interface Plan {
  task: string;
  task_type: string;
  steps: PlanStep[];
  strategy: string;
  notes: string[];
}

export interface StepTrace {
  index: number;
  attempt: number;
  step: PlanStep;
  result: ToolResult;
}

export interface FailedStep {
  index: number;
  attempt: number;
  tool: string;
  error: string;
  error_code: string | null;
  outcome_type: OutcomeType;
}

export interface Recommendation {
  memory_id: string;
  prevention: string;
  prevention_actions: string[];
  confidence: number;
  applicable: boolean;
  applied: boolean;
  reason: string;
  followed: boolean | null;
}

export interface CauseCandidate {
  category: FailureCategory;
  cause: string;
  confidence: number;
  confirmed: boolean;
  error_code: string | null;
  tool: string | null;
  evidence: string[];
}

export interface FailureAnalysis {
  execution_id: string;
  task: string;
  task_type: string;
  action: string;
  failure: string;
  failure_category: FailureCategory;
  root_cause: string;
  cause_status: CauseStatus;
  confidence: number;
  evidence: string[];
  lesson: string;
  prevention: string;
  prevention_actions: string[];
  tags: string[];
  alternatives: CauseCandidate[];
  analyzer: string;
  created_at: string;
}

export interface RetrievalComponents {
  similarity: number;
  confidence: number;
  recency: number;
  feedback: number;
  status_penalty: number;
}

export interface FailureMemory {
  id: string;
  schema_version: number;
  task: string;
  task_type: string;
  action: string;
  failure: string;
  failure_category: FailureCategory;
  root_cause: string;
  cause_status: CauseStatus;
  evidence: string[];
  lesson: string;
  prevention: string;
  prevention_actions: string[];
  tags: string[];
  confidence: number;
  status: MemoryStatus;
  occurrence_count: number;
  use_count: number;
  success_count: number;
  failure_count: number;
  helpful_count: number;
  unhelpful_count: number;
  source_execution_id: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  effective_confidence: number;
  label: string;
  uses: number;
  success_rate: number | null;
}

export interface MemoryFeedback {
  id: string;
  memory_id: string;
  verdict: FeedbackVerdict;
  comment: string;
  execution_id: string | null;
  applied: boolean;
  created_at: string;
}

export interface RetrievalResult {
  memory: FailureMemory;
  rank: number;
  score: number;
  similarity: number;
  components: RetrievalComponents;
  matched_terms: string[];
  selected: boolean;
  reason: string;
  retrieval_mode: RetrievalMode;
}

export interface ExecutionRecord {
  execution_id: string;
  task: string;
  task_type: string;
  mode: ExecutionMode;
  environment_id: string;
  plan: Plan;
  traces: StepTrace[];
  outcome: OutcomeType;
  success: boolean;
  attempts: number;
  retries: number;
  error: string | null;
  error_code: string | null;
  applied_memory_ids: string[];
  recommendations: Recommendation[];
  retrieved: RetrievalResult[];
  started_at: string;
  finished_at: string;
  duration_ms: number;
  fingerprint: string;
  failed_step: FailedStep | null;
}

export interface TaskRun {
  run_id: string;
  task: string;
  task_type: string;
  mode: ExecutionMode;
  environment_id: string;
  max_attempts: number;
  attempts: ExecutionRecord[];
  final_success: boolean;
  final_outcome: OutcomeType;
  memory_ids_applied: string[];
  memory_ids_created: string[];
  memory_ids_reinforced: string[];
  retrieved_memory_ids: string[];
  prevented_failure: boolean;
  prevention_evidence: string;
  analyses: FailureAnalysis[];
  notes: string[];
  started_at: string;
  finished_at: string;
  attempts_used: number;
  duration_ms: number;
  success: boolean;
}

export interface EnvironmentSpec {
  id?: string | null;
  config?: Record<string, string>;
  secrets?: Record<string, string>;
  packages?: Record<string, string>;
  registry?: Record<string, string>;
  services?: Record<string, Record<string, unknown>>;
  faults?: Record<string, unknown>;
}

export interface RunTaskRequest {
  task: string;
  mode: ExecutionMode;
  max_attempts: number;
  environment?: EnvironmentSpec | null;
}

export interface CompareTasksRequest {
  task: string;
  max_attempts: number;
  environment?: EnvironmentSpec | null;
}

export interface CompareResult {
  task: string;
  max_attempts: number;
  baseline: TaskRun;
  memory: TaskRun;
}

export interface RetrievalPreviewRequest {
  task?: string;
  scenario_id?: string;
  limit?: number;
}

export interface RetrievalPreviewResponse {
  task: string;
  retrieval_mode: RetrievalMode | null;
  selected_ids: string[];
  candidate_count: number;
  results: RetrievalResult[];
}

export interface MemoryListResponse {
  items: FailureMemory[];
  total: number;
  limit: number;
  offset: number;
}

export interface MemoryStats {
  total_memories: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  repeated_failure_patterns: number;
  total_occurrences: number;
  times_applied: number;
  prevention_successes: number;
  prevention_failures: number;
  prevention_success_rate: number | null;
  lifecycle: LifecycleSummary;
}

export interface ContradictionMemory {
  id: string;
  prevention: string;
  effective_confidence: number;
}

export interface Contradiction {
  task_type: string;
  action: string;
  preferred_id: string;
  memories: ContradictionMemory[];
}

export interface ContradictionsResponse {
  count: number;
  conflicts: Contradiction[];
}

export interface MemoryDetailResponse {
  memory: FailureMemory;
  feedback: MemoryFeedback[];
}

export interface MemoryMutationResponse {
  memory: FailureMemory;
}

export interface FeedbackMutationResponse {
  memory: FailureMemory;
  feedback: MemoryFeedback;
}

export interface ScenarioRunResponse {
  scenario: ScenarioSummary;
  baseline: TaskRun;
  memory: TaskRun;
  retrieval: RetrievalResult[];
  metrics: { baseline: RunMetrics; memory: RunMetrics };
  memory_stats: { before: MemoryStats; after: MemoryStats };
  seeded_memory_ids: string[];
}

export interface RunMetrics {
  [key: string]: unknown;
}

export interface ScenarioDetail {
  scenario_id: string;
  name: string;
  category: string;
  simulated: boolean;
}

export interface EvaluationScenarioRow {
  scenario_id: string;
  name: string;
  category: string;
  description: string;
  simulated: boolean;
  notes: string;
  expected: ScenarioExpected;
  baseline: RunMetrics;
  memory: RunMetrics;
  prevention_evidence: string;
}

export interface AggregateMetrics {
  tasks: number;
  successes: number;
  failures: number;
  success_rate: number;
  failure_rate: number;
  repeated_failure_tasks: number;
  repeated_failure_rate: number;
  prevented_failures: number;
  harmful_memory_applications: number;
  memories_created: number;
  total_attempts: number;
  avg_attempts: number;
  total_retries: number;
  avg_retries: number;
  avg_steps: number;
  avg_duration_ms: number;
}

export interface RelevanceMetrics {
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  precision: number;
  recall: number;
}

export interface ArmMetrics {
  success_rate: number;
  avg_attempts: number;
  avg_retries: number;
  prevented_failures: number;
  harmful_memory_applications: number;
  memories_created: number;
}

export interface RetrievalMethodMetrics {
  precision: number | null;
  recall: number | null;
  f1: number | null;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
}

export interface RetrievalMethodComparison {
  selection_rule: string;
  probe_count: number;
  methods: Record<string, RetrievalMethodMetrics>;
}

export interface EvaluationLifecycleView {
  total: number;
  active: number;
  counts: LifecycleCounts;
  stale: number;
  obsolete: number;
  expired: number;
  planned_transitions: number;
}

export interface EvaluationLifecycle {
  unique_memories: number;
  at_run: EvaluationLifecycleView;
  projected: EvaluationLifecycleView & { horizon_days: number };
}

export interface EvaluationReport {
  schema_version: number;
  generated_at: string;
  simulated: boolean;
  retrieval_mode: RetrievalMode;
  settings: Record<string, unknown>;
  scenario_count: number;
  scenarios_expectations_met: number;
  scenarios: EvaluationScenarioRow[];
  aggregate: {
    baseline: AggregateMetrics;
    naive?: AggregateMetrics;
    memory: AggregateMetrics;
  };
  arms?: Record<string, ArmMetrics>;
  comparison: Record<string, unknown>;
  retrieval_relevance: {
    scope: Record<string, string>;
    probes: Array<Record<string, unknown>>;
    application: RelevanceMetrics;
    selection: RelevanceMetrics;
    precision: number;
    recall: number;
  };
  retrieval_method_comparison?: RetrievalMethodComparison;
  lifecycle?: EvaluationLifecycle;
  methodology: Record<string, unknown>;
  limitations: string[];
}
