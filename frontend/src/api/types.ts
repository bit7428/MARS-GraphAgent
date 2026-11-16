export type RunStatus = "pending" | "running" | "paused" | "completed" | "failed";
export type NodeId =
  | "user"
  | "planner"
  | "teacher"
  | "student"
  | "critic"
  | "target"
  | "output"
  | "manager";

export type Comparator = "gte" | "lte" | "eq";

export interface Criterion {
  name: string;
  threshold: number;
  comparator: Comparator;
}

export interface Subtask {
  id: string;
  content: string;
  source: "planner" | "critic" | "user";
  status: "pending" | "done" | "dropped";
  score: number;
}

export interface Question {
  id: string;
  content: string;
  target_task_id: string | null;
  status: "open" | "resolved" | "dropped";
  score: number;
}

export interface ScoreDetail {
  score: number;
  dimensions: Record<string, number>;
  summary: string;
  evidence: string[];
}

export interface Issue {
  code: string;
  level: 1 | 2;
  field: string | null;
  message: string;
}

export interface Trace {
  node: string;
  started_at: string;
  duration_ms: number;
  model: string | null;
  prompt_version: string | null;
  issues: Issue[];
  writes: string[];
  side_effects: string[];
  summary: string;
  human_intervention?: boolean;
  original_route?: string | null;
  new_route?: string | null;
  operator?: string | null;
  at?: string | null;
}

export interface RunValues {
  initial_prompt?: string;
  working_prompt?: string;
  optimized_prompt?: string;
  optimization_goal?: string;
  subtasks?: Subtask[];
  questions?: Question[];
  heuristic_score?: ScoreDetail | null;
  execution_score?: ScoreDetail | null;
  performance_criteria?: Criterion[];
  tsc_count?: number;
  m_count?: number;
  report_md?: string | null;
  trace?: Trace[];
  route_critic?: "teacher" | "target";
  route_target?: "output" | "manager";
  route_manager?: "user" | "planner" | "teacher" | "output";
}

export interface InterruptPayload {
  edge_id: string;
  state_digest: string;
  route: string;
  allowed_reroutes: string[];
  counters?: { tsc_count: number; m_count: number };
}

export interface RunSnapshot {
  thread_id: string;
  name: string;
  status: RunStatus;
  next: string[];
  interrupts: InterruptPayload[];
  values: RunValues;
  breakpoints: string[];
  tsc_max: number;
  m_max: number;
  acceptance: string;
  created_at: string;
  finished_at: string;
}

export interface RunEvent {
  event: string;
  thread_id: string;
  node?: string;
  writes?: string[];
  trace?: Trace | null;
  message?: string;
  payload?: InterruptPayload;
  counters?: { tsc_count: number; m_count: number };
  issues?: Issue[];
  optimized_prompt?: string;
  report_md?: string;
  decision?: unknown;
  edge_ids?: string[];
}

export interface EdgeSpec {
  edge_id: string;
  source: NodeId;
  target: NodeId;
  kind: "static" | "conditional";
  condition: string;
  side_effects: string[];
  breakpoint: boolean;
}

export interface NodeConfig {
  node: NodeId;
  model: string;
  base_url: string | null;
  api_key_env: string;
  temperature: number;
  timeout_s: number;
  max_retries: number;
  prompt_version: string;
  available_versions: string[];
}

export interface RunSummary {
  thread_id: string;
  name: string;
  status: RunStatus;
  created_at: string;
  finished_at: string;
  tsc_max: number;
  m_max: number;
  tsc_count: number;
  m_count: number;
  acceptance: string;
  next: string[];
}

export interface CreateRunPayload {
  name?: string;
  initial_prompt: string;
  optimization_goal: string;
  performance_criteria: Criterion[];
  breakpoints: string[];
  tsc_max: number;
  m_max: number;
}

export interface Meta {
  tsc_max: number;
  m_max: number;
  data_dir: string;
  secret_path: string;
  prompt_root: string;
}

export interface SecretStatus {
  env_name: string;
  configured: boolean;
  tail: string | null;
  source: "env" | "file" | null;
  used_by: NodeId[];
}

export interface PromptVersionView {
  node: NodeId;
  version: string;
  content: string;
  versions: string[];
  recommended: string;
}

export interface ConnectionTest {
  ok: boolean;
  model: string;
  latency_ms: number;
  message: string;
}

export interface RunLog {
  thread_id: string;
  lines: string[];
}

export interface DeleteRunResult {
  thread_id: string;
  deleted: boolean;
}
