import { BarChartOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Segmented, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, daySwitch, fmtInt, fmtMoney, fmtPct } from "../components/analytics/analytics-ui";
import type { AnalyticsProduct, AnalyticsProducts } from "../types";

const { Text } = Typography;

const MODE_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "近 7 天", value: "7" },
  { label: "近 14 天", value: "14" },
  { label: "近 30 天", value: "30" },
];

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

  const load = useCallback(async (m: string, sid?: number) => {
    setLoading(true);
    setData(null);
    try {
      const params = new URLSearchParams();
      if (m === "realtime") {
        params.set("mode", "realtime");
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
      const itemsUrl = mode === "realtime" ? "/stores/sync-items-realtime" : `/stores/sync-items?days=${mode}`;
      const itemsRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(itemsUrl);
      const promoMode = mode === "realtime" ? "realtime" : "7";
      const promoRes = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(`/promotions/sync?mode=${promoMode}`);
      const label = mode === "realtime" ? "实时商品" : `近 ${mode} 天商品`;
      message.success(`同步完成：店铺 ${storeRes.data.ok}/${storeRes.data.total}，${label} ${itemsRes.data.ok}/${itemsRes.data.total} 家，推广 ${promoRes.data.ok}/${promoRes.data.total} 家`);
      [...storeRes.data.results.filter((r) => !r.ok), ...itemsRes.data.results.filter((r) => !r.ok), ...promoRes.data.results.filter((r) => !r.ok)]
        .slice(0, 3)
        .forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await load(mode, storeId);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
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
        <div style={{ minWidth: 0, position: "relative", paddingTop: hovered ? 26 : 0, transition: "padding-top 0.15s" }}>
          {hovered && (
            <div
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                right: 0,
                display: "flex",
                background: "#1677ff",
                borderRadius: 4,
                overflow: "hidden",
                zIndex: 2,
              }}
            >
              <Button
                size="small"
                type="text"
                style={{ color: "#fff", height: 22, lineHeight: "22px", padding: "0 10px", fontSize: 12 }}
                onClick={(e) => {
                  e.stopPropagation();
                  copyItemId(row.item_id);
                }}
              >
                复制
              </Button>
              <Button
                size="small"
                type="text"
                style={{ color: "#fff", height: 22, lineHeight: "22px", padding: "0 10px", fontSize: 12 }}
                onClick={(e) => {
                  e.stopPropagation();
                  message.info("AI分析功能开发中");
                }}
              >
                AI分析
              </Button>
            </div>
          )}
          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.item_title}</div>
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
          { title: "商品", key: "item", width: 320, render: renderItem },
          { title: "访客", dataIndex: "visitors", align: "right", width: 110, sorter: numSorter("visitors"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.visitors_cycle ?? 0} /> },
          { title: "浏览量", dataIndex: "pv", align: "right", width: 110, sorter: numSorter("pv"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.pv_cycle ?? 0} /> },
          { title: "买家", dataIndex: "buyers", align: "right", width: 100, sorter: numSorter("buyers"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.buyers_cycle ?? 0} /> },
          { title: "销售额", dataIndex: "sales", align: "right", width: 130, sorter: numSorter("sales"), render: (v: number, row) => <MetricCell value={fmtMoney(v)} change={row.sales_cycle ?? 0} /> },
          { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 120, sorter: numSorter("conversion_rate"), render: (v: number, row) => <MetricCell value={fmtPct(v)} change={row.conversion_cycle ?? 0} /> },
          { title: "加购", dataIndex: "add_cart", align: "right", width: 100, sorter: numSorter("add_cart"), render: (v: number, row) => <MetricCell value={fmtInt(v)} change={row.add_cart_cycle ?? 0} /> },
        ] as TableColumnsType<AnalyticsProduct>)
      : ([
          { title: "排名", dataIndex: "rank", width: 70, align: "center", render: (v: number) => <span style={{ fontWeight: 700, color: v <= 3 ? "#ff4d4f" : undefined }}>{v}</span> },
          { title: "商品", key: "item", width: 340, render: renderItem },
          { title: "销售额", dataIndex: "sales", align: "right", width: 120, sorter: numSorter("sales"), render: (v: number) => fmtMoney(v) },
          { title: "销量", dataIndex: "orders", align: "right", width: 90, sorter: numSorter("orders"), render: (v: number) => fmtInt(v) },
          { title: "买家", dataIndex: "buyers", align: "right", width: 90, sorter: numSorter("buyers"), render: (v: number) => fmtInt(v) },
          { title: "访客", dataIndex: "visitors", align: "right", width: 100, sorter: numSorter("visitors"), render: (v: number) => fmtInt(v) },
          { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 100, sorter: numSorter("conversion_rate"), render: (v: number) => fmtPct(v) },
          { title: "加购", dataIndex: "add_cart", align: "right", width: 90, sorter: numSorter("add_cart"), render: (v: number) => fmtInt(v) },
          { title: "占比", dataIndex: "sales_share", align: "right", width: 90, sorter: numSorter("sales_share"), render: (v: number) => (v != null ? `${v.toFixed(1)}%` : "—") },
          { title: "天数", dataIndex: "days", align: "right", width: 80, sorter: numSorter("days") },
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
        {!isRealtime && <Text type="secondary" style={{ fontSize: 12 }}>统计范围</Text>}
        {!isRealtime && daySwitch(Number(mode), (d) => setMode(String(d)))}
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
          title={isRealtime ? "实时商品榜（今日）" : `商品销售排行 TOP（近 ${mode} 天）`}
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
            scroll={{ x: 900 }}
          />
        </Card>
      )}
    </div>
  );
}
