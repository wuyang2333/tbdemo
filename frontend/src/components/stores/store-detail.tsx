import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { Col, Descriptions, Drawer, Empty, Row, Spin, Statistic, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import http from "../../lib/api";
import type { Store, StoreAlert, StoreMetricsResponse } from "../../types";

const { Text } = Typography;

function TrendChart({ trend }: { trend: StoreMetricsResponse["trend"] }) {
  const width = 560;
  const height = 170;
  const pad = 8;
  if (!trend.length) return null;
  const values = trend.map((point) => point.sales);
  const max = Math.max(...values);
  const min = Math.min(...values);
  const range = max - min || 1;
  const points = trend.map((point, index) => {
    const x = pad + (index * (width - pad * 2)) / (trend.length - 1);
    const y = height - pad - ((point.sales - min) / range) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = points.map(([x, y]) => `${x},${y}`).join(" ");
  const area = `${pad},${height - pad} ${line} ${width - pad},${height - pad}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height: 170, display: "block" }}>
      <defs>
        <linearGradient id="salesArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#ff5000" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#ff5000" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polygon points={area} fill="url(#salesArea)" />
      <polyline
        points={line}
        fill="none"
        stroke="#ff5000"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <text x={pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)">
        {trend[0].date}
      </text>
      <text x={width - pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)" textAnchor="end">
        {trend[trend.length - 1].date}
      </text>
    </svg>
  );
}

function AlertLevelTag({ level }: { level: StoreAlert["level"] }) {
  if (level === "error") return <Tag color="red">严重</Tag>;
  if (level === "warn") return <Tag color="orange">提醒</Tag>;
  return <Tag>提示</Tag>;
}

export function StoreDetailDrawer({
  store,
  open,
  alerts,
  onClose,
}: {
  store: Store | null;
  open: boolean;
  alerts: StoreAlert[];
  onClose: () => void;
}) {
  const [data, setData] = useState<StoreMetricsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !store) return;
    let cancelled = false;
    setLoading(true);
    http
      .get<StoreMetricsResponse>(`/stores/${store.id}/metrics`)
      .then((response) => {
        if (!cancelled) setData(response.data);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, store]);

  const storeAlerts = store ? alerts.filter((alert) => alert.store_id === store.id) : [];

  return (
    <Drawer title={store?.name ?? "店铺详情"} open={open} onClose={onClose} size="large">
      {loading || !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : (
        <>
          <Row gutter={[12, 12]}>
            <Col span={6}>
              <Statistic
                title="今日销售额"
                value={data.today.sales}
                precision={2}
                prefix="¥"
                styles={{ content: { fontSize: 18 } }}
              />
            </Col>
            <Col span={6}>
              <Statistic title="今日订单" value={data.today.orders} styles={{ content: { fontSize: 18 } }} />
            </Col>
            <Col span={6}>
              <Statistic title="今日访客" value={data.today.visitors} styles={{ content: { fontSize: 18 } }} />
            </Col>
            <Col span={6}>
              <Statistic
                title="退款率"
                value={data.today.refund_rate}
                suffix="%"
                styles={{
                  content: {
                    fontSize: 18,
                    color: data.today.refund_rate > 8 ? "#ff4d4f" : undefined,
                  },
                }}
              />
            </Col>
          </Row>

          <div style={{ marginTop: 22 }}>
            <Text strong>近 14 天销售额趋势</Text>
            <div
              style={{
                marginTop: 10,
                border: "1px solid var(--ops-border)",
                borderRadius: 12,
                padding: "10px 14px",
              }}
            >
              <TrendChart trend={data.trend} />
            </div>
          </div>

          <div style={{ marginTop: 22 }}>
            <Text strong>近 7 天汇总</Text>
            <Row gutter={[12, 12]} style={{ marginTop: 10 }}>
              <Col span={8}>
                <Statistic
                  title="销售额"
                  value={data.summary.sales_7d}
                  precision={0}
                  prefix="¥"
                  styles={{ content: { fontSize: 18 } }}
                />
              </Col>
              <Col span={8}>
                <Statistic title="订单数" value={data.summary.orders_7d} styles={{ content: { fontSize: 18 } }} />
              </Col>
              <Col span={8}>
                <Statistic
                  title="销售额环比"
                  value={Math.abs(data.summary.sales_change_7d)}
                  precision={1}
                  suffix="%"
                  prefix={
                    data.summary.sales_change_7d >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />
                  }
                  styles={{
                    content: {
                      fontSize: 18,
                      color: data.summary.sales_change_7d >= 0 ? "#52c41a" : "#ff4d4f",
                    },
                  }}
                />
              </Col>
            </Row>
          </div>

          <div style={{ marginTop: 22 }}>
            <Text strong>店铺信息</Text>
            <Descriptions
              size="small"
              column={2}
              style={{ marginTop: 10 }}
              items={[
                { key: "owner", label: "掌柜", children: data.store.owner || "—" },
                { key: "category", label: "主营类目", children: data.store.category || "—" },
                { key: "level", label: "等级", children: data.store.level || "—" },
                { key: "location", label: "所在地", children: data.store.location || "—" },
                {
                  key: "dsr",
                  label: "DSR 描述/服务/物流",
                  children: `${data.store.dsr_desc.toFixed(1)} / ${data.store.dsr_service.toFixed(1)} / ${data.store.dsr_logistics.toFixed(1)}`,
                },
              ]}
            />
          </div>

          <div style={{ marginTop: 22 }}>
            <Text strong>店铺提醒</Text>
            {storeAlerts.length === 0 ? (
              <Empty
                description="暂无提醒"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                style={{ marginTop: 12 }}
              />
            ) : (
              <div style={{ marginTop: 10 }}>
                {storeAlerts.map((alert) => (
                  <div
                    key={alert.id}
                    style={{
                      display: "flex",
                      gap: 8,
                      padding: "9px 0",
                      borderBottom: "1px solid var(--ops-border)",
                      alignItems: "center",
                    }}
                  >
                    <WarningOutlined
                      style={{
                        color: alert.level === "error" ? "#ff4d4f" : "#fa8c16",
                        marginTop: 3,
                      }}
                    />
                    <Text style={{ fontSize: 13, flex: 1 }}>{alert.message}</Text>
                    <AlertLevelTag level={alert.level} />
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Drawer>
  );
}
