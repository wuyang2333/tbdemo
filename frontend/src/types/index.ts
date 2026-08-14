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

export type Gift = {
  id: number;
  store_id: number;
  store_name: string;
  order_no: string;
  recipient: string;
  gift_name: string;
  quantity: number;
  price: number;
  status: GiftStatus;
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
