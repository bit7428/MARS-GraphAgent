import type { NodeId } from "../api/types";

export interface FieldMeta {
  index: number;
  key: string;
  name: string;
  writer: string;
  readonly: boolean;
  kind: "text" | "list" | "score" | "criteria" | "counter";
  hint: string;
}

export const FIELDS: FieldMeta[] = [
  {
    index: 1,
    key: "initial_prompt",
    name: "初始提示词",
    writer: "仅 User 可更新",
    readonly: true,
    kind: "text",
    hint: "优化的基础模板；运行期只能在断点补充输入时更新",
  },
  {
    index: 2,
    key: "working_prompt",
    name: "待优化提示词",
    writer: "Planner / Critic 边副作用",
    readonly: true,
    kind: "text",
    hint: "TSC 循环的临时模板；Critic 进入循环时由 3 赋值得来",
  },
  {
    index: 3,
    key: "optimized_prompt",
    name: "已优化提示词",
    writer: "Student / Manager 清理",
    readonly: true,
    kind: "text",
    hint: "局部 TSC 循环的产物，也是最终输出",
  },
  {
    index: 4,
    key: "optimization_goal",
    name: "优化方向及目的",
    writer: "仅 User 可更新",
    readonly: true,
    kind: "text",
    hint: "方向性约束；与 9 性能指标共同决定验收口径",
  },
  {
    index: 5,
    key: "subtasks",
    name: "子任务列表",
    writer: "Planner / Critic",
    readonly: true,
    kind: "list",
    hint: ">85 分子任务由 Critic 划去（dropped），记录保留",
  },
  {
    index: 6,
    key: "questions",
    name: "启发式提问列表",
    writer: "Teacher / Critic",
    readonly: true,
    kind: "list",
    hint: ">60 分提问由 Critic 划去（dropped），记录保留",
  },
  {
    index: 7,
    key: "heuristic_score",
    name: "启发得分及摘要",
    writer: "Critic",
    readonly: true,
    kind: "score",
    hint: "低于 60 时 Teacher 应优先聚焦低分维度",
  },
  {
    index: 8,
    key: "execution_score",
    name: "执行得分及摘要",
    writer: "Critic",
    readonly: true,
    kind: "score",
    hint: "低于 60 时 Teacher 应优先聚焦低分维度",
  },
  {
    index: 9,
    key: "performance_criteria",
    name: "性能指标",
    writer: "入口配置（只读）",
    readonly: true,
    kind: "criteria",
    hint: "初始化后为不变量，任何节点不得修改",
  },
  {
    index: 10,
    key: "tsc_count",
    name: "TSC 循环次数",
    writer: "Critic 递增",
    readonly: true,
    kind: "counter",
    hint: "达到上限且未达标时结束局部循环进入 Target",
  },
  {
    index: 11,
    key: "m_count",
    name: "M 循环次数",
    writer: "Manager 递增",
    readonly: true,
    kind: "counter",
    hint: "达到上限后不再回退，强制 Output 并生成失败报告",
  },
];

export interface NodeContractMeta {
  required: number[];
  optional: number[];
  writes: number[];
  sideEffects: number[];
}

export const NODE_CONTRACTS: Record<NodeId, NodeContractMeta> = {
  user: { required: [], optional: [1, 4], writes: [1, 4], sideEffects: [] },
  planner: { required: [1, 4], optional: [3, 5], writes: [2, 5], sideEffects: [] },
  teacher: {
    required: [2, 5],
    optional: [6, 7, 8, 1, 3, 4],
    writes: [6],
    sideEffects: [],
  },
  student: { required: [2, 4, 6], optional: [5], writes: [3], sideEffects: [] },
  critic: {
    required: [3, 4, 5, 6],
    optional: [2, 7, 8],
    writes: [5, 6, 7, 8, 10],
    sideEffects: [2, 3],
  },
  target: { required: [3, 9, 10, 11], optional: [], writes: [], sideEffects: [] },
  output: { required: [3], optional: [], writes: [], sideEffects: [] },
  manager: {
    required: [2, 3, 5, 6, 7, 8, 9, 10, 11],
    optional: [],
    writes: [11],
    sideEffects: [2, 3, 5, 6, 7, 8, 10],
  },
};

export const fieldName = (index: number): string =>
  FIELDS.find((field) => field.index === index)?.name ?? `字段 ${index}`;
