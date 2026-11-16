import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import type { Issue, NodeId, RunSnapshot, RunValues, ScoreDetail, Trace } from "../api/types";
import { Icon } from "../components/Icons";
import { Badge, CopyButton, EmptyState, Meter } from "../components/ui";
import { comparatorLabel, formatClock, formatDuration, nodeLabel } from "../utils/format";
import type { Derived } from "../utils/derive";
import { isRoutineIssue } from "../utils/derive";
import { FIELDS, NODE_CONTRACTS, fieldName } from "../graph/meta";
import type { FieldMeta } from "../graph/meta";

export type DrawerTab = "state" | "log" | "issue" | "llm" | "node";

interface Props {
  snapshot: RunSnapshot;
  derived: Derived;
  selectedNode: NodeId | null;
  tab: DrawerTab;
  onTab: (tab: DrawerTab) => void;
  onCollapse: () => void;
}

function valueOf(values: RunValues, key: string): unknown {
  return (values as unknown as Record<string, unknown>)[key];
}

function TextValue({ text }: { text: string }): ReactNode {
  return <pre className="field-text">{text}</pre>;
}

function ListValue({
  items,
}: {
  items: Array<{
    id: string;
    content: string;
    status: string;
    score: number;
    target_task_id?: string | null;
  }>;
}): ReactNode {  const [showDropped, setShowDropped] = useState(false);
  const droppedCount = items.filter((item) => item.status === "dropped").length;
  const visible = showDropped ? items : items.filter((item) => item.status !== "dropped");
  if (items.length === 0) {
    return <p className="field-empty">空列表（非缺失，节点已在摘要中说明无可处理项）</p>;
  }
  return (
    <div className="list-field">
      <div className="list-field__bar">
        <span className="mono">{items.length} 项</span>
        {droppedCount > 0 ? (
          <button
            type="button"
            className="link-btn"
            onClick={() => setShowDropped((value) => !value)}
          >
            {showDropped ? "隐藏已划去" : `显示已划去 ${droppedCount}`}
          </button>
        ) : null}
      </div>
      <ul className="list-field__items">
        {visible.map((item) => (
          <li key={item.id} className={`list-item list-item--${item.status}`}>
            <div className="list-item__head">
              <code className="list-item__id">{item.id}</code>
              <Badge
                tone={
                  item.status === "dropped"
                    ? "muted"
                    : item.status === "open" || item.status === "pending"
                      ? "warn"
                      : "success"
                }
              >
                {item.status}
              </Badge>
              <span className="list-item__score mono">{item.score}</span>
              {item.target_task_id ? (
                <span className="list-item__target mono">→ {item.target_task_id}</span>
              ) : null}
            </div>
            <p className="list-item__content">{item.content}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ScoreValue({ detail }: { detail: ScoreDetail | null | undefined }): ReactNode {
  if (!detail) return <p className="field-empty">未评分</p>;
  const dimensions = Object.entries(detail.dimensions ?? {});
  return (
    <div className="score-field">
      <div className="score-field__head">
        <span className={`score-field__value${detail.score < 60 ? " is-low" : ""}`}>
          {detail.score}
        </span>
        <span className="score-field__unit">/ 100</span>
      </div>
      {dimensions.map(([name, value]) => (
        <div className="dim" key={name}>
          <span className="dim__name">{name}</span>
          <span className="dim__bar">
            <span
              className={`dim__fill${value < 60 ? " is-low" : ""}`}
              style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
            />
          </span>
          <span className="dim__value mono">{value}</span>
        </div>
      ))}
      <p className="score-field__summary">{detail.summary}</p>
      {detail.evidence?.length ? (
        <p className="score-field__evidence">证据：{detail.evidence.join("、")}</p>
      ) : null}
    </div>
  );
}

function FieldBody({
  field,
  values,
  tscMax,
  mMax,
}: {
  field: FieldMeta;
  values: RunValues;
  tscMax: number;
  mMax: number;
}): ReactNode {
  const raw = valueOf(values, field.key);
  if (field.kind === "list") {
    if (raw === undefined || raw === null) return <p className="field-empty">未设置（缺失）</p>;
    return (
      <ListValue
        items={
          (raw as Array<{
            id: string;
            content: string;
            status: string;
            score: number;
            target_task_id?: string | null;
          }>) ?? []
        }
      />
    );
  }
  if (field.kind === "score") {
    return <ScoreValue detail={(raw as ScoreDetail | null) ?? null} />;
  }
  if (field.kind === "criteria") {
    const criteria = (raw as RunValues["performance_criteria"]) ?? [];
    if (!criteria.length) return <p className="field-empty">未设置（缺失）</p>;
    return (
      <ul className="criteria-list">
        {criteria.map((item) => (
          <li key={item.name}>
            <span className="criteria-list__name">{item.name}</span>
            <span className="mono criteria-list__cmp">
              {comparatorLabel(item.comparator)} {item.threshold}
            </span>
          </li>
        ))}
      </ul>
    );
  }
  if (field.kind === "counter") {
    const value = typeof raw === "number" ? raw : 0;
    const max = field.index === 10 ? tscMax : mMax;
    return (
      <Meter
        label={field.index === 10 ? "TSC" : "M"}
        value={value}
        max={max}
        tone={value >= max ? "warn" : "accent"}
      />
    );
  }
  if (typeof raw !== "string" || raw.length === 0) {
    if (field.index === 3 && raw === "") {
      return <p className="field-empty">空（已快照到 02，等待 Student 重写）</p>;
    }
    return <p className="field-empty">未设置（缺失）</p>;
  }
  return <TextValue text={raw} />;
}

function StatePanel({ snapshot }: { snapshot: RunSnapshot }): ReactNode {
  return (
    <div className="fields">
      {FIELDS.map((field) => (
        <section className="field" key={field.key}>
          <header className="field__head">
            <span className="field__index mono">{String(field.index).padStart(2, "0")}</span>
            <span className="field__name">{field.name}</span>
            <span className="field__writer">{field.writer}</span>
            <Badge tone="muted">只读</Badge>
          </header>
          <p className="field__hint">{field.hint}</p>
          <FieldBody
            field={field}
            values={snapshot.values}
            tscMax={snapshot.tsc_max}
            mMax={snapshot.m_max}
          />
        </section>
      ))}
    </div>
  );
}

interface LogEntry {
  key: string;
  at: string;
  node: string;
  kind: "node" | "gate" | "run";
  summary: string;
  duration: number;
  issues: Issue[];
  writes: string[];
  sideEffects: string[];
  model: string | null;
  version: string | null;
  human: boolean;
}

function traceEntries(snapshot: RunSnapshot): LogEntry[] {
  return (snapshot.values.trace ?? []).map((trace, index) => ({
    key: `trace-${index}`,
    at: trace.started_at,
    node: trace.node,
    kind: trace.node.startsWith("gate:") ? "gate" : "node",
    summary: trace.summary,
    duration: trace.duration_ms,
    issues: trace.issues ?? [],
    writes: trace.writes ?? [],
    sideEffects: trace.side_effects ?? [],
    model: trace.model ?? null,
    version: trace.prompt_version ?? null,
    human: Boolean(trace.human_intervention),
  }));
}

function LogPanel({ snapshot }: { snapshot: RunSnapshot }): ReactNode {
  const [keyword, setKeyword] = useState("");
  const [level, setLevel] = useState<"all" | "warn" | "error">("all");
  const [node, setNode] = useState("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const entries = useMemo(() => traceEntries(snapshot), [snapshot]);
  const nodeOptions = useMemo(
    () => Array.from(new Set(entries.map((entry) => entry.node))).sort(),
    [entries],
  );

  const filtered = entries.filter((entry) => {
    if (node !== "all" && entry.node !== node) return false;
    if (level === "error" && !entry.issues.some((issue) => issue.level === 1)) return false;
    if (level === "warn" && !entry.issues.some((issue) => issue.level === 2)) return false;
    if (keyword.trim()) {
      const haystack = `${entry.node} ${entry.summary} ${entry.writes.join(" ")}`.toLowerCase();
      if (!haystack.includes(keyword.trim().toLowerCase())) return false;
    }
    return true;
  });

  return (
    <div className="log-panel">
      <div className="filter-bar">
        <label className="search">
          <Icon name="search" size={13} />
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索节点 / 摘要 / 写入字段"
          />
        </label>
        <select value={level} onChange={(event) => setLevel(event.target.value as typeof level)}>
          <option value="all">全部级别</option>
          <option value="warn">含 2 级</option>
          <option value="error">含 1 级</option>
        </select>
        <select value={node} onChange={(event) => setNode(event.target.value)}>
          <option value="all">全部节点</option>
          {nodeOptions.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon="terminal" title="没有匹配的日志" hint="调整筛选条件或清空搜索" />
      ) : (
        <ol className="log-list">
          {filtered.map((entry) => {
            const open = expanded === entry.key;
            const worst = entry.issues.some((issue) => issue.level === 1)
              ? 1
              : entry.issues.some((issue) => issue.level === 2)
                ? 2
                : 0;
            return (
              <li
                key={entry.key}
                className={`log-row${worst === 1 ? " log-row--error" : worst === 2 ? " log-row--warn" : ""}`}
              >
                <button
                  type="button"
                  className="log-row__head"
                  onClick={() => setExpanded(open ? null : entry.key)}
                >
                  <span className="log-row__time mono">{formatClock(entry.at)}</span>
                  <span className={`log-row__node${entry.kind === "gate" ? " is-gate" : ""}`}>
                    {entry.kind === "gate" ? entry.node.replace("gate:", "") : entry.node}
                  </span>
                  <span className="log-row__summary">{entry.summary}</span>
                  {entry.human ? <Badge tone="accent">人工</Badge> : null}
                  <span className="log-row__dur mono">{formatDuration(entry.duration)}</span>
                  <Icon name={open ? "chevronDown" : "chevron"} size={12} />
                </button>
                {open ? (
                  <div className="log-row__detail">
                    <div className="log-row__kv">
                      <span>写入</span>
                      <code>{entry.writes.length ? entry.writes.join(", ") : "无"}</code>
                    </div>
                    <div className="log-row__kv">
                      <span>副作用</span>
                      <code>{entry.sideEffects.length ? entry.sideEffects.join(", ") : "无"}</code>
                    </div>
                    <div className="log-row__kv">
                      <span>模型</span>
                      <code>
                        {entry.model ?? "未调用 LLM"}
                        {entry.version ? ` · ${entry.version}` : ""}
                      </code>
                    </div>
                    {entry.issues.length ? (
                      <div className="log-row__issues">
                        {entry.issues.map((issue, index) => (
                          <p key={index} className={`issue-line issue-line--${issue.level}`}>
                            <code>{issue.code}</code>
                            <span>{issue.message}</span>
                          </p>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

function IssuePanel({ issues }: { issues: Derived["issues"] }): ReactNode {
  const [mode, setMode] = useState<"attention" | "routine" | "all">("attention");
  const attention = issues.filter((issue) => !isRoutineIssue(issue));
  const routine = issues.filter((issue) => isRoutineIssue(issue));
  const base = mode === "attention" ? attention : mode === "routine" ? routine : issues;
  const filtered = base.filter((issue) => issue.level === 1 || issue.level === 2);

  const emptyHint =
    mode === "attention"
      ? "节点在流程早期读不到待选字段属于正常路径，已折叠为「常规缺失」"
      : mode === "routine"
        ? "常规缺失由 2 级报错记录，不影响流程推进"
        : "1 级报错会终止运行，2 级警告会记录但不阻断";

  return (
    <div className="issues">
      <div className="segmented">
        <button
          type="button"
          className={mode === "attention" ? "is-active" : ""}
          onClick={() => setMode("attention")}
        >
          需关注 {attention.length}
        </button>
        <button
          type="button"
          className={mode === "routine" ? "is-active" : ""}
          onClick={() => setMode("routine")}
        >
          常规缺失 {routine.length}
        </button>
        <button
          type="button"
          className={mode === "all" ? "is-active" : ""}
          onClick={() => setMode("all")}
        >
          全部 {issues.length}
        </button>
      </div>

      {issues.length === 0 ? (
        <EmptyState icon="check" title="本次运行没有报错" hint={emptyHint} />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="check"
          title={mode === "attention" ? "没有需要关注的报错" : "该分类没有记录"}
          hint={emptyHint}
          action={
            routine.length && mode === "attention" ? (
              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setMode("routine")}>
                查看 {routine.length} 条常规缺失
              </button>
            ) : undefined
          }
        />
      ) : (
        <ul className="issue-list">
          {filtered.map((issue, index) => (
            <li key={`${issue.code}-${index}`} className={`issue issue--${issue.level}`}>
              <div className="issue__head">
                <Badge tone={issue.level === 1 ? "error" : isRoutineIssue(issue) ? "muted" : "warn"}>
                  {issue.level === 1 ? "E1 终止" : isRoutineIssue(issue) ? "E2 常规" : "E2 警告"}
                </Badge>
                <code className="issue__code">{issue.code}</code>
                <CopyButton text={issue.code} label="" className="btn btn--ghost btn--icon" />
              </div>
              <p className="issue__message">{issue.message}</p>
              <div className="issue__meta">
                <span>{nodeLabel(issue.node)}</span>
                {issue.field ? <span className="mono">字段 {issue.field}</span> : null}
                <span className="mono">{formatClock(issue.at)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LlmPanel({ derived }: { derived: Derived }): ReactNode {
  if (!derived.llmCalls.length) {
    return <EmptyState icon="spark" title="还没有 LLM 调用" hint="运行开始后这里会记录每次模型调用" />;
  }
  return (
    <div className="llm-table">
      <div className="llm-table__head">
        <span>节点</span>
        <span>模型 / 模板</span>
        <span>耗时</span>
        <span>结果</span>
      </div>
      {derived.llmCalls.map((call, index) => {
        const failed = call.issues.some((issue) => issue.code.startsWith("E2-LLM"));
        return (
          <div key={`${call.node}-${index}`} className="llm-table__row">
            <span className="llm-table__node">{call.node}</span>
            <span className="llm-table__model mono">
              {call.model ?? "—"}
              <em>{call.version ?? "—"}</em>
            </span>
            <span className="mono">{formatDuration(call.duration)}</span>
            <span>
              {failed ? <Badge tone="warn">降级</Badge> : <Badge tone="success">成功</Badge>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function TraceDetail({ trace }: { trace: Trace }): ReactNode {
  return (
    <div className="trace">
      <div className="trace__meta">
        <span className="mono">{formatClock(trace.started_at)}</span>
        <span className="mono">{formatDuration(trace.duration_ms)}</span>
        {trace.model ? <span className="mono">{trace.model}</span> : null}
        {trace.prompt_version ? <span className="mono">{trace.prompt_version}</span> : null}
        {trace.human_intervention ? <Badge tone="accent">人工介入</Badge> : null}
      </div>
      <p className="trace__summary">{trace.summary}</p>
      <div className="trace__grid">
        <div>
          <span className="trace__label">写入字段</span>
          <code>{trace.writes?.length ? trace.writes.join(", ") : "无"}</code>
        </div>
        <div>
          <span className="trace__label">边副作用</span>
          <code>{trace.side_effects?.length ? trace.side_effects.join(", ") : "无"}</code>
        </div>
        {trace.human_intervention ? (
          <div>
            <span className="trace__label">路由变更</span>
            <code>
              {trace.original_route ?? "—"} → {trace.new_route ?? "终止"}
            </code>
          </div>
        ) : null}
      </div>
      {trace.issues?.length ? (
        <div className="trace__issues">
          {trace.issues.map((issue, index) => (
            <p key={index} className={`issue-line issue-line--${issue.level}`}>
              <code>{issue.code}</code>
              <span>{issue.message}</span>
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function NodePanel({ node, derived }: { node: NodeId; derived: Derived }): ReactNode {
  const state = derived.nodes[node];
  const contract = NODE_CONTRACTS[node];
  const traces = state?.traces ?? [];
  return (
    <div className="node-panel">
      <header className="node-panel__head">
        <div>
          <h3>{nodeLabel(node)}</h3>
          <p className="node-panel__sub">
            {traces.length ? `已执行 ${traces.length} 次` : "本次运行尚未执行"}
          </p>
        </div>
        <Badge tone={state?.status === "success" ? "success" : "neutral"}>
          {state?.status ?? "idle"}
        </Badge>
      </header>

      <section className="contract">
        <div className="contract__group">
          <span className="contract__label">必要输入</span>
          <div className="contract__chips">
            {contract.required.length ? (
              contract.required.map((index) => (
                <span className="chip" key={index} title={fieldName(index)}>
                  <b>{index}</b>
                  {fieldName(index)}
                </span>
              ))
            ) : (
              <span className="contract__none">无</span>
            )}
          </div>
        </div>
        <div className="contract__group">
          <span className="contract__label">待选输入</span>
          <div className="contract__chips">
            {contract.optional.length ? (
              contract.optional.map((index) => (
                <span className="chip chip--optional" key={index} title={fieldName(index)}>
                  <b>{index}</b>
                  {fieldName(index)}
                </span>
              ))
            ) : (
              <span className="contract__none">无</span>
            )}
          </div>
        </div>
        <div className="contract__group">
          <span className="contract__label">写入</span>
          <div className="contract__chips">
            {contract.writes.length ? (
              contract.writes.map((index) => (
                <span className="chip chip--write" key={index} title={fieldName(index)}>
                  <b>{index}</b>
                  {fieldName(index)}
                </span>
              ))
            ) : (
              <span className="contract__none">不写业务字段</span>
            )}
          </div>
        </div>
        {contract.sideEffects.length ? (
          <div className="contract__group">
            <span className="contract__label">条件边副作用</span>
            <div className="contract__chips">
              {contract.sideEffects.map((index) => (
                <span className="chip chip--side" key={index} title={fieldName(index)}>
                  <b>{index}</b>
                  {fieldName(index)}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      {traces.length ? (
        traces
          .slice()
          .reverse()
          .map((trace, index) => (
            <TraceDetail key={`${trace.started_at}-${index}`} trace={trace} />
          ))
      ) : (
        <EmptyState icon="dot" title="没有执行记录" hint="被改道跳过或尚未轮到的节点不会有 trace" />
      )}
    </div>
  );
}

export function InspectorDrawer({
  snapshot,
  derived,
  selectedNode,
  tab,
  onTab,
  onCollapse,
}: Props): ReactNode {
  const payloadForCopy =
    tab === "issue"
      ? JSON.stringify(derived.issues, null, 2)
      : tab === "llm"
        ? JSON.stringify(derived.llmCalls, null, 2)
        : JSON.stringify(snapshot.values, null, 2);

  return (
    <aside className="drawer">
      <div className="drawer__tabs">
        <button
          type="button"
          className={`drawer__tab${tab === "state" ? " is-active" : ""}`}
          onClick={() => onTab("state")}
        >
          状态字段
        </button>
        <button
          type="button"
          className={`drawer__tab${tab === "log" ? " is-active" : ""}`}
          onClick={() => onTab("log")}
        >
          运行日志
        </button>
        <button
          type="button"
          className={`drawer__tab${tab === "issue" ? " is-active" : ""}`}
          onClick={() => onTab("issue")}
          title={`需关注 ${derived.attentionIssues.length} 条 · 常规缺失 ${derived.routineCount} 条`}
        >
          报错
          {derived.attentionIssues.length ? (
            <span className={`drawer__count${derived.errorCount ? " is-error" : ""}`}>
              {derived.attentionIssues.length}
            </span>
          ) : derived.routineCount ? (
            <span className="drawer__count drawer__count--muted">{derived.routineCount}</span>
          ) : null}
        </button>
        <button
          type="button"
          className={`drawer__tab${tab === "llm" ? " is-active" : ""}`}
          onClick={() => onTab("llm")}
        >
          LLM 调用
          {derived.llmCalls.length ? (
            <span className="drawer__count">{derived.llmCalls.length}</span>
          ) : null}
        </button>
        {selectedNode ? (
          <button
            type="button"
            className={`drawer__tab${tab === "node" ? " is-active" : ""}`}
            onClick={() => onTab("node")}
          >
            {nodeLabel(selectedNode)}
          </button>
        ) : null}
        <button
          type="button"
          className="drawer__collapse"
          onClick={onCollapse}
          title="收起抽屉"
        >
          <Icon name="chevron" size={14} />
        </button>
      </div>

      <div className="drawer__body">
        {tab === "state" ? <StatePanel snapshot={snapshot} /> : null}
        {tab === "log" ? <LogPanel snapshot={snapshot} /> : null}
        {tab === "issue" ? <IssuePanel issues={derived.issues} /> : null}
        {tab === "llm" ? <LlmPanel derived={derived} /> : null}
        {tab === "node" && selectedNode ? (
          <NodePanel node={selectedNode} derived={derived} />
        ) : null}
      </div>

      <div className="drawer__foot">
        <span className="drawer__hint">字段只读 · 无人工写入入口</span>
        <CopyButton text={payloadForCopy} label="复制 JSON" />
      </div>
    </aside>
  );
}
