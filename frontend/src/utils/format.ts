import type { RunStatus } from "../api/types";

export const STATUS_LABEL: Record<RunStatus, string> = {
  pending: "待启动",
  running: "运行中",
  paused: "已暂停",
  completed: "已结束",
  failed: "已终止",
};

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms <= 0) return "0ms";
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m${seconds.toString().padStart(2, "0")}s`;
}

export function formatClock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function elapsedSince(iso: string | null | undefined, end?: string | null): number {
  if (!iso) return 0;
  const start = new Date(iso).getTime();
  const stop = end ? new Date(end).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(stop)) return 0;
  return Math.max(0, stop - start);
}

export function clampText(text: string, limit: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit)}…` : clean;
}

export function comparatorLabel(comparator: string): string {
  if (comparator === "gte") return "≥";
  if (comparator === "lte") return "≤";
  return "=";
}

export function nodeLabel(node: string): string {
  const map: Record<string, string> = {
    user: "User",
    planner: "Planner",
    teacher: "Teacher",
    student: "Student",
    critic: "Critic",
    target: "Target",
    output: "Output",
    manager: "Manager",
  };
  return map[node] ?? node;
}

export function downloadText(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  }
}
