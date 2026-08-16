import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Row, Space, Spin, Table, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, StoreScopeSelect, daySwitch, fmtMoney, fmtPct, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsDailyPoint, AnalyticsForecast } from "../types";

const { Text } = Typography;

export function AnalyticsTrendPage() {
  const [daily, setDaily] = useState<AnalyticsDailyPoint[]>([]);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [forecast, setForecast] = useState<AnalyticsForecast | null>(null);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: AnalyticsDailyPoint[] }>(`/analytics/daily?days=${d}${storeId ? `&store_id=${storeId}` : ""}`);
      setDaily(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setDaily([]);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    load(days);
    http
      .get<AnalyticsForecast>("/analytics/forecast?days=7")
      .then(({ data }) => setForecast(data))
      .catch(() => setForecast(null));
  }, [days, load]);

  const { syncing, syncAll } = useSyncStores(() => load(days));

  const labels = daily.map((d) => d.date_label);
  const columns: TableColumnsType<AnalyticsDailyPoint> = [
    { title: "日期", dataIndex: "date_label", width: 90 },
    { title: "访客", dataIndex: "visitors", align: "right", width: 90 },
    { title: "浏览量", dataIndex: "pv", align: "right", width: 90 },
    { title: "销售额", dataIndex: "sales", align: "right", width: 110, render: (v: number) => fmtMoney(v) },
    { title: "订单", dataIndex: "orders", align: "right", width: 80 },
    { title: "转化率", dataIndex: "conversion_rate", align: "right", width: 100, render: (v: number) => fmtPct(v) },
    { title: "客单价", dataIndex: "avg_order_value", align: "right", width: 110, render: (v: number) => fmtMoney(v) },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="趋势分析"
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
        <Text type="secondary" style={{ fontSize: 12 }}>时间范围</Text>
        {daySwitch(days, setDays)}
      </Space>

      {loading && daily.length === 0 ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={14}>
            <Card variant="borderless" title="销售额 / 订单数" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
              <LineChart
                labels={labels}
                series={[
                  { name: "销售额", color: "#ff5000", values: daily.map((d) => d.sales), format: fmtMoney },
                  { name: "订单数", color: "#1677ff", values: daily.map((d) => d.orders) },
                ]}
              />
            </Card>
            <Card variant="borderless" title="访客 / 浏览量" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <LineChart
                labels={labels}
                series={[
                  { name: "访客数", color: "#52c41a", values: daily.map((d) => d.visitors) },
                  { name: "浏览量", color: "#faad14", values: daily.map((d) => d.pv) },
                ]}
              />
            </Card>
          </Col>
          <Col xs={24} lg={10}>
            <Card variant="borderless" title="转化率" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
              <LineChart
                labels={labels}
                series={[{ name: "转化率", color: "#1677ff", values: daily.map((d) => d.conversion_rate), format: fmtPct }]}
                height={170}
              />
            </Card>
            <Card variant="borderless" title="每日明细" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <Table<AnalyticsDailyPoint>
                rowKey="date"
                size="small"
                columns={columns}
                dataSource={daily}
                pagination={{ pageSize: 8, showTotal: (c) => `共 ${c} 天` }}
                scroll={{ x: 640 }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {forecast && (
        <Card variant="borderless" title="趋势预测（近 14 天实际 + 未来 7 天，仅供参考）" style={{ boxShadow: "var(--ops-shadow-sm)", marginTop: 16 }}>
          <LineChart
            labels={[...forecast.actual.map((p) => p.date), ...forecast.predicted.map((p) => p.date)]}
            series={[
              { name: "实际", color: "#1677ff", values: [...forecast.actual.map((p) => p.sales), ...Array(forecast.predicted.length).fill(null as unknown as number)], format: fmtMoney },
              { name: "预测", color: "#fa8c16", values: [...Array(forecast.actual.length).fill(null as unknown as number), ...forecast.predicted.map((p) => p.sales)], format: fmtMoney },
            ]}
          />
        </Card>
      )}
    </div>
  );
}
