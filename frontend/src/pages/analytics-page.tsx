import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Empty, Row, Space, Spin, Statistic, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { AnalyticsStoreAgg, AnalyticsSummary, AnalyticsTrendPoint } from "../types";

const { Text } = Typography;

const DAY_OPTIONS = [7, 14, 30];

function TrendChart({ trend }: { trend: AnalyticsTrendPoint[] }) {
  const width = 720;
  const height = 210;
  const pad = 12;
  if (!trend.length) return <Empty description="还没有数据，先同步各店铺数据" style={{ padding: 24 }} />;
  const maxVal = Math.max(1, ...trend.map((p) => Math.max(p.sales, p.orders)));
  const pointsFor = (key: "sales" | "orders") =>
    trend.map((point, index) => {
      const x = pad + (index * (width - pad * 2)) / (trend.length - 1);
      const y = height - pad - (point[key] / maxVal) * (height - pad * 2);
      return [x, y] as const;
    });
  const lineFor = (key: "sales" | "orders") =>
    pointsFor(key)
      .map(([x, y]) => `${x},${y}`)
      .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: 210, display: "block" }}>
      <polyline points={lineFor("sales")} fill="none" stroke="#ff5000" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
      <polyline points={lineFor("orders")} fill="none" stroke="#1677ff" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
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
  if (!items.length) return <Empty description="还没有店铺数据" style={{ padding: 24 }} />;
  const max = Math.max(1, ...items.map((item) => item.sales));
  return (
    <div>
      {items.map((item) => (
        <div key={item.store_id} style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
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
            title={item.store_name}
          >
            {item.store_name}
          </div>
          <div style={{ flex: 1, height: 18, background: "var(--ops-card-bg-2)", borderRadius: 4, overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.max((item.sales / max) * 100, 1.5)}%`,
                height: "100%",
                background: "var(--ops-accent)",
                borderRadius: 4,
              }}
            />
          </div>
          <div style={{ width: 130, textAlign: "right", fontSize: 12, flexShrink: 0 }}>
            ¥{item.sales.toFixed(2)} · {item.orders} 单
          </div>
        </div>
      ))}
    </div>
  );
}

function BucketCard({ title, data }: { title: string; data: AnalyticsSummary["today"] }) {
  return (
    <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%" }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{title}</Text>
      <div style={{ marginTop: 10, display: "flex", gap: 20, flexWrap: "wrap" }}>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>访客</Text>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{data.visitors}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>销售额</Text>
          <div style={{ fontSize: 20, fontWeight: 700 }}>¥{data.sales.toFixed(2)}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>订单</Text>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{data.orders}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>转化率</Text>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#1677ff" }}>{data.conversion_rate.toFixed(2)}%</div>
        </div>
      </div>
    </Card>
  );
}

export function AnalyticsPage() {
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const { data } = await http.get<AnalyticsSummary>(`/analytics/summary?days=${d}`);
      setSummary(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(days);
  }, [days, load]);

  const syncAll = async () => {
    setSyncing(true);
    try {
      const { data } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(
        "/stores/sync-all"
      );
      message.success(`同步完成：成功 ${data.ok} / 共 ${data.total} 家`);
      const failed = data.results.filter((r) => !r.ok);
      if (failed.length) {
        failed.slice(0, 3).forEach((f) => message.warning(`${f.store_name}：${f.error || "同步失败"}`));
      }
      load(days);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="数据洞察"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load(days)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      {summary?.last_sync && (
        <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
          最近同步：{dayjs(summary.last_sync).format("YYYY-MM-DD HH:mm:ss")} · 已配置 {summary.store_count} 家店铺
        </Text>
      )}

      {loading && !summary ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : summary ? (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日访客" value={summary.today.visitors} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日销售额" value={summary.today.sales} precision={2} prefix="¥" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日订单" value={summary.today.orders} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic
                  title="今日转化率"
                  value={summary.today.conversion_rate}
                  precision={2}
                  suffix="%"
                  valueStyle={{ color: "#1677ff" }}
                />
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
                title="近 N 天销售额 / 订单数趋势"
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
                  <Tag color="#ff5000">销售额</Tag>
                  <Tag color="#1677ff">订单数</Tag>
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
        </>
      ) : (
        <Card variant="borderless">
          <Empty description="还没有数据，点击右上角「同步店铺数据」抓取生意参谋数据" />
        </Card>
      )}
    </div>
  );
}
