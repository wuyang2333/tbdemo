import { useCallback, useEffect, useState } from "react";

import http from "./api";

export type AlertConfig = {
  hour: { roi_high: number; roi_low: number; drop_pct: number; surge_pct: number };
  product: {
    sales_drop_pct: number;
    visitors_drop_pct: number;
    conversion_low: number;
    promo_roi_low: number;
    min_visitors: number;
  };
  plan: { budget_over: number; budget_warn: number; roi_drop_ratio: number };
};

export const DEFAULT_ALERT_CONFIG: AlertConfig = {
  hour: { roi_high: 2, roi_low: 1, drop_pct: 50, surge_pct: 100 },
  product: { sales_drop_pct: 50, visitors_drop_pct: 50, conversion_low: 0.5, promo_roi_low: 1, min_visitors: 50 },
  plan: { budget_over: 1, budget_warn: 0.8, roi_drop_ratio: 0.6 },
};

const KEY = "alert_config_v1";

function mergeConfig(data: Partial<AlertConfig> | null | undefined): AlertConfig {
  const base = JSON.parse(JSON.stringify(DEFAULT_ALERT_CONFIG)) as AlertConfig;
  if (!data || typeof data !== "object") return base;
  const groups: (keyof AlertConfig)[] = ["hour", "product", "plan"];
  for (const g of groups) {
    const src = (data as Record<string, unknown>)[g as string];
    if (src && typeof src === "object") {
      const s = src as Record<string, unknown>;
      for (const k of Object.keys(base[g] as Record<string, number>)) {
        const v = s[k];
        if (typeof v === "number" || (typeof v === "string" && v !== "" && !Number.isNaN(Number(v)))) {
          (base[g] as unknown as Record<string, number>)[k] = Number(v);
        }
      }
    }
  }
  return base;
}

/** 预警配置：本地缓存秒读 + 后台配置为准（换设备跟随账号）。 */
export function useAlertConfig() {
  const [config, setConfig] = useState<AlertConfig>(() => {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? mergeConfig(JSON.parse(raw)) : DEFAULT_ALERT_CONFIG;
    } catch {
      return DEFAULT_ALERT_CONFIG;
    }
  });
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    http
      .get<AlertConfig>("/alerts/config")
      .then(({ data }) => {
        const merged = mergeConfig(data);
        setConfig(merged);
        try {
          localStorage.setItem(KEY, JSON.stringify(merged));
        } catch {}
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const saveConfig = useCallback(async (patch: Partial<AlertConfig>) => {
    const { data } = await http.put<AlertConfig>("/alerts/config", patch, { timeout: 20000 });
    const merged = mergeConfig(data);
    setConfig(merged);
    try {
      localStorage.setItem(KEY, JSON.stringify(merged));
    } catch {}
    return merged;
  }, []);

  return { config, saveConfig, loaded };
}
