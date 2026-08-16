import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type {
  AnalyticsAlert,
  AnalyticsCompareMetric,
  AnalyticsDailyPoint,
  AnalyticsStoreAgg,
  AnalyticsSummary,
  AnalyticsTrendPoint,
} from "../types";

const { Text } = Typography;

const DAY_OPTIONS = [7, 14, 30];

function fmtMoney(value: number): string {
  return `¥${value.toFixed(2)}`;
}

function fmtPct(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatValue(fmt: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (fmt === "money") return fmtMoney(value);
  if (fmt === "pct") return fmtPct(value);
  return `${value}`;
}

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

type LineSeries = {
  name: string;
  color: string;
  values: number[];
  format?: (value: number) => string;
};

function LineChart({ labels, series, height = 200 }: { labels: string[]; series: LineSeries[]; height?: number }) {
  const width = 720;
  const pad = 14;
  if (!labels.length) return <Empty description="暂无数据" style={{ padding: 24 }} />;
  const n = labels.length;
  const xs = labels.map((_, i) => (n === 1 ? width / 2 : pad + (i * (width - pad * 2)) / (n - 1)));
  const paths = series.map((s) => {
    const max = Math.max(1, ...s.values);
    const pts = s.values.map((v, i) => `${xs[i]},${height - pad - (v / max) * (height - pad * 2)}`);
    return { ...s, path: pts.join(" ") };
  });
  return (
    <div>
      <Space style={{ marginBottom: 8 }} wrap>
        {series.map((s) => {
          const latest = s.values.length ? s.values[s.values.length - 1] : 0;
          return (
            <Tag key={s.name} color={s.color}>
              {s.name} · 最新 {s.format ? s.format(latest) : latest}
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
            {fmtMoney(item.sales)} · {item.orders} 单
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
    </Card>
  );
}

function ChangeBadge({ change, prevText }: { change: number | null; prevText?: string }) {
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

function OverviewTab({ summary }: { summary: AnalyticsSummary | null }) {
  if (!summary) return null;
  return (
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

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={15}>
          <Card variant="borderless" title="销售额 / 订单数趋势" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <Space style={{ marginBottom: 8 }}>
              <Tag color="#ff5000">销售额</Tag>
              <Tag color="#1677ff">订单数</Tag>
            </Space>
            <TrendChart trend={summary.trend} />
          </Card>
        </Col>
        <Col xs={24} lg={9}>
          <Card variant="borderless" title="按店铺汇总（累计）" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%" }}>
            <StoreBars items={summary.by_store} />
          </Card>
        </Col>
      </Row>
    </>
  );
}

function TrendTab({ daily, days, onDays }: { daily: AnalyticsDailyPoint[]; days: number; onDays: (d: number) => void }) {
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
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={14}>
        <Card
          variant="borderless"
          title="销售额 / 订单数"
          style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}
          extra={daySwitch(days, onDays)}
        >
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
  );
}

function CompareTab({
  stores,
  days,
  onDays,
}: {
  stores: AnalyticsStoreAgg[];
  days: number;
  onDays: (d: number) => void;
}) {
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
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={10}>
        <Card
          variant="borderless"
          title={`店铺销售额排行（近 ${days} 天）`}
          style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%" }}
          extra={daySwitch(days, onDays)}
        >
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
  );
}

function ConversionTab({ daily }: { daily: AnalyticsDailyPoint[] }) {
  const labels = daily.map((d) => d.date_label);
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card variant="borderless" title="转化率趋势" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
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
  );
}

function YoyTab({ metrics }: { metrics: AnalyticsCompareMetric[] }) {
  const columns: TableColumnsType<AnalyticsCompareMetric> = [
    { title: "指标", dataIndex: "name", width: 110 },
    {
      title: "今日",
      dataIndex: "today",
      width: 140,
      align: "right",
      render: (v: number, row) => (
        <span style={{ fontWeight: 700 }}>{formatValue(row.fmt, v)}</span>
      ),
    },
    {
      title: "较昨日（环比）",
      key: "dod",
      width: 170,
      render: (_, row) => (
        <ChangeBadge change={row.dod.change_pct} prevText={`昨日 ${formatValue(row.fmt, row.dod.prev)}`} />
      ),
    },
    {
      title: "较上周（环比）",
      key: "wow",
      width: 170,
      render: (_, row) => (
        <ChangeBadge change={row.wow.change_pct} prevText={`上周 ${formatValue(row.fmt, row.wow.prev)}`} />
      ),
    },
    {
      title: "较上月（环比）",
      key: "mom",
      width: 170,
      render: (_, row) => (
        <ChangeBadge change={row.mom.change_pct} prevText={`上月 ${formatValue(row.fmt, row.mom.prev)}`} />
      ),
    },
    {
      title: "较去年今日（同比）",
      key: "yoy",
      width: 180,
      render: (_, row) => (
        <ChangeBadge change={row.yoy.change_pct} prevText={`去年 ${formatValue(row.fmt, row.yoy.prev)}`} />
      ),
    },
  ];
  return (
    <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
        说明：环比=与上一周期比，同比=与去年同一天比。数据积累满相应周期后自动显示，未积累显示「无数据」。
      </Text>
      <Table<AnalyticsCompareMetric>
        rowKey="key"
        size="small"
        columns={columns}
        dataSource={metrics}
        pagination={false}
        scroll={{ x: 820 }}
      />
    </Card>
  );
}

function AlertsTab({ alerts, baselineDays }: { alerts: AnalyticsAlert[]; baselineDays: number }) {
  const columns: TableColumnsType<AnalyticsAlert> = [
    { title: "日期", dataIndex: "date_label", width: 90 },
    { title: "店铺", dataIndex: "store_name", width: 160 },
    { title: "指标", dataIndex: "metric", width: 90 },
    {
      title: "波动",
      dataIndex: "change_pct",
      width: 100,
      align: "right",
      render: (v: number) => <ChangeBadge change={v} />,
    },
    {
      title: "等级",
      dataIndex: "level",
      width: 80,
      render: (level: AnalyticsAlert["level"]) =>
        level === "error" ? <Tag color="red">严重</Tag> : level === "warn" ? <Tag color="orange">提醒</Tag> : <Tag>信息</Tag>,
    },
    { title: "说明", dataIndex: "message" },
  ];
  return (
    <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
      <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
        检测规则：按店铺对比每天指标与前 {baselineDays} 天均值——销售额下跌超 30%（严重）/上涨超 60%、订单或访客下跌超 30%、转化率下滑超 20% 时提醒。
      </Text>
      {alerts.length === 0 ? (
        <Empty
          description="目前还没有波动提醒。需要至少积累 3 天数据，系统才会开始自动判断波动。"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          style={{ padding: 24 }}
        />
      ) : (
        <Table<AnalyticsAlert>
          rowKey={(row) => `${row.date}_${row.store_id}_${row.metric}`}
          size="small"
          columns={columns}
          dataSource={alerts}
          pagination={{ pageSize: 10, showTotal: (c) => `共 ${c} 条` }}
          scroll={{ x: 760 }}
        />
      )}
    </Card>
  );
}

function daySwitch(days: number, onDays: (d: number) => void) {
  return (
    <Space>
      {DAY_OPTIONS.map((option) => (
        <Button key={option} size="small" type={days === option ? "primary" : "default"} onClick={() => onDays(option)}>
          {option} 天
        </Button>
      ))}
    </Space>
  );
}

const VALID_TABS = ["overview", "trend", "compare", "conversion", "yoy", "alerts"];

export function AnalyticsPage() {
  const navigate = useNavigate();
  const { tab } = useParams<{ tab?: string }>();
  const validTab = tab && VALID_TABS.includes(tab) ? tab : "overview";
  const [active, setActive] = useState(validTab);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [daily, setDaily] = useState<AnalyticsDailyPoint[]>([]);
  const [stores, setStores] = useState<AnalyticsStoreAgg[]>([]);
  const [compareMetrics, setCompareMetrics] = useState<AnalyticsCompareMetric[]>([]);
  const [alerts, setAlerts] = useState<AnalyticsAlert[]>([]);
  const [baselineDays, setBaselineDays] = useState(7);
  const [trendDays, setTrendDays] = useState(14);
  const [compareDays, setCompareDays] = useState(14);
  const [loading, setLoading] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    setActive(validTab);
  }, [validTab]);
  const [syncing, setSyncing] = useState(false);

  const loadSummary = useCallback(async () => {
    const { data } = await http.get<AnalyticsSummary>("/analytics/summary?days=14");
    setSummary(data);
  }, []);

  const loadDaily = useCallback(async (d: number) => {
    const { data } = await http.get<{ items: AnalyticsDailyPoint[] }>(`/analytics/daily?days=${d}`);
    setDaily(data.items);
  }, []);

  const loadStores = useCallback(async (d: number) => {
    const { data } = await http.get<{ items: AnalyticsStoreAgg[] }>(`/analytics/stores?days=${d}`);
    setStores(data.items);
  }, []);

  const loadCompare = useCallback(async () => {
    const { data } = await http.get<{ metrics: AnalyticsCompareMetric[] }>("/analytics/compare");
    setCompareMetrics(data.metrics);
  }, []);

  const loadAlerts = useCallback(async () => {
    const { data } = await http.get<{ items: AnalyticsAlert[]; baseline_days: number }>("/analytics/alerts");
    setAlerts(data.items);
    setBaselineDays(data.baseline_days);
  }, []);

  const reload = useCallback(async () => {
    if (active === "overview") await loadSummary();
    else if (active === "trend") await loadDaily(trendDays);
    else if (active === "compare") await loadStores(compareDays);
    else if (active === "conversion") await loadDaily(30);
    else if (active === "yoy") await loadCompare();
    else await loadAlerts();
  }, [active, trendDays, compareDays, loadSummary, loadDaily, loadStores, loadCompare, loadAlerts]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    reload()
      .catch((error) => {
        if (!cancelled) message.error(getApiErrorMessage(error));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reload, reloadTick]);

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
      await reload();
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
            <Button icon={<ReloadOutlined />} onClick={() => setReloadTick((t) => t + 1)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      {summary?.last_sync && active === "overview" && (
        <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
          最近同步：{dayjs(summary.last_sync).format("YYYY-MM-DD HH:mm:ss")} · 已配置 {summary.store_count} 家店铺
        </Text>
      )}

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        <Tabs
          activeKey={active}
          onChange={(key) => {
            setActive(String(key));
            navigate(`/analytics/${key}`, { replace: true });
          }}
          items={[
            { key: "overview", label: "总览", children: <OverviewTab summary={summary} /> },
            { key: "trend", label: "趋势分析", children: <TrendTab daily={daily} days={trendDays} onDays={setTrendDays} /> },
            { key: "compare", label: "店铺对比", children: <CompareTab stores={stores} days={compareDays} onDays={setCompareDays} /> },
            { key: "conversion", label: "转化分析", children: <ConversionTab daily={daily} /> },
            { key: "yoy", label: "同比环比", children: <YoyTab metrics={compareMetrics} /> },
            { key: "alerts", label: "异常提醒", children: <AlertsTab alerts={alerts} baselineDays={baselineDays} /> },
          ]}
        />
        {loading && (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        )}
      </Card>
    </div>
  );
}
