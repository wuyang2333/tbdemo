import { Tag } from "antd";

export type PromotionChannel = "whole_site" | "search" | "audience" | "content" | "other";

export const PROMOTION_CHANNELS: Array<{ value: PromotionChannel; label: string }> = [
  { value: "whole_site", label: "全站推广" },
  { value: "search", label: "搜索推广" },
  { value: "audience", label: "人群推广" },
  { value: "content", label: "内容推广" },
  { value: "other", label: "其他渠道" },
];

const CHANNEL_LABELS = Object.fromEntries(PROMOTION_CHANNELS.map((item) => [item.value, item.label]));
const CHANNEL_COLORS: Record<PromotionChannel, string> = {
  whole_site: "blue",
  search: "cyan",
  audience: "purple",
  content: "green",
  other: "default",
};

export function inferPromotionChannel(scene?: string | null): PromotionChannel {
  const normalized = (scene || "").toLowerCase();
  if (normalized.includes("whole") || normalized.includes("site") || normalized.includes("全站")) return "whole_site";
  if (normalized.includes("search") || normalized.includes("keyword") || normalized.includes("搜索") || normalized.includes("关键词")) return "search";
  if (normalized.includes("audience") || normalized.includes("display") || normalized.includes("crowd") || normalized.includes("人群")) return "audience";
  if (normalized.includes("content") || normalized.includes("video") || normalized.includes("内容") || normalized.includes("短视频")) return "content";
  return "other";
}

export function getPromotionChannel<T extends object>(item: T): PromotionChannel {
  const value = item as { channel?: string | null; scene?: string | null };
  const channel = value.channel as PromotionChannel | undefined;
  return channel && CHANNEL_LABELS[channel] ? channel : inferPromotionChannel(value.scene);
}

export function getPromotionChannelName<T extends object>(item: T): string {
  const value = item as { channel_name?: string | null };
  return value.channel_name || CHANNEL_LABELS[getPromotionChannel(item)] || "其他渠道";
}

export function PromotionChannelTag<T extends object>({ item }: { item: T }) {
  const channel = getPromotionChannel(item);
  return <Tag color={CHANNEL_COLORS[channel]}>{getPromotionChannelName(item)}</Tag>;
}
