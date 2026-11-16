import { useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type { EdgeSpec, InterruptPayload, RunSnapshot } from "../api/types";
import { Icon } from "../components/Icons";
import { Badge } from "../components/ui";
import { nodeLabel } from "../utils/format";
import { FIELDS, NODE_CONTRACTS, fieldName } from "../graph/meta";

interface Props {
  snapshot: RunSnapshot;
  interrupt: InterruptPayload;
  edge: EdgeSpec | undefined;
  onResolved: (snapshot: RunSnapshot) => void;
}

type Mode = "continue" | "reroute" | "abort";

/**
 * 前端预校验：目标节点的必需字段必须已存在于当前快照。
 * 后端会拒绝不满足契约的改道（E2-REROUTE-REJECTED）并按原路由继续，
 * 提前禁用可以避免「看起来可选、提交却被拒绝」。
 */
function missingRequired(
  node: string,
  values: RunSnapshot["values"],
): number[] {
  const contract = NODE_CONTRACTS[node as keyof typeof NODE_CONTRACTS];
  if (!contract) return [];
  const raw = values as unknown as Record<string, unknown>;
  return contract.required.filter((index) => {
    const meta = FIELDS.find((field) => field.index === index);
    if (!meta) return false;
    const value = raw[meta.key];
    if (value === undefined || value === null) return true;
    if (meta.kind === "text") return typeof value === "string" ? value.trim() === "" : true;
    if (meta.kind === "list") return !Array.isArray(value);
    if (meta.kind === "score") return typeof value !== "object";
    if (meta.kind === "criteria") return !Array.isArray(value) || value.length === 0;
    if (meta.kind === "counter") return typeof value !== "number";
    return false;
  });
}

export function BreakpointModal({
  snapshot,
  interrupt,
  edge,
  onResolved,
}: Props): ReactNode {
  const [mode, setMode] = useState<Mode>("continue");
  const [target, setTarget] = useState<string>("");
  const [operator, setOperator] = useState("");
  const [supplement, setSupplement] = useState({ initial_prompt: "", optimization_goal: "" });
  const [supplementMode, setSupplementMode] = useState<"append" | "replace">("append");
  const [abortArmed, setAbortArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allowed = new Set(interrupt.allowed_reroutes);
  const targetMissing = target ? missingRequired(target, snapshot.values) : [];
  const targetBlocked = !target || !allowed.has(target) || targetMissing.length > 0;
  const needsSupplement = mode === "reroute" && target === "user";
  const blocked =
    (mode === "reroute" && targetBlocked) || (mode === "abort" && !abortArmed) || busy;

  const submit = async () => {
    if (mode === "abort" && !abortArmed) return;
    setBusy(true);
    setError(null);
    try {
      const payload: Parameters<typeof api.resume>[1] = {
        action: mode,
        operator: operator.trim() || undefined,
      };
      if (mode === "reroute") {
        payload.target = target;
      }
      if (needsSupplement) {
        if (supplement.initial_prompt.trim()) {
          payload.initial_prompt = supplement.initial_prompt.trim();
          payload.supplement_mode = supplementMode;
        }
        if (supplement.optimization_goal.trim()) {
          payload.optimization_goal = supplement.optimization_goal.trim();
          payload.supplement_mode = supplementMode;
        }
      }
      const next = await api.resume(snapshot.thread_id, payload);
      onResolved(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop">
      <div className="modal" role="dialog" aria-modal="true" aria-label="断点干预">
        <header className="modal__head">
          <div className="modal__title">
            <span className="modal__pulse" />
            <div>
              <h2>运行已在断点处暂停</h2>
              <p>
                状态已冻结在当前节点更新完成之后、下一节点执行之前 ·{" "}
                <code className="mono">{interrupt.state_digest.slice(0, 12)}</code>
              </p>
            </div>
          </div>
          <Badge tone="warn">已暂停</Badge>
        </header>

        <div className="modal__body">
          <section className="bp-col bp-col--left">
            <h3 className="bp-h3">命中边</h3>
            <div className="bp-edge">
              <code className="bp-edge__id">{interrupt.edge_id}</code>
              <div className="bp-edge__route">
                <span>{nodeLabel(edge?.source ?? interrupt.edge_id.split("->")[0])}</span>
                <Icon name="chevron" size={12} />
                <span>{nodeLabel(edge?.target ?? interrupt.edge_id.split("->")[1])}</span>
              </div>
              <dl>
                <div>
                  <dt>类型</dt>
                  <dd>{edge?.kind === "conditional" ? "条件边" : "普通边"}</dd>
                </div>
                <div>
                  <dt>条件</dt>
                  <dd>{edge?.condition ?? "—"}</dd>
                </div>
                <div>
                  <dt>原路由</dt>
                  <dd className="mono">{interrupt.route}</dd>
                </div>
              </dl>
            </div>

            <h3 className="bp-h3">本次已发生的副作用</h3>
            <div className="bp-effects">
              {edge?.side_effects?.length ? (
                edge.side_effects.map((effect) => (
                  <span key={effect} className="bp-effect">
                    {effect}
                  </span>
                ))
              ) : (
                <span className="bp-effect bp-effect--none">无</span>
              )}
            </div>
            <p className="bp-warn">
              <Icon name="warn" size={13} />
              副作用已生效且不可回滚，改道不会撤销上述变更。
            </p>

            <h3 className="bp-h3">计数</h3>
            <div className="bp-counters">
              <div>
                <span className="bp-count__label">TSC</span>
                <span className="bp-count__value mono">
                  {interrupt.counters?.tsc_count ?? snapshot.values.tsc_count ?? 0}
                  <em>/{snapshot.tsc_max}</em>
                </span>
              </div>
              <div>
                <span className="bp-count__label">M</span>
                <span className="bp-count__value mono">
                  {interrupt.counters?.m_count ?? snapshot.values.m_count ?? 0}
                  <em>/{snapshot.m_max}</em>
                </span>
              </div>
              <p className="bp-counters__note">决策不会改变 10 / 11 计数</p>
            </div>
          </section>

          <section className="bp-col bp-col--mid">
            <h3 className="bp-h3">命中时状态快照</h3>
            <dl className="bp-snapshot">
              <div>
                <dt>01 初始提示词</dt>
                <dd>{snapshot.values.initial_prompt ?? "未设置"}</dd>
              </div>
              <div>
                <dt>04 优化方向</dt>
                <dd>{snapshot.values.optimization_goal ?? "未设置"}</dd>
              </div>
              <div>
                <dt>03 已优化提示词</dt>
                <dd>
                  {snapshot.values.optimized_prompt
                    ? snapshot.values.optimized_prompt.slice(0, 120)
                    : "空（已快照到 02）"}
                </dd>
              </div>
              <div>
                <dt>05 / 06 列表</dt>
                <dd>
                  子任务 {snapshot.values.subtasks?.length ?? 0} 项 · 提问{" "}
                  {snapshot.values.questions?.length ?? 0} 项
                </dd>
              </div>
              <div>
                <dt>07 / 08 得分</dt>
                <dd>
                  {snapshot.values.heuristic_score?.score ?? "—"} /{" "}
                  {snapshot.values.execution_score?.score ?? "—"}
                </dd>
              </div>
            </dl>
            <p className="bp-hint">
              完整 11 个字段可在右侧抽屉「状态字段」中查看；此处只展示决策所需摘要。
            </p>
          </section>

          <section className="bp-col bp-col--right">
            <h3 className="bp-h3">决策</h3>
            <div className="bp-decisions">
              <button
                type="button"
                className={`bp-choice${mode === "continue" ? " is-active" : ""}`}
                onClick={() => setMode("continue")}
              >
                <span className="bp-choice__title">继续原路由</span>
                <span className="bp-choice__desc">
                  按 {interrupt.route} 继续，保留本次已发生的计数变化
                </span>
              </button>
              <button
                type="button"
                className={`bp-choice${mode === "reroute" ? " is-active" : ""}`}
                onClick={() => setMode("reroute")}
              >
                <span className="bp-choice__title">强制改道</span>
                <span className="bp-choice__desc">只改变下一个节点，不改计数</span>
              </button>
              <button
                type="button"
                className={`bp-choice bp-choice--danger${mode === "abort" ? " is-active" : ""}`}
                onClick={() => setMode("abort")}
              >
                <span className="bp-choice__title">终止运行</span>
                <span className="bp-choice__desc">立即结束，不生成报告</span>
              </button>
            </div>

            {mode === "reroute" ? (
              <div className="bp-reroute">
                <label className="bp-label" htmlFor="reroute-target">
                  改道目标
                </label>
                <select
                  id="reroute-target"
                  value={target}
                  onChange={(event) => setTarget(event.target.value)}
                >
                  <option value="">选择目标节点…</option>
                  {Object.keys(NODE_CONTRACTS).map((node) => {
                    const missing = missingRequired(node, snapshot.values);
                    const disabled = !allowed.has(node) || missing.length > 0;
                    return (
                      <option key={node} value={node} disabled={disabled}>
                        {nodeLabel(node)}
                        {!allowed.has(node)
                          ? "（不在候选）"
                          : missing.length
                            ? `（缺少${missing.map(fieldName).join("、")}）`
                            : ""}
                      </option>
                    );
                  })}
                </select>
                {target && !allowed.has(target) ? (
                  <p className="bp-inline-error">该目标不在可改道范围内</p>
                ) : null}
                {target && allowed.has(target) && targetMissing.length > 0 ? (
                  <p className="bp-inline-error">
                    <Icon name="warn" size={13} />
                    目标缺少必需字段：{targetMissing.map(fieldName).join("、")}
                    （后端会拒绝改道并按原路由继续）
                  </p>
                ) : null}
                {target && allowed.has(target) && targetMissing.length === 0 ? (
                  <p className="bp-inline-ok">
                    <Icon name="check" size={12} />
                    必要输入已齐备，可安全改道至 {nodeLabel(target)}
                  </p>
                ) : null}

                {needsSupplement ? (
                  <div className="bp-supplement">
                    <p className="bp-supplement__title">补充用户输入（仅改道到 User 时可用）</p>
                    <label className="bp-label" htmlFor="sup-mode">
                      写入方式
                    </label>
                    <select
                      id="sup-mode"
                      value={supplementMode}
                      onChange={(event) =>
                        setSupplementMode(event.target.value as "append" | "replace")
                      }
                    >
                      <option value="append">追加（append）</option>
                      <option value="replace">替换（replace）</option>
                    </select>
                    <label className="bp-label" htmlFor="sup-initial">
                      初始提示词（01）
                    </label>
                    <textarea
                      id="sup-initial"
                      rows={3}
                      value={supplement.initial_prompt}
                      onChange={(event) =>
                        setSupplement((current) => ({
                          ...current,
                          initial_prompt: event.target.value,
                        }))
                      }
                      placeholder="留空表示不修改"
                    />
                    <label className="bp-label" htmlFor="sup-goal">
                      优化方向及目的（04）
                    </label>
                    <textarea
                      id="sup-goal"
                      rows={2}
                      value={supplement.optimization_goal}
                      onChange={(event) =>
                        setSupplement((current) => ({
                          ...current,
                          optimization_goal: event.target.value,
                        }))
                      }
                      placeholder="留空表示不修改"
                    />
                  </div>
                ) : null}
              </div>
            ) : null}

            {mode === "abort" ? (
              <label className="bp-confirm">
                <input
                  type="checkbox"
                  checked={abortArmed}
                  onChange={(event) => setAbortArmed(event.target.checked)}
                />
                我确认立即结束本次运行，且不会生成优化报告
              </label>
            ) : null}

            <div className="bp-invariant">
              <p>
                <Icon name="check" size={12} />
                不跳过目标节点的必要输入校验；校验失败将拒绝改道并按原路由继续
              </p>
              <p>
                <Icon name="check" size={12} />
                不改变 10 / 11 计数
              </p>
              <p>
                <Icon name="check" size={12} />
                本次决策写入人工介入记录（gate:{interrupt.edge_id}）
              </p>
            </div>

            <label className="bp-label" htmlFor="operator">
              操作人（可选，用于留痕）
            </label>
            <input
              id="operator"
              value={operator}
              onChange={(event) => setOperator(event.target.value)}
              placeholder="例如 dillow"
            />

            {error ? (
              <p className="bp-inline-error">
                <Icon name="error" size={13} />
                {error}
              </p>
            ) : null}
          </section>
        </div>

        <footer className="modal__foot">
          <span className="modal__foot-hint">
            决策前弹窗不可关闭；字段 1–11 的只读视图在右侧抽屉
          </span>
          <div className="modal__foot-actions">
            <button
              type="button"
              className={`btn ${mode === "abort" ? "btn--danger" : "btn--primary"}`}
              disabled={blocked}
              onClick={submit}
            >
              {busy ? "提交中…" : mode === "continue" ? "继续原路由" : mode === "reroute" ? "确认改道" : "确认终止"}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
