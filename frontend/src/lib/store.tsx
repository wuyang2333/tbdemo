import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import http from "./api";
import { useAuth } from "./auth";
import type { Store } from "../types";

type StoreContextValue = {
  stores: Store[];
  currentStore: Store | null;
  loading: boolean;
  refresh: () => Promise<void>;
  setCurrent: (storeId: number | null) => Promise<void>;
};

const StoreContext = createContext<StoreContextValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [stores, setStores] = useState<Store[]>([]);
  const [currentStore, setCurrentStore] = useState<Store | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!user) {
      setStores([]);
      setCurrentStore(null);
      return;
    }
    setLoading(true);
    try {
      const [listRes, currentRes] = await Promise.all([
        http.get<{ items: Store[] }>("/stores"),
        http.get<{ store: Store | null }>("/stores/current"),
      ]);
      setStores(listRes.data.items);
      setCurrentStore(currentRes.data.store);
    } catch {
      setStores([]);
      setCurrentStore(null);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const setCurrent = useCallback(
    async (storeId: number | null) => {
      await http.post("/stores/current", { store_id: storeId });
      await refresh();
    },
    [refresh]
  );

  const value = useMemo(
    () => ({ stores, currentStore, loading, refresh, setCurrent }),
    [stores, currentStore, loading, refresh, setCurrent]
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStores(): StoreContextValue {
  const context = useContext(StoreContext);
  if (!context) throw new Error("useStores must be used within StoreProvider");
  return context;
}
