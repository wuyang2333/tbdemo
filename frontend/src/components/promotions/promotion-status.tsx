import { Tag } from "antd";

export const PROMOTION_STATUS_META: Record<string, { label: string; color: string; description: string }> = {
  planned: { label: "待执行", color: "default", description: "方案已确认，尚未写入平台" },
  executing: { label: "执行中", color: "blue", description: "正在等待平台回执" },
  executed: { label: "已执行", color: "blue", description: "平台已接收操作，等待回查" },
  effective: { label: "平台已生效", color: "cyan", description: "回查值与目标值一致" },
  observing: { label: "观察中", color: "blue", description: "保持单一变量，等待观察窗口结束" },
  pending_verification: { label: "待验证", color: "orange", description: "观察窗口已到期，需要形成结论" },
  success: { label: "改善", color: "green", description: "核心目标指标达到成功标准" },
  partial: { label: "部分改善", color: "gold", description: "部分指标改善，仍需谨慎复核" },
  unchanged: { label: "无明显变化", color: "default", description: "当前变化不足以支持好坏判断" },
  failed: { label: "恶化", color: "red", description: "核心指标恶化，需要评估回退" },
  insufficient: { label: "数据不足", color: "default", description: "样本或数据完整性不足，暂不判断" },
  rolled_back: { label: "已回退", color: "purple", description: "已恢复到调整前配置" },
  selected: { label: "已确认", color: "purple", description: "人工已确认决策方案" },
  verified: { label: "已验证", color: "green", description: "观察验证已经完成" },
};

export function normalizePromotionStatus(status?: string): string {
  const aliases: Record<string, string> = {
    pending: "planned",
    adopted: "selected",
    platform_success: "effective",
    active: "observing",
    due: "pending_verification",
    no_change: "unchanged",
    no_significant_change: "unchanged",
    data_insufficient: "insufficient",
    rollback: "rolled_back",
  };
  return aliases[status || ""] || status || "insufficient";
}

export function PromotionStatusTag({ status, showDescription = false }: { status?: string; showDescription?: boolean }) {
  const normalized = normalizePromotionStatus(status);
  const meta = PROMOTION_STATUS_META[normalized] || { label: status || "状态未知", color: "default", description: "尚未形成统一状态" };
  return <Tag color={meta.color} title={showDescription ? meta.description : undefined}>{meta.label}</Tag>;
}
