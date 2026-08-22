import axios from "axios";
import type { AxiosError } from "axios";

import type { ModuleData, ModuleMeta } from "../types";

export const TOKEN_KEY = "tb-workbench-token";
export const USER_KEY = "tb-workbench-user";
export const CURRENT_STORE_KEY = "tb-workbench-current-store";

export function clearStoredAuth(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(CURRENT_STORE_KEY);
}

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as { detail?: unknown } | undefined;
    if (typeof data?.detail === "string") return data.detail;
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
  (response) => response,
  (error: AxiosError) => {
    const url = (error.config?.url ?? "") as string;
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
