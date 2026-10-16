import { useCallback, useEffect, useState } from "react";

import http from "./api";
import type { AlertRule, RuleModule } from "./alert-rules";

export type AlertConfig = {
  hour: { roi_high: number; roi_low: number; drop_pct: number; surge_pct: number };
  product: {
    sales_drop_pct: number;
    visitors_drop_pct: number;
    conversion_low: number;
    promo_roi_low: number;
    roi_high: number;
    min_visitors: number;
  };
  plan: { budget_over: number; budget_warn: number; roi_low: number; roi_drop_ratio: number };
  diagnostics: {
    channels: Record<string, boolean>;
    rules: Record<string, { enabled: boolean; priority: "p0" | "p1" | "p2" | "p3"; priority_mode?: "dynamic" | "fixed" }>;
    thresholds: Record<string, number>;
    priority_thresholds: Record<string, Record<string, Record<string, number>>>;
  };
  rules: AlertRule[];
};

export const DEFAULT_ALERT_CONFIG: AlertConfig = {
  hour: { roi_high: 2, roi_low: 1, drop_pct: 50, surge_pct: 100 },
  product: { sales_drop_pct: 50, visitors_drop_pct: 50, conversion_low: 0.5, promo_roi_low: 1, roi_high: 2, min_visitors: 50 },
  plan: { budget_over: 1, budget_warn: 0.8, roi_low: 1, roi_drop_ratio: 0.6 },
  diagnostics: {
    channels: { whole_site: true, search: true, audience: true, content: true, other: true },
    rules: {
      data_stale: { enabled: true, priority: "p1", priority_mode: "dynamic" }, budget_over: { enabled: true, priority: "p0", priority_mode: "dynamic" }, budget_near: { enabled: true, priority: "p2", priority_mode: "dynamic" },
      spend_without_sales: { enabled: true, priority: "p1", priority_mode: "dynamic" }, roi_drop: { enabled: true, priority: "p1", priority_mode: "dynamic" }, roi_low: { enabled: true, priority: "p1", priority_mode: "dynamic" },
      delivery_stopped: { enabled: true, priority: "p1", priority_mode: "dynamic" }, no_spend: { enabled: true, priority: "p2", priority_mode: "dynamic" }, delivery_slow: { enabled: true, priority: "p2", priority_mode: "dynamic" },
      low_spend: { enabled: true, priority: "p3", priority_mode: "dynamic" }, high_roi_low_spend: { enabled: true, priority: "p2", priority_mode: "dynamic" }, spend_too_fast: { enabled: true, priority: "p2", priority_mode: "dynamic" },
    },
    thresholds: {
      spend_without_sales_min_spend: 50, roi_drop_min_spend: 20, roi_drop_high_drop_pct: 50, roi_drop_high_spend: 100,
      roi_low_min_spend: 50, roi_low_high_spend: 200, delivery_stopped_min_yesterday_spend: 50, delivery_slow_min_yesterday_spend: 50,
    },
    priority_thresholds: {
      data_stale: { p0: { stale_hours: 72 }, p1: { stale_hours: 24 }, p2: { stale_hours: 12 } },
      budget_over: { p0: { budget_utilization_pct: 120 }, p1: { budget_utilization_pct: 100 }, p2: { budget_utilization_pct: 90 } },
      budget_near: { p0: { budget_utilization_pct: 110 }, p1: { budget_utilization_pct: 100 }, p2: { budget_utilization_pct: 80 } },
      spend_without_sales: { p0: { spend: 300 }, p1: { spend: 100 }, p2: { spend: 50 } },
      roi_drop: { p0: { drop_pct: 60, spend: 300 }, p1: { drop_pct: 40, spend: 100 }, p2: { drop_pct: 20, spend: 50 } },
      roi_low: { p0: { spend: 500 }, p1: { spend: 200 }, p2: { spend: 50 } },
      delivery_stopped: { p0: { elapsed_pct: 75, yesterday_spend: 300 }, p1: { elapsed_pct: 55, yesterday_spend: 100 }, p2: { elapsed_pct: 40, yesterday_spend: 50 } },
      no_spend: { p0: { elapsed_pct: 80 }, p1: { elapsed_pct: 65 }, p2: { elapsed_pct: 40 } },
      delivery_slow: { p0: { pace_gap_pct: 70 }, p1: { pace_gap_pct: 50 }, p2: { pace_gap_pct: 30 } },
      low_spend: { p2: { pace_gap_pct: 50 }, p3: { pace_gap_pct: 25 } },
      high_roi_low_spend: { p1: { pace_gap_pct: 70 }, p2: { pace_gap_pct: 40 }, p3: { pace_gap_pct: 20 } },
      spend_too_fast: { p0: { pace_gap_pct: 70 }, p1: { pace_gap_pct: 40 }, p2: { pace_gap_pct: 15 } },
    },
  },
  rules: [],
};

const KEY = "alert_config_v1";

function mergeConfig(data: Partial<AlertConfig> | null | undefined): AlertConfig {
  const base = JSON.parse(JSON.stringify(DEFAULT_ALERT_CONFIG)) as AlertConfig;
  if (!data || typeof data !== "object") return base;
  const groups: (keyof AlertConfig)[] = ["hour", "product", "plan"];
  if (Array.isArray((data as Record<string, unknown>).rules)) {
    const rs = (data as Record<string, unknown>).rules as unknown[];
    base.rules = rs
      .filter(
        (r): r is AlertRule =>
          !!r &&
          typeof r === "object" &&
          ["product", "plan", "hour"].includes((r as AlertRule).module) &&
          ["cycle_drop_pct", "cycle_up_pct", "lt", "gt"].includes((r as AlertRule).operator)
      )
      .map((r) => ({
        id: String(r.id || ""),
        module: r.module as RuleModule,
        field: String(r.field || ""),
        operator: r.operator,
        threshold: Number(r.threshold || 0),
        enabled: r.enabled !== false,
        conditions: Array.isArray((r as AlertRule).conditions)
          ? (r as AlertRule).conditions!.filter((c) => c && typeof c === "object").map((c) => ({ module: c.module, field: String(c.field || ""), operator: c.operator, threshold: Number(c.threshold || 0) }))
          : undefined,
      }));
  }
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
  if (data.diagnostics && typeof data.diagnostics === "object") {
    const incoming = data.diagnostics as Partial<AlertConfig["diagnostics"]>;
    if (incoming.channels && typeof incoming.channels === "object") {
      for (const [channel, value] of Object.entries(incoming.channels)) {
        if (channel in base.diagnostics.channels && typeof value === "boolean") base.diagnostics.channels[channel] = value;
      }
    }
    if (incoming.rules && typeof incoming.rules === "object") {
      for (const [code, value] of Object.entries(incoming.rules)) {
        if (!base.diagnostics.rules[code] || !value) continue;
        base.diagnostics.rules[code] = {
          enabled: value.enabled !== false,
          priority: ["p0", "p1", "p2", "p3"].includes(value.priority || "") ? value.priority! : base.diagnostics.rules[code].priority,
          priority_mode: value.priority_mode === "fixed" ? "fixed" : "dynamic",
        };
      }
    }
    if (incoming.thresholds && typeof incoming.thresholds === "object") {
      for (const [key, value] of Object.entries(incoming.thresholds)) if (typeof value === "number" && key in base.diagnostics.thresholds) base.diagnostics.thresholds[key] = value;
    }
    if (incoming.priority_thresholds && typeof incoming.priority_thresholds === "object") {
      for (const [code, rule] of Object.entries(incoming.priority_thresholds)) {
        if (!base.diagnostics.priority_thresholds[code] || !rule || typeof rule !== "object") continue;
        for (const [priority, clauses] of Object.entries(rule)) {
          if (!["p0", "p1", "p2", "p3"].includes(priority) || !clauses || typeof clauses !== "object") continue;
          base.diagnostics.priority_thresholds[code][priority] = {
            ...base.diagnostics.priority_thresholds[code][priority],
            ...Object.fromEntries(Object.entries(clauses).filter(([, value]) => typeof value === "number")),
          };
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
