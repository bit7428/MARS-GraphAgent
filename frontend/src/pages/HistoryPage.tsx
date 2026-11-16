import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import type { RunSummary } from "../api/types";
import { Icon } from "../components/Icons";
import { Badge, EmptyState, RunStatusPill, toast } from "../components/ui";
import { useMeta } from "../hooks/useCatalog";
import {
  copyText,
  downloadText,
  elapsedSince,
  formatDateTime,
  formatDuration,
} from "../utils/format";

function acceptanceTone(value: string): "success" | "warn" | "error" | "muted" {
  if (value.startsWith("通过")) return "success";
  if (value.includes("M 超限")) return "error";
  if (value.startsWith("未通过")) return "warn";
  if (value.includes("终止") || value.includes("中断")) return "error";
  return "muted";
}

function isTerminated(value: string): boolean {
  return value.includes("终止") || value.includes("中断");
}

export function HistoryPage(): ReactNode {
  const navigate = useNavigate();
  const meta = useMeta();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("all");
  const [acceptance, setAcceptance] = useState("all");
  const [logFor, setLogFor] = useState<RunSummary | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [logLoading, setLogLoading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const loadRuns = async (): Promise<void> => {
    try {
      const items = await api.listRuns();
      setRuns(items);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    api
      .listRuns()
      .then((items) => {
        if (!active) return;
        setRuns(items);
        setError(null);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const openLog = async (run: RunSummary): Promise<void> => {
    setLogFor(run);
    setLogLoading(true);
    setLogLines([]);
    try {
      const result = await api.getRunLog(run.thread_id, 200);
      setLogLines(result.lines);
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : "读取日志失败", "error");
    } finally {
      setLogLoading(false);
    }
  };

  const removeData = async (run: RunSummary): Promise<void> => {
    const dataDir = meta?.data_dir ?? "data/runs";
    const confirmed = window.confirm(
      `确认删除优化「${run.name}」的全部数据？\n\n` +
        `将删除 ${dataDir}/${run.thread_id}/ 及其报告、日志和状态快照，操作不可恢复。`,
    );
    if (!confirmed) return;
    setDeleting(run.thread_id);
    try {
      await api.deleteRunData(run.thread_id);
      setRuns((items) => items.filter((item) => item.thread_id !== run.thread_id));
      if (logFor?.thread_id === run.thread_id) setLogFor(null);
      toast("运行数据已删除", "success");
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : "删除失败", "error");
    } finally {
      setDeleting(null);
    }
  };

  const filtered = useMemo(
    () =>
      runs.filter((run) => {
        if (status !== "all" && run.status !== status) return false;
        if (acceptance === "passed" && !run.acceptance.startsWith("通过")) return false;
        if (acceptance === "failed" && !run.acceptance.includes("未通过")) return false;
        if (acceptance === "terminated" && !isTerminated(run.acceptance)) return false;
        if (keyword.trim()) {
          const haystack = `${run.name} ${run.thread_id}`.toLowerCase();
          if (!haystack.includes(keyword.trim().toLowerCase())) return false;
        }
        return true;
      }),
    [runs, status, acceptance, keyword],
  );

  const stats = useMemo(() => {
    const passed = runs.filter((run) => run.acceptance.startsWith("通过")).length;
    const failed = runs.filter((run) => run.acceptance.includes("未通过")).length;
    const terminated = runs.filter((run) => isTerminated(run.acceptance)).length;
    return { total: runs.length, passed, failed, terminated };
  }, [runs]);

  return (
    <div className="page">
      <header className="page__head">
        <div>
          <h1>历史运行</h1>
          <p className="page__sub">
            报告、日志与状态快照持久化在{" "}
            <code className="mono">{meta?.data_dir ?? "data/runs"}/&lt;run_id&gt;/</code>
            ，服务重启后仍可查看、下载与删除。
          </p>
        </div>
        <div className="page__head-actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void loadRuns()}
            title="重新扫描持久化数据"
          >
            <Icon name="refresh" size={13} />
            刷新
          </button>
          <button type="button" className="btn btn--primary" onClick={() => navigate("/new")}>
            <Icon name="plus" size={13} />
            新建任务
          </button>
        </div>
      </header>

      <div className="stat-row">
        <div className="stat">
          <span className="stat__label">总运行</span>
          <span className="stat__value">{stats.total}</span>
        </div>
        <div className="stat">
          <span className="stat__label">通过验收</span>
          <span className="stat__value stat__value--ok">{stats.passed}</span>
        </div>
        <div className="stat">
          <span className="stat__label">未通过</span>
          <span className="stat__value stat__value--warn">{stats.failed}</span>
        </div>
        <div className="stat">
          <span className="stat__label">终止</span>
          <span className="stat__value stat__value--err">{stats.terminated}</span>
        </div>
      </div>

      <div className="filter-bar filter-bar--page">
        <label className="search">
          <Icon name="search" size={13} />
          <input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索任务名或 run_id"
          />
        </label>
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="all">全部状态</option>
          <option value="running">运行中</option>
          <option value="paused">已暂停</option>
          <option value="completed">已结束</option>
          <option value="failed">已终止</option>
        </select>
        <select value={acceptance} onChange={(event) => setAcceptance(event.target.value)}>
          <option value="all">全部验收结论</option>
          <option value="passed">通过</option>
          <option value="failed">未通过</option>
          <option value="terminated">终止</option>
        </select>
      </div>

      {loading ? (
        <div className="table">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="skeleton skeleton--row" />
          ))}
        </div>
      ) : error ? (
        <EmptyState icon="error" title="无法读取历史" hint={error} />
      ) : runs.length === 0 ? (
        <EmptyState
          icon="history"
          title="还没有运行记录"
          hint="创建一个优化任务后，运行会出现在这里"
          action={
            <button type="button" className="btn btn--primary" onClick={() => navigate("/new")}>
              新建任务
            </button>
          }
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="search"
          title="没有匹配的记录"
          action={
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => {
                setKeyword("");
                setStatus("all");
                setAcceptance("all");
              }}
            >
              清空筛选
            </button>
          }
        />
      ) : (
        <div className="table">
          <div className="table__head">
            <span>任务</span>
            <span>状态</span>
            <span>TSC / M</span>
            <span>验收结论</span>
            <span>耗时</span>
            <span>开始时间</span>
            <span>操作</span>
          </div>
          {filtered.map((run) => (
            <div key={run.thread_id} className="table__row">
              <span className="table__cell table__cell--main">
                <button
                  type="button"
                  className="link-strong"
                  onClick={() => navigate(`/console/${run.thread_id}`)}
                >
                  {run.name}
                </button>
                <button
                  type="button"
                  className="table__id mono"
                  onClick={async () => {
                    const ok = await copyText(run.thread_id);
                    toast(ok ? "run_id 已复制" : "复制失败", ok ? "success" : "error");
                  }}
                >
                  {run.thread_id}
                </button>
              </span>
              <span>
                <RunStatusPill status={run.status} />
              </span>
              <span className="mono table__counters">
                {run.tsc_count}/{run.tsc_max}
                <em>·</em>
                {run.m_count}/{run.m_max}
              </span>
              <span>
                <Badge tone={acceptanceTone(run.acceptance)}>{run.acceptance}</Badge>
              </span>
              <span className="mono">
                {formatDuration(elapsedSince(run.created_at, run.finished_at || undefined))}
              </span>
              <span className="mono table__time">{formatDateTime(run.created_at)}</span>
              <span className="table__actions">
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => navigate(`/console/${run.thread_id}`)}
                >
                  查看
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={run.status === "running" || run.status === "paused"}
                  onClick={() => navigate(`/report/${run.thread_id}`)}
                >
                  报告
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => void openLog(run)}
                >
                  <Icon name="terminal" size={12} />
                  日志
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => navigate(`/new?from=${run.thread_id}`)}
                >
                  复制为新任务
                </button>
                <button
                  type="button"
                  className="btn btn--danger btn--sm"
                  disabled={
                    deleting === run.thread_id ||
                    run.status === "running" ||
                    run.status === "pending" ||
                    run.status === "paused"
                  }
                  title={
                    run.status === "running" || run.status === "paused"
                      ? "运行未结束，不能删除数据"
                      : `删除 ${run.thread_id} 的数据文件夹`
                  }
                  onClick={() => void removeData(run)}
                >
                  <Icon name="trash" size={12} />
                  {deleting === run.thread_id ? "删除中…" : "删除数据"}
                </button>
              </span>
            </div>
          ))}
        </div>
      )}

      {logFor ? (
        <div className="modal-backdrop" onClick={() => setLogFor(null)}>
          <div
            className="modal modal--log"
            role="dialog"
            aria-modal="true"
            aria-label="运行日志"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="modal__head">
              <div className="modal__title">
                <Icon name="terminal" size={16} />
                <div>
                  <h2>运行日志</h2>
                  <p>
                    {logFor.name} · <code className="mono">{logFor.thread_id}</code> ·
                    最近 {logLines.length} 条
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => setLogFor(null)}
              >
                关闭
              </button>
            </header>
            <div className="modal__body modal__body--single">
              {logLoading ? (
                <div className="skeleton skeleton--bar" />
              ) : logLines.length ? (
                <pre className="log-view">{logLines.join("\n")}</pre>
              ) : (
                <EmptyState icon="terminal" title="暂无运行日志" hint="运行开始后会持续写入 run.log" />
              )}
            </div>
            <footer className="modal__foot">
              <span className="modal__foot-hint mono">
                {meta?.data_dir ?? "data/runs"}/{logFor.thread_id}/run.log
              </span>
              <div className="modal__foot-actions">
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => downloadText(`${logFor.thread_id}-run.log`, logLines.join("\n"))}
                >
                  <Icon name="download" size={12} />
                  下载日志
                </button>
              </div>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
