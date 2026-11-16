import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type { NodeConfig, NodeId } from "../api/types";
import { Icon } from "../components/Icons";
import { Badge, EmptyState, toast } from "../components/ui";
import { useNodeConfigs } from "../hooks/useCatalog";
import { nodeLabel } from "../utils/format";

interface FormState {
  model: string;
  base_url: string;
  api_key_env: string;
  temperature: number;
  timeout_s: number;
  max_retries: number;
  prompt_version: string;
}

function toForm(config: NodeConfig): FormState {
  return {
    model: config.model,
    base_url: config.base_url ?? "",
    api_key_env: config.api_key_env,
    temperature: config.temperature,
    timeout_s: config.timeout_s,
    max_retries: config.max_retries,
    prompt_version: config.prompt_version,
  };
}

export function NodeConfigPage(): ReactNode {
  const { configs, loading, error, reload } = useNodeConfigs();
  const [selected, setSelected] = useState<NodeId>("planner");
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const active = useMemo(
    () => configs.find((config) => config.node === selected),
    [configs, selected],
  );

  useEffect(() => {
    if (active) {
      setForm(toForm(active));
      setConfirmReset(false);
    }
  }, [active]);

  if (loading) {
    return (
      <div className="page">
        <div className="skeleton skeleton--bar" />
        <div className="skeleton skeleton--canvas" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="page">
        <EmptyState icon="error" title="无法读取节点配置" hint={error} />
      </div>
    );
  }

  const dirty =
    active && form
      ? form.model !== active.model ||
        form.base_url !== (active.base_url ?? "") ||
        form.api_key_env !== active.api_key_env ||
        form.temperature !== active.temperature ||
        form.timeout_s !== active.timeout_s ||
        form.max_retries !== active.max_retries ||
        form.prompt_version !== active.prompt_version
      : false;

  const save = async () => {
    if (!form || !active) return;
    if (!form.model.trim()) {
      toast("模型名不能为空", "error");
      return;
    }
    if (!form.api_key_env.trim()) {
      toast("API Key 环境变量名不能为空", "error");
      return;
    }
    setSaving(true);
    try {
      await api.patchNodeConfig(active.node, {
        model: form.model.trim(),
        base_url: form.base_url.trim() || null,
        api_key_env: form.api_key_env.trim(),
        temperature: form.temperature,
        timeout_s: form.timeout_s,
        max_retries: form.max_retries,
        prompt_version: form.prompt_version,
      });
      await reload();
      toast(`${nodeLabel(active.node)} 配置已生效（新运行）`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    if (!active) return;
    setSaving(true);
    try {
      await api.resetNodeConfig(active.node);
      await reload();
      setConfirmReset(false);
      toast(`${nodeLabel(active.node)} 已恢复默认配置`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <header className="page__head">
        <div>
          <h1>LLM 节点配置</h1>
          <p className="page__sub">
            6 个 LLM 节点的接口、采样与提示词版本；运行使用启动时的配置快照，运行中修改只影响之后新建的运行
          </p>
        </div>
      </header>

      <div className="config-grid">
        <aside className="config-list">
          {configs.map((config) => (
            <button
              key={config.node}
              type="button"
              className={`config-list__item${selected === config.node ? " is-active" : ""}`}
              onClick={() => setSelected(config.node)}
            >
              <span className="config-list__name">{nodeLabel(config.node)}</span>
              <span className="config-list__model mono">{config.model}</span>
              <span className="config-list__meta">
                T{config.temperature} · {config.prompt_version}
              </span>
            </button>
          ))}
        </aside>

        <section className="config-form">
          {active && form ? (
            <>
              <div className="config-form__head">
                <div>
                  <h2>{nodeLabel(active.node)}</h2>
                  <p className="mono config-form__path">
                    POST /config/nodes/{active.node}
                  </p>
                </div>
                <div className="row">
                  {dirty ? <Badge tone="warn">未保存</Badge> : <Badge tone="muted">已同步</Badge>}
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => setForm(toForm(active))}
                    disabled={!dirty || saving}
                  >
                    撤销修改
                  </button>
                  <button
                    type="button"
                    className="btn btn--primary btn--sm"
                    onClick={save}
                    disabled={!dirty || saving}
                  >
                    {saving ? "保存中…" : "保存配置"}
                  </button>
                </div>
              </div>

              <div className="config-section">
                <h3>连接</h3>
                <div className="config-row">
                  <label className="field-label" htmlFor="model">
                    模型名
                  </label>
                  <input
                    id="model"
                    value={form.model}
                    onChange={(event) => setForm({ ...form, model: event.target.value })}
                    placeholder="deepseek-chat"
                  />
                </div>
                <div className="config-row">
                  <label className="field-label" htmlFor="base-url">
                    Base URL
                  </label>
                  <input
                    id="base-url"
                    value={form.base_url}
                    onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                    placeholder="https://api.deepseek.com/v1"
                  />
                </div>
                <div className="config-row">
                  <label className="field-label" htmlFor="key-env">
                    API Key 环境变量名
                  </label>
                  <div className="secret-row">
                    <input
                      id="key-env"
                      value={form.api_key_env}
                      onChange={(event) => setForm({ ...form, api_key_env: event.target.value })}
                      placeholder="MARS_LLM_API_KEY"
                    />
                    <span className="secret-mask mono" title="后端只保存环境变量名，不保存密钥">
                      ••••••••
                    </span>
                  </div>
                  <p className="field-help">
                    后端只保存变量名，密钥从进程环境读取；页面与日志永远不会显示明文
                  </p>
                </div>
              </div>

              <div className="config-section">
                <h3>采样与可靠性</h3>
                <div className="config-row config-row--inline">
                  <div>
                    <label className="field-label" htmlFor="temperature">
                      温度（0–2）
                    </label>
                    <div className="range-row">
                      <input
                        id="temperature"
                        type="range"
                        min={0}
                        max={2}
                        step={0.1}
                        value={form.temperature}
                        onChange={(event) =>
                          setForm({ ...form, temperature: Number(event.target.value) })
                        }
                      />
                      <span className="mono">{form.temperature.toFixed(1)}</span>
                    </div>
                  </div>
                  <div>
                    <label className="field-label" htmlFor="timeout">
                      超时（秒）
                    </label>
                    <input
                      id="timeout"
                      type="number"
                      min={1}
                      step={1}
                      value={form.timeout_s}
                      onChange={(event) =>
                        setForm({ ...form, timeout_s: Number(event.target.value) })
                      }
                    />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="retries">
                      最大重试
                    </label>
                    <input
                      id="retries"
                      type="number"
                      min={0}
                      max={10}
                      value={form.max_retries}
                      onChange={(event) =>
                        setForm({ ...form, max_retries: Number(event.target.value) })
                      }
                    />
                  </div>
                </div>
              </div>

              <div className="config-section">
                <h3>提示词模板</h3>
                <div className="config-row config-row--inline">
                  <div>
                    <label className="field-label" htmlFor="prompt-version">
                      版本
                    </label>
                    <select
                      id="prompt-version"
                      value={form.prompt_version}
                      onChange={(event) =>
                        setForm({ ...form, prompt_version: event.target.value })
                      }
                    >
                      {(active.available_versions.length
                        ? active.available_versions
                        : [active.prompt_version]
                      ).map((version) => (
                        <option key={version} value={version}>
                          {version}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="config-version-meta">
                    <span className="field-help">
                      可用版本：{active.available_versions.join("、") || "未发现"}
                    </span>
                    <span className="field-help">
                      模板文件位于 mars/prompts/{active.node}/
                    </span>
                  </div>
                </div>
                <p className="field-help">
                  当前后端不提供模板正文读写接口，版本切换只改变实际加载的提示词文件
                </p>
              </div>

              <div className="config-foot">
                <button
                  type="button"
                  className={`btn ${confirmReset ? "btn--danger" : "btn--ghost"}`}
                  onClick={() => (confirmReset ? reset() : setConfirmReset(true))}
                  disabled={saving}
                >
                  <Icon name="refresh" size={13} />
                  {confirmReset ? "确认恢复默认？" : "恢复默认配置"}
                </button>
                <span className="field-help">
                  默认值来自环境变量（MARS_*），恢复后进程重启仍保持默认
                </span>
              </div>
            </>
          ) : (
            <EmptyState icon="settings" title="选择一个节点" />
          )}
        </section>
      </div>

      <p className="config-note">
        <Icon name="clock" size={13} />
        配置覆盖保存在进程内存，重启后回落到环境变量默认值；API Key 只从环境变量读取
        {configs[0] ? `（当前引用 ${configs[0].api_key_env}）` : ""}
      </p>
    </div>
  );
}
