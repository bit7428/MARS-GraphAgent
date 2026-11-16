import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { EdgeSpec, Meta, NodeConfig } from "../api/types";

export function useEdges(): { edges: EdgeSpec[]; error: string | null } {
  const [edges, setEdges] = useState<EdgeSpec[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .listEdges()
      .then((items) => {
        if (active) setEdges(items);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      active = false;
    };
  }, []);

  return { edges, error };
}

export function useMeta(): Meta | null {
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    let active = true;
    api
      .meta()
      .then((value) => {
        if (active) setMeta(value);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  return meta;
}

export function useNodeConfigs(): {
  configs: NodeConfig[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
} {
  const [configs, setConfigs] = useState<NodeConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = async () => {
    try {
      const items = await api.listNodeConfigs();
      setConfigs(items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
  }, []);

  return { configs, loading, error, reload };
}
