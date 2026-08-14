import { BarChartOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Card, Col, Empty, Row, Space, Spin, Statistic, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import http from "../../src/lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { AnalyticsStoreAgg, AnalyticsSummary, AnalyticsTrendPoint } from "../types";

const { Text } = Typography;

const DAY_OPTIONS = [7, 14, 30];

function TrendChart({ trend }: { trend: AnalyticsTrendPoint[] }) {
  const width = 720;
  const height = 210;
  const pad = 12;
  if (!trend.length) return <Empty description="暂无数据" style={{ padding: 24 }} />;
  const maxVal = Math.max(1, ...trend.map((p) => Math.max(p.amount, p.commission)));
  const pointsFor = (key: "amount" | "commission") =>
    trend.map((point, index) => {
      const x = pad + (index * (width - pad * 2)) / (trend.length - 1);
      const y = height - pad - (point[key] / maxVal) * (height - pad * 2);
      return [x, y] as const;
    });
  const lineFor = (key: "amount" | "commission") =>
    pointsFor(key)
      .map(([x, y]) => `${x},${y}`)
      .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: 210, display: "block" }}>
      <polyline points={lineFor("amount")} fill="none" stroke="#ff5000" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      <polyline points={lineFor("commission")} fill="none" stroke="#1677ff" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      <text x={pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)">
        {trend[0].date}
      </text>
      <text x={width - pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)" textAnchor="end">
        {trend[trend.length - 1].date}
      </text>
    </svg>
  );
}

function StoreBars({ items }: { items: AnalyticsStoreAgg[] }) {
  if (!items.length) return <Empty description="暂无数据" style={{ padding: 24 }} />;
  const max = Math.max(1, ...items.map((item) => item.amount));
  return (
    <div>
      {items.map((item) => (
        <div key={item.store} style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
          <div
            style={{
              width: 150,
              textAlign: "right",
              paddingRight: 10,
              fontSize: 12,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              flexShrink: 0,
            }}
            title={item.store}
          >
            {item.store}
          </div>
          <div style={{ flex: 1, height: 18, background: "var(--ops-card-bg-2)", borderRadius: 4, overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.max((item.amount / max) * 100, 1.5)}%`,
                height: "100%",
                background: "var(--ops-accent)",
                borderRadius: 4,
              }}
            />
          </div>
          <div style={{ width: 130, textAlign: "right", fontSize: 12, flexShrink: 0 }}>
            ¥{item.amount.toFixed(2)} · {item.orders} 单
          </div>
        </div>
      ))}
    </div>
  );
}

function BucketCard({ title, data }: { title: string; data: { orders: number; amount: number; commission: number } }) {
  return (
    <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%" }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{title}</Text>
      <div style={{ marginTop: 10, display: "flex", gap: 24, flexWrap: "wrap" }}>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>单数</Text>
          <div style={{ fontSize: 22, fontWeight: 700 }}>{data.orders}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>金额</Text>
          <div style={{ fontSize: 22, fontWeight: 700 }}>¥{data.amount.toFixed(2)}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>佣金</Text>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#1677ff" }}>¥{data.commission.toFixed(2)}</div>
        </div>
      </div>
    </Card>
  );
}

export function AnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const { data } = await http.get<AnalyticsSummary>(`/analytics/summary?days=${d}`);
      setSummary(data);
    } catch {
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(days);
  }, [days, load]);

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="数据洞察"
        extra={
          <Button icon={<ReloadOutlined />} onClick={() => load(days)}>
            刷新
          </Button>
        }
      />

      {loading && !summary ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : summary ? (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日单数" value={summary.today.orders} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日金额" value={summary.today.amount} precision={2} prefix="¥" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日佣金" value={summary.today.commission} precision={2} prefix="¥" valueStyle={{ color: "#1677ff" }} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="未结款" value={summary.status.unsettled} valueStyle={{ color: "#fa8c16" }} />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} md={8}><BucketCard title="本周（近 7 天）" data={summary.week} /></Col>
            <Col xs={24} md={8}><BucketCard title="本月" data={summary.month} /></Col>
            <Col xs={24} md={8}><BucketCard title="累计" data={summary.total} /></Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} lg={15}>
              <Card
                variant="borderless"
                title="近 N 天金额 / 佣金趋势"
                style={{ boxShadow: "var(--ops-shadow-sm)" }}
                extra={
                  <Space>
                    {DAY_OPTIONS.map((option) => (
                      <Button
                        key={option}
                        size="small"
                        type={days === option ? "primary" : "default"}
                        onClick={() => setDays(option)}
                      >
                        {option} 天
                      </Button>
                    ))}
                  </Space>
                }
              >
                <Space style={{ marginBottom: 8 }}>
                  <Tag color="#ff5000">金额</Tag>
                  <Tag color="#1677ff">佣金</Tag>
                </Space>
                <TrendChart trend={summary.trend} />
              </Card>
            </Col>
            <Col xs={24} lg={9}>
              <Card variant="borderless" title="按店铺汇总" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%" }}>
                <StoreBars items={summary.by_store} />
              </Card>
            </Col>
          </Row>

          <Card variant="borderless" title="状态分布" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <Row gutter={[16, 16]}>
              <Col xs={12} sm={6}>
                <Statistic title="已评论" value={summary.status.reviewed} valueStyle={{ color: "#52c41a" }} />
              </Col>
              <Col xs={12} sm={6}>
                <Statistic title="未评论" value={summary.status.unreviewed} valueStyle={{ color: "#fa8c16" }} />
              </Col>
              <Col xs={12} sm={6}>
                <Statistic title="已结款" value={summary.status.settled} valueStyle={{ color: "#52c41a" }} />
              </Col>
              <Col xs={12} sm={6}>
                <Statistic title="未结款" value={summary.status.unsettled} valueStyle={{ color: "#fa8c16" }} />
              </Col>
            </Row>
          </Card>
        </>
      ) : (
        <Card variant="borderless">
          <Empty description="暂时没有可统计的数据" />
        </Card>
      )}
    </div>
  );
}
