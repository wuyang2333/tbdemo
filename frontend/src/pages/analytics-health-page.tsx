import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Empty, Progress, Row, Space, Spin, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsHealth } from "../types";

const { Text } = Typography;

function scoreColor(score: number): string {
  if (score >= 80) return "#52c41a";
  if (score >= 60) return "#fa8c16";
  return "#ff4d4f";
}

export function AnalyticsHealthPage() {
  const [data, setData] = useState<AnalyticsHealth | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await http.get<AnalyticsHealth>("/analytics/health");
      setData(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="经营健康分"
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

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description="暂无数据，先同步店铺与推广数据" />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} md={8}>
            <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", textAlign: "center" }}>
              <Text type="secondary" style={{ fontSize: 14 }}>综合健康分</Text>
              <div style={{ fontSize: 64, fontWeight: 800, color: scoreColor(data.score), margin: "12px 0" }}>
                {data.score}
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                {data.score >= 80 ? "经营健康，保持节奏" : data.score >= 60 ? "总体正常，有可优化项" : "需要重点关注"}
              </Text>
            </Card>
          </Col>
          <Col xs={24} md={16}>
            <Card variant="borderless" title="分项得分" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              {data.items.map((item) => (
                <div key={item.key} style={{ marginBottom: 18 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <Text strong style={{ fontSize: 13 }}>{item.name}</Text>
                    <Text style={{ fontSize: 12, color: scoreColor(item.score) }}>{item.score} 分</Text>
                  </div>
                  <Progress percent={item.score} showInfo={false} strokeColor={scoreColor(item.score)} />
                  <Text type="secondary" style={{ fontSize: 12 }}>{item.detail}</Text>
                </div>
              ))}
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}
