import { createContext, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

import type { RunSnapshot } from "../api/types";

interface CurrentRunValue {
  snapshot: RunSnapshot | null;
  setSnapshot: (snapshot: RunSnapshot | null) => void;
}

const CurrentRunContext = createContext<CurrentRunValue>({
  snapshot: null,
  setSnapshot: () => undefined,
});

export function CurrentRunProvider({ children }: { children: ReactNode }): ReactNode {
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const value = useMemo(() => ({ snapshot, setSnapshot }), [snapshot]);
  return <CurrentRunContext.Provider value={value}>{children}</CurrentRunContext.Provider>;
}

export function useCurrentRun(): CurrentRunValue {
  return useContext(CurrentRunContext);
}
