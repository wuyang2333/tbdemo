export type CompetitorShop = {
  id: number;
  name: string;
  url: string;
  competitor_type: string;
  priority: string;
  category: string;
  price_band: string;
  notes?: string;
  monitor_frequency: string;
  status: string;
  product_count?: number;
  new_product_count?: number;
  rising_product_count?: number;
  failed_collection_count?: number;
  last_success_at?: string | null;
  last_scan_attempt_at?: string | null;
  last_scanned_at?: string | null;
  last_scan_status?: "pending" | "scanning" | "success" | "failed";
  last_scan_error?: string;
  last_scan_product_count?: number;
  last_new_product_count?: number;
};

export type CompetitorProduct = {
  id: number;
  shop_id: number;
  shop_name: string;
  title: string;
  alias?: string;
  display_name: string;
  url?: string;
  own_product: string;
  price: number | null;
  coupon_price: number | null;
  review_count: number | null;
  review_count_text?: string;
  rating?: number | null;
  good_rate?: number | null;
  negative_keywords?: string;
  sku_prices?: string;
  promotion_tags?: string;
  sales_text?: string;
  image_url?: string;
  status: string;
  discovery_source?: "manual" | "shop_scan";
  platform_item_id?: string;
  first_seen_at?: string | null;
  age_days?: number | null;
  is_new: boolean;
  snapshot_count: number;
  sales_count?: number | null;
  sales_delta_7d?: number | null;
  review_delta_7d?: number | null;
  growth_score: number;
  growth_level: string;
  growth_confidence: "low" | "medium" | "high";
  growth_reasons: string[];
  last_snapshot_at?: string | null;
  last_collected_at?: string | null;
  collection_status?: string;
  collection_error?: string;
  last_success_at?: string | null;
};

export type CompetitorEvent = {
  id: number;
  shop_id?: number | null;
  product_id?: number | null;
  event_type: string;
  title: string;
  detail: string;
  severity: string;
  status: string;
  observed_at: string;
  shop_name?: string;
  product_title?: string;
};

export type CompetitorSnapshot = {
  id: number;
  product_id: number;
  title: string;
  price: number | null;
  coupon_price: number | null;
  review_count: number | null;
  review_count_text?: string;
  sales_text?: string;
  sku_prices?: string;
  promotion_tags?: string;
  status: string;
  observed_at: string;
};

export type MonitoringIntelligence = {
  products: CompetitorProduct[];
  rising_products: CompetitorProduct[];
  new_products: CompetitorProduct[];
  shops: CompetitorShop[];
  events: CompetitorEvent[];
  summary: {
    shops: number;
    products: number;
    new_products: number;
    rising_products: number;
    unread_events: number;
    failed_collections: number;
  };
};

export type CollectorStatus = {
  connected: boolean;
  login_ready: boolean;
  state?: "ready" | "login_required" | "not_configured";
  message?: string;
};

export function parseStored<T>(value: string | undefined, fallback: T): T {
  if (!value) return fallback;
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
}

export function formatObservedAt(value?: string | null): string {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

export function formatEventDetail(detail: string): string {
  try {
    const parsed = JSON.parse(detail) as { old?: unknown; new?: unknown };
    if (Object.prototype.hasOwnProperty.call(parsed, "old")) {
      const readable = (value: unknown) => {
        if (Array.isArray(value)) return value.map((item) => typeof item === "object" && item !== null ? String((item as { label?: string; name?: string }).label || (item as { name?: string }).name || "数据项") : String(item)).join("、") || "无";
        return value === null || value === undefined || value === "" ? "未填写" : String(value);
      };
      const restore = (value: unknown) => {
        if (typeof value !== "string") return value;
        try { return JSON.parse(value) as unknown; } catch { return value; }
      };
      return `${readable(restore(parsed.old))} → ${readable(restore(parsed.new))}`;
    }
    if (typeof (parsed as { title?: unknown }).title === "string" && (parsed as { first_seen_at?: unknown }).first_seen_at) {
      return `首次发现：${String((parsed as { title?: unknown }).title)}`;
    }
  } catch {
    // Keep raw detail for manually recorded events.
  }
  return detail || "—";
}

export function growthColor(level: string): string {
  return level === "快速起量" ? "red" : level === "持续增长" ? "orange" : level === "疑似起量" ? "gold" : "default";
}

export function confidenceLabel(value: CompetitorProduct["growth_confidence"]): string {
  return value === "high" ? "高可信" : value === "medium" ? "继续观察" : "数据不足";
}
