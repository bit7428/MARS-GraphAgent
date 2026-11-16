import type { NodeId } from "../api/types";

export const NODE_W = 180;
export const NODE_H = 88;
export const CANVAS_W = 984;
export const CANVAS_H = 596;

export interface NodeBox {
  id: NodeId;
  title: string;
  cn: string;
  x: number;
  y: number;
  role: "input" | "llm" | "verify" | "sink" | "control";
}

export const NODES: NodeBox[] = [
  { id: "user", title: "USER", cn: "入口", x: 96, y: 56, role: "input" },
  { id: "planner", title: "PLANNER", cn: "规划", x: 400, y: 56, role: "llm" },
  { id: "teacher", title: "TEACHER", cn: "启发", x: 704, y: 56, role: "llm" },
  { id: "student", title: "STUDENT", cn: "执行", x: 704, y: 246, role: "llm" },
  { id: "critic", title: "CRITIC", cn: "监督", x: 400, y: 246, role: "llm" },
  { id: "target", title: "TARGET", cn: "验证", x: 96, y: 246, role: "verify" },
  { id: "manager", title: "MANAGER", cn: "管控", x: 400, y: 436, role: "control" },
  { id: "output", title: "OUTPUT", cn: "输出", x: 96, y: 436, role: "sink" },
];

export const NODE_MAP: Record<string, NodeBox> = Object.fromEntries(
  NODES.map((node) => [node.id, node]),
);

export const NODE_ORDER: NodeId[] = [
  "user",
  "planner",
  "teacher",
  "student",
  "critic",
  "target",
  "manager",
  "output",
];

export type Point = [number, number];

export interface EdgeRoute {
  points: Point[];
  label?: Point;
  labelAlign?: "start" | "middle" | "end";
}

/**
 * 固定分层布局的手工路由：正交折线，避免穿过节点卡片。
 * 未登记的边回落到「源中心 → 目标中心」直线，保证后端扩展边表时不崩。
 */
export const EDGE_ROUTES: Record<string, EdgeRoute> = {
  "user->planner": { points: [[276, 100], [400, 100]] },
  "planner->teacher": { points: [[580, 100], [704, 100]] },
  "teacher->student": { points: [[794, 144], [794, 246]] },
  "student->critic": { points: [[704, 290], [580, 290]] },
  "critic->teacher": {
    points: [[490, 246], [490, 196], [830, 196], [830, 144]],
    label: [660, 182],
  },
  "critic->target": { points: [[400, 290], [276, 290]], label: [338, 290] },
  "target->output": {
    points: [[186, 334], [186, 436]],
    label: [188, 385],
    labelAlign: "start",
  },
  "target->manager": {
    points: [[276, 314], [330, 314], [330, 480], [400, 480]],
    label: [334, 398],
    labelAlign: "start",
  },
  "manager->output": { points: [[400, 464], [276, 464]], label: [338, 464] },
  "manager->user": {
    points: [[490, 436], [490, 404], [52, 404], [52, 100], [96, 100]],
    label: [64, 346],
    labelAlign: "start",
  },
  "manager->planner": {
    points: [[450, 436], [450, 410], [352, 410], [352, 152], [430, 152], [430, 144]],
    label: [364, 346],
    labelAlign: "start",
  },
  "manager->teacher": {
    points: [[580, 464], [640, 464], [640, 180], [740, 180], [740, 144]],
    label: [652, 346],
    labelAlign: "start",
  },
};

export function routeFor(edgeId: string, source: NodeId, target: NodeId): EdgeRoute {
  const route = EDGE_ROUTES[edgeId];
  if (route) {
    return route;
  }
  const from = NODE_MAP[source];
  const to = NODE_MAP[target];
  return {
    points: [
      [from.x + NODE_W / 2, from.y + NODE_H / 2],
      [to.x + NODE_W / 2, to.y + NODE_H / 2],
    ],
  };
}

/** 折线转圆角路径，避免直角生硬。 */
export function roundedPath(points: Point[], radius = 10): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0][0]} ${points[0][1]}`;
  let path = `M ${points[0][0]} ${points[0][1]}`;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    if (index === points.length - 1) {
      path += ` L ${current[0]} ${current[1]}`;
      continue;
    }
    const next = points[index + 1];
    const inVector: Point = [current[0] - previous[0], current[1] - previous[1]];
    const outVector: Point = [next[0] - current[0], next[1] - current[1]];
    const inLength = Math.hypot(inVector[0], inVector[1]) || 1;
    const outLength = Math.hypot(outVector[0], outVector[1]) || 1;
    const r = Math.min(radius, inLength / 2, outLength / 2);
    const enter: Point = [
      current[0] - (inVector[0] / inLength) * r,
      current[1] - (inVector[1] / inLength) * r,
    ];
    const exit: Point = [
      current[0] + (outVector[0] / outLength) * r,
      current[1] + (outVector[1] / outLength) * r,
    ];
    path += ` L ${enter[0]} ${enter[1]} Q ${current[0]} ${current[1]} ${exit[0]} ${exit[1]}`;
  }
  return path;
}

export function midOf(points: Point[]): Point {
  if (points.length < 2) return points[0] ?? [0, 0];
  let total = 0;
  const segments: number[] = [];
  for (let index = 1; index < points.length; index += 1) {
    const length = Math.hypot(
      points[index][0] - points[index - 1][0],
      points[index][1] - points[index - 1][1],
    );
    segments.push(length);
    total += length;
  }
  let remaining = total / 2;
  for (let index = 0; index < segments.length; index += 1) {
    if (remaining <= segments[index]) {
      const ratio = segments[index] === 0 ? 0 : remaining / segments[index];
      const start = points[index];
      const end = points[index + 1];
      return [start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio];
    }
    remaining -= segments[index];
  }
  return points[points.length - 1];
}
