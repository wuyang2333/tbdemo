import axios from "axios";
import type { AxiosError } from "axios";

import type { ModuleData, ModuleMeta } from "../types";

export const TOKEN_KEY = "tb-workbench-token";
export const USER_KEY = "tb-workbench-user";
export const CURRENT_STORE_KEY = "tb-workbench-current-store";

export type ProductAlias = { store_id: number; item_id: string; alias: string; note: string; original_title?: string };

let productAliasMap = new Map<string, ProductAlias>();
let productAliasByItemId = new Map<string, ProductAlias | null>();
let productAliasesLoaded = false;
let productAliasesPromise: Promise<void> | null = null;

function aliasKey(storeId: unknown, itemId: string): string {
  return `${String(storeId)}:${itemId}`;
}

function findProductAlias(item: Record<string, unknown>, itemId: string): ProductAlias | undefined {
  if (item.store_id !== undefined && item.store_id !== null) {
    return productAliasMap.get(aliasKey(item.store_id, itemId));
  }
  return productAliasByItemId.get(itemId) ?? undefined;
}

function applyProductAliases(value: unknown): void {
  if (!value || typeof value !== "object") return;
  if (Array.isArray(value)) {
    value.forEach(applyProductAliases);
    return;
  }
  const item = value as Record<string, unknown>;
  const itemId = item.item_id === undefined || item.item_id === null ? "" : String(item.item_id);
  const alias = itemId ? findProductAlias(item, itemId)?.alias : "";
  if (alias) {
    if (typeof item.item_title === "string") {
      if (item.original_item_title === undefined) item.original_item_title = item.item_title;
      item.item_title = alias;
      item.product_alias = alias;
    }
    if (typeof item.title === "string" && ("original_title" in item || "sold_quantity" in item || "monthly_sold" in item)) {
      if (item.original_title === undefined) item.original_title = item.title;
      item.title = alias;
      item.product_alias = alias;
    }
    if (typeof item.name === "string" && "count" in item) {
      if (item.original_name === undefined) item.original_name = item.name;
      item.name = alias;
    }
  }
  Object.values(item).forEach(applyProductAliases);
}

export async function refreshProductAliases(): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    productAliasMap = new Map();
    productAliasByItemId = new Map();
    productAliasesLoaded = false;
    return;
  }
  const response = await axios.get<{ items: ProductAlias[] }>("/api/products/aliases", {
    headers: { Authorization: `Bearer ${token}` },
    timeout: 30000,
  });
  productAliasMap = new Map(
    response.data.items.map((item) => [aliasKey(item.store_id, String(item.item_id)), item]),
  );
  productAliasByItemId = new Map();
  response.data.items.forEach((item) => {
    const itemId = String(item.item_id);
    productAliasByItemId.set(itemId, productAliasByItemId.has(itemId) ? null : item);
  });
  productAliasesLoaded = true;
}

async function ensureProductAliases(): Promise<void> {
  if (productAliasesLoaded || !localStorage.getItem(TOKEN_KEY)) return;
  if (!productAliasesPromise) {
    productAliasesPromise = refreshProductAliases().catch(() => {
      productAliasMap = new Map();
      productAliasByItemId = new Map();
      productAliasesLoaded = true;
    }).finally(() => {
      productAliasesPromise = null;
    });
  }
  await productAliasesPromise;
}

export function clearStoredAuth(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(CURRENT_STORE_KEY);
  productAliasMap = new Map();
  productAliasByItemId = new Map();
  productAliasesLoaded = false;
}

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: unknown } | undefined;
    if (typeof data?.detail === "string") return data.detail;
    if (error.code === "ECONNABORTED") return "请求处理超时，请刷新页面确认结果";
    if (!error.response) return `无法连接后端服务：${error.message}`;
    return `请求失败（HTTP ${error.response.status}）`;
  }
  return "操作失败，请稍后重试";
}

const http = axios.create({
  baseURL: "/api",
  timeout: 30000,
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  const storeId = localStorage.getItem(CURRENT_STORE_KEY);
  const url = config.url ?? "";
  const scoped = url.startsWith("/dashboard") || url.startsWith("/products") || url.startsWith("/analytics/") || url.startsWith("/promotions/");
  if (config.method?.toLowerCase() === "get" && storeId && scoped && !url.includes("store_id=")) {
    config.params = { ...(config.params ?? {}), store_id: Number(storeId) };
  }
  return config;
});

http.interceptors.response.use(
  async (response) => {
    const url = response.config.url ?? "";
    if (!url.startsWith("/products/aliases")) {
      await ensureProductAliases();
      applyProductAliases(response.data);
    }
    return response;
  },
  (error: AxiosError) => {
    const url = (error.config?.url ?? "") as string;
    const data = error.response?.data as { detail?: unknown } | undefined;
    const detail = typeof data?.detail === "string" ? data.detail : "";
    if (
      typeof window !== "undefined" &&
      (detail.includes("生意参谋登录已失效") ||
        detail.includes("生意参谋登录已过期") ||
        detail.includes("生意参谋登录态无效"))
    ) {
      window.dispatchEvent(new CustomEvent("tb-sycm-login-invalid"));
    }
    if (error.response?.status === 401 && !url.startsWith("/auth/")) {
      clearStoredAuth();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    return Promise.reject(error);
  }
);

export async function fetchModules(): Promise<ModuleMeta[]> {
  const response = await http.get<{ items: ModuleMeta[] }>("/modules");
  return response.data.items;
}

export async function fetchModuleData(moduleId: string): Promise<ModuleData> {
  const response = await http.get<ModuleData>(`/${moduleId}`);
  return response.data;
}

export default http;
