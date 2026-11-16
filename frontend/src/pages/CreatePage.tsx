import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Comparator, Criterion } from "../api/types";
import { Icon } from "../components/Icons";
import { Badge, toast } from "../components/ui";
import { useEdges, useMeta, useNodeConfigs } from "../hooks/useCatalog";
import { comparatorLabel, nodeLabel } from "../utils/format";

const DRAFT_KEY = "mars.draft.v1";

interface Draft {
  name: string;
  initial_prompt: string;
  optimization_goal: string;
  criteria: Criterion[];
  tsc_max: number;
  m_max: number;
  breakpoints: string[];
}

const EMPTY_DRAFT: Draft = {
  name: "",
  initial_prompt: "",
  optimization_goal: "",
  criteria: [{ name: "可执行性", threshold: 0.85, comparator: "gte" }],
  tsc_max: 5,
  m_max: 3,
  breakpoints: [],
};

const SAMPLE: Draft = {
  name: "客服话术结构化",
  initial_prompt: "帮我把客服聊天记录整理一下，输出重点。",
  optimization_goal: "把口语化记录整理成结构化、可执行的分析报告，包含客户诉求、处理动作与兜底话术",
  criteria: [
    { name: "可执行性", threshold: 0.85, comparator: "gte" },
    { name: "结构完整度", threshold: 0.9, comparator: "gte" },
  ],
  tsc_max: 5,
  m_max: 3,
  breakpoints: [],
};

function loadDraft(): Draft {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (!raw) return EMPTY_DRAFT;
    const parsed = JSON.parse(raw) as Partial<Draft>;
    return { ...EMPTY_DRAFT, ...parsed, breakpoints: parsed.breakpoints ?? [] };
  } catch {
    return EMPTY_DRAFT;
  }
}

export function CreatePage(): ReactNode {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const meta = useMeta();
  const { edges } = useEdges();
  const { configs } = useNodeConfigs();
  const [draft, setDraft] = useState<Draft>(loadDraft);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [showEdges, setShowEdges] = useState(false);
  const [copiedFrom, setCopiedFrom] = useState<string | null>(null);

  useEffect(() => {
    const from = params.get("from");
    if (!from) return;
    let active = true;
    api
      .getRun(from)
      .then((run) => {
        if (!active) return;
        setDraft({
          name: `${run.name}（复制）`,
          initial_prompt: run.values.optimized_prompt || run.values.initial_prompt || "",
          optimization_goal: run.values.optimization_goal || "",
          criteria: run.values.performance_criteria ?? [],
          tsc_max: run.tsc_max,
          m_max: run.m_max,
          breakpoints: run.breakpoints ?? [],
        });
        setCopiedFrom(run.thread_id);
      })
      .catch(() => toast("无法读取源运行，已保留当前草稿", "warn"));
    return () => {
      active = false;
    };
  }, [params]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
      setSavedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draft]);

  const issues = useMemo(() => {
    const blocking: string[] = [];
    const warnings: string[] = [];
    if (!draft.initial_prompt.trim()) blocking.push("初始提示词不能为空");
    if (!draft.optimization_goal.trim()) blocking.push("优化方向及目的不能为空");
    if (draft.criteria.length === 0) blocking.push("性能指标至少需要 1 条");
    draft.criteria.forEach((criterion, index) => {
      if (!criterion.name.trim()) blocking.push(`第 ${index + 1} 条指标缺少名称`);
      if (!Number.isFinite(criterion.threshold)) blocking.push(`第 ${index + 1} 条指标阈值非法`);
    });
    const names = draft.criteria.map((criterion) => criterion.name.trim());
    if (new Set(names).size !== names.length) warnings.push("存在重复的指标名称");
    if (draft.initial_prompt.trim().length > 0 && draft.initial_prompt.trim().length < 20) {
      warnings.push("初始提示词较短（<20 字），优化空间有限");
    }
    if (draft.tsc_max < 1) blocking.push("TSC 上限必须 ≥ 1");
    if (draft.m_max < 1) blocking.push("M 上限必须 ≥ 1");
    const unset = configs.filter((config) => !config.api_key_env);
    if (unset.length) warnings.push(`${unset.length} 个节点未设置 API Key 环境变量`);
    return { blocking, warnings };
  }, [draft, configs]);

  const start = async () => {
    if (issues.blocking.length) {
      toast(issues.blocking[0], "error");
      return;
    }
    setStarting(true);
    try {
      const created = await api.createRun({
        name: draft.name.trim() || undefined,
        initial_prompt: draft.initial_prompt.trim(),
        optimization_goal: draft.optimization_goal.trim(),
        performance_criteria: draft.criteria.map((criterion) => ({
          ...criterion,
          name: criterion.name.trim(),
        })),
        breakpoints: draft.breakpoints,
        tsc_max: draft.tsc_max,
        m_max: draft.m_max,
      });
      toast(`${created.thread_id} 已启动`, "success");
      navigate(`/console/${created.thread_id}`);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setStarting(false);
    }
  };

  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  return (
    <div className="page page--form">
      <header className="page__head">
        <div>
          <h1>新建优化任务</h1>
          <p className="page__sub">
            填写初始提示词与验收口径，启动后可在运行控制台设断点、改道、查看最终报告
          </p>
        </div>
        <div className="page__head-actions">
          <span className="page__saved">
            {savedAt ? `草稿已保存 ${savedAt}` : "正在保存草稿…"}
          </span>
          <button type="button" className="btn btn--ghost" onClick={() => setDraft(SAMPLE)}>
            <Icon name="spark" size={13} />
            填入示例
          </button>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setDraft(EMPTY_DRAFT);
              window.localStorage.removeItem(DRAFT_KEY);
              toast("草稿已清空", "info");
            }}
          >
            清空
          </button>
          <button
            type="button"
            className="btn btn--primary"
            disabled={starting || issues.blocking.length > 0}
            onClick={start}
          >
            <Icon name="play" size={13} />
            {starting ? "启动中…" : "启动运行"}
          </button>
        </div>
      </header>

      <div className="form-grid">
        <div className="form-main">
          {copiedFrom ? (
            <div className="banner banner--info">
              <Icon name="copy" size={14} />
              <span>
                已从 <code>{copiedFrom}</code> 复制参数：初始提示词使用该运行的最优产出，指标与循环上限沿用
              </span>
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                onClick={() => navigate(`/console/${copiedFrom}`)}
              >
                查看源运行
              </button>
            </div>
          ) : null}
          <section className="card">
            <h2 className="card__title">基本信息</h2>
            <label className="field-label" htmlFor="task-name">
              任务名
            </label>
            <input
              id="task-name"
              value={draft.name}
              onChange={(event) => update({ name: event.target.value })}
              placeholder="例如 客服话术结构化 v3"
            />
            <p className="field-help">留空时以初始提示词前 24 个字符命名</p>
          </section>

          <section className="card">
            <h2 className="card__title">
              提示词 <Badge tone="muted">字段 01 / 04</Badge>
            </h2>
            <label className="field-label" htmlFor="initial-prompt">
              初始提示词 <span className="req">*</span>
              <em>{draft.initial_prompt.length} 字</em>
            </label>
            <textarea
              id="initial-prompt"
              rows={8}
              value={draft.initial_prompt}
              onChange={(event) => update({ initial_prompt: event.target.value })}
              placeholder="把待优化的原始提示词完整粘贴到这里"
            />
            <label className="field-label" htmlFor="optimization-goal">
              优化方向及目的 <span className="req">*</span>
              <em>{draft.optimization_goal.length} 字</em>
            </label>
            <textarea
              id="optimization-goal"
              rows={4}
              value={draft.optimization_goal}
              onChange={(event) => update({ optimization_goal: event.target.value })}
              placeholder="希望往哪个方向优化？解决什么问题？"
            />
            <p className="field-help">01 / 04 仅 User 节点可写，运行中只能在断点补充输入时更新</p>
          </section>

          <section className="card">
            <h2 className="card__title">
              性能指标 <Badge tone="muted">字段 09</Badge>
            </h2>
            <p className="field-help">初始化后视为不变量，Target 节点据此做最终验收</p>
            <div className="criteria-editor">
              <div className="criteria-editor__head">
                <span>指标名</span>
                <span>比较</span>
                <span>阈值</span>
                <span />
              </div>
              {draft.criteria.map((criterion, index) => (
                <div className="criteria-editor__row" key={index}>
                  <input
                    value={criterion.name}
                    onChange={(event) => {
                      const next = draft.criteria.slice();
                      next[index] = { ...criterion, name: event.target.value };
                      update({ criteria: next });
                    }}
                    placeholder="例如 可执行性"
                  />
                  <select
                    value={criterion.comparator}
                    onChange={(event) => {
                      const next = draft.criteria.slice();
                      next[index] = {
                        ...criterion,
                        comparator: event.target.value as Comparator,
                      };
                      update({ criteria: next });
                    }}
                  >
                    <option value="gte">≥ 不小于</option>
                    <option value="lte">≤ 不大于</option>
                    <option value="eq">= 等于</option>
                  </select>
                  <input
                    type="number"
                    step="0.05"
                    value={criterion.threshold}
                    onChange={(event) => {
                      const next = draft.criteria.slice();
                      next[index] = { ...criterion, threshold: Number(event.target.value) };
                      update({ criteria: next });
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn--ghost btn--icon"
                    title="删除该指标"
                    disabled={draft.criteria.length <= 1}
                    onClick={() =>
                      update({ criteria: draft.criteria.filter((_, i) => i !== index) })
                    }
                  >
                    <Icon name="trash" size={13} />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() =>
                update({
                  criteria: [
                    ...draft.criteria,
                    { name: "", threshold: 0.8, comparator: "gte" },
                  ],
                })
              }
            >
              <Icon name="plus" size={13} />
              添加指标
            </button>
          </section>

          <section className="card">
            <h2 className="card__title">
              循环上限 <Badge tone="muted">字段 10 / 11</Badge>
            </h2>
            <div className="inline-fields">
              <div>
                <label className="field-label" htmlFor="tsc-max">
                  TSC 循环上限（Critic 递增）
                </label>
                <input
                  id="tsc-max"
                  type="number"
                  min={1}
                  max={50}
                  value={draft.tsc_max}
                  onChange={(event) => update({ tsc_max: Number(event.target.value) })}
                />
              </div>
              <div>
                <label className="field-label" htmlFor="m-max">
                  M 循环上限（Manager 递增）
                </label>
                <input
                  id="m-max"
                  type="number"
                  min={1}
                  max={20}
                  value={draft.m_max}
                  onChange={(event) => update({ m_max: Number(event.target.value) })}
                />
              </div>
            </div>
            <p className="field-help">
              达到 TSC 上限且未达标 → 结束局部循环进入 Target；达到 M 上限 → 不再回退，强制
              Output 并生成失败报告
            </p>
          </section>

          <section className="card">
            <button
              type="button"
              className="card__toggle"
              onClick={() => setShowEdges((value) => !value)}
            >
              <h2 className="card__title">
                预置断点 <Badge tone="muted">{draft.breakpoints.length} 条</Badge>
              </h2>
              <Icon name={showEdges ? "chevronDown" : "chevron"} size={14} />
            </button>
            {showEdges ? (
              <div className="edge-picker">
                {edges.map((edge) => (
                  <label key={edge.edge_id} className="edge-picker__row">
                    <input
                      type="checkbox"
                      checked={draft.breakpoints.includes(edge.edge_id)}
                      onChange={(event) =>
                        update({
                          breakpoints: event.target.checked
                            ? [...draft.breakpoints, edge.edge_id]
                            : draft.breakpoints.filter((item) => item !== edge.edge_id),
                        })
                      }
                    />
                    <code>{edge.edge_id}</code>
                    <span className={`edge-picker__kind${edge.kind === "conditional" ? " is-cond" : ""}`}>
                      {edge.kind === "static" ? "普通" : "条件"}
                    </span>
                    <span className="edge-picker__cond">{edge.condition}</span>
                  </label>
                ))}
              </div>
            ) : (
              <p className="field-help">启动前预置断点，运行命中后会弹出干预窗口</p>
            )}
          </section>
        </div>

        <aside className="form-side">
          <section className="card card--sticky">
            <h2 className="card__title">启动前校验</h2>
            {issues.blocking.length === 0 ? (
              <p className="check check--ok">
                <Icon name="check" size={13} />
                可以启动
              </p>
            ) : (
              issues.blocking.map((item) => (
                <p key={item} className="check check--error">
                  <Icon name="error" size={13} />
                  {item}
                </p>
              ))
            )}
            {issues.warnings.map((item) => (
              <p key={item} className="check check--warn">
                <Icon name="warn" size={13} />
                {item}
              </p>
            ))}

            <h3 className="card__subtitle">本次将使用的模型配置</h3>
            <ul className="config-brief">
              {configs.map((config) => (
                <li key={config.node}>
                  <span>{nodeLabel(config.node)}</span>
                  <code>{config.model}</code>
                  <em>{config.prompt_version}</em>
                </li>
              ))}
              {configs.length === 0 ? <li className="config-brief__empty">加载中…</li> : null}
            </ul>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => navigate("/settings/nodes")}
            >
              <Icon name="settings" size={13} />
              去节点配置
            </button>

            {meta?.demo ? (
              <p className="demo-note">
                <Icon name="spark" size={12} />
                演示模式：使用内置样例模型，无需 API Key
              </p>
            ) : null}

            <div className="criteria-preview">
              <h3 className="card__subtitle">验收口径</h3>
              {draft.criteria.map((criterion, index) => (
                <p key={index} className="mono">
                  {criterion.name || "未命名"} {comparatorLabel(criterion.comparator)}{" "}
                  {criterion.threshold}
                </p>
              ))}
            </div>
          </section>
        </aside>
      </div>

      {issues.blocking.length ? (
        <div className="banner banner--warn">
          <Icon name="warn" size={14} />
          仍有 {issues.blocking.length} 项阻断问题，启动按钮已禁用
        </div>
      ) : null}
    </div>
  );
}
