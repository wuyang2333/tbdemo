// 自定义预警规则：字段/算子/求值/消息 工具

export type RuleModule = "product" | "plan" | "hour";

export type AlertRule = {
  id: string;
  module: RuleModule;
  field: string;
  operator: "cycle_drop_pct" | "cycle_up_pct" | "lt" | "gt";
  threshold: number;
  enabled: boolean;
};

export type RuleField = { key: string; label: string; kind: "cycle" | "value"; unit?: string };

export const RULE_FIELDS: Record<RuleModule, RuleField[]> = {
  product: [
    { key: "sales", label: "销售额", kind: "cycle" },
    { key: "orders", label: "订单", kind: "cycle" },
    { key: "visitors", label: "访客", kind: "cycle" },
    { key: "conversion_rate", label: "转化率", kind: "value", unit: "%" },
    { key: "promo_spend", label: "推广花费", kind: "value" },
    { key: "promo_sales", label: "推广成交", kind: "value" },
    { key: "promo_roi", label: "推广ROI", kind: "value" },
  ],
  plan: [
    { key: "spend", label: "花费", kind: "cycle" },
    { key: "sales", label: "成交", kind: "cycle" },
    { key: "roi", label: "ROI", kind: "cycle" },
    { key: "clicks", label: "点击", kind: "value" },
  ],
  hour: [
    { key: "sales", label: "销售额", kind: "cycle" },
    { key: "visitors", label: "访客", kind: "cycle" },
    { key: "conversion_rate", label: "转化率", kind: "value", unit: "%" },
    { key: "promo_spend", label: "推广花费", kind: "value" },
    { key: "promo_roi", label: "推广ROI", kind: "value" },
  ],
};

export const RULE_OPERATORS = [
  { value: "cycle_drop_pct", label: "环比跌超 %" },
  { value: "cycle_up_pct", label: "环比涨超 %" },
  { value: "lt", label: "低于" },
  { value: "gt", label: "高于" },
];

const CYCLE_MAP: Record<string, string> = {
  sales: "sales_cycle",
  orders: "orders_cycle",
  visitors: "visitors_cycle",
  conversion_rate: "conversion_cycle",
  spend: "spend_cycle",
  roi: "roi_cycle",
};

export function ruleValue(item: Record<string, unknown>, field: string): number | null {
  const v = item[field];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function ruleCycle(item: Record<string, unknown>, field: string): number | null {
  const ck = CYCLE_MAP[field];
  if (!ck) return null;
  const v = item[ck];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function evalRule(rule: AlertRule, item: Record<string, unknown>): boolean {
  if (!rule.enabled) return false;
  if (rule.operator === "cycle_drop_pct") {
    const c = ruleCycle(item, rule.field);
    return c != null && c <= -Math.abs(rule.threshold);
  }
  if (rule.operator === "cycle_up_pct") {
    const c = ruleCycle(item, rule.field);
    return c != null && c >= rule.threshold;
  }
  if (rule.operator === "lt") {
    const v = ruleValue(item, rule.field);
    return v != null && v < rule.threshold;
  }
  if (rule.operator === "gt") {
    const v = ruleValue(item, rule.field);
    return v != null && v > rule.threshold;
  }
  return false;
}

export function ruleFieldLabel(module: RuleModule, field: string): string {
  return RULE_FIELDS[module]?.find((f) => f.key === field)?.label || field;
}

export function ruleText(rule: AlertRule): string {
  const fl = ruleFieldLabel(rule.module, rule.field);
  if (rule.operator === "cycle_drop_pct") return `${fl} 环比跌超 ${Math.abs(rule.threshold)}%`;
  if (rule.operator === "cycle_up_pct") return `${fl} 环比涨超 ${rule.threshold}%`;
  return `${fl} ${rule.operator === "lt" ? "低于" : "高于"} ${rule.threshold}`;
}

export function buildRuleMessage(rule: AlertRule, item: Record<string, unknown>, name: string): string {
  const fl = ruleFieldLabel(rule.module, rule.field);
  if (rule.operator === "cycle_drop_pct") {
    const c = ruleCycle(item, rule.field);
    return `${name}：${fl}环比跌 ${c != null ? Math.abs(c).toFixed(1) : "?"}%（阈值 ${Math.abs(rule.threshold)}%）`;
  }
  if (rule.operator === "cycle_up_pct") {
    const c = ruleCycle(item, rule.field);
    return `${name}：${fl}环比涨 ${c != null ? c.toFixed(1) : "?"}%（阈值 ${rule.threshold}%）`;
  }
  const v = ruleValue(item, rule.field);
  const vv = v != null ? v.toFixed(rule.field === "conversion_rate" ? 2 : 1) : "?";
  return `${name}：${fl} ${vv} ${rule.operator === "lt" ? "低于" : "超过"} 阈值 ${rule.threshold}`;
}
