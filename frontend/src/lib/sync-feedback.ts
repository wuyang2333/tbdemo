import { message } from "antd";

export interface SyncResultItem {
  store_name?: string;
  ok?: boolean;
  error?: string;
}

export interface SyncGroup {
  ok: number;
  total: number;
  results?: SyncResultItem[];
}

/**
 * 同步结果统一反馈：
 * - 无店铺（total === 0）→ 提示先配置店铺与登录档案
 * - 全部成功 → 绿色「xxx完成：全部 N 家店铺成功」
 * - 有失败 → 红色「xxx未完成：店名：原因…」，去重后最多列 3 条，附失败总数
 * groups 支持多接口合并（如店铺+推广一起同步），同一家店多次同步只算一家。
 */
export function showSyncFeedback(label: string, groups: SyncGroup[]) {
  // 多个接口会重复遍历同一批店铺，按店铺名去重后才是真实店铺数
  const all = groups.flatMap((g) => (g.results ?? []));
  const stores = new Set<string>();
  const failedStores = new Set<string>();
  for (const r of all) {
    if (!r.store_name) continue;
    stores.add(r.store_name);
    if (!r.ok) failedStores.add(r.store_name);
  }
  const total = stores.size;
  const ok = total - failedStores.size;
  const failed = all.filter((r) => !r.ok);

  if (total === 0) {
    message.info("没有可同步的店铺，请先在「店铺管理」中添加店铺并配置生意参谋登录档案");
    return;
  }
  if (ok === total) {
    message.success(`${label}完成：全部 ${total} 家店铺成功`);
    return;
  }

  const seen = new Set<string>();
  const dedup = failed.filter((r) => {
    const key = `${r.store_name ?? ""}|${r.error ?? ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const lines = dedup
    .slice(0, 3)
    .map((r) => `${r.store_name || "店铺"}：${r.error || "同步失败"}`)
    .join("；");
  const extra = failed.length > 3 ? `，等共 ${failed.length} 次失败` : `，共 ${failed.length} 次失败`;
  message.error(`${label}未完成：${lines}${extra}`);
}
