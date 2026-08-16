import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Empty, Row, Segmented, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, StoreScopeSelect, daySwitch, fmtInt, fmtMoney, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsProduct, AnalyticsProductDetail, AnalyticsProducts } from "../types";

const { Text } = Typography;

const MODE_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "近 7 天", value: "7" },
  { label: "近 14 天", value: "14" },
  { label: "近 30 天", value: "30" },
];

export function AnalyticsProductsPage() {
  const [data, setData] = useState<AnalyticsProducts | null>(null);
  const [detail, setDetail] = useState<AnalyticsProductDetail | null>(null);
  const [mode, setMode] = useState("realtime");
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async (m: string, sid?: number) => {
    setLoading(true);
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
      setDetail(null);
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

  const openDetail = async (item: AnalyticsProduct) => {
    const params = new URLSearchParams({ days: String(mode === "realtime" ? 7 : Number(mode)) });
    if (storeId) params.set("store_id", String(storeId));
    try {
      const { data: res } = await http.get<AnalyticsProductDetail>(`/analytics/products/${encodeURIComponent(item.item_id)}?${params.toString()}`);
      setDetail({ ...res, item_title: item.item_title || res.item_title });
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const isRealtime = mode === "realtime";
  const columns: TableColumnsType<AnalyticsProduct> = [
    ...(isRealtime
      ? ([
          { title: "商品", dataIndex: "item_title", width: 280, ellipsis: true },
          { title: "访客", dataIndex: "visitors", align: "right", width: 80, render: (v: number) => fmtInt(v) },
          { title: "浏览量", dataIndex: "pv", align: "right", width: 80, render: (v: number) => fmtInt(v) },
          { title: "买家", dataIndex: "buyers", align: "right", width: 70, render: (v: number) => fmtInt(v) },
          { title: "销售额", dataIndex: "sales", align: "right", width: 110, render: (v: number) => fmtMoney(v) },
          { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 90, render: (v: number) => `${v.toFixed(2)}%` },
        ] as TableColumnsType<AnalyticsProduct>)
      : ([
          { title: "商品", dataIndex: "item_title", width: 300, ellipsis: true },
          { title: "销售额", dataIndex: "sales", align: "right", width: 110, render: (v: number) => fmtMoney(v) },
          { title: "销量", dataIndex: "orders", align: "right", width: 80, render: (v: number) => fmtInt(v) },
          { title: "销售人数", dataIndex: "buyers", align: "right", width: 90, render: (v: number) => fmtInt(v) },
          { title: "销售占比", dataIndex: "sales_share", align: "right", width: 90, render: (v: number) => (v != null ? `${v.toFixed(1)}%` : "—") },
          { title: "有数据天数", dataIndex: "days", align: "right", width: 90 },
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
        <Segmented options={MODE_OPTIONS} value={mode} onChange={(v) => setMode(String(v))} />
        {!isRealtime && <Text type="secondary" style={{ fontSize: 12 }}>统计范围</Text>}
        {!isRealtime && daySwitch(Number(mode), (d) => setMode(String(d)))}
        {isRealtime && <Text type="secondary" style={{ fontSize: 12 }}>今日实时，按销售额排序，每 30 分钟可手动刷新</Text>}
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
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={13}>
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
                pagination={{ pageSize: 10, showTotal: () => `共 ${data.total} 个商品` }}
                scroll={{ x: 720 }}
                onRow={(record) => ({ onClick: () => openDetail(record), style: { cursor: "pointer" } })}
              />
            </Card>
          </Col>
          <Col xs={24} lg={11}>
            <Card
              variant="borderless"
              title={detail ? `单品趋势 · ${detail.item_title.slice(0, 24)}${detail.item_title.length > 24 ? "…" : ""}` : "单品趋势"}
              style={{ boxShadow: "var(--ops-shadow-sm)" }}
            >
              {!detail ? (
                <Empty description="点击左侧商品查看单品每日趋势（含今日实时）" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />
              ) : (
                <>
                  <LineChart
                    labels={detail.series.map((p) => p.date)}
                    series={[
                      { name: "销售额", color: "#ff5000", values: detail.series.map((p) => p.sales), format: fmtMoney },
                      { name: "销量", color: "#1677ff", values: detail.series.map((p) => p.orders) },
                    ]}
                  />
                  <Tag style={{ marginTop: 8 }} color="blue">最后一天为今日实时数据</Tag>
                </>
              )}
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}
