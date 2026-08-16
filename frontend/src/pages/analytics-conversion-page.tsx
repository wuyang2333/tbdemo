import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Row, Space, Spin, message } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, fmtMoney, fmtPct, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsDailyPoint } from "../types";

export function AnalyticsConversionPage() {
  const [daily, setDaily] = useState<AnalyticsDailyPoint[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: AnalyticsDailyPoint[] }>("/analytics/daily?days=30");
      setDaily(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setDaily([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);
  const labels = daily.map((d) => d.date_label);

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="转化分析"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      {loading && daily.length === 0 ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card variant="borderless" title="转化率趋势（近 30 天）" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
              <LineChart
                labels={labels}
                series={[{ name: "转化率", color: "#1677ff", values: daily.map((d) => d.conversion_rate), format: fmtPct }]}
              />
            </Card>
            <Card variant="borderless" title="客单价（销售额 / 订单）" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <LineChart
                labels={labels}
                series={[{ name: "客单价", color: "#ff5000", values: daily.map((d) => d.avg_order_value), format: fmtMoney }]}
              />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card variant="borderless" title="单访客价值（销售额 / 访客）" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <LineChart
                labels={labels}
                series={[{ name: "单访客价值", color: "#52c41a", values: daily.map((d) => d.value_per_visitor), format: fmtMoney }]}
              />
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}
