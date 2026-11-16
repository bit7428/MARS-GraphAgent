import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { EdgeSpec, NodeId } from "../api/types";
import { BreakpointModal } from "../breakpoint/BreakpointModal";
import { Icon } from "../components/Icons";
import { CopyButton, EmptyState, Meter, RunStatusPill, toast } from "../components/ui";
import { InspectorDrawer, type DrawerTab } from "../drawer/InspectorDrawer";
import { GraphCanvas } from "../graph/GraphCanvas";
import { useEdges } from "../hooks/useCatalog";
import { useRunStream } from "../hooks/useRunStream";
import { useCurrentRun } from "../store/currentRun";
import { elapsedSince, formatDuration, nodeLabel } from "../utils/format";
import { deriveRun } from "../utils/derive";

function displayNode(name: string): string {
  if (name.startsWith("gate__")) {
    const [, source, target] = name.split("__");
    if (source && target) return `${nodeLabel(source)} → ${nodeLabel(target)}`;
  }
  return nodeLabel(name);
}

export function ConsolePage(): ReactNode {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { edges } = useEdges();
  const { snapshot, events, loading, error, connected, refresh, applySnapshot } =
    useRunStream(runId);
  const { setSnapshot } = useCurrentRun();

  const [tab, setTab] = useState<DrawerTab>("state");
  const [selectedNode, setSelectedNode] = useState<NodeId | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<EdgeSpec | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);

  const derived = useMemo(() => deriveRun(snapshot, events, edges), [snapshot, events, edges]);

  useEffect(() => {
    setSnapshot(snapshot);
  }, [snapshot, setSnapshot]);

  useEffect(() => {
    if (snapshot?.status !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [snapshot?.status]);

  useEffect(() => {
    if (selectedNode) setTab("node");
  }, [selectedNode]);

  if (!runId) {
    return <EmptyState title="缺少 run_id" hint="请从历史运行中打开一个任务" />;
  }

  if (loading && !snapshot) {
    return (
      <div className="page">
        <div className="skeleton skeleton--bar" />
        <div className="skeleton skeleton--canvas" />
      </div>
    );
  }

  if (!snapshot) {
    return (
      <div className="page">
        <EmptyState
          icon="error"
          title="运行不存在"
          hint={error ?? "进程重启后内存中的运行会丢失，请从历史记录重新开始"}
          action={
            <div className="row">
              <button type="button" className="btn btn--ghost" onClick={() => navigate("/history")}>
                查看历史
              </button>
              <button type="button" className="btn btn--primary" onClick={() => navigate("/new")}>
                新建任务
              </button>
            </div>
          }
        />
      </div>
    );
  }

  const values = snapshot.values;
  const status = snapshot.status;
  const interrupted = snapshot.interrupts?.[0];
  const currentName =
    derived.currentNode ??
    snapshot.next?.[0] ??
    derived.sequence[derived.sequence.length - 1] ??
    null;
  const elapsed =
    status === "running"
      ? Math.max(0, now - new Date(snapshot.created_at).getTime())
      : elapsedSince(snapshot.created_at, snapshot.finished_at || undefined);
  const finalPrompt = values.optimized_prompt || values.working_prompt || "";

  const toggleBreakpoint = async (edgeId: string) => {
    const next = snapshot.breakpoints.includes(edgeId)
      ? snapshot.breakpoints.filter((item) => item !== edgeId)
      : [...snapshot.breakpoints, edgeId];
    try {
      const updated = await api.setBreakpoints(snapshot.thread_id, next);
      applySnapshot(updated);
      toast(
        next.includes(edgeId) ? `已在 ${edgeId} 设断点` : `已取消 ${edgeId} 的断点`,
        "success",
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    }
  };

  const pauseSoon = async () => {
    const targets = new Set<string>();
    for (const item of snapshot.next) {
      if (item.startsWith("gate__")) {
        const [, source, target] = item.split("__");
        if (source && target) targets.add(`${source}->${target}`);
      } else {
        for (const edge of edges) {
          if (edge.target === item) targets.add(edge.edge_id);
        }
      }
    }
    if (!targets.size) {
      toast("当前没有可挂起的边，请稍后再试", "warn");
      return;
    }
    const merged = Array.from(new Set([...snapshot.breakpoints, ...targets]));
    try {
      const updated = await api.setBreakpoints(snapshot.thread_id, merged);
      applySnapshot(updated);
      toast(`已设断点，运行将在下一节点执行前挂起（${targets.size} 条边）`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    }
  };

  const resumeContinue = async () => {
    setBusy(true);
    try {
      const updated = await api.resume(snapshot.thread_id, { action: "continue" });
      applySnapshot(updated);
      toast("已继续原路由", "success");
      void refresh();
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setBusy(false);
    }
  };

  const exportSnapshot = () => {
    const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${snapshot.thread_id}-snapshot.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="console">
      <section className="runbar">
        <div className="runbar__identity">
          <h1 className="runbar__name">{snapshot.name}</h1>
          <button
            type="button"
            className="runbar__id mono"
            title="复制 run_id"
            onClick={() => {
              void navigator.clipboard.writeText(snapshot.thread_id);
              toast("run_id 已复制", "success");
            }}
          >
            {snapshot.thread_id}
            <Icon name="copy" size={11} />
          </button>
          <RunStatusPill status={status} />
          {!connected && status === "running" ? (
            <span className="runbar__stream" title="SSE 连接已断开，浏览器会自动重连">
              <Icon name="warn" size={12} />
              事件流重连中
            </span>
          ) : null}
        </div>

        <div className="runbar__metrics">
          <Meter
            label="TSC"
            value={values.tsc_count ?? 0}
            max={snapshot.tsc_max}
            tone={(values.tsc_count ?? 0) >= snapshot.tsc_max ? "warn" : "accent"}
          />
          <Meter
            label="M"
            value={values.m_count ?? 0}
            max={snapshot.m_max}
            tone={(values.m_count ?? 0) >= snapshot.m_max ? "error" : "accent"}
          />
          <div className="runbar__misc">
            <span className="runbar__chip" title="当前 / 最近执行的节点">
              <Icon name="dot" size={10} />
              {currentName ? displayNode(currentName) : "等待调度"}
            </span>
            <span className="runbar__chip" title="已设断点">
              <Icon name="breakpoint" size={11} />
              {snapshot.breakpoints.length}
            </span>
            {derived.attentionIssues.length ? (
              <span
                className={`runbar__chip${derived.errorCount ? " is-error" : " is-warn"}`}
                title="需关注的问题；点击查看报错列表"
                onClick={() => {
                  setTab("issue");
                  setDrawerOpen(true);
                }}
                role="button"
                tabIndex={0}
              >
                <Icon name={derived.errorCount ? "error" : "warn"} size={11} />
                {derived.attentionIssues.length}
              </span>
            ) : derived.routineCount ? (
              <span
                className="runbar__chip"
                title={`常规缺失 ${derived.routineCount} 条（2 级，不阻断流程）`}
                onClick={() => {
                  setTab("issue");
                  setDrawerOpen(true);
                }}
                role="button"
                tabIndex={0}
              >
                <Icon name="check" size={11} />
                {derived.routineCount}
              </span>
            ) : null}
            <span className="runbar__elapsed mono">
              {formatDuration(Number.isFinite(elapsed) ? elapsed : 0)}
            </span>
          </div>
        </div>

        <div className="runbar__actions">
          {status === "running" ? (
            <button
              type="button"
              className="btn btn--ghost"
              onClick={pauseSoon}
              title="通过边断点实现：在下一节点执行前挂起"
            >
              <Icon name="pause" size={13} />
              暂停
            </button>
          ) : null}
          {status === "paused" ? (
            <button
              type="button"
              className="btn btn--primary"
              onClick={resumeContinue}
              disabled={busy}
              title="等同于「继续原路由」"
            >
              <Icon name="play" size={13} />
              继续
            </button>
          ) : null}
          <button
            type="button"
            className="btn btn--ghost"
            disabled={status === "paused" || status === "completed" || status === "failed"}
            title={
              status === "paused"
                ? "请在干预弹窗中选择终止"
                : "先暂停再终止：立即 abort 需要运行处于 paused"
            }
            onClick={async () => {
              await pauseSoon();
              toast("已请求暂停，抵达断点后可在弹窗中终止或改道", "info");
            }}
          >
            <Icon name="stop" size={13} />
            终止
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            disabled={status !== "completed" && status !== "failed"}
            onClick={() => navigate(`/report/${snapshot.thread_id}`)}
          >
            <Icon name="report" size={13} />
            报告
          </button>
        </div>
      </section>

      {derived.errorCount > 0 ? (
        <div className="banner banner--error">
          <Icon name="error" size={14} />
          <span>
            运行已因 1 级报错终止：
            <code>
              {derived.issues.find((issue) => issue.level === 1)?.code ?? "E1"}
            </code>
            <em>{derived.issues.find((issue) => issue.level === 1)?.message}</em>
          </span>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              setTab("issue");
              setDrawerOpen(true);
            }}
          >
            查看现场
          </button>
        </div>
      ) : null}

      <div className={`console__body${drawerOpen ? "" : " is-collapsed"}`}>
        <GraphCanvas
          snapshot={snapshot}
          edges={edges}
          derived={derived}
          selectedNode={selectedNode}
          onSelectNode={(node) => {
            setSelectedNode(node);
            if (node) setDrawerOpen(true);
          }}
          onSelectEdge={(edge) => {
            setSelectedEdge(edge);
            if (edge) setDrawerOpen(true);
          }}
          onToggleBreakpoint={toggleBreakpoint}
        />
        {drawerOpen ? (
          <InspectorDrawer
            snapshot={snapshot}
            derived={derived}
            selectedNode={selectedNode}
            tab={tab}
            onTab={setTab}
            onCollapse={() => setDrawerOpen(false)}
          />
        ) : (
          <button
            type="button"
            className="drawer-reopen"
            onClick={() => setDrawerOpen(true)}
            title="展开状态与日志"
          >
            <Icon name="chevron" size={13} />
            状态与日志
          </button>
        )}
      </div>

      <footer className="console__foot">
        <div className="console__summary">
          <span>
            <b>02</b> 待优化 {values.working_prompt?.length ?? 0} 字
          </span>
          <span>
            <b>03</b> 已优化 {values.optimized_prompt?.length ?? 0} 字
          </span>
          <span>
            <b>05</b> 子任务 {values.subtasks?.length ?? 0}
            <em>（{(values.subtasks ?? []).filter((item) => item.status === "pending").length} pending）</em>
          </span>
          <span>
            <b>06</b> 提问 {values.questions?.length ?? 0}
            <em>（{(values.questions ?? []).filter((item) => item.status === "open").length} open）</em>
          </span>
          {selectedEdge ? (
            <span className="console__edge">
              已选边 <code>{selectedEdge.edge_id}</code>
            </span>
          ) : null}
        </div>
        <div className="console__actions">
          <CopyButton text={finalPrompt} label="复制当前提示词" />
          <button type="button" className="btn btn--ghost btn--sm" onClick={exportSnapshot}>
            <Icon name="download" size={13} />
            导出快照
          </button>
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={status !== "completed" && status !== "failed"}
            onClick={() => navigate(`/report/${snapshot.thread_id}`)}
          >
            <Icon name="report" size={13} />
            查看报告
          </button>
        </div>
      </footer>

      {interrupted ? (
        <BreakpointModal
          snapshot={snapshot}
          interrupt={interrupted}
          edge={edges.find((edge) => edge.edge_id === interrupted.edge_id)}
          onResolved={(next) => {
            applySnapshot(next);
            void refresh();
          }}
        />
      ) : null}
    </div>
  );
}
