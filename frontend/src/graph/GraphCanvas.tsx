import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode, WheelEvent as ReactWheelEvent } from "react";

import type { EdgeSpec, NodeId, RunSnapshot } from "../api/types";
import { Icon } from "../components/Icons";
import { Badge } from "../components/ui";
import { formatDuration } from "../utils/format";
import type { Derived, NodeStatus } from "../utils/derive";
import { isRoutineIssue } from "../utils/derive";
import {
  CANVAS_H,
  CANVAS_W,
  NODES,
  NODE_H,
  NODE_W,
  midOf,
  routeFor,
  roundedPath,
} from "./layout";

interface Props {
  snapshot: RunSnapshot;
  edges: EdgeSpec[];
  derived: Derived;
  selectedNode: NodeId | null;
  onSelectNode: (node: NodeId | null) => void;
  onSelectEdge: (edge: EdgeSpec | null) => void;
  onToggleBreakpoint: (edgeId: string) => void;
}

const STATUS_TEXT: Record<NodeStatus, string> = {
  idle: "待运行",
  running: "运行中",
  success: "成功",
  warn: "含警告",
  error: "已终止",
  paused: "暂停在此",
  skipped: "已跳过",
};

export function GraphCanvas({
  snapshot,
  edges,
  derived,
  selectedNode,
  onSelectNode,
  onSelectEdge,
  onToggleBreakpoint,
}: Props): ReactNode {
  const containerRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 });
  const [popover, setPopover] = useState<{ edgeId: string; x: number; y: number } | null>(null);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  const fit = useCallback(() => {
    const element = containerRef.current;
    if (!element) return;
    const width = element.clientWidth;
    const height = element.clientHeight;
    if (width < 40 || height < 40) return;
    const scale = Math.min((width - 56) / CANVAS_W, (height - 56) / CANVAS_H, 1.1);
    setView({
      k: scale,
      tx: (width - CANVAS_W * scale) / 2,
      ty: (height - CANVAS_H * scale) / 2,
    });
  }, []);

  useEffect(() => {
    fit();
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(() => fit());
    observer.observe(element);
    return () => observer.disconnect();
  }, [fit]);

  const zoomCenter = () => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  };

  const zoomAt = useCallback((clientX: number, clientY: number, factor: number) => {
    const element = containerRef.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    setView((current) => {
      const next = Math.min(2, Math.max(0.32, current.k * factor));
      if (next === current.k) return current;
      const px = clientX - rect.left;
      const py = clientY - rect.top;
      const worldX = (px - current.tx) / current.k;
      const worldY = (py - current.ty) / current.k;
      return { k: next, tx: px - worldX * next, ty: py - worldY * next };
    });
  }, []);

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    const factor = Math.exp(-event.deltaY * 0.0016);
    zoomAt(event.clientX, event.clientY, factor);
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest(".node-card, .edge-hit, .bp-marker, .edge-label, .graph-popover")) {
      return;
    }
    if (event.button !== 0) return;
    drag.current = { x: event.clientX, y: event.clientY, tx: view.tx, ty: view.ty };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    setPopover(null);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (!state) return;
    setView((current) => ({
      ...current,
      tx: state.tx + (event.clientX - state.x),
      ty: state.ty + (event.clientY - state.y),
    }));
  };

  const onPointerUp = () => {
    drag.current = null;
  };

  const armed = new Set(snapshot.breakpoints);
  const activeEdge = popover ? edges.find((edge) => edge.edge_id === popover.edgeId) : null;

  return (
    <div
      className="graph"
      ref={containerRef}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      onClick={(event) => {
        const target = event.target as HTMLElement;
        if (!target.closest(".node-card, .edge-hit, .bp-marker, .graph-popover")) {
          onSelectNode(null);
          onSelectEdge(null);
          setPopover(null);
        }
      }}
    >
      <div className="graph__toolbar">
        <button type="button" className="btn btn--ghost btn--icon" title="适配画布" onClick={fit}>
          <Icon name="route" size={15} />
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--icon"
          title="放大"
          onClick={() => {
            const center = zoomCenter();
            zoomAt(center.x, center.y, 1.15);
          }}
        >
          ＋
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--icon"
          title="缩小"
          onClick={() => {
            const center = zoomCenter();
            zoomAt(center.x, center.y, 0.87);
          }}
        >
          －
        </button>
        <span className="graph__zoom mono">{Math.round(view.k * 100)}%</span>
      </div>

      <div
        className="graph__world"
        style={{
          width: CANVAS_W,
          height: CANVAS_H,
          transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.k})`,
        }}
      >
        <svg
          className="graph__edges"
          width={CANVAS_W}
          height={CANVAS_H}
          viewBox={`0 0 ${CANVAS_W} ${CANVAS_H}`}
        >
          <defs>
            <marker
              id="arrow-idle"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M0 0L10 5L0 10z" fill="#3d475a" />
            </marker>
            <marker
              id="arrow-done"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M0 0L10 5L0 10z" fill="#3fb950" />
            </marker>
            <marker
              id="arrow-hit"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M0 0L10 5L0 10z" fill="#f0a020" />
            </marker>
          </defs>
          {edges.map((edge) => {
            const route = routeFor(edge.edge_id, edge.source, edge.target);
            const path = roundedPath(route.points);
            const state = derived.edges[edge.edge_id] ?? "pending";
            const marker =
              state === "hit" ? "arrow-hit" : state === "traversed" ? "arrow-done" : "arrow-idle";
            return (
              <g key={edge.edge_id}>
                <path
                  d={path}
                  className={[
                    "edge",
                    `edge--${edge.kind}`,
                    `edge--${state}`,
                    armed.has(edge.edge_id) ? "is-armed" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  markerEnd={`url(#${marker})`}
                />
                <path
                  d={path}
                  className="edge-hit"
                  onClick={(event) => {
                    event.stopPropagation();
                    const rect = containerRef.current?.getBoundingClientRect();
                    if (!rect) return;
                    onSelectEdge(edge);
                    setPopover({
                      edgeId: edge.edge_id,
                      x: event.clientX - rect.left,
                      y: event.clientY - rect.top,
                    });
                  }}
                />
              </g>
            );
          })}
        </svg>

        {edges
          .filter((edge) => edge.kind === "conditional")
          .map((edge) => {
            const route = routeFor(edge.edge_id, edge.source, edge.target);
            const point = route.label ?? midOf(route.points);
            const state = derived.edges[edge.edge_id] ?? "pending";
            return (
              <div
                key={`label-${edge.edge_id}`}
                className={`edge-label edge-label--${state}${route.labelAlign === "start" ? " edge-label--start" : ""}`}
                style={{ left: point[0], top: point[1] }}
                title={`${edge.condition}${edge.side_effects.length ? ` · 副作用：${edge.side_effects.join(" / ")}` : ""}`}
              >
                {edge.side_effects.length ? <span className="edge-label__gear">⚙</span> : null}
                <span className="edge-label__text">{edge.condition}</span>
              </div>
            );
          })}

        {edges.map((edge) => {
          const route = routeFor(edge.edge_id, edge.source, edge.target);
          const point = route.label ?? midOf(route.points);
          const armedHere = armed.has(edge.edge_id);
          const hit = derived.edges[edge.edge_id] === "hit";
          return (
            <button
              key={`bp-${edge.edge_id}`}
              type="button"
              className={`bp-marker${armedHere ? " is-armed" : ""}${hit ? " is-hit" : ""}`}
              style={{ left: point[0], top: point[1] + 22 }}
              title={armedHere ? "已设断点，点击取消" : "点击在此边设断点"}
              onClick={(event) => {
                event.stopPropagation();
                onToggleBreakpoint(edge.edge_id);
              }}
            >
              <Icon name="breakpoint" size={12} />
            </button>
          );
        })}

        {NODES.map((node) => {
          const state = derived.nodes[node.id] ?? { status: "idle" as NodeStatus, traces: [] };
          const last = state.traces[state.traces.length - 1];
          const issue = last?.issues?.find(
            (item) => item.level === 1 || !isRoutineIssue(item),
          );
          const isSelected = selectedNode === node.id;
          return (
            <button
              key={node.id}
              type="button"
              className={`node-card node-card--${state.status}${isSelected ? " is-selected" : ""}`}
              style={{ left: node.x, top: node.y, width: NODE_W, height: NODE_H }}
              onClick={(event) => {
                event.stopPropagation();
                onSelectNode(node.id);
                setPopover(null);
              }}
              title={`${node.title} · ${STATUS_TEXT[state.status]}`}
            >
              <span className="node-card__head">
                <span className="node-card__dot" />
                <span className="node-card__title">{node.title}</span>
                <span className="node-card__cn">{node.cn}</span>
                {state.traces.length > 1 ? (
                  <span className="node-card__count">×{state.traces.length}</span>
                ) : null}
              </span>
              <span className="node-card__summary">
                {last?.summary ?? (state.status === "skipped" ? "本次运行未经过该节点" : "尚未执行")}
              </span>
              <span className="node-card__foot">
                <span className="node-card__state">{STATUS_TEXT[state.status]}</span>
                <span className="node-card__time mono">
                  {last ? formatDuration(last.duration_ms) : "—"}
                </span>
                {issue ? (
                  <Badge
                    tone={issue.level === 1 ? "error" : isRoutineIssue(issue) ? "muted" : "warn"}
                    title={`${issue.code} · ${issue.message}`}
                  >
                    {issue.level === 1 ? "E1" : "W2"}
                  </Badge>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>

      {activeEdge && popover ? (
        <div
          className="graph-popover"
          style={{ left: popover.x, top: popover.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="graph-popover__head">
            <code>{activeEdge.edge_id}</code>
            <button
              type="button"
              className="btn btn--ghost btn--icon"
              onClick={() => {
                setPopover(null);
                onSelectEdge(null);
              }}
            >
              <Icon name="close" size={13} />
            </button>
          </div>
          <dl className="graph-popover__meta">
            <div>
              <dt>类型</dt>
              <dd>{activeEdge.kind === "static" ? "普通边（固定指向）" : "条件边"}</dd>
            </div>
            <div>
              <dt>条件</dt>
              <dd>{activeEdge.condition}</dd>
            </div>
            <div>
              <dt>副作用</dt>
              <dd>{activeEdge.side_effects.length ? activeEdge.side_effects.join(" / ") : "无"}</dd>
            </div>
          </dl>
          <div className="graph-popover__actions">
            <button
              type="button"
              className={`btn btn--sm ${armed.has(activeEdge.edge_id) ? "btn--danger" : "btn--primary"}`}
              onClick={() => onToggleBreakpoint(activeEdge.edge_id)}
            >
              <Icon name="breakpoint" size={13} />
              {armed.has(activeEdge.edge_id) ? "取消断点" : "设断点"}
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => {
                const node = activeEdge.source;
                onSelectNode(node);
                setPopover(null);
              }}
            >
              查看源节点
            </button>
          </div>
        </div>
      ) : null}

      <div className="graph__legend">
        <span>
          <i className="legend-dot legend-dot--success" />成功
        </span>
        <span>
          <i className="legend-dot legend-dot--running" />运行中
        </span>
        <span>
          <i className="legend-dot legend-dot--paused" />暂停
        </span>
        <span>
          <i className="legend-dot legend-dot--warn" />2 级警告
        </span>
        <span>
          <i className="legend-dot legend-dot--error" />1 级报错
        </span>
        <span>
          <i className="legend-dot legend-dot--idle" />待运行
        </span>
        <span className="legend-sep">
          <i className="legend-line legend-line--static" />普通边
        </span>
        <span>
          <i className="legend-line legend-line--conditional" />条件边
        </span>
      </div>
    </div>
  );
}
