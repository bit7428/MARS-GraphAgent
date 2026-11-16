import { useCallback, useEffect, useRef, useState } from "react";

import { api, eventsUrl } from "../api/client";
import type { RunEvent, RunSnapshot } from "../api/types";

export interface RunStream {
  snapshot: RunSnapshot | null;
  events: RunEvent[];
  loading: boolean;
  error: string | null;
  connected: boolean;
  refresh: () => Promise<void>;
  applySnapshot: (snapshot: RunSnapshot) => void;
}

/**
 * 运行数据单一来源：快照负责「事实」，SSE 负责「时序」。
 * 事件到达后按需刷新快照，避免用事件增量拼装状态导致漂移。
 * 终态运行不再订阅事件流：服务端在 completed/failed 后会结束连接，
 * 继续订阅会导致 EventSource 反复重连并重放全部事件。
 */
export function useRunStream(runId: string | undefined): RunStream {
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const timer = useRef<number | null>(null);
  const mounted = useRef(true);

  const terminal =
    snapshot?.status === "completed" || snapshot?.status === "failed";

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const next = await api.getRun(runId);
      if (!mounted.current) return;
      setSnapshot(next);
      setError(null);
    } catch (err) {
      if (!mounted.current) return;
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [runId]);

  const applySnapshot = useCallback((next: RunSnapshot) => {
    setSnapshot(next);
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!runId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setEvents([]);
    setSnapshot(null);
    void refresh().finally(() => {
      if (mounted.current) setLoading(false);
    });
    return () => {
      mounted.current = false;
    };
  }, [runId, refresh]);

  const scheduleRefresh = useCallback(() => {
    if (timer.current !== null) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void refresh();
    }, 100);
  }, [refresh]);

  useEffect(() => {
    if (!runId || terminal) {
      setConnected(false);
      return;
    }
    const source = new EventSource(eventsUrl(runId));
    let buffer: RunEvent[] = [];
    source.onopen = () => {
      buffer = [];
      setConnected(true);
    };
    source.onmessage = (message) => {
      let parsed: RunEvent;
      try {
        parsed = JSON.parse(message.data) as RunEvent;
      } catch {
        return;
      }
      buffer = [...buffer, parsed];
      setEvents(buffer);
      scheduleRefresh();
    };
    source.onerror = () => {
      setConnected(false);
    };
    return () => {
      source.close();
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
        timer.current = null;
      }
    };
  }, [runId, terminal, scheduleRefresh]);

  return { snapshot, events, loading, error, connected, refresh, applySnapshot };
}
