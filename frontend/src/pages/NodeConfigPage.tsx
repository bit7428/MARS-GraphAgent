import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type {
  ConnectionTest,
  NodeConfig,
  NodeId,
  PromptVersionView,
  SecretStatus,
} from "../api/types";
import { Icon } from "../components/Icons";
import { Badge, EmptyState, toast } from "../components/ui";
import { useMeta, useNodeConfigs } from "../hooks/useCatalog";
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

function nextVersionName(versions: string[]): string {
  const max = versions.reduce((acc, item) => Math.max(acc, Number(item.slice(1)) || 0), 0);
  return `v${max + 1}`;
}

export function NodeConfigPage(): ReactNode {
  const { configs, loading, error, reload } = useNodeConfigs();
  const meta = useMeta();
  const [selected, setSelected] = useState<NodeId>("planner");
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const [secrets, setSecrets] = useState<SecretStatus[]>([]);
  const [secretEditing, setSecretEditing] = useState(false);
  const [secretValue, setSecretValue] = useState("");
  const [secretBusy, setSecretBusy] = useState(false);
  const [probing, setProbing] = useState(false);
  const [probe, setProbe] = useState<ConnectionTest | null>(null);

  const [prompt, setPrompt] = useState<PromptVersionView | null>(null);
  const [promptDraft, setPromptDraft] = useState("");
  const [promptBusy, setPromptBusy] = useState(false);

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

  const loadSecrets = useCallback(async () => {
    try {
      setSecrets(await api.listSecrets());
    } catch {
      /* 密钥状态读取失败不影响主流程 */
    }
  }, []);

  useEffect(() => {
    void loadSecrets();
  }, [loadSecrets]);

  const promptVersion = form?.prompt_version;

  useEffect(() => {
    if (!promptVersion) return;
    let cancelled = false;
    setPromptBusy(true);
    api
      .getPrompt(selected, promptVersion)
      .then((view) => {
        if (cancelled) return;
        setPrompt(view);
        setPromptDraft(view.content);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPrompt(null);
        setPromptDraft("");
        toast(err instanceof Error ? err.message : String(err), "error");
      })
      .finally(() => {
        if (!cancelled) setPromptBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selected, promptVersion]);

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
      await loadSecrets();
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

  const currentSecret = secrets.find((item) => item.env_name === form?.api_key_env.trim());
  const promptDirty = prompt ? promptDraft !== prompt.content : promptDraft.length > 0;
  const versions = prompt?.versions ?? active?.available_versions ?? [];

  const saveSecret = async () => {
    const envName = form?.api_key_env.trim() ?? "";
    if (!envName) {
      toast("请先填写环境变量名", "error");
      return;
    }
    if (secretValue.trim().length < 8) {
      toast("密钥至少 8 个字符", "error");
      return;
    }
    setSecretBusy(true);
    try {
      const status = await api.setSecret(envName, secretValue);
      setSecrets((prev) => [...prev.filter((item) => item.env_name !== status.env_name), status]);
      setSecretValue("");
      setSecretEditing(false);
      toast(`密钥已保存（尾号 ${status.tail ?? "----"}）`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setSecretBusy(false);
    }
  };

  const clearSecret = async () => {
    const envName = form?.api_key_env.trim() ?? "";
    if (!envName) return;
    setSecretBusy(true);
    try {
      const status = await api.clearSecret(envName);
      setSecrets((prev) => [...prev.filter((item) => item.env_name !== status.env_name), status]);
      setProbe(null);
      toast("已清除该环境变量下的密钥", "info");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setSecretBusy(false);
    }
  };

  const runProbe = async () => {
    setProbing(true);
    try {
      const result = await api.testNode(selected);
      setProbe(result);
      toast(result.ok ? "连接正常" : "连接失败，请检查模型与密钥", result.ok ? "success" : "error");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setProbing(false);
    }
  };

  const savePromptContent = async () => {
    if (!form) return;
    setPromptBusy(true);
    try {
      const view = await api.savePrompt(selected, form.prompt_version, promptDraft);
      setPrompt(view);
      setPromptDraft(view.content);
      toast(`模板 ${selected}/${view.version} 已保存`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setPromptBusy(false);
    }
  };

  const createPromptVersion = async () => {
    if (!form) return;
    const target = nextVersionName(versions);
    setPromptBusy(true);
    try {
      const view = await api.savePrompt(selected, target, promptDraft);
      setPrompt(view);
      setPromptDraft(view.content);
      setForm({ ...form, prompt_version: target });
      toast(`已创建 ${target}，保存配置后生效`, "info");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setPromptBusy(false);
    }
  };

  const removePromptVersion = async () => {
    if (!form) return;
    setPromptBusy(true);
    try {
      const view = await api.deletePrompt(selected, form.prompt_version);
      setPrompt(view);
      setPromptDraft(view.content);
      setForm({ ...form, prompt_version: view.version });
      toast(`已删除 ${form.prompt_version}`, "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setPromptBusy(false);
    }
  };

  return (
    <div className="page">
      <header className="page__head">
        <div>
          <h1>LLM 节点配置</h1>
          <p className="page__sub">
            6 个 LLM 节点的接口、密钥、采样与系统提示词；运行使用启动时的配置快照，修改只影响之后新建的运行
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
                  <p className="mono config-form__path">POST /config/nodes/{active.node}</p>
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
                    <span className="secret-mask mono" title="接口只返回尾号，不回传明文">
                      ••••••••
                    </span>
                  </div>
                  <div className="secret-state">
                    <Badge tone={currentSecret?.configured ? "success" : "warn"}>
                      {currentSecret?.configured
                        ? `已配置 ${currentSecret.tail ?? ""}`
                        : "未配置"}
                    </Badge>
                    {currentSecret?.source ? (
                      <span className="field-help">
                        来源：{currentSecret.source === "file" ? "本地密钥文件" : "进程环境变量"}
                      </span>
                    ) : null}
                    {currentSecret?.used_by?.length ? (
                      <span className="field-help">
                        被 {currentSecret.used_by.length} 个节点引用
                      </span>
                    ) : null}
                    <span className="secret-state__actions">
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setSecretEditing(true);
                          setProbe(null);
                        }}
                      >
                        <Icon name="lock" size={12} />
                        {currentSecret?.configured ? "更换密钥" : "设置密钥"}
                      </button>
                      {currentSecret?.configured ? (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          onClick={clearSecret}
                          disabled={secretBusy}
                        >
                          清除
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={runProbe}
                        disabled={probing}
                      >
                        <Icon name="spark" size={12} />
                        {probing ? "测试中…" : "测试连接"}
                      </button>
                    </span>
                  </div>

                  {secretEditing ? (
                    <div className="secret-editor">
                      <input
                        type="password"
                        autoComplete="off"
                        autoFocus
                        value={secretValue}
                        onChange={(event) => setSecretValue(event.target.value)}
                        placeholder="粘贴 API Key（保存后只显示尾号）"
                        onKeyDown={(event) => {
                          if (event.key === "Enter") void saveSecret();
                          if (event.key === "Escape") {
                            setSecretEditing(false);
                            setSecretValue("");
                          }
                        }}
                      />
                      <button
                        type="button"
                        className="btn btn--primary btn--sm"
                        onClick={saveSecret}
                        disabled={secretBusy}
                      >
                        保存密钥
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost btn--sm"
                        onClick={() => {
                          setSecretEditing(false);
                          setSecretValue("");
                        }}
                      >
                        取消
                      </button>
                    </div>
                  ) : null}

                  {probe ? (
                    <p className={`probe ${probe.ok ? "probe--ok" : "probe--error"}`}>
                      <Icon name={probe.ok ? "check" : "error"} size={12} />
                      {probe.ok
                        ? `连通正常 · ${probe.model} · ${probe.latency_ms}ms`
                        : `连接失败：${probe.message}`}
                    </p>
                  ) : null}

                  <p className="field-help">
                    密钥写入 {meta?.secret_path ?? ".mars/secrets.json"}（仅本机、权限 600），接口与日志只返回尾号
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
                <div className="config-section__head">
                  <h3>系统提示词模板</h3>
                  <div className="row">
                    {promptDirty ? (
                      <Badge tone="warn">未保存</Badge>
                    ) : (
                      <Badge tone="muted">已同步</Badge>
                    )}
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={() => setPromptDraft(prompt?.recommended ?? "")}
                      disabled={!prompt?.recommended || promptBusy}
                      title="填入符合该节点 JSON 契约的推荐模板"
                    >
                      <Icon name="spark" size={12} />
                      载入推荐模板
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={createPromptVersion}
                      disabled={promptBusy}
                    >
                      <Icon name="plus" size={12} />
                      新建版本
                    </button>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm"
                      onClick={removePromptVersion}
                      disabled={promptBusy || versions.length <= 1}
                      title={versions.length <= 1 ? "至少保留一个版本" : "删除当前版本"}
                    >
                      <Icon name="trash" size={12} />
                      删除版本
                    </button>
                    <button
                      type="button"
                      className="btn btn--primary btn--sm"
                      onClick={savePromptContent}
                      disabled={!promptDirty || promptBusy}
                    >
                      {promptBusy ? "处理中…" : "保存模板"}
                    </button>
                  </div>
                </div>

                <div className="config-row config-row--inline">
                  <div>
                    <label className="field-label" htmlFor="prompt-version">
                      编辑版本
                    </label>
                    <select
                      id="prompt-version"
                      value={form.prompt_version}
                      onChange={(event) =>
                        setForm({ ...form, prompt_version: event.target.value })
                      }
                    >
                      {versions.map((version) => (
                        <option key={version} value={version}>
                          {version}
                          {version === active.prompt_version ? "（当前使用）" : ""}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="config-version-meta">
                    <span className="field-help">可用版本：{versions.join("、") || "未发现"}</span>
                    <span className="field-help mono">
                      mars/prompts/{active.node}/{form.prompt_version}.md
                    </span>
                  </div>
                </div>

                <textarea
                  className="prompt-editor"
                  rows={16}
                  spellCheck={false}
                  value={promptDraft}
                  disabled={promptBusy}
                  onChange={(event) => setPromptDraft(event.target.value)}
                  placeholder="留空则仅依赖节点代码内的 JSON schema 校验；建议写明角色、输入、以及要求返回的 JSON 字段。"
                />
                <div className="prompt-editor__foot">
                  <span>
                    {promptDraft.split("\n").length} 行 · {promptDraft.length} 字符
                  </span>
                  <span>保存后立即失效缓存，下一次节点调用即生效</span>
                </div>
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
        节点配置覆盖保存在进程内存，重启后回落到环境变量默认；密钥与提示词模板落盘到本地文件
        {meta?.prompt_root ? `（模板目录 ${meta.prompt_root}）` : ""}
      </p>
    </div>
  );
}
