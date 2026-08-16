import { BarChartOutlined, BulbOutlined, CheckCircleOutlined, CopyOutlined, RobotOutlined, SendOutlined, SyncOutlined, WarningOutlined } from "@ant-design/icons";
import { Button, Card, Drawer, Empty, Input, Segmented, Space, Spin, Table, Tag, Tooltip, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, fmtInt, fmtMoney, fmtPct } from "../components/analytics/analytics-ui";
import type { AnalyticsProduct, AnalyticsProducts } from "../types";

const { Text } = Typography;

const MODE_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "昨天", value: "yesterday" },
];

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

function MetricCell({ value, change }: { value: string; change: number }) {
  const up = change >= 0;
  return (
    <div>
      <div>{value}</div>
      <div style={{ fontSize: 11, fontWeight: 600, color: up ? "#ff4d4f" : "#52c41a" }}>
        {up ? "+" : "-"}
        {Math.abs(change).toFixed(2)}%
      </div>
    </div>
  );
}

export function AnalyticsProductsPage() {
  const [data, setData] = useState<AnalyticsProducts | null>(null);
  const [mode, setMode] = useState("realtime");
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

  const load = useCallback(async (m: string, sid?: number) => {
    setLoading(true);
    setData(null);
    try {
      const params = new URLSearchParams();
      if (m === "realtime") {
        params.set("mode", "realtime");
      } else if (m === "yesterday") {
        params.set("mode", "yesterday");
      } else {
        params.set("mode", "days");
        params.set("days", m);
      }
      if (sid) params.set("store_id", String(sid));
      const { data: res } = await http.get<AnalyticsProducts>(`/analytics/products?${params.toString()}`);
      setData(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(mode, storeId);
  }, [mode, storeId, load]);

  const syncAll = async () => {
    setSyncing(true);
    try {
      const storeRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/stores/sync-all");
      const itemsUrl =
        mode === "realtime"
          ? "/stores/sync-items-realtime"
          : mode === "yesterday"
            ? `/stores/sync-items?date=${dayjs().subtract(1, "day").format("YYYY-MM-DD")}`
            : `/stores/sync-items?days=${mode}`;
      const itemsRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(itemsUrl);
      const promoMode = mode === "realtime" ? "realtime" : mode === "yesterday" ? "yesterday" : "7";
      const promoRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(`/promotions/sync?mode=${promoMode}`);
      const promoItemsRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(`/promotions/sync-items?mode=${mode === "realtime" ? "realtime" : mode}`);
      const label = mode === "realtime" ? "实时商品" : mode === "yesterday" ? "昨日商品" : `近 ${mode} 天商品`;
      message.success(`同步完成：店铺 ${storeRes.data.ok}/${storeRes.data.total}，${label} ${itemsRes.data.ok}/${itemsRes.data.total} 家，推广 ${promoRes.data.ok}/${promoRes.data.total} 家，商品推广 ${promoItemsRes.data.ok}/${promoItemsRes.data.total} 家`);
      [...storeRes.data.results.filter((r) => !r.ok), ...itemsRes.data.results.filter((r) => !r.ok), ...promoRes.data.results.filter((r) => !r.ok), ...promoItemsRes.data.results.filter((r) => !r.ok)]
        .slice(0, 3)
        .forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await load(mode, storeId);
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
      const params = new URLSearchParams({ mode: isRealtime ? "realtime" : mode });
      if (storeId) params.set("store_id", String(storeId));
      const { data } = await http.post<ProductInsightResult>(
        `/analytics/products/${encodeURIComponent(row.item_id)}/insight?${params.toString()}`
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
      const { data } = await http.post<{ reply: string }>(
        `/analytics/products/${encodeURIComponent(detail.item_id)}/insight/chat`,
        {
          mode: isRealtime ? "realtime" : mode,
          store_id: storeId,
          messages: [{ role: "assistant", content: detailResult.reply }, ...next],
        }
      );
      setDetailChat([...next, { role: "assistant" as const, content: data.reply }]);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setDetailChatLoading(false);
    }
  };

  const isRealtime = mode === "realtime";
  const numSorter = (key: keyof AnalyticsProduct) => (a: AnalyticsProduct, b: AnalyticsProduct) =>
    Number(a[key] ?? 0) - Number(b[key] ?? 0);
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
          { title: "访客", dataIndex: "visitors", align: "right", width: 110, sorter: numSorter("visitors"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.visitors_cycle ?? 0} /> },
          { title: "浏览量", dataIndex: "pv", align: "right", width: 110, sorter: numSorter("pv"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.pv_cycle ?? 0} /> },
          { title: "买家", dataIndex: "buyers", align: "right", width: 100, sorter: numSorter("buyers"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.buyers_cycle ?? 0} /> },
          { title: "销售额", dataIndex: "sales", align: "right", width: 130, sorter: numSorter("sales"), render: (v: number, row) => <MetricCell value={fmtMoney(v)} change={row.sales_cycle ?? 0} /> },
          { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 120, sorter: numSorter("conversion_rate"), render: (v: number, row) => <MetricCell value={fmtPct(v)} change={row.conversion_cycle ?? 0} /> },
          { title: "加购", dataIndex: "add_cart", align: "right", width: 100, sorter: numSorter("add_cart"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.add_cart_cycle ?? 0} /> },
          { title: "推广花费", dataIndex: "promo_spend", align: "right", width: 100, render: (v: number | null | undefined) => (v != null ? fmtMoney(v) : "—") },
          { title: "推广ROI", dataIndex: "promo_roi", align: "right", width: 90, render: (v: number | null | undefined) => (v != null ? v.toFixed(2) : "—") },
          { title: "广告占比", dataIndex: "promo_share", align: "right", width: 90, render: (v: number | null | undefined) => (v != null ? `${v.toFixed(1)}%` : "—") },
        ] as TableColumnsType<AnalyticsProduct>)
      : ([
          { title: "排名", dataIndex: "rank", width: 70, align: "center", render: (v: number) => <span style={{ fontWeight: 700, color: v <= 3 ? "#ff4d4f" : undefined }}>{v}</span> },
          { title: "商品", key: "item", width: 200, render: renderItem },
          { title: "销售额", dataIndex: "sales", align: "right", width: 120, sorter: numSorter("sales"), render: (v: number) => fmtMoney(v) },
          { title: "销量", dataIndex: "orders", align: "right", width: 90, sorter: numSorter("orders"), render: (v: number) => fmtInt(v) },
          { title: "买家", dataIndex: "buyers", align: "right", width: 90, sorter: numSorter("buyers"), render: (v: number) => fmtInt(v) },
          { title: "访客", dataIndex: "visitors", align: "right", width: 100, sorter: numSorter("visitors"), render: (v: number) => fmtInt(v) },
          { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 100, sorter: numSorter("conversion_rate"), render: (v: number) => fmtPct(v) },
          { title: "加购", dataIndex: "add_cart", align: "right", width: 90, sorter: numSorter("add_cart"), render: (v: number) => fmtInt(v) },
          { title: "推广花费", dataIndex: "promo_spend", align: "right", width: 100, render: (v: number | null | undefined) => (v != null ? fmtMoney(v) : "—") },
          { title: "推广ROI", dataIndex: "promo_roi", align: "right", width: 90, render: (v: number | null | undefined) => (v != null ? v.toFixed(2) : "—") },
          { title: "广告占比", dataIndex: "promo_share", align: "right", width: 90, render: (v: number | null | undefined) => (v != null ? `${v.toFixed(1)}%` : "—") },
          { title: "占比", dataIndex: "sales_share", align: "right", width: 90, sorter: numSorter("sales_share"), render: (v: number) => (v != null ? `${v.toFixed(1)}%` : "—") },
        ] as TableColumnsType<AnalyticsProduct>)),
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="商品分析"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented options={MODE_OPTIONS} value={mode} onChange={(v) => { setData(null); setMode(String(v)); }} />
        {isRealtime && (
        <Text type="secondary" style={{ fontSize: 12 }}>
          全量商品 · 按销售额排序
          {data?.fetched_at ? ` · 抓取时间 ${dayjs(data.fetched_at).format("MM-DD HH:mm:ss")}` : ""}
        </Text>
      )}
      </Space>

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
          title={isRealtime ? "实时商品榜（今日）" : "昨日商品销售排行"}
          style={{ boxShadow: "var(--ops-shadow-sm)" }}
          extra={isRealtime ? <Tag color="green">实时</Tag> : undefined}
        >
          <Table<AnalyticsProduct>
            rowKey="item_id"
            size="small"
            columns={columns}
            dataSource={data.items.map((item, index) => ({ ...item, rank: index + 1 }))}
            onRow={(record) => ({
              onMouseEnter: () => setHoverKey(record.item_id),
              onMouseLeave: () => setHoverKey((k) => (k === record.item_id ? null : k)),
            })}
            pagination={{ pageSize: 20, showTotal: () => `共 ${data.total} 个商品` }}
            tableLayout="fixed"
            scroll={{ x: isRealtime ? 1220 : 1230 }}
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
        destroyOnClose
      >
        {detailLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin tip="AI 正在分析该商品…" />
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
    </div>
  );
}
