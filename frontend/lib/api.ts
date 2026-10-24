// Thin, typed client for the FastAPI backend.
//
// The base URL is configurable via NEXT_PUBLIC_API_BASE_URL and defaults to the
// local development server. All calls are client-side; the backend is expected
// to run locally and the app degrades gracefully (with an error banner) when it
// is unreachable.

import type {
  CompareResult,
  CompareTasksRequest,
  ConfigResponse,
  ContradictionsResponse,
  EvaluationReport,
  FailureMemory,
  FeedbackMutationResponse,
  FeedbackVerdict,
  HealthResponse,
  LifecycleSummary,
  LlmEvaluationReport,
  LlmEvaluationRequest,
  LlmReportSummary,
  MemoryAttributionLab,
  MemoryDetailResponse,
  MemoryListResponse,
  MemoryMutationResponse,
  MemoryStats,
  MemoryStatus,
  ReplayRunRequest,
  ReplayRunResponse,
  RetrievalPreviewRequest,
  RetrievalPreviewResponse,
  RunTaskRequest,
  ScenarioRunResponse,
  ScenarioSummary,
  StepTraceLab,
  TaskRun,
} from "./types";

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
).replace(/\/+$/, "");

// Optional shared token for the backend's API access control. When the backend
// is started with API_AUTH_TOKEN set, pass the same value here (inlined at
// build time) so the dashboard can keep running tasks and mutating memories.
// Single-user local deployments only — see the "API security" README section.
const API_TOKEN = process.env.NEXT_PUBLIC_API_TOKEN || "";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      `Cannot reach the backend at ${API_BASE}. Start it with "uvicorn backend.api.routes:app".`,
    );
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body) {
        const raw = (body as { detail: unknown }).detail;
        detail = typeof raw === "string" ? raw : JSON.stringify(raw);
      }
    } catch {
      /* non-JSON error body; keep the status text */
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

const post = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

const patch = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  config: () => request<ConfigResponse>("/api/config"),

  listScenarios: () => request<ScenarioSummary[]>("/api/scenarios"),
  runScenario: (id: string) =>
    post<ScenarioRunResponse>(`/api/scenarios/${encodeURIComponent(id)}/run`, {}),

  runTask: (body: RunTaskRequest) => post<TaskRun>("/api/tasks/run", body),
  compareTask: (body: CompareTasksRequest) =>
    post<CompareResult>("/api/tasks/compare", body),

  previewRetrieval: (body: RetrievalPreviewRequest) =>
    post<RetrievalPreviewResponse>("/api/retrieval/preview", body),

  listMemories: (params?: {
    status?: MemoryStatus | "";
    task_type?: string;
    limit?: number;
    offset?: number;
    include_inactive?: boolean;
  }) => {
    const search = new URLSearchParams();
    if (params?.status) search.set("status", params.status);
    if (params?.task_type) search.set("task_type", params.task_type);
    if (params?.limit != null) search.set("limit", String(params.limit));
    if (params?.offset != null) search.set("offset", String(params.offset));
    if (params?.include_inactive != null)
      search.set("include_inactive", String(params.include_inactive));
    const qs = search.toString();
    return request<MemoryListResponse>(`/api/memories${qs ? `?${qs}` : ""}`);
  },
  memoryStats: () => request<MemoryStats>("/api/memories/stats"),
  contradictions: () =>
    request<ContradictionsResponse>("/api/memories/contradictions"),
  lifecycle: () => request<LifecycleSummary>("/api/memories/lifecycle"),
  applyLifecycle: () =>
    post<{
      applied: number;
      transitions: Array<Record<string, unknown>>;
      report: LifecycleSummary;
    }>("/api/memories/lifecycle/apply", {}),
  getMemory: (id: string) =>
    request<MemoryDetailResponse>(`/api/memories/${encodeURIComponent(id)}`),
  addFeedback: (id: string, verdict: FeedbackVerdict, comment = "") =>
    post<FeedbackMutationResponse>(
      `/api/memories/${encodeURIComponent(id)}/feedback`,
      { verdict, comment },
    ),
  setStatus: (id: string, status: MemoryStatus) =>
    patch<MemoryMutationResponse>(
      `/api/memories/${encodeURIComponent(id)}/status`,
      { status },
    ),
  deleteMemory: (id: string) =>
    request<{ deleted: boolean; memory_id: string }>(
      `/api/memories/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),

  runEvaluation: (scenarios?: string[]) =>
    post<EvaluationReport>("/api/evaluation/run", {
      scenarios: scenarios ?? null,
    }),
  evaluationReport: () =>
    request<EvaluationReport>("/api/evaluation/report"),

  // LLM evaluation benchmark (requires a configured real LLM provider; the
  // response honestly reports status "skipped"/"aborted" instead of fabricating
  // model results when none is available).
  runLlmEvaluation: (body: LlmEvaluationRequest, signal?: AbortSignal) =>
    request<LlmEvaluationReport>("/api/evaluation/llm/run", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
    }),
  llmReports: () =>
    request<{ reports: LlmReportSummary[] }>("/api/evaluation/llm/reports"),
  llmReport: (runId: string) =>
    request<LlmEvaluationReport>(
      `/api/evaluation/llm/reports/${encodeURIComponent(runId)}`,
    ),

  // Memory Replay Lab
  replayRun: (body: ReplayRunRequest) =>
    post<ReplayRunResponse>("/lab/replay", body),
};

export type { FailureMemory };
