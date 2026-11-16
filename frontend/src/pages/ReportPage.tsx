import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { RunSnapshot } from "../api/types";
import { DiffView } from "../components/Diff";
import { Icon } from "../components/Icons";
import { Markdown } from "../components/Markdown";
import { Badge, CopyButton, EmptyState, Meter, RunStatusPill } from "../components/ui";
import {
  comparatorLabel,
  downloadText,
  elapsedSince,
  formatDateTime,
  formatDuration,
} from "../utils/format";
import { isRoutineIssue } from "../utils/derive";

function toneOf(acceptance: string): "success" | "warn" | "error" | "muted" {
  if (acceptance.startsWith("通过")) return "success";
  if (acceptance.includes("M 超限")) return "error";
  if (acceptance.startsWith("未通过")) return "warn";
  return "muted";
}

export function ReportPage(): ReactNode {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [wrap, setWrap] = useState(true);

  useEffect(() => {
    if (!runId) return;
    let active = true;
    api
      .getRun(runId)
      .then((value) => {
        if (active) setSnapshot(value);
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
  }, [runId]);

  if (loading) {
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
          title="报告不存在"
          hint={error ?? "该运行可能已随进程重启丢失"}
          action={
            <button type="button" className="btn btn--primary" onClick={() => navigate("/history")}>
              查看历史
            </button>
          }
        />
      </div>
    );
  }

  const values = snapshot.values;
  const prompt = values.optimized_prompt ?? "";
  const acceptance = snapshot.acceptance;
  const tone = toneOf(acceptance);
  const failed = snapshot.status === "failed";
  const criteria = values.performance_criteria ?? [];
  const report = values.report_md ?? "";
  const targetTrace = (values.trace ?? []).filter((trace) => trace.node === "target").pop();
  const level2 = (values.trace ?? [])
    .flatMap((trace) => trace.issues ?? [])
    .filter((issue) => issue.level === 2);
  const attention = level2.filter((issue) => !isRoutineIssue(issue));
  const routine = level2.length - attention.length;

  return (
    <div className="page page--report">
      <header className={`verdict verdict--${tone}`}>
        <div className="verdict__main">
          <span className="verdict__eyebrow">
            {failed ? "运行终止" : "验收结论"}
          </span>
          <h1>{acceptance}</h1>
          <div className="verdict__meta">
            <span>{snapshot.name}</span>
            <code className="mono">{snapshot.thread_id}</code>
            <RunStatusPill status={snapshot.status} />
            <span className="mono">
              {formatDateTime(snapshot.created_at)} ·{" "}
              {formatDuration(elapsedSince(snapshot.created_at, snapshot.finished_at || undefined))}
            </span>
          </div>
        </div>
        <div className="verdict__metrics">
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
        </div>
        <div className="verdict__badges">
          {(values.tsc_count ?? 0) >= snapshot.tsc_max ? <Badge tone="warn">TSC 超限</Badge> : null}
          {(values.m_count ?? 0) >= snapshot.m_max ? <Badge tone="error">M 超限</Badge> : null}
          {attention.length ? (
            <Badge tone="warn">需关注 {attention.length} 条</Badge>
          ) : null}
          {routine ? <Badge tone="muted">{routine} 条常规缺失</Badge> : null}
        </div>
      </header>

      <div className="report-grid">
        <div className="report-main">
          <section className="card">
            <div className="card__head">
              <h2 className="card__title">
                <Icon name="code" size={15} /> 最终提示词
                <Badge tone="muted">字段 03</Badge>
              </h2>
              <div className="row">
                <label className="switch">
                  <input
                    type="checkbox"
                    checked={wrap}
                    onChange={(event) => setWrap(event.target.checked)}
                  />
                  自动换行
                </label>
                <CopyButton text={prompt} label="复制" />
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => downloadText(`${snapshot.thread_id}-prompt.md`, prompt)}
                >
                  <Icon name="download" size={13} />
                  .md
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => downloadText(`${snapshot.thread_id}-prompt.txt`, prompt)}
                >
                  <Icon name="download" size={13} />
                  .txt
                </button>
              </div>
            </div>
            {prompt ? (
              <div className={`prompt-block${wrap ? " is-wrap" : ""}`}>
                <div className="prompt-block__gutter" aria-hidden="true">
                  {prompt.split("\n").map((_, index) => (
                    <span key={index}>{index + 1}</span>
                  ))}
                </div>
                <pre className="prompt-block__code">
                  <code>{prompt}</code>
                </pre>
              </div>
            ) : (
              <EmptyState
                icon="error"
                title="未产出最终提示词"
                hint="字段 03 为空，可能是运行在 Student 之前被终止"
              />
            )}
          </section>

          {values.initial_prompt ? (
            <section className="card">
              <div className="card__head">
                <h2 className="card__title">
                  <Icon name="route" size={15} /> 初始 ↔ 最终差异
                </h2>
                <span className="field-help">字段 01 → 字段 03</span>
              </div>
              <DiffView before={values.initial_prompt} after={prompt} />
            </section>
          ) : null}

          <section className="card">
            <div className="card__head">
              <h2 className="card__title">
                <Icon name="report" size={15} /> 优化报告
              </h2>
              <CopyButton text={report} label="复制 Markdown" />
            </div>
            {report ? (
              <Markdown source={report} />
            ) : (
              <EmptyState
                icon="report"
                title="没有生成报告"
                hint="Output 节点未执行（运行被终止时不会生成 report_md）"
              />
            )}
          </section>

          <section className="card">
            <h2 className="card__title">子任务与提问（保留全部状态）</h2>
            <div className="two-tables">
              <div>
                <h3 className="card__subtitle">05 子任务列表</h3>
                {(values.subtasks ?? []).length === 0 ? (
                  <p className="field-empty">空列表</p>
                ) : (
                  <table className="mini-table">
                    <thead>
                      <tr>
                        <th>id</th>
                        <th>内容</th>
                        <th>状态</th>
                        <th>得分</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(values.subtasks ?? []).map((item) => (
                        <tr key={item.id} className={item.status === "dropped" ? "is-dropped" : ""}>
                          <td className="mono">{item.id}</td>
                          <td>{item.content}</td>
                          <td>
                            <Badge
                              tone={
                                item.status === "dropped"
                                  ? "muted"
                                  : item.status === "pending"
                                    ? "warn"
                                    : "success"
                              }
                            >
                              {item.status}
                            </Badge>
                          </td>
                          <td className="mono">{item.score}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div>
                <h3 className="card__subtitle">06 启发式提问</h3>
                {(values.questions ?? []).length === 0 ? (
                  <p className="field-empty">空列表</p>
                ) : (
                  <table className="mini-table">
                    <thead>
                      <tr>
                        <th>id</th>
                        <th>内容</th>
                        <th>状态</th>
                        <th>得分</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(values.questions ?? []).map((item) => (
                        <tr key={item.id} className={item.status === "dropped" ? "is-dropped" : ""}>
                          <td className="mono">{item.id}</td>
                          <td>{item.content}</td>
                          <td>
                            <Badge
                              tone={
                                item.status === "dropped"
                                  ? "muted"
                                  : item.status === "open"
                                    ? "warn"
                                    : "success"
                              }
                            >
                              {item.status}
                            </Badge>
                          </td>
                          <td className="mono">{item.score}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </section>
        </div>

        <aside className="report-side">
          <section className="card">
            <h2 className="card__title">逐项验收</h2>
            <ul className="acceptance">
              {criteria.map((criterion) => (
                <li key={criterion.name}>
                  <span className="acceptance__name">{criterion.name}</span>
                  <span className="mono acceptance__threshold">
                    {comparatorLabel(criterion.comparator)} {criterion.threshold}
                  </span>
                  <Badge tone="muted">{targetTrace ? "无逐项结论" : "未验收"}</Badge>
                </li>
              ))}
            </ul>
            <p className="field-help">
              Target 节点只回写整体结论与路由，逐项判定理由未落状态；完整依据见右侧运行详情。
            </p>
            {targetTrace ? (
              <div className="target-summary">
                <span className="target-summary__label">Target 摘要</span>
                <p>{targetTrace.summary}</p>
              </div>
            ) : null}
          </section>

          <section className="card">
            <h2 className="card__title">评分摘要</h2>
            {[
              { label: "07 启发得分", detail: values.heuristic_score },
              { label: "08 执行得分", detail: values.execution_score },
            ].map((item) => (
              <div className="score-line" key={item.label}>
                <div className="score-line__head">
                  <span>{item.label}</span>
                  <strong className={item.detail && item.detail.score < 60 ? "is-low" : ""}>
                    {item.detail?.score ?? "—"}
                  </strong>
                </div>
                <p>{item.detail?.summary ?? "未评分"}</p>
              </div>
            ))}
          </section>

          <section className="card">
            <h2 className="card__title">运行信息</h2>
            <dl className="kv-list">
              <div>
                <dt>run_id</dt>
                <dd className="mono">{snapshot.thread_id}</dd>
              </div>
              <div>
                <dt>创建时间</dt>
                <dd className="mono">{formatDateTime(snapshot.created_at)}</dd>
              </div>
              <div>
                <dt>节点执行</dt>
                <dd className="mono">
                  {(values.trace ?? []).filter((trace) => !trace.node.startsWith("gate:")).length} 次
                </dd>
              </div>
              <div>
                <dt>LLM 调用</dt>
                <dd className="mono">
                  {(values.trace ?? []).filter((trace) => trace.model).length} 次
                </dd>
              </div>
            </dl>
          </section>

          <section className="card card--actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => downloadText(`${snapshot.thread_id}-report.md`, report || prompt)}
            >
              <Icon name="download" size={13} />
              下载完整报告
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => navigate(`/console/${snapshot.thread_id}`)}
            >
              <Icon name="console" size={13} />
              回到控制台
            </button>
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => navigate(`/new?from=${snapshot.thread_id}`)}
            >
              <Icon name="refresh" size={13} />
              复制为新任务
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
}
