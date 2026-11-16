import type {
  EdgeSpec,
  Issue,
  NodeId,
  RunEvent,
  RunSnapshot,
  Trace,
} from "../api/types";

export type NodeStatus =
  | "idle"
  | "running"
  | "success"
  | "warn"
  | "error"
  | "paused"
  | "skipped";

export type EdgeState = "pending" | "traversed" | "skipped" | "hit";

export interface NodeState {
  status: NodeStatus;
  traces: Trace[];
}

export interface IssueEntry extends Issue {
  node: string;
  at: string;
}

export interface LlmCall {
  node: string;
  model: string | null;
  version: string | null;
  duration: number;
  issues: Issue[];
  summary: string;
  at: string;
}

export interface Derived {
  nodes: Record<string, NodeState>;
  edges: Record<string, EdgeState>;
  currentNode: NodeId | null;
  pausedTarget: NodeId | null;
  issues: IssueEntry[];
  attentionIssues: IssueEntry[];
  routineCount: number;
  llmCalls: LlmCall[];
  humanEvents: Trace[];
  sequence: NodeId[];
  warningCount: number;
  errorCount: number;
}

const NODE_IDS = new Set([
  "user",
  "planner",
  "teacher",
  "student",
  "critic",
  "target",
  "output",
  "manager",
]);

/**
 * 常规缺失：节点在流程早期读取不到的待选字段，以及 TSC 循环中按设计被置空的字段 3。
 * 它们是文档定义的 2 级报错，但属于正常路径，不应把节点染成警告色。
 */
const ROUTINE_ISSUE = /^E2-(?:MISSING|CONDITIONAL-MISSING)-|^E2-SCHEMA-OPTIMIZED-PROMPT$/;

export function isRoutineIssue(issue: Issue): boolean {
  return ROUTINE_ISSUE.test(issue.code);
}

function isNode(value: string | undefined): value is NodeId {
  return value !== undefined && NODE_IDS.has(value);
}

function nodeTraces(snapshot: RunSnapshot | null): Trace[] {
  const traces = snapshot?.values.trace ?? [];
  return traces.filter((trace) => isNode(trace.node));
}

function buildSequence(traces: Trace[], events: RunEvent[]): NodeId[] {
  const fromTraces: NodeId[] = [];
  for (const trace of traces) {
    if (isNode(trace.node) && fromTraces[fromTraces.length - 1] !== trace.node) {
      fromTraces.push(trace.node);
    }
  }
  const fromEvents: NodeId[] = [];
  for (const event of events) {
    if (event.event === "node_start" && isNode(event.node)) {
      if (fromEvents[fromEvents.length - 1] !== event.node) {
        fromEvents.push(event.node);
      }
    }
  }
  return fromEvents.length > fromTraces.length ? fromEvents : fromTraces;
}

function runningNode(events: RunEvent[], status: string): NodeId | null {
  if (status !== "running") return null;
  let current: NodeId | null = null;
  for (const event of events) {
    if (event.event === "node_start" && isNode(event.node)) {
      current = event.node;
    } else if (event.event === "node_end" && isNode(event.node) && current === event.node) {
      current = null;
    }
  }
  return current;
}

export function deriveRun(
  snapshot: RunSnapshot | null,
  events: RunEvent[],
  edgeList: EdgeSpec[],
): Derived {
  const traces = nodeTraces(snapshot);
  const sequence = buildSequence(traces, events);
  const status = snapshot?.status ?? "pending";
  const current = runningNode(events, status);
  const interrupt = snapshot?.interrupts?.[0];
  const pausedTarget = interrupt ? (interrupt.edge_id.split("->")[1] as NodeId) : null;

  const visited = new Set<string>();
  for (let index = 1; index < sequence.length; index += 1) {
    const edgeId = `${sequence[index - 1]}->${sequence[index]}`;
    if (edgeList.some((edge) => edge.edge_id === edgeId)) {
      visited.add(edgeId);
    }
  }

  const nodes: Record<string, NodeState> = {};
  for (const edge of edgeList) {
    for (const node of [edge.source, edge.target]) {
      if (nodes[node]) continue;
      const nodeTraceList = traces.filter((trace) => trace.node === node);
      const last = nodeTraceList[nodeTraceList.length - 1];
      let nodeStatus: NodeStatus = "idle";
      if (last) {
        if (current === node) {
          nodeStatus = "running";
        } else if (last.issues.some((issue) => issue.level === 1)) {
          nodeStatus = "error";
        } else if (status === "paused" && pausedTarget === node) {
          nodeStatus = "paused";
        } else if (last.issues.some((issue) => issue.level === 2 && !isRoutineIssue(issue))) {
          nodeStatus = "warn";
        } else {
          nodeStatus = "success";
        }
      } else if (
        sequence.length > 0 &&
        (status === "completed" || status === "failed")
      ) {
        nodeStatus = "skipped";
      }
      nodes[node] = { status: nodeStatus, traces: nodeTraceList };
    }
  }

  const edges: Record<string, EdgeState> = {};
  for (const edge of edgeList) {
    const sourceIndex = sequence.lastIndexOf(edge.source);
    if (interrupt?.edge_id === edge.edge_id) {
      edges[edge.edge_id] = "hit";
    } else if (visited.has(edge.edge_id)) {
      edges[edge.edge_id] = "traversed";
    } else if (sourceIndex >= 0 && sourceIndex < sequence.length - 1) {
      edges[edge.edge_id] = "skipped";
    } else {
      edges[edge.edge_id] = "pending";
    }
  }

  const issues: IssueEntry[] = [];
  for (const trace of traces) {
    for (const issue of trace.issues ?? []) {
      issues.push({ ...issue, node: trace.node, at: trace.started_at });
    }
  }
  const attentionIssues = issues.filter((issue) => !isRoutineIssue(issue));

  const llmCalls: LlmCall[] = traces
    .filter((trace) => trace.model !== null && trace.model !== undefined)
    .map((trace) => ({
      node: trace.node,
      model: trace.model,
      version: trace.prompt_version,
      duration: trace.duration_ms,
      issues: trace.issues ?? [],
      summary: trace.summary,
      at: trace.started_at,
    }));

  return {
    nodes,
    edges,
    currentNode: current,
    pausedTarget,
    issues,
    attentionIssues,
    routineCount: issues.length - attentionIssues.length,
    llmCalls,
    humanEvents: traces.filter((trace) => trace.human_intervention),
    sequence,
    warningCount: issues.filter((issue) => issue.level === 2 && !isRoutineIssue(issue)).length,
    errorCount: issues.filter((issue) => issue.level === 1).length,
  };
}
