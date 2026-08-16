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


export type PromoSceneAgg = {
  scene: string;
  scene_name: string;
  impressions: number;
  clicks: number;
  ctr: number;
  spend: number;
  sales: number;
  roi: number;
  orders: number;
  add_cart: number;
};

export type PromoTrendPoint = {
  label: string;
  impressions: number;
  clicks: number;
  spend: number;
  sales: number;
  orders: number;
  roi: number;
};

export type PromoData = {
  mode: "realtime" | "yesterday" | "7d";
  summary: PromoSceneAgg;
  scenes: PromoSceneAgg[];
  trend: PromoTrendPoint[];
  trend_unit: "hour" | "day";
  bound_stores: number;
  last_sync: string | null;
};

export type PromoPlan = {
  id: number;
  store_id: number;
  scene: string;
  scene_name: string;
  campaign_id: string;
  plan_name: string;
  day_budget: number;
  bid_type: string;
  bid_value: number;
  status: string;
  gmt_create: string;
  spend: number;
  sales: number;
  roi: number;
  clicks: number;
  note: string;
  tag: string;
  updated_at: string;
};

export type AnalyticsLinkagePoint = {
  date: string;
  label: string;
  total_sales: number;
  total_visitors: number;
  total_orders: number;
  promo_spend: number;
  promo_sales: number;
  promo_roi: number;
  ad_share: number;
  overall_roi: number;
  natural_sales: number;
};

export type AnalyticsLinkage = {
  items: AnalyticsLinkagePoint[];
  summary: {
    total_sales: number;
    promo_spend: number;
    promo_sales: number;
    natural_sales: number;
    ad_share: number;
    promo_roi: number;
    overall_roi: number;
    days: number;
  };
  days: number;
};

export type AnalyticsRangeBucket = {
  start: string;
  end: string;
  visitors: number;
  pv: number;
  sales: number;
  orders: number;
  conversion_rate: number;
};

export type AnalyticsRangeCompare = {
  range1: AnalyticsRangeBucket;
  range2: AnalyticsRangeBucket;
  compare: { key: string; name: string; fmt: string; r1: number | null; r2: number | null; change_pct: number | null }[];
  series: (AnalyticsBucket & { date: string })[];
};

export type AnalyticsGoalProgress = {
  month: string;
  goal: number;
  sales: number;
  progress_pct: number;
  days_elapsed: number;
  days_total: number;
  avg_daily: number;
  forecast: number;
  remaining: number;
  remaining_daily: number;
};

export type AnalyticsForecast = {
  actual: { date: string; sales: number }[];
  predicted: { date: string; sales: number }[];
  days: number;
};

export type AnalyticsReport = {
  date: string;
  today: AnalyticsBucket;
  yesterday: AnalyticsBucket;
  promo_today: { spend: number; sales: number; roi: number };
  promo_yesterday: { spend: number; sales: number; roi: number };
  goal: number;
  month_sales: number;
  month: string;
};

export type AnalyticsHealth = {
  score: number;
  items: { key: string; name: string; score: number; detail: string }[];
  days: number;
};

export type AnalyticsCustomers = {
  items: { date: string; repeat_rate: number; new_rate: number; repeat_sales: number; old_buyer_cnt: number; sales: number }[];
  summary: { sales: number; repeat_sales: number; repeat_rate: number; new_rate: number; old_buyer_cnt: number; orders: number };
  days: number;
};

export type AnalyticsHourPoint = {
  hour: string;
  visitors: number;
  pv: number;
  sales: number;
  orders: number;
  buyers: number;
  conversion_rate: number;
  promo_spend: number;
  promo_sales: number;
  promo_roi: number;
  visitors_cycle?: number | null;
  sales_cycle?: number | null;
};

export type AnalyticsHours = {
  date: string;
  start: string;
  end: string;
  label: string;
  items: AnalyticsHourPoint[];
  prev_items: { hour: string; visitors: number; sales: number }[];
  prev_promo_items: { hour: string; spend: number; sales: number }[];
  summary: {
    visitors: number;
    pv: number;
    sales: number;
    orders: number;
    promo_spend: number;
    promo_sales: number;
    promo_roi: number;
  };
  segments: {
    name: string;
    hours: string;
    visitors: number;
    sales: number;
    orders: number;
    promo_spend: number;
    promo_sales: number;
    promo_roi: number;
  }[];
  peak_hour: string;
  peak_sales: number;
};

export type AnalyticsAlertsConfig = {
  baseline_days: number;
  sales_down: number;
  sales_up: number;
  orders_down: number;
  visitors_down: number;
  conversion_down: number;
};

export type AnalyticsProduct = {
  rank?: number;
  item_id: string;
  item_title: string;
  image?: string;
  sales: number;
  orders: number;
  buyers: number;
  days: number;
  latest_date: string;
  sales_share?: number;
  live?: boolean;
  date_label?: string;
  add_cart?: number;
  refund_amount?: number;
  visitors?: number;
  pv?: number;
  conversion_rate?: number;
  visitors_cycle?: number;
  pv_cycle?: number;
  buyers_cycle?: number;
  orders_cycle?: number;
  sales_cycle?: number;
  conversion_cycle?: number;
  add_cart_cycle?: number;
  promo_spend?: number | null;
  promo_sales?: number | null;
  promo_roi?: number | null;
  promo_share?: number | null;
};

export type AnalyticsProducts = {
  items: AnalyticsProduct[];
  total: number;
  days: number;
  fetched_at?: string | null;
};

export type AnalyticsProductDetail = {
  item_id: string;
  item_title: string;
  image?: string;
  series: { date: string; sales: number; orders: number; buyers: number }[];
};
