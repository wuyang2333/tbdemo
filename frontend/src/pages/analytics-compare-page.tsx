import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Row, Space, Spin, Table, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { StoreBars, StoreScopeSelect, daySwitch, fmtMoney, fmtPct, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsStoreAgg } from "../types";

const { Text } = Typography;

export function AnalyticsComparePage() {
  const [stores, setStores] = useState<AnalyticsStoreAgg[]>([]);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: AnalyticsStoreAgg[] }>(`/analytics/stores?days=${d}${storeId ? `&store_id=${storeId}` : ""}`);
      setStores(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setStores([]);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    load(days);
  }, [days, load]);

  const { syncing, syncAll } = useSyncStores(() => load(days));

  const columns: TableColumnsType<AnalyticsStoreAgg> = [
    { title: "店铺", dataIndex: "store_name", width: 160 },
    { title: "访客", dataIndex: "visitors", align: "right", width: 90 },
    { title: "浏览量", dataIndex: "pv", align: "right", width: 90 },
    { title: "销售额", dataIndex: "sales", align: "right", width: 120, render: (v: number) => fmtMoney(v) },
    { title: "订单", dataIndex: "orders", align: "right", width: 80 },
    { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 100, render: (v: number) => fmtPct(v) },
    { title: "客单价", dataIndex: "avg_order_value", align: "right", width: 110, render: (v: number) => fmtMoney(v) },
    { title: "单访客价值", dataIndex: "value_per_visitor", align: "right", width: 120, render: (v: number) => fmtMoney(v) },
    { title: "有数据天数", dataIndex: "days", align: "right", width: 100 },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="店铺对比"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<ReloadOutlined />} onClick={() => load(days)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>统计范围</Text>
        {daySwitch(days, setDays)}
      </Space>

      {loading && stores.length === 0 ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card variant="borderless" title={`店铺销售额排行（近 ${days} 天）`} style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%" }}>
              <StoreBars items={stores} />
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Card variant="borderless" title="店铺对比明细" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <Table<AnalyticsStoreAgg>
                rowKey="store_id"
                size="small"
                columns={columns}
                dataSource={stores}
                pagination={false}
                scroll={{ x: 900 }}
              />
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}
