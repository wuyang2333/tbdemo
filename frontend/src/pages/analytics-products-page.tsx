import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Segmented, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, daySwitch, fmtInt, fmtMoney, fmtPct, useSyncStores } from "../components/analytics/analytics-ui";
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

  const { syncing: syncStores, syncAll } = useSyncStores(() => load(mode, storeId));

  const syncProducts = async () => {
    setSyncing(true);
    try {
      const url = mode === "realtime" ? "/stores/sync-items-realtime" : `/stores/sync-items?days=${mode}`;
      const { data: res } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(url);
      const label = mode === "realtime" ? "实时商品" : `近 ${mode} 天商品`;
      message.success(`${label}同步完成：成功 ${res.ok} / 共 ${res.total} 家`);
      res.results.filter((r) => !r.ok).slice(0, 3).forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
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
  const renderItem = (_: unknown, row: AnalyticsProduct) => (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      {row.image ? (
        <img src={row.image} alt="" style={{ width: 40, height: 40, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} />
      ) : (
        <div style={{ width: 40, height: 40, borderRadius: 6, background: "var(--ops-card-bg-2)", flexShrink: 0 }} />
      )}
      <div style={{ minWidth: 0 }}>
        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{row.item_title}</div>
        <div style={{ fontSize: 11, color: "rgba(128,128,128,0.75)" }}>ID {row.item_id}</div>
      </div>
    </div>
  );
  const columns: TableColumnsType<AnalyticsProduct> = [
    ...(isRealtime
      ? ([
          {
            title: "数据",
            dataIndex: "date_label",
            width: 90,
            render: (v: string, row) =>
              row.live ? <Tag color="green">今日实时</Tag> : <Tag>{String(v)}</Tag>,
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
            <Button icon={<ReloadOutlined />} onClick={() => load(mode, storeId)}>
              刷新
            </Button>
            <Button icon={<SyncOutlined />} loading={syncing} onClick={syncProducts}>
              {isRealtime ? "同步实时商品" : "同步商品数据"}
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncStores} onClick={syncAll}>
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
          全量商品今日实时 · 按销售额排序
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
          <Empty description={`暂无${isRealtime ? "实时" : ""}商品数据，点「${isRealtime ? "同步实时商品" : "同步商品数据"}」抓取`} />
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
            dataSource={data.items}
            pagination={{ pageSize: 20, showTotal: () => `共 ${data.total} 个商品` }}
            scroll={{ x: 900 }}
          />
        </Card>
      )}
    </div>
  );
}
