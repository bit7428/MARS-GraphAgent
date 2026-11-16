import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import type { RunStatus } from "../api/types";
import { STATUS_LABEL, copyText, formatDuration } from "../utils/format";
import { Icon, type IconName } from "./Icons";

type Tone = "info" | "success" | "warn" | "error";

interface ToastItem {
  id: number;
  message: string;
  tone: Tone;
}

let items: ToastItem[] = [];
const listeners = new Set<(next: ToastItem[]) => void>();
let seq = 0;

function emit(): void {
  for (const listener of listeners) listener(items);
}

export function toast(message: string, tone: Tone = "info"): void {
  const id = seq + 1;
  seq = id;
  items = [...items, { id, message, tone }];
  emit();
  window.setTimeout(() => {
    items = items.filter((item) => item.id !== id);
    emit();
  }, 4600);
}

export function Toaster(): ReactNode {
  const [list, setList] = useState<ToastItem[]>(items);
  useEffect(() => {
    listeners.add(setList);
    return () => {
      listeners.delete(setList);
    };
  }, []);
  return (
    <div className="toaster" role="status" aria-live="polite">
      {list.map((item) => (
        <div key={item.id} className={`toast toast--${item.tone}`}>
          <span className="toast__icon">
            <Icon
              name={
                item.tone === "error"
                  ? "error"
                  : item.tone === "warn"
                    ? "warn"
                    : item.tone === "success"
                      ? "check"
                      : "dot"
              }
              size={14}
            />
          </span>
          <span>{item.message}</span>
        </div>
      ))}
    </div>
  );
}

export function RunStatusPill({ status }: { status: RunStatus }): ReactNode {
  return (
    <span className={`status-pill status-pill--${status}`}>
      <span className="status-pill__dot" />
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Meter({
  label,
  value,
  max,
  tone = "accent",
}: {
  label: string;
  value: number;
  max: number;
  tone?: "accent" | "warn" | "error";
}): ReactNode {
  const safeMax = Math.max(1, max);
  const filled = Math.min(value, safeMax);
  return (
    <div className={`meter meter--${tone}`} title={`${label} ${value}/${max}`}>
      <span className="meter__label">{label}</span>
      <span className="meter__value">
        {value}
        <span className="meter__max">/{max}</span>
      </span>
      <span className="meter__bars" aria-hidden="true">
        {Array.from({ length: safeMax }).map((_, index) => (
          <span key={index} className={`meter__bar${index < filled ? " is-on" : ""}`} />
        ))}
      </span>
    </div>
  );
}

export function CopyButton({
  text,
  label = "复制",
  className = "btn btn--ghost btn--sm",
  title,
}: {
  text: string;
  label?: string;
  className?: string;
  title?: string;
}): ReactNode {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={className}
      title={title ?? label}
      onClick={async () => {
        const ok = await copyText(text);
        setCopied(ok);
        toast(ok ? "已复制到剪贴板" : "复制失败，请手动选择", ok ? "success" : "error");
        window.setTimeout(() => setCopied(false), 1600);
      }}
    >
      <Icon name={copied ? "check" : "copy"} size={13} />
      {copied ? "已复制" : label}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "success" | "warn" | "error" | "muted";
  title?: string;
}): ReactNode {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      {children}
    </span>
  );
}

export function EmptyState({
  icon = "dot",
  title,
  hint,
  action,
}: {
  icon?: IconName;
  title: string;
  hint?: string;
  action?: ReactNode;
}): ReactNode {
  return (
    <div className="empty">
      <span className="empty__icon">
        <Icon name={icon} size={18} />
      </span>
      <p className="empty__title">{title}</p>
      {hint ? <p className="empty__hint">{hint}</p> : null}
      {action ? <div className="empty__action">{action}</div> : null}
    </div>
  );
}

export function KV({
  label,
  children,
  mono,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}): ReactNode {
  return (
    <div className="kv">
      <span className="kv__label">{label}</span>
      <span className={`kv__value${mono ? " is-mono" : ""}`}>{children}</span>
    </div>
  );
}

export function Duration({ value }: { value: number | null | undefined }): ReactNode {
  return <span className="mono">{formatDuration(value)}</span>;
}

export function SectionTitle({
  children,
  extra,
}: {
  children: ReactNode;
  extra?: ReactNode;
}): ReactNode {
  return (
    <div className="section-title">
      <h3>{children}</h3>
      {extra}
    </div>
  );
}
