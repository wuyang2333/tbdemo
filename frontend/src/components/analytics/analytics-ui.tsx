import { Button, Empty, Select, Space, Tag, Typography, message } from "antd";

import { useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../../lib/api";
import type { AnalyticsStoreAgg, AnalyticsSummary, AnalyticsTrendPoint } from "../../types";

const { Text } = Typography;

export const ANALYTICS_DAY_OPTIONS = [7, 14, 30];

export function fmtMoney(value: number): string {
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function fmtPct(value: number): string {
  return `${value.toFixed(2)}%`;
}

export function fmtInt(value: number): string {
  return value.toLocaleString("zh-CN");
}

export function formatValue(fmt: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (fmt === "money") return fmtMoney(value);
  if (fmt === "pct") return fmtPct(value);
  return `${value}`;
}

export function daySwitch(days: number, onDays: (d: number) => void) {
  return (
    <Space>
      {ANALYTICS_DAY_OPTIONS.map((option) => (
        <Button key={option} size="small" type={days === option ? "primary" : "default"} onClick={() => onDays(option)}>
          {option} 天
        </Button>
      ))}
    </Space>
  );
}

export function useSyncStores(onDone: () => void) {
  const [syncing, setSyncing] = useState(false);
  const syncAll = async () => {
    setSyncing(true);
    try {
      const { data } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(
        "/stores/sync-all"
      );
      message.success(`同步完成：成功 ${data.ok} / 共 ${data.total} 家`);
      data.results
        .filter((r) => !r.ok)
        .slice(0, 3)
        .forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      onDone();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };
  return { syncing, syncAll };
}

export function TrendChart({ trend }: { trend: AnalyticsTrendPoint[] }) {
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

export type LineSeries = {
  name: string;
  color: string;
  values: number[];
  format?: (value: number) => string;
};

export function LineChart({ labels, series, height = 200 }: { labels: string[]; series: LineSeries[]; height?: number }) {
  const width = 720;
  const pad = 14;
  if (!labels.length) return <Empty description="暂无数据" style={{ padding: 24 }} />;
  const n = labels.length;
  const xs = labels.map((_, i) => (n === 1 ? width / 2 : pad + (i * (width - pad * 2)) / (n - 1)));
  const paths = series.map((s) => {
    const nums = s.values.map((v) => (typeof v === "number" && Number.isFinite(v) ? v : 0));
    const max = Math.max(1, ...nums);
    const pts = nums.map((v, i) => `${xs[i]},${height - pad - (v / max) * (height - pad * 2)}`);
    return { ...s, path: pts.join(" ") };
  });
  return (
    <div>
      <Space style={{ marginBottom: 8 }} wrap>
        {series.map((s) => {
          const latest = s.values.length ? s.values[s.values.length - 1] : 0;
          const latestText =
            latest === null || latest === undefined ? "—" : s.format ? s.format(latest) : latest;
          return (
            <Tag key={s.name} color={s.color}>
              {s.name} · 最新 {latestText}
            </Tag>
          );
        })}
      </Space>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height, display: "block" }}>
        {paths.map((s) => (
          <polyline key={s.name} points={s.path} fill="none" stroke={s.color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
        ))}
        <text x={pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)">
          {labels[0]}
        </text>
        <text x={width - pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)" textAnchor="end">
          {labels[n - 1]}
        </text>
      </svg>
    </div>
  );
}

export function StoreBars({ items }: { items: AnalyticsStoreAgg[] }) {
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
            {fmtMoney(item.sales)} · {item.orders} 单
          </div>
        </div>
      ))}
    </div>
  );
}

export function BucketCard({ title, data }: { title: string; data: AnalyticsSummary["today"] }) {
  return (
    <div
      style={{
        border: "1px solid var(--ops-border)",
        borderRadius: 12,
        padding: "14px 16px",
        height: "100%",
        background: "var(--ops-card-bg)",
      }}
    >
      <Text type="secondary" style={{ fontSize: 12 }}>{title}</Text>
      <div style={{ marginTop: 10, display: "flex", gap: 20, flexWrap: "wrap" }}>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>访客</Text>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{data.visitors}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>销售额</Text>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{fmtMoney(data.sales)}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>订单</Text>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{data.orders}</div>
        </div>
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>转化率</Text>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#1677ff" }}>{fmtPct(data.conversion_rate)}</div>
        </div>
      </div>
    </div>
  );
}

export function ChangeBadge({ change, prevText }: { change: number | null; prevText?: string }) {
  if (change === null || change === undefined) {
    return (
      <div>
        <Tag>无数据</Tag>
        {prevText ? <div style={{ fontSize: 11, color: "rgba(128,128,128,0.75)" }}>{prevText}</div> : null}
      </div>
    );
  }
  const up = change >= 0;
  return (
    <div>
      <span style={{ color: up ? "#52c41a" : "#ff4d4f", fontWeight: 600, whiteSpace: "nowrap" }}>
        {up ? "▲" : "▼"} {Math.abs(change).toFixed(1)}%
      </span>
      {prevText ? <div style={{ fontSize: 11, color: "rgba(128,128,128,0.75)" }}>{prevText}</div> : null}
    </div>
  );
}
export function StoreScopeSelect({
  value,
  onChange,
}: {
  value: number | undefined;
  onChange: (v: number | undefined) => void;
}) {
  const [stores, setStores] = useState<{ id: number; name: string }[]>([]);
  useEffect(() => {
    http
      .get<{ items: { id: number; name: string }[] }>("/stores")
      .then(({ data }) => setStores(data.items))
      .catch(() => setStores([]));
  }, []);
  return (
    <Select
      allowClear
      placeholder="全部店铺"
      style={{ width: 160 }}
      value={value}
      onChange={(v) => onChange(v ?? undefined)}
      options={stores.map((s) => ({ value: s.id, label: s.name }))}
    />
  );
}
