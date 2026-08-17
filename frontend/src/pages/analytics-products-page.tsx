import { BarChartOutlined, BulbOutlined, CheckCircleOutlined, CopyOutlined, HolderOutlined, LineChartOutlined, RocketOutlined, RobotOutlined, SendOutlined, SettingOutlined, SyncOutlined, WarningOutlined } from "@ant-design/icons";
import { Button, Card, Checkbox, DatePicker, Drawer, Empty, Input, Popover, Segmented, Select, Space, Spin, Table, Tag, Tooltip, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, fmtInt, fmtMoney, fmtPct } from "../components/analytics/analytics-ui";
import { LineChart } from "../components/promotions/promotions-ui";
import { AlertSettingsModal } from "../components/ui/alert-settings-modal";
import { useAlertConfig } from "../lib/use-alert-config";
import { HourlyPushButton } from "../components/ui/hourly-push";
import { buildRuleMessage, evalRule, ruleText } from "../lib/alert-rules";
import type { AnalyticsProduct, AnalyticsProducts } from "../types";

const { Text } = Typography;

const SEG_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "昨日", value: "yesterday" },
];

const BUILTIN_COL_ORDER: Record<string, string[]> = {
  realtime: ["rank", "item", "diag", "visitors", "pv", "buyers", "sales", "conversion_rate", "add_cart", "promo_spend", "promo_roi", "real_roi", "promo_share"],
  days: ["rank", "item", "diag", "sales", "orders", "buyers", "visitors", "conversion_rate", "add_cart", "promo_spend", "promo_roi", "real_roi", "promo_share", "sales_share"],
};

const RANGE_PRESETS: { label: string; value: [dayjs.Dayjs, dayjs.Dayjs] }[] = [
  { label: "今日", value: [dayjs().startOf("day"), dayjs().endOf("day")] },
  { label: "昨日", value: [dayjs().subtract(1, "day").startOf("day"), dayjs().subtract(1, "day").endOf("day")] },
  { label: "过去7天", value: [dayjs().subtract(6, "day").startOf("day"), dayjs().endOf("day")] },
  { label: "过去15天", value: [dayjs().subtract(14, "day").startOf("day"), dayjs().endOf("day")] },
  { label: "过去30天", value: [dayjs().subtract(29, "day").startOf("day"), dayjs().endOf("day")] },
  { label: "本月", value: [dayjs().startOf("month"), dayjs().endOf("month")] },
  { label: "上月", value: [dayjs().subtract(1, "month").startOf("month"), dayjs().subtract(1, "month").endOf("month")] },
];

function rangePromoMode(r: [string, string]): string | null {
  const s = dayjs(r[0]);
  const e = dayjs(r[1]);
  const len = e.diff(s, "day") + 1;
  if (s.isSame(e, "day") && s.isSame(dayjs(), "day")) return "realtime";
  if (s.isSame(e, "day") && s.isSame(dayjs().subtract(1, "day"), "day")) return "yesterday";
  if (len === 7 || len === 14 || len === 30) return String(len);
  return null;
}

interface ProductInsightSections {
  overall: string;
  highlights: string[];
  risks: string[];
  suggestions: string[];
}
interface ProductInsightMetric {
  label: string;
  value: string;
  change: number | null;
  unit: string;
}
interface ProductInsightResult {
  sections: ProductInsightSections;
  metrics: ProductInsightMetric[];
  range: string;
  reply: string;
  product: { item_id: string; item_title: string; image?: string };
}

function ProductChangeBadge({ change, unit }: { change: number | null; unit: string }) {
  if (change == null) return <span style={{ color: "rgba(128,128,128,0.55)", fontSize: 12 }}>—</span>;
  const up = change >= 0;
  const color = up ? "#ff4d4f" : "#52c41a";
  const suffix = unit === "%" ? "%" : unit === "pp" ? "pp" : "";
  return (
    <span style={{ color, fontSize: 12, fontWeight: 600 }}>
      {up ? "+" : "-"}
      {Math.abs(change).toFixed(unit === "val" ? 0 : 1)}
      {suffix}
    </span>
  );
}

function ProductSection({
  icon,
  color,
  title,
  items,
}: {
  icon: React.ReactNode;
  color: string;
  title: string;
  items: string[];
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        padding: "10px 12px",
        borderRadius: 10,
        background: "var(--ops-card-bg-2)",
        border: "1px solid var(--ops-border)",
      }}
    >
      <span style={{ color, fontSize: 15, marginTop: 2, flexShrink: 0 }}>{icon}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
        {items.map((it, idx) => (
          <div key={idx} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>
            {it}
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricCell({ value, change }: { value: string; change: number | null | undefined }) {
  const hasChange = change != null;
  return (
    <div>
      <div>{value}</div>
      {hasChange ? (
        <div style={{ fontSize: 11, fontWeight: 600, color: change >= 0 ? "#ff4d4f" : "#52c41a" }}>
          {change >= 0 ? "+" : "-"}
          {Math.abs(change).toFixed(2)}%
        </div>
      ) : (
        <div style={{ fontSize: 11, color: "rgba(128,128,128,0.55)" }}>—</div>
      )}
    </div>
  );
}

export function AnalyticsProductsPage() {
  const [data, setData] = useState<AnalyticsProducts | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [view, setView] = useState<"realtime" | "yesterday" | "range">("realtime");
  const [range, setRange] = useState<[string, string] | null>(null);
  const [filterItemId, setFilterItemId] = useState("");
  const [hiddenCols, setHiddenCols] = useState<string[]>([]);
  const [colOrders, setColOrders] = useState<Record<string, string[]>>({});
  const [dragCol, setDragCol] = useState<string | null>(null);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<{ item_id: string; item_title: string; image?: string } | null>(null);
  const [detailResult, setDetailResult] = useState<ProductInsightResult | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailChat, setDetailChat] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [detailChatInput, setDetailChatInput] = useState("");
  const [detailChatLoading, setDetailChatLoading] = useState(false);
  const { config: alertConfig, saveConfig: saveAlertConfig } = useAlertConfig();
  const [alertCfgOpen, setAlertCfgOpen] = useState(false);
  const [alertSaving, setAlertSaving] = useState(false);
  const [diagFilter, setDiagFilter] = useState("");
  const [trendOpen, setTrendOpen] = useState(false);
  const [trendItem, setTrendItem] = useState<AnalyticsProduct | null>(null);
  const [trendDays, setTrendDays] = useState(7);
  const [trendData, setTrendData] = useState<{ date: string; sales: number; orders: number; visitors: number; conversion_rate: number }[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);
  const [promoOpen, setPromoOpen] = useState(false);
  const [promoItem, setPromoItem] = useState<AnalyticsProduct | null>(null);
  const [promoMode, setPromoMode] = useState("realtime");
  const [promoData, setPromoData] = useState<{
    plans: { campaign_id: string; plan_name: string; scene_name: string; status: string; day_budget: number; spend: number; sales: number; roi: number; clicks: number }[];
    keywords: { word: string; promotion: string; spend: number; sales: number; roi: number; clicks: number; orders: number }[];
  } | null>(null);
  const [promoLoading, setPromoLoading] = useState(false);

  const load = useCallback(async () => {
    if (view === "range" && !range) {
      setData(null);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (view === "realtime") {
        params.set("mode", "realtime");
      } else if (view === "yesterday") {
        params.set("mode", "yesterday");
      } else if (range) {
        params.set("mode", "days");
        params.set("start", range[0]);
        params.set("end", range[1]);
      }
      if (storeId) params.set("store_id", String(storeId));
      const { data: res } = await http.get<AnalyticsProducts>(`/analytics/products?${params.toString()}`);
      setData(res);
      setLastUpdated(dayjs().format("HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [view, range, storeId]);

  useEffect(() => {
    load();
  }, [load]);
  useAutoRefresh(load);

  const syncAll = async () => {
    setSyncing(true);
    try {
      const storeRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/stores/sync-all");
      const itemsUrl =
        view === "realtime"
          ? "/stores/sync-items-realtime"
          : view === "yesterday"
            ? `/stores/sync-items?date=${dayjs().subtract(1, "day").format("YYYY-MM-DD")}`
            : range
              ? `/stores/sync-items?start=${range[0]}&end=${range[1]}`
              : "/stores/sync-items?days=1";
      const itemsRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(itemsUrl);
      const promoMode = view === "realtime" ? "realtime" : view === "yesterday" ? "yesterday" : range ? (rangePromoMode(range) ?? "7") : "7";
      const promoRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(`/promotions/sync?mode=${promoMode}`);
      const promoItemsRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(`/promotions/sync-items?mode=${promoMode}`);
      const label = view === "realtime" ? "实时商品" : view === "yesterday" ? "昨日商品" : range ? `${range[0]}~${range[1]} 商品` : "商品";
      showSyncFeedback(`同步（${label}）`, [
        { ok: storeRes.data.ok, total: storeRes.data.total, results: storeRes.data.results },
        { ok: itemsRes.data.ok, total: itemsRes.data.total, results: itemsRes.data.results },
        { ok: promoRes.data.ok, total: promoRes.data.total, results: promoRes.data.results },
        { ok: promoItemsRes.data.ok, total: promoItemsRes.data.total, results: promoItemsRes.data.results },
      ]);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const openProductAI = async (row: AnalyticsProduct) => {
    setDetail({ item_id: row.item_id, item_title: row.item_title, image: row.image });
    setDetailResult(null);
    setDetailChat([]);
    setDetailOpen(true);
    setDetailLoading(true);
    try {
      const params = new URLSearchParams({ mode: view === "realtime" ? "realtime" : view === "yesterday" ? "yesterday" : "days" });
      if (view === "range" && range) {
        params.set("start", range[0]);
        params.set("end", range[1]);
      }
      if (storeId) params.set("store_id", String(storeId));
      const { data } = await http.post<ProductInsightResult>(
        `/analytics/products/${encodeURIComponent(row.item_id)}/insight?${params.toString()}`,
        undefined,
        { timeout: 120000 }
      );
      setDetailResult(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setDetailLoading(false);
    }
  };

  const sendDetailChat = async () => {
    const q = detailChatInput.trim();
    if (!q || !detail || !detailResult) return;
    const next = [...detailChat, { role: "user" as const, content: q }];
    setDetailChat(next);
    setDetailChatInput("");
    setDetailChatLoading(true);
    try {
      const chatParams = new URLSearchParams();
      if (view === "range" && range) {
        chatParams.set("start", range[0]);
        chatParams.set("end", range[1]);
      }
      const chatSuffix = chatParams.toString() ? `?${chatParams.toString()}` : "";
      const { data } = await http.post<{ reply: string }>(
        `/analytics/products/${encodeURIComponent(detail.item_id)}/insight/chat${chatSuffix}`,
        {
          mode: view === "realtime" ? "realtime" : view === "yesterday" ? "yesterday" : "days",
          store_id: storeId,
          messages: [{ role: "assistant", content: detailResult.reply }, ...next],
        },
        { timeout: 120000 }
      );
      setDetailChat([...next, { role: "assistant" as const, content: data.reply }]);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setDetailChatLoading(false);
    }
  };

  const isRealtime = view === "realtime";
  const productDiag = (item: AnalyticsProduct) => {
    const sales = item.sales || 0;
    const cyc = item.sales_cycle;
    const conv = item.conversion_rate;
    const roi = item.promo_roi;
    const share = item.sales_share;
    if (!sales) return { label: "无销量", color: "default" as const };
    if (cyc == null) return { label: "新品", color: "blue" as const };
    if (cyc < -50) return { label: "骤降", color: "red" as const };
    if (cyc < -10) return { label: "下滑", color: "orange" as const };
    if ((conv != null && conv < 0.5) || (roi != null && roi < 1 && (item.promo_spend ?? 0) > 0)) return { label: "需关注", color: "volcano" as const };
    if (share != null && share >= 5) return { label: "爆款", color: "gold" as const };
    return { label: "稳定", color: "green" as const };
  };
  const productAlerts = (data?.items ?? [])
    .map((item) => {
      const cyc = item.sales_cycle;
      const vcyc = item.visitors_cycle;
      const conv = item.conversion_rate;
      const roi = item.promo_roi;
      const spend = item.promo_spend ?? 0;
      const out: { level: string; type: string; message: string }[] = [];
      const name = `${item.item_title}（${item.item_id}）`;
      if (cyc != null && cyc < -alertConfig.product.sales_drop_pct) out.push({ level: "error", type: "销售额骤降", message: `${name}销售额环比 ${cyc.toFixed(1)}%` });
      if (vcyc != null && vcyc < -alertConfig.product.visitors_drop_pct) out.push({ level: "warning", type: "访客骤降", message: `${name}访客环比 ${vcyc.toFixed(1)}%` });
      if (conv != null && conv < alertConfig.product.conversion_low && (item.visitors ?? 0) > alertConfig.product.min_visitors) out.push({ level: "warning", type: "转化异常", message: `${name}转化率仅 ${conv.toFixed(2)}%` });
      if (roi != null && roi < alertConfig.product.promo_roi_low && spend > 0) out.push({ level: "error", type: "推广ROI偏低", message: `${name}推广ROI ${roi.toFixed(2)}` });
      if (roi != null && roi >= alertConfig.product.roi_high && spend > 0) out.push({ level: "success", type: "推广ROI优秀", message: `${name}推广ROI ${roi.toFixed(2)}，值得加推` });
      return out;
    })
    .flat()
    .slice(0, 8);
  const saveAlertCfg = async (patch: Parameters<typeof saveAlertConfig>[0]) => {
    setAlertSaving(true);
    try {
      await saveAlertConfig(patch);
      message.success("预警条件已保存");
      setAlertCfgOpen(false);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAlertSaving(false);
    }
  };
  const ruleAlerts: { level: string; type: string; message: string }[] = [];
  for (const rule of alertConfig.rules.filter((r) => r.module === "product")) {
    for (const item of data?.items ?? []) {
      if (evalRule(rule, item as unknown as Record<string, unknown>)) {
        ruleAlerts.push({ level: "warning", type: `自定义·${ruleText(rule)}`, message: buildRuleMessage(rule, item as unknown as Record<string, unknown>, item.item_title) });
        if (ruleAlerts.length >= 20) break;
      }
    }
    if (ruleAlerts.length >= 20) break;
  }
  const allProductAlerts = [...ruleAlerts, ...productAlerts];
  const filteredItems = (data?.items ?? [])
    .map((item, index) => ({ ...item, rank: index + 1 }))
    .filter((item) => {
      const q = filterItemId.trim().toLowerCase();
      if (q && !item.item_id.toLowerCase().includes(q) && !(item.item_title || "").toLowerCase().includes(q)) return false;
      if (diagFilter && productDiag(item).label !== diagFilter) return false;
      return true;
    });
  const numSorter = (key: keyof AnalyticsProduct) => (a: AnalyticsProduct, b: AnalyticsProduct) =>
    Number(a[key] ?? 0) - Number(b[key] ?? 0);
  const realRoiValue = (row: AnalyticsProduct) => (row.promo_spend ? row.sales / row.promo_spend : -1);
  const realRoiSorter = (a: AnalyticsProduct, b: AnalyticsProduct) => realRoiValue(a) - realRoiValue(b);
  const copyItemId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = id;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    message.success(`已复制商品ID：${id}`);
  };
  const loadTrend = async (itemId: string, days: number) => {
    setTrendLoading(true);
    try {
      const params = new URLSearchParams({ days: String(days) });
      if (storeId) params.set("store_id", String(storeId));
      const { data } = await http.get<{ items: { date: string; sales: number; orders: number; visitors: number; conversion_rate: number }[] }>(
        `/analytics/products/${encodeURIComponent(itemId)}/trend?${params.toString()}`,
        { timeout: 30000 }
      );
      setTrendData(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTrendLoading(false);
    }
  };
  const openTrend = (row: AnalyticsProduct) => {
    setTrendItem(row);
    setTrendOpen(true);
    setTrendData([]);
    loadTrend(row.item_id, trendDays);
  };
  const changeTrendDays = (d: number) => {
    setTrendDays(d);
    if (trendItem) loadTrend(trendItem.item_id, d);
  };
  const loadPromo = async (itemId: string, mode: string) => {
    setPromoLoading(true);
    try {
      const params = new URLSearchParams({ mode });
      if (storeId) params.set("store_id", String(storeId));
      const { data } = await http.get<{ plans: unknown[]; keywords: unknown[] }>(
        `/analytics/products/${encodeURIComponent(itemId)}/promo?${params.toString()}`,
        { timeout: 60000 }
      );
      setPromoData(data as typeof promoData);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setPromoLoading(false);
    }
  };
  const openPromo = (row: AnalyticsProduct) => {
    setPromoItem(row);
    setPromoOpen(true);
    setPromoData(null);
    loadPromo(row.item_id, promoMode);
  };
  const changePromoMode = (m: string) => {
    setPromoMode(m);
    if (promoItem) loadPromo(promoItem.item_id, m);
  };

  const renderItem = (_: unknown, row: AnalyticsProduct) => {
    const hovered = hoverKey === row.item_id;
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {row.image ? (
          <img src={row.image} alt="" style={{ width: 40, height: 40, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} />
        ) : (
          <div style={{ width: 40, height: 40, borderRadius: 6, background: "var(--ops-card-bg-2)", flexShrink: 0 }} />
        )}
        <div style={{ minWidth: 0, position: "relative", paddingTop: hovered ? 28 : 0, transition: "padding-top 0.16s ease" }}>
          <div className={`product-hover-bar${hovered ? " visible" : ""}`} onClick={(e) => e.stopPropagation()}>
            <button type="button" className="phb-btn" onClick={() => copyItemId(row.item_id)}>
              <CopyOutlined /> 复制
            </button>
            <button type="button" className="phb-btn" onClick={() => openProductAI(row)}>
              <RobotOutlined /> AI分析
            </button>
            <button type="button" className="phb-btn" onClick={() => openTrend(row)}>
              <LineChartOutlined /> 趋势
            </button>
            <button type="button" className="phb-btn" onClick={() => openPromo(row)}>
              <RocketOutlined /> 推广
            </button>
          </div>
          <Tooltip title={row.item_title}>
            <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.item_title}</div>
          </Tooltip>
          <div style={{ fontSize: 11, color: "rgba(128,128,128,0.75)" }}>ID {row.item_id}</div>
        </div>
      </div>
    );
  };
  const columns: TableColumnsType<AnalyticsProduct> = [
    ...(isRealtime
      ? ([
          {
            title: "排名",
            dataIndex: "rank",
            width: 70,
            align: "center",
            render: (v: number) => (
              <span style={{ fontWeight: 700, color: v <= 3 ? "#ff4d4f" : undefined }}>{v}</span>
            ),
          },
          { title: "商品", key: "item", width: 200, render: renderItem },
          {
            title: "诊断",
            key: "diag",
            width: 90,
            render: (_, row: AnalyticsProduct) => {
              const d = productDiag(row);
              return <Tag color={d.color}>{d.label}</Tag>;
            },
          },
          { title: "访客", dataIndex: "visitors", align: "right", width: 110, sorter: numSorter("visitors"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.visitors_cycle ?? 0} /> },
          { title: "浏览量", dataIndex: "pv", align: "right", width: 110, sorter: numSorter("pv"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.pv_cycle ?? 0} /> },
          { title: "买家", dataIndex: "buyers", align: "right", width: 100, sorter: numSorter("buyers"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.buyers_cycle ?? 0} /> },
          { title: "销售额", dataIndex: "sales", align: "right", width: 130, sorter: numSorter("sales"), render: (v: number, row) => <MetricCell value={fmtMoney(v)} change={row.sales_cycle ?? 0} /> },
          { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 120, sorter: numSorter("conversion_rate"), render: (v: number, row) => <MetricCell value={fmtPct(v)} change={row.conversion_cycle ?? 0} /> },
          { title: "加购", dataIndex: "add_cart", align: "right", width: 100, sorter: numSorter("add_cart"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.add_cart_cycle ?? 0} /> },
          { title: "推广花费", dataIndex: "promo_spend", align: "right", width: 100, sorter: numSorter("promo_spend"), render: (v: number | null | undefined) => (v != null ? fmtMoney(v) : "—") },
          { title: "推广ROI", dataIndex: "promo_roi", align: "right", width: 90, sorter: numSorter("promo_roi"), render: (v: number | null | undefined) => (v != null ? v.toFixed(2) : "—") },
          { title: "真实ROI", key: "real_roi", align: "right", width: 90, sorter: realRoiSorter, render: (_: unknown, row: AnalyticsProduct) => (row.promo_spend ? (row.sales / row.promo_spend).toFixed(2) : "—") },
          { title: "广告占比", dataIndex: "promo_share", align: "right", width: 90, sorter: numSorter("promo_share"), render: (v: number | null | undefined) => (v != null ? `${v.toFixed(1)}%` : "—") },
        ] as TableColumnsType<AnalyticsProduct>)
      : ([
          { title: "排名", dataIndex: "rank", width: 70, align: "center", render: (v: number) => <span style={{ fontWeight: 700, color: v <= 3 ? "#ff4d4f" : undefined }}>{v}</span> },
          { title: "商品", key: "item", width: 200, render: renderItem },
          {
            title: "诊断",
            key: "diag",
            width: 90,
            render: (_, row: AnalyticsProduct) => {
              const d = productDiag(row);
              return <Tag color={d.color}>{d.label}</Tag>;
            },
          },
          { title: "销售额", dataIndex: "sales", align: "right", width: 120, sorter: numSorter("sales"), render: (v: number, row: AnalyticsProduct) => <MetricCell value={fmtMoney(v)} change={row.sales_cycle} /> },
          { title: "销量", dataIndex: "orders", align: "right", width: 90, sorter: numSorter("orders"), render: (v: number, row: AnalyticsProduct) => <MetricCell value={fmtInt(v)} change={row.orders_cycle} /> },
          { title: "买家", dataIndex: "buyers", align: "right", width: 90, sorter: numSorter("buyers"), render: (v: number, row: AnalyticsProduct) => <MetricCell value={fmtInt(v)} change={row.buyers_cycle} /> },
          { title: "访客", dataIndex: "visitors", align: "right", width: 100, sorter: numSorter("visitors"), render: (v: number, row: AnalyticsProduct) => <MetricCell value={fmtInt(v)} change={row.visitors_cycle} /> },
          { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 100, sorter: numSorter("conversion_rate"), render: (v: number, row: AnalyticsProduct) => <MetricCell value={fmtPct(v)} change={row.conversion_cycle} /> },
          { title: "加购", dataIndex: "add_cart", align: "right", width: 90, sorter: numSorter("add_cart"), render: (v: number, row: AnalyticsProduct) => <MetricCell value={fmtInt(v)} change={row.add_cart_cycle} /> },
          { title: "推广花费", dataIndex: "promo_spend", align: "right", width: 100, render: (v: number | null | undefined) => (v != null ? fmtMoney(v) : "—") },
          { title: "推广ROI", dataIndex: "promo_roi", align: "right", width: 90, render: (v: number | null | undefined) => (v != null ? v.toFixed(2) : "—") },
          { title: "真实ROI", align: "right", width: 90, render: (_: unknown, row: AnalyticsProduct) => (row.promo_spend ? (row.sales / row.promo_spend).toFixed(2) : "—") },
          { title: "广告占比", dataIndex: "promo_share", align: "right", width: 90, render: (v: number | null | undefined) => (v != null ? `${v.toFixed(1)}%` : "—") },
          { title: "占比", dataIndex: "sales_share", align: "right", width: 90, sorter: numSorter("sales_share"), render: (v: number) => (v != null ? `${v.toFixed(1)}%` : "—") },
        ] as TableColumnsType<AnalyticsProduct>)),
  ];

  const viewKey = isRealtime ? "realtime" : "days";
  const effectiveOrder = colOrders[viewKey] ?? BUILTIN_COL_ORDER[viewKey] ?? [];
  const reorderCols = (from: string, to: string) => {
    if (!from || from === to) return;
    setColOrders((prev) => {
      const base = prev[viewKey] ?? BUILTIN_COL_ORDER[viewKey] ?? [];
      const next = base.filter((k) => k !== from);
      const idx = next.indexOf(to);
      next.splice(idx >= 0 ? idx : next.length, 0, from);
      return { ...prev, [viewKey]: next };
    });
  };
  const toggleCol = (key: string, checked: boolean) => {
    setHiddenCols((prev) => (checked ? prev.filter((k) => k !== key) : [...prev, key]));
  };
  const visibleColumns = columns
    .filter((col) => {
      const k = (col.key as string) ?? ((col as { dataIndex?: string }).dataIndex as string);
      return !k || !hiddenCols.includes(k);
    })
    .sort((a, b) => {
      const ka = (a.key as string) ?? ((a as { dataIndex?: string }).dataIndex as string) ?? "";
      const kb = (b.key as string) ?? ((b as { dataIndex?: string }).dataIndex as string) ?? "";
      const ia = effectiveOrder.indexOf(ka);
      const ib = effectiveOrder.indexOf(kb);
      return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    });
  const settingsOptions = columns
    .map((col) => ({
      label: col.title as string,
      value: String((col.key as string) ?? ((col as { dataIndex?: string }).dataIndex as string) ?? ""),
    }))
    .filter((o) => o.value);
  const orderedSettings = [...settingsOptions].sort((a, b) => {
    const ia = effectiveOrder.indexOf(a.value);
    const ib = effectiveOrder.indexOf(b.value);
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
  });
  const tableX = visibleColumns.reduce((sum, col) => sum + ((col.width as number) || 90), 0);

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="商品分析"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Popover
              trigger="click"
              placement="bottomRight"
              content={
                <div style={{ width: 240 }}>
                  {orderedSettings.map((o) => (
                    <div
                      key={o.value}
                      draggable
                      onDragStart={() => setDragCol(o.value)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => reorderCols(dragCol ?? "", o.value)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "4px 6px",
                        borderRadius: 6,
                        cursor: "grab",
                        background: dragCol === o.value ? "var(--ops-accent-soft)" : "transparent",
                      }}
                    >
                      <HolderOutlined style={{ color: "rgba(128,128,128,0.6)", fontSize: 12 }} />
                      <Checkbox checked={!hiddenCols.includes(o.value)} onChange={(e) => toggleCol(o.value, e.target.checked)}>
                        {o.label}
                      </Checkbox>
                    </div>
                  ))}
                  <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 6, paddingLeft: 6 }}>
                    拖动调整列顺序 · 勾选控制显示
                  </Text>
                </div>
              }
            >
              <Button icon={<SettingOutlined />}>字段设置</Button>
            </Popover>
            <HourlyPushButton />
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented
          options={SEG_OPTIONS}
          value={view === "range" ? undefined : view}
          onChange={(v) => {
            setData(null);
            setView(String(v) as "realtime" | "yesterday");
          }}
        />
        <DatePicker.RangePicker
          presets={RANGE_PRESETS}
          value={view === "range" && range ? [dayjs(range[0]), dayjs(range[1])] : null}
          onChange={(dates) => {
            setData(null);
            if (dates && dates[0] && dates[1]) {
              setView("range");
              setRange([dates[0].format("YYYY-MM-DD"), dates[1].format("YYYY-MM-DD")]);
            } else {
              setView("realtime");
              setRange(null);
            }
          }}
          placeholder={["开始日期", "结束日期"]}
          allowClear
        />
        <Input
          allowClear
          placeholder="搜商品名 / ID"
          value={filterItemId}
          onChange={(e) => setFilterItemId(e.target.value)}
          style={{ width: 180 }}
        />
        <Select
          style={{ width: 120 }}
          value={diagFilter}
          onChange={setDiagFilter}
          options={[
            { value: "", label: "全部诊断" },
            { value: "爆款", label: "爆款" },
            { value: "稳定", label: "稳定" },
            { value: "新品", label: "新品" },
            { value: "下滑", label: "下滑" },
            { value: "骤降", label: "骤降" },
            { value: "需关注", label: "需关注" },
            { value: "无销量", label: "无销量" },
          ]}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
        {isRealtime && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          全量商品 · 按销售额排序
        </Text>
      )}
      </Space>

      {allProductAlerts.length > 0 && (
        <Card
          variant="borderless"
          title="商品预警"
          style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 12 }}
          extra={
            <Button size="small" icon={<SettingOutlined />} onClick={() => setAlertCfgOpen(true)}>预警设置</Button>
          }
        >
          <div style={{ maxHeight: 170, overflowY: "auto", paddingRight: 4 }}>
            <div style={{ display: "grid", gap: 4 }}>
              {allProductAlerts.map((a, i) => (
                <div key={i} style={{ fontSize: 13, color: a.level === "error" ? "#ff4d4f" : "#fa8c16" }}>
                  {a.level === "error" ? "⚠️ " : "❗ "}
                  [{a.type}] {a.message}
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description={`暂无${isRealtime ? "实时" : ""}商品数据，点右上角「同步店铺数据」同步`} />
        </Card>
      ) : (
        <Card
          variant="borderless"
          title={isRealtime ? "实时商品榜（今日）" : view === "yesterday" ? "昨日商品销售排行" : range ? `商品销售排行（${range[0]} ~ ${range[1]}）` : "商品销售排行"}
          style={{ boxShadow: "var(--ops-shadow-sm)" }}
          extra={isRealtime ? <Tag color="green">实时</Tag> : undefined}
        >
          <Table<AnalyticsProduct>
            rowKey="item_id"
            size="small"
            columns={visibleColumns}
            dataSource={filteredItems}
            onRow={(record) => ({
              onMouseEnter: () => setHoverKey(record.item_id),
              onMouseLeave: () => setHoverKey((k) => (k === record.item_id ? null : k)),
            })}
            pagination={{ defaultPageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: () => (filterItemId.trim() ? `匹配 ${filteredItems.length} 个商品` : `共 ${data.total} 个商品`) }}
            tableLayout="fixed"
            scroll={{ x: tableX }}
          />
        </Card>
      )}

      <Drawer
        title={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {detail?.image ? (
              <img src={detail.image} alt="" style={{ width: 36, height: 36, borderRadius: 6, objectFit: "cover" }} />
            ) : null}
            <div style={{ minWidth: 0 }}>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 420, fontWeight: 600 }}>
                {detail?.item_title}
              </div>
              <div style={{ fontSize: 12, color: "rgba(128,128,128,0.75)" }}>ID {detail?.item_id}</div>
            </div>
          </div>
        }
        width={640}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        destroyOnHidden
      >
        {detailLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="AI 正在分析该商品…" />
          </div>
        ) : detailResult ? (
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
              分析范围：{detailResult.range} · 基于生意参谋商品数据
            </Text>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
              {detailResult.metrics.map((m) => (
                <div
                  key={m.label}
                  style={{
                    flex: "1 1 130px",
                    minWidth: 120,
                    padding: "8px 12px",
                    borderRadius: 10,
                    background: "var(--ops-card-bg-2)",
                    border: "1px solid var(--ops-border)",
                  }}
                >
                  <div style={{ fontSize: 12, color: "var(--ops-text-secondary)", marginBottom: 2 }}>{m.label}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{m.value}</div>
                  <ProductChangeBadge change={m.change} unit={m.unit} />
                </div>
              ))}
            </div>

            {detailResult.sections.overall && (
              <div
                style={{
                  padding: "12px 14px",
                  borderRadius: 10,
                  background: "var(--ops-accent-soft)",
                  borderLeft: "3px solid var(--ops-accent)",
                  marginBottom: 10,
                }}
              >
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{detailResult.sections.overall}</Text>
              </div>
            )}

            <div style={{ display: "grid", gap: 8 }}>
              {detailResult.sections.highlights.length > 0 && (
                <ProductSection icon={<CheckCircleOutlined />} color="#52c41a" title="亮点" items={detailResult.sections.highlights} />
              )}
              {detailResult.sections.risks.length > 0 && (
                <ProductSection icon={<WarningOutlined />} color="#ff4d4f" title="风险" items={detailResult.sections.risks} />
              )}
              {detailResult.sections.suggestions.length > 0 && (
                <ProductSection icon={<BulbOutlined />} color="var(--ops-accent-light)" title="建议" items={detailResult.sections.suggestions} />
              )}
            </div>

            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--ops-border)" }}>
              <div style={{ fontWeight: 600, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <RobotOutlined style={{ color: "var(--ops-accent-light)" }} /> 追问 AI
              </div>
              {detailChat.length > 0 && (
                <div style={{ display: "grid", gap: 8, marginBottom: 10, maxHeight: 260, overflowY: "auto" }}>
                  {detailChat.map((m, i) =>
                    m.role === "user" ? (
                      <div key={i} style={{ alignSelf: "flex-end", maxWidth: "85%", background: "var(--ops-accent-soft)", padding: "8px 12px", borderRadius: 10, fontSize: 13, whiteSpace: "pre-wrap" }}>
                        {m.content}
                      </div>
                    ) : (
                      <div key={i} style={{ alignSelf: "flex-start", maxWidth: "95%", background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", padding: "8px 12px", borderRadius: 10, fontSize: 13, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                        {m.content}
                      </div>
                    ),
                  )}
                </div>
              )}
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <Input.TextArea
                  rows={2}
                  value={detailChatInput}
                  onChange={(e) => setDetailChatInput(e.target.value)}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      sendDetailChat();
                    }
                  }}
                  placeholder={"比如：为什么转化低？要不要降价？该加推吗？"}
                  disabled={detailChatLoading}
                />
                <Button type="primary" icon={<SendOutlined />} loading={detailChatLoading} onClick={sendDetailChat} style={{ flexShrink: 0 }}>
                  发送
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <Empty description="生成失败或暂无数据，请重试" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 40 }} />
        )}
      </Drawer>
      <Drawer
        title={trendItem ? `趋势：${trendItem.item_title}` : "商品趋势"}
        width={620}
        open={trendOpen}
        onClose={() => setTrendOpen(false)}
        destroyOnHidden
      >
        {trendItem && (
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>ID {trendItem.item_id}</Text>
          </div>
        )}
        <Segmented
          options={[7, 14, 30].map((d) => ({ label: `近${d}天`, value: d }))}
          value={trendDays}
          onChange={(v) => changeTrendDays(Number(v))}
          style={{ marginBottom: 12 }}
        />
        {trendLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="加载趋势数据…" />
          </div>
        ) : trendData.length ? (
          <div>
            <LineChart
              labels={trendData.map((d) => d.date.slice(5))}
              series={[
                { name: "销售额", color: "#fa8c16", values: trendData.map((d) => d.sales), format: (v: number) => fmtMoney(v) },
                { name: "访客", color: "#1677ff", values: trendData.map((d) => d.visitors), format: (v: number) => fmtInt(v) },
              ]}
            />
            <Table
              rowKey="date"
              size="small"
              style={{ marginTop: 12 }}
              columns={[
                { title: "日期", dataIndex: "date", width: 110 },
                { title: "销售额", dataIndex: "sales", align: "right", render: (v: number) => (v ? fmtMoney(v) : "—") },
                { title: "订单", dataIndex: "orders", align: "right", render: (v: number) => (v ? fmtInt(v) : "—") },
                { title: "访客", dataIndex: "visitors", align: "right", render: (v: number) => (v ? fmtInt(v) : "—") },
                { title: "转化率", dataIndex: "conversion_rate", align: "right", render: (v: number) => (v ? `${v.toFixed(2)}%` : "—") },
              ]}
              dataSource={trendData}
              pagination={false}
            />
          </div>
        ) : (
          <Empty description="暂无趋势数据，请先同步" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 40 }} />
        )}
      </Drawer>
      <Drawer
        title={promoItem ? `推广联动：${promoItem.item_title}` : "推广联动"}
        width={700}
        open={promoOpen}
        onClose={() => setPromoOpen(false)}
        destroyOnHidden
      >
        <Segmented
          options={[
            { label: "实时", value: "realtime" },
            { label: "昨天", value: "yesterday" },
            { label: "近7天", value: "7d" },
          ]}
          value={promoMode}
          onChange={(v) => changePromoMode(String(v))}
          style={{ marginBottom: 12 }}
        />
        {promoLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="加载推广数据…" />
          </div>
        ) : (
          <div>
            <Text strong>推广计划（{promoData?.plans?.length ?? 0}）</Text>
            <Table
              rowKey="campaign_id"
              size="small"
              style={{ margin: "8px 0 18px" }}
              columns={[
                { title: "计划", dataIndex: "plan_name", ellipsis: true },
                { title: "场景", dataIndex: "scene_name", width: 110 },
                { title: "状态", dataIndex: "status", width: 70, render: (v: string) => (v === "在投" ? <Tag color="green">在投</Tag> : <Tag>暂停</Tag>) },
                { title: "日预算", dataIndex: "day_budget", align: "right", width: 90, render: (v: number) => (v ? fmtMoney(v) : "—") },
                { title: "花费", dataIndex: "spend", align: "right", width: 90, render: (v: number) => (v ? fmtMoney(v) : "—") },
                { title: "成交", dataIndex: "sales", align: "right", width: 100, render: (v: number) => (v ? fmtMoney(v) : "—") },
                { title: "ROI", dataIndex: "roi", align: "right", width: 70, render: (v: number) => (v ? v.toFixed(2) : "—") },
              ]}
              dataSource={promoData?.plans ?? []}
              pagination={false}
            />
            <Text strong>关键词表现（{promoData?.keywords?.length ?? 0}）</Text>
            {promoData?.keywords?.length ? (
              <Table
                rowKey="word"
                size="small"
                style={{ marginTop: 8 }}
                columns={[
                  { title: "关键词", dataIndex: "word", ellipsis: true },
                  { title: "所属计划", dataIndex: "promotion", ellipsis: true, width: 180 },
                  { title: "花费", dataIndex: "spend", align: "right", width: 90, render: (v: number) => (v ? fmtMoney(v) : "—") },
                  { title: "成交", dataIndex: "sales", align: "right", width: 100, render: (v: number) => (v ? fmtMoney(v) : "—") },
                  { title: "ROI", dataIndex: "roi", align: "right", width: 70, render: (v: number) => (v ? v.toFixed(2) : "—") },
                  { title: "点击", dataIndex: "clicks", align: "right", width: 70, render: (v: number) => (v ? fmtInt(v) : "—") },
                ]}
                dataSource={promoData.keywords}
                pagination={{ pageSize: 10 }}
              />
            ) : (
              <Empty description="暂无该商品计划的关键词数据（先同步关键词/推广数据）" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 20 }} />
            )}
          </div>
        )}
      </Drawer>
      <AlertSettingsModal
        open={alertCfgOpen}
        title="商品预警条件设置"
        module="product"
        config={alertConfig}
        rules={alertConfig.rules}
        onCancel={() => setAlertCfgOpen(false)}
        onSave={saveAlertCfg}
        saving={alertSaving}
        fields={[
          { group: "product", key: "sales_drop_pct", label: "销售额骤降阈值 %", hint: "销售额环比下跌超过该百分比提醒", min: 1, max: 500, step: 5 },
          { group: "product", key: "visitors_drop_pct", label: "访客骤降阈值 %", hint: "访客环比下跌超过该百分比提醒", min: 1, max: 500, step: 5 },
          { group: "product", key: "conversion_low", label: "转化率下限 %", hint: "转化率低于该值且有流量时提醒", min: 0.01, max: 10, step: 0.1 },
          { group: "product", key: "promo_roi_low", label: "推广 ROI 下限", hint: "推广ROI低于该值提醒", min: 0.1, max: 10, step: 0.1 },
          { group: "product", key: "roi_high", label: "建议加推 ROI 门槛", hint: "推广ROI达到该值提示值得加推", min: 0.1, max: 100, step: 0.1 },
          { group: "product", key: "min_visitors", label: "最低访客数", hint: "转化提醒的访客门槛（避免低流量误报）", min: 1, max: 1000, step: 10 },
        ]}
      />
    </div>
  );
}
