import type { AuthUser, ModuleMeta } from "../types";

/** 与后端 backend/app/core/modules.py 保持一致。 */
export const MODULES: ModuleMeta[] = [
  { id: "dashboard", name: "总览", description: "店铺核心指标一屏总览", icon: "dashboard" },
  { id: "stores", name: "店铺管理", description: "多店铺绑定、健康状态、授权管理", icon: "shop" },
  { id: "products", name: "商品管理", description: "淘宝在售商品、价格库存与经营状态", icon: "product" },
  { id: "gifts", name: "礼品单", description: "礼品订单列表、发货、售后、批量处理", icon: "order" },
  { id: "ai", name: "AI 助手", description: "AI 对话：问数据、写文案、给建议", icon: "robot" },
  { id: "customers", name: "评价管理", description: "评价同步、情感分析、差评处理与 AI 回复", icon: "customer" },
  { id: "analytics", name: "数据洞察", description: "流量、转化、销售趋势分析", icon: "analytics" },
  { id: "promotions", name: "推广管理", description: "直通车/引力魔方/万相台推广计划", icon: "promotion" },
  { id: "content", name: "内容运营", description: "素材库、内容创作、AI 图文/短视频", icon: "content" },
  { id: "monitoring", name: "竞品监控", description: "关键词/店铺/商品监控与快照", icon: "monitor" },
  { id: "market", name: "市场洞察", description: "选品机会、关键词运营与机会雷达", icon: "market" },
  { id: "growth-lab", name: "增长实验室", description: "商品策略、价格促销、沙盘与营销实验", icon: "experiment" },
  { id: "ops-knowledge", name: "运营知识库", description: "经营复盘、决策档案、SOP 与自动化", icon: "knowledge" },
  { id: "tasks", name: "系统任务", description: "后台任务状态、执行历史与重试", icon: "task" },
  { id: "model-configs", name: "模型配置", description: "AI 模型接入（OpenAI 兼容 / 阿里云百炼等）", icon: "api" },
  { id: "settings", name: "设置", description: "系统设置与偏好", icon: "settings" },
  { id: "profile", name: "个人中心", description: "个人资料、头像与密码管理", icon: "profile" },
  { id: "accounts", name: "账号管理", description: "账号权限、角色与模块可见范围管理", icon: "accounts" },
  { id: "logs", name: "操作日志", description: "全模块操作审计记录", icon: "logs" },
];

const FOOTER_IDS = new Set(["tasks", "model-configs", "settings", "profile", "accounts", "logs"]);

export const MAIN_MODULES = MODULES.filter((module) => !FOOTER_IDS.has(module.id));
export const FOOTER_MODULES = MODULES.filter((module) => FOOTER_IDS.has(module.id));

export function getModule(id: string | undefined): ModuleMeta | undefined {
  return MODULES.find((module) => module.id === id);
}

/** 权限判断：总览始终可见，账号管理仅管理员可见，其余按 allowed_modules。 */
export function canAccessModule(user: AuthUser | null, id: string): boolean {
  if (!user) return false;
  if (id === "dashboard" || id === "profile") return true;
  if (id === "accounts") return user.role === "admin" || user.role === "super_admin";
  if (id === "logs") return user.role === "admin" || user.role === "super_admin";
  if (id === "settings") return user.role === "admin" || user.role === "super_admin";
  if (user.role === "admin" || user.role === "super_admin" || user.allowed_modules == null) return true;
  return user.allowed_modules.includes(id);
}
