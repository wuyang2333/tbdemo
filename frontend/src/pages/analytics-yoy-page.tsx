import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Space, Spin, Table, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { ChangeBadge, StoreScopeSelect, formatValue, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsCompareMetric } from "../types";

const { Text } = Typography;

export function AnalyticsYoyPage() {
  const [metrics, setMetrics] = useState<AnalyticsCompareMetric[]>([]);
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ metrics: AnalyticsCompareMetric[] }>(`/analytics/compare${storeId ? `?store_id=${storeId}` : ""}`);
      setMetrics(data.metrics);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setMetrics([]);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);

  const columns: TableColumnsType<AnalyticsCompareMetric> = [
    { title: "指标", dataIndex: "name", width: 110 },
    { title: "今日", dataIndex: "today", width: 140, align: "right", render: (v: number, row) => <span style={{ fontWeight: 700 }}>{formatValue(row.fmt, v)}</span> },
    { title: "较昨日（环比）", key: "dod", width: 170, render: (_, row) => <ChangeBadge change={row.dod.change_pct} prevText={`昨日 ${formatValue(row.fmt, row.dod.prev)}`} /> },
    { title: "较上周（环比）", key: "wow", width: 170, render: (_, row) => <ChangeBadge change={row.wow.change_pct} prevText={`上周 ${formatValue(row.fmt, row.wow.prev)}`} /> },
    { title: "较上月（环比）", key: "mom", width: 170, render: (_, row) => <ChangeBadge change={row.mom.change_pct} prevText={`上月 ${formatValue(row.fmt, row.mom.prev)}`} /> },
    { title: "较去年今日（同比）", key: "yoy", width: 180, render: (_, row) => <ChangeBadge change={row.yoy.change_pct} prevText={`去年 ${formatValue(row.fmt, row.yoy.prev)}`} /> },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="同比环比"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
          说明：环比=与上一周期比，同比=与去年同一天比。数据积累满相应周期后自动显示，未积累显示「无数据」。
        </Text>
        {loading && metrics.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : metrics.length === 0 ? (
          <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />
        ) : (
          <Table<AnalyticsCompareMetric>
            rowKey="key"
            size="small"
            columns={columns}
            dataSource={metrics}
            pagination={false}
            scroll={{ x: 820 }}
          />
        )}
      </Card>
    </div>
  );
}
