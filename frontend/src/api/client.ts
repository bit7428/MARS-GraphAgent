import type {
  ConnectionTest,
  CreateRunPayload,
  DeleteRunResult,
  EdgeSpec,
  Meta,
  NodeConfig,
  NodeId,
  PromptVersionView,
  RunLog,
  RunSnapshot,
  RunSummary,
  SecretStatus,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      detail = await response.text().catch(() => detail);
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  meta: () => request<Meta>("/meta"),

  listRuns: () => request<RunSummary[]>("/runs"),

  getRun: (id: string) => request<RunSnapshot>(`/runs/${id}`),

  createRun: (payload: CreateRunPayload) =>
    request<{ thread_id: string }>("/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  setBreakpoints: (id: string, edgeIds: string[]) =>
    request<RunSnapshot>(`/runs/${id}/breakpoints`, {
      method: "POST",
      body: JSON.stringify({ edge_ids: edgeIds }),
    }),

  resume: (
    id: string,
    payload: {
      action: "continue" | "reroute" | "abort";
      target?: string;
      operator?: string;
      initial_prompt?: string;
      optimization_goal?: string;
      supplement_mode?: "append" | "replace";
    },
  ) =>
    request<RunSnapshot>(`/runs/${id}/resume`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getRunLog: (id: string, tail = 200) =>
    request<RunLog>(`/runs/${id}/log?tail=${tail}`),

  deleteRunData: (id: string) =>
    request<DeleteRunResult>(`/runs/${id}/data`, { method: "DELETE" }),

  listEdges: () => request<EdgeSpec[]>("/graph/edges"),

  listNodeConfigs: () => request<NodeConfig[]>("/config/nodes"),

  patchNodeConfig: (node: NodeId, patch: Partial<NodeConfig>) =>
    request<NodeConfig>(`/config/nodes/${node}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  resetNodeConfig: (node: NodeId) =>
    request<NodeConfig>(`/config/nodes/${node}`, { method: "DELETE" }),

  listSecrets: () => request<SecretStatus[]>("/config/secrets"),

  setSecret: (envName: string, apiKey: string) =>
    request<SecretStatus>(`/config/secrets/${envName}`, {
      method: "PUT",
      body: JSON.stringify({ api_key: apiKey }),
    }),

  clearSecret: (envName: string) =>
    request<SecretStatus>(`/config/secrets/${envName}`, { method: "DELETE" }),

  testNode: (node: NodeId) =>
    request<ConnectionTest>(`/config/nodes/${node}/test`, { method: "POST" }),

  getPrompt: (node: NodeId, version?: string) =>
    request<PromptVersionView>(
      `/config/nodes/${node}/prompt${version ? `?version=${encodeURIComponent(version)}` : ""}`,
    ),

  savePrompt: (node: NodeId, version: string, content: string) =>
    request<PromptVersionView>(`/config/nodes/${node}/prompt`, {
      method: "PUT",
      body: JSON.stringify({ version, content }),
    }),

  deletePrompt: (node: NodeId, version: string) =>
    request<PromptVersionView>(
      `/config/nodes/${node}/prompt?version=${encodeURIComponent(version)}`,
      { method: "DELETE" },
    ),
};

export const eventsUrl = (id: string) => `/runs/${id}/events?start_index=0`;
