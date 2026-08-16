export type ModuleMeta = {
  id: string;
  name: string;
  description: string;
  icon: string;
};

export type ModuleData = {
  message?: string;
  items?: unknown[];
  [key: string]: unknown;
};

export type AuthUser = {
  id: number;
  username: string;
  nickname: string;
  role: "super_admin" | "admin" | "member";
  status: "active" | "disabled";
  allowed_modules: string[] | null;
  avatar_url: string | null;
  allowed_store_ids: number[] | null;
};

export type AuthResponse = {
  token: string;
  user: AuthUser;
};

export type Store = {
  id: number;
  name: string;
  owner: string;
  category: string;
  level: string;
  location: string;
  dsr_desc: number;
  dsr_service: number;
  dsr_logistics: number;
  status: "active" | "auth_error" | "stopped";
  display_status: "active" | "auth_error" | "stopped" | "auth_expired";
  auth_expires_at: string | null;
  created_at: string;
  sycm_username: string;
  sycm_configured: boolean;
  sycm_cookie_masked: string;
};

export type StoreMetrics = {
  sales: number;
  orders: number;
  visitors: number;
  refund_rate: number;
};

export type StoreTrendPoint = StoreMetrics & {
  date: string;
};

export type StoreMetricsResponse = {
  store: Store;
  today: StoreMetrics;
  summary: {
    sales_7d: number;
    orders_7d: number;
    avg_refund_rate: number;
    sales_change_7d: number;
  };
  trend: StoreTrendPoint[];
};

export type StoreAlert = {
  id: string;
  store_id: number;
  store_name: string;
  type: "refund" | "dsr" | "auth_expiring" | "auth_expired" | "stopped" | "delivery";
  level: "error" | "warn" | "info";
  message: string;
  created_at: string;
};

export type StoreCompareItem = StoreMetrics & {
  store_id: number;
  name: string;
  display_status: Store["display_status"];
};

export type StoreLog = {
  id: number;
  user_id: number;
  username: string;
  action: string;
  target_name: string;
  detail: string;
  created_at: string;
};

export type GiftStatus = "pending" | "shipped" | "delivered" | "refunded";

export type GiftReviewStatus = "none" | "reviewed";

export type GiftSettleStatus = "unsettled" | "settled";

export type Gift = {
  id: number;
  store_id: number;
  store_name: string;
  order_no: string;
  keyword: string;
  spec: string;
  price: number;
  commission: number;
  wangwang: string;
  order_time: string;
  review_status: GiftReviewStatus;
  settle_status: GiftSettleStatus;
  image: string;
  status: GiftStatus;
  recipient: string;
  gift_name: string;
  quantity: number;
  created_at: string;
};

export type OpLog = {
  id: number;
  module: string;
  user_id: number;
  username: string;
  action: string;
  target_name: string;
  detail: string;
  created_at: string;
};

export type ChatRole = "user" | "assistant";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ModelConfig = {
  id: number;
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
  is_default: boolean;
  configured: boolean;
  created_at: string;
  updated_at: string;
};


export type AnalyticsBucket = {
  visitors: number;
  pv: number;
  sales: number;
  orders: number;
  conversion_rate: number;
};

export type AnalyticsTrendPoint = AnalyticsBucket & {
  date: string;
};

export type AnalyticsStoreAgg = {
  store_id: number;
  store_name: string;
  visitors: number;
  pv: number;
  sales: number;
  orders: number;
  conversion_rate: number;
  avg_order_value: number;
  value_per_visitor: number;
  days: number;
  latest_date: string;
};

export type AnalyticsDailyPoint = AnalyticsBucket & {
  date: string;
  date_label: string;
  avg_order_value: number;
  value_per_visitor: number;
};

export type AnalyticsCompareEntry = {
  change_pct: number | null;
  prev: number | null;
};

export type AnalyticsCompareMetric = {
  key: string;
  name: string;
  fmt: "money" | "int" | "pct";
  today: number;
  dod: AnalyticsCompareEntry;
  wow: AnalyticsCompareEntry;
  mom: AnalyticsCompareEntry;
  yoy: AnalyticsCompareEntry;
};

export type AnalyticsAlert = {
  date: string;
  date_label: string;
  store_id: number;
  store_name: string;
  metric: string;
  level: "error" | "warn" | "info";
  change_pct: number;
  message: string;
};

export type AnalyticsSummary = {
  today: AnalyticsBucket;
  week: AnalyticsBucket;
  month: AnalyticsBucket;
  total: AnalyticsBucket;
  trend: AnalyticsTrendPoint[];
  by_store: AnalyticsStoreAgg[];
  store_count: number;
  last_sync: string | null;
};

