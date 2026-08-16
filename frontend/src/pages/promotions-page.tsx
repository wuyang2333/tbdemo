import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Segmented,
  Select,
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
import type { PromoData, PromoPlan, PromoSceneAgg } from "../types";

const { Text } = Typography;

const MODE_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "昨天", value: "yesterday" },
  { label: "近七天", value: "7d" },
];
const SCENE_OPTIONS = [
  { value: "", label: "全部场景" },
  { value: "wholesite", label: "货品全站推广" },
  { value: "keyword", label: "关键词推广" },
  { value: "crowd", label: "人群推广" },
];
const TAG_OPTIONS = [
  { value: "", label: "无标记" },
  { value: "重点", label: "重点关注" },
  { value: "优化", label: "待优化" },
  { value: "观察", label: "暂停观察" },
];

function fmtMoney(value: number): string {
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtInt(value: number): string {
  return value.toLocaleString("zh-CN");
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
  if (!labels.length) return <Empty description="暂无数据，先点「同步数据」" style={{ padding: 24 }} />;
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

function SceneTable({ scenes, summary }: { scenes: PromoSceneAgg[]; summary: PromoSceneAgg }) {
  const columns: TableColumnsType<PromoSceneAgg> = [
    { title: "场景", dataIndex: "scene_name", width: 130 },
    { title: "展现量", dataIndex: "impressions", align: "right", render: (v: number) => fmtInt(v) },
    { title: "点击量", dataIndex: "clicks", align: "right", render: (v: number) => fmtInt(v) },
    { title: "点击率", dataIndex: "ctr", align: "right", render: (v: number) => `${v.toFixed(2)}%` },
    { title: "花费", dataIndex: "spend", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "成交金额", dataIndex: "sales", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "ROI", dataIndex: "roi", align: "right", render: (v: number) => v.toFixed(2) },
    { title: "加购", dataIndex: "add_cart", align: "right", render: (v: number) => fmtInt(v) },
  ];
  const dataSource = [
    ...scenes,
    { scene: "", scene_name: "合计", impressions: summary.impressions, clicks: summary.clicks, ctr: summary.ctr, spend: summary.spend, sales: summary.sales, roi: summary.roi, orders: summary.orders, add_cart: summary.add_cart },
  ];
  return (
    <Table<PromoSceneAgg>
      rowKey={(row) => row.scene || "total"}
      size="small"
      columns={columns}
      dataSource={dataSource}
      pagination={false}
      scroll={{ x: 760 }}
      rowClassName={(row) => (row.scene === "" ? "ant-table-row-selected" : "")}
    />
  );
}

function PromoDataTab({
  data,
  mode,
  onMode,
  syncing,
  onSync,
}: {
  data: PromoData | null;
  mode: string;
  onMode: (m: string) => void;
  syncing: boolean;
  onSync: () => void;
}) {
  const labels = (data?.trend ?? []).map((p) => p.label);
  const trend = data?.trend ?? [];
  const isRealtime = data?.mode === "realtime";
  const periodTitle = mode === "realtime" ? "今日实时" : mode === "yesterday" ? "昨天" : "近七天";
  return (
    <>
      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented options={MODE_OPTIONS} value={mode} onChange={(value) => onMode(String(value))} />
        <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={onSync}>
          同步{periodTitle}数据
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          {data
            ? `${periodTitle} · 已绑定 ${data.bound_stores} 家店铺 · 最近同步 ${data.last_sync ? dayjs(data.last_sync).format("MM-DD HH:mm") : "—"}`
            : "先同步数据"}
        </Text>
      </Space>
      {!data ? (
        <Empty description={`暂无${periodTitle}数据，点「同步${periodTitle}数据」从万相台自动抓取`} style={{ padding: 24 }} />
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title={isRealtime ? "今日实时花费" : "区间花费"} value={data.summary.spend} precision={2} prefix="¥" />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title={isRealtime ? "今日实时成交" : "成交金额"} value={data.summary.sales} precision={2} prefix="¥" />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="ROI" value={data.summary.roi} precision={2} valueStyle={{ color: "#1677ff" }} />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="点击量" value={data.summary.clicks} />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="点击率" value={data.summary.ctr} precision={2} suffix="%" />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="成交订单" value={data.summary.orders} />
              </Card>
            </Col>
          </Row>

          {isRealtime ? (
            <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
                实时数据为全渠道合计，按小时更新（00:00 起到当前小时）。
              </Text>
              <Row gutter={[16, 16]}>
                <Col xs={24} lg={14}>
                  <Card variant="borderless" title="今日分时：花费 / 成交金额" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
                    <LineChart
                      labels={labels}
                      series={[
                        { name: "花费", color: "#ff5000", values: trend.map((p) => p.spend), format: fmtMoney },
                        { name: "成交金额", color: "#52c41a", values: trend.map((p) => p.sales), format: fmtMoney },
                      ]}
                    />
                  </Card>
                </Col>
                <Col xs={24} lg={10}>
                  <Card variant="borderless" title="今日分时 ROI" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                    <LineChart
                      labels={labels}
                      series={[{ name: "ROI", color: "#1677ff", values: trend.map((p) => p.roi) }]}
                      height={170}
                    />
                  </Card>
                </Col>
              </Row>
            </Card>
          ) : (
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={10}>
                <Card variant="borderless" title={`各推广场景 · ${periodTitle}`} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                  <SceneTable scenes={data.scenes} summary={data.summary} />
                </Card>
              </Col>
              <Col xs={24} lg={14}>
                <Card variant="borderless" title="花费 / 成交金额 趋势" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
                  <LineChart
                    labels={labels}
                    series={[
                      { name: "花费", color: "#ff5000", values: trend.map((p) => p.spend), format: fmtMoney },
                      { name: "成交金额", color: "#52c41a", values: trend.map((p) => p.sales), format: fmtMoney },
                    ]}
                  />
                </Card>
                <Card variant="borderless" title="ROI 趋势" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                  <LineChart
                    labels={labels}
                    series={[{ name: "ROI", color: "#1677ff", values: trend.map((p) => p.roi) }]}
                    height={160}
                  />
                </Card>
              </Col>
            </Row>
          )}
        </>
      )}
    </>
  );
}

function PlanNoteCell({ plan, onSaved }: { plan: PromoPlan; onSaved: () => void }) {
  const [value, setValue] = useState(plan.note);
  useEffect(() => setValue(plan.note), [plan.note]);
  const save = async (next: string) => {
    if (next === plan.note) return;
    try {
      await http.put(`/promotions/plans/${plan.id}`, { note: next, tag: plan.tag });
      message.success("备注已保存");
      onSaved();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };
  return (
    <Input
      size="small"
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onBlur={() => save(value)}
      placeholder="写备注，回车/失焦保存"
    />
  );
}

function PlanTagCell({ plan, onSaved }: { plan: PromoPlan; onSaved: () => void }) {
  const [tag, setTag] = useState(plan.tag);
  useEffect(() => setTag(plan.tag), [plan.tag]);
  const save = async (next: string) => {
    setTag(next);
    try {
      await http.put(`/promotions/plans/${plan.id}`, { note: plan.note, tag: next });
      onSaved();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };
  return <Select size="small" style={{ width: 110 }} value={tag} options={TAG_OPTIONS} onChange={save} />;
}

function PromoPlansTab({
  plans,
  scene,
  onScene,
  syncing,
  onSync,
  onReload,
}: {
  plans: PromoPlan[];
  scene: string;
  onScene: (v: string) => void;
  syncing: boolean;
  onSync: () => void;
  onReload: () => void;
}) {
  const columns: TableColumnsType<PromoPlan> = [
    { title: "场景", dataIndex: "scene_name", width: 120 },
    { title: "计划名", dataIndex: "plan_name", width: 200, ellipsis: true },
    {
      title: "状态",
      dataIndex: "status",
      width: 80,
      render: (status: string) => (status === "在投" ? <Tag color="green">在投</Tag> : <Tag>暂停</Tag>),
    },
    { title: "日预算", dataIndex: "day_budget", align: "right", width: 90, render: (v: number) => (v ? fmtMoney(v) : "—") },
    {
      title: "出价",
      key: "bid",
      width: 110,
      render: (_, row) => (row.bid_value ? `${row.bid_value}${row.bid_type === "roi" ? " ROI" : ""}` : row.bid_type || "—"),
    },
    { title: "花费", dataIndex: "spend", align: "right", width: 110, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "成交", dataIndex: "sales", align: "right", width: 120, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "ROI", dataIndex: "roi", align: "right", width: 80, render: (v: number) => (v ? v.toFixed(2) : "—") },
    { title: "点击", dataIndex: "clicks", align: "right", width: 90, render: (v: number) => (v ? fmtInt(v) : "—") },
    { title: "标记", key: "tag", width: 130, render: (_, row) => <PlanTagCell plan={row} onSaved={onReload} /> },
    { title: "备注", key: "note", width: 200, render: (_, row) => <PlanNoteCell plan={row} onSaved={onReload} /> },
  ];
  return (
    <>
      <Space style={{ marginBottom: 12 }} wrap>
        <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={onSync}>
          同步推广计划
        </Button>
        <Select style={{ width: 150 }} value={scene} onChange={onScene} options={SCENE_OPTIONS} />
        <Text type="secondary" style={{ fontSize: 12 }}>共 {plans.length} 个计划（数据来自万相台）</Text>
      </Space>
      <Table<PromoPlan>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={plans}
        pagination={{ pageSize: 20, showTotal: (c) => `共 ${c} 个计划` }}
        scroll={{ x: 1250 }}
      />
    </>
  );
}

const VALID_TABS = ["data", "plans"];

export function PromotionsPage() {
  const navigate = useNavigate();
  const { tab } = useParams<{ tab?: string }>();
  const validTab = tab && VALID_TABS.includes(tab) ? tab : "data";
  const [active, setActive] = useState(validTab);
  const [data, setData] = useState<PromoData | null>(null);
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [mode, setMode] = useState("realtime");
  const [scene, setScene] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    setActive(validTab);
  }, [validTab]);

  const loadData = useCallback(async (m: string) => {
    const { data: res } = await http.get<PromoData>(`/promotions/data?mode=${encodeURIComponent(m)}`);
    setData(res);
  }, []);

  const loadPlans = useCallback(async (sc: string) => {
    const { data: res } = await http.get<{ items: PromoPlan[] }>(`/promotions/plans?scene=${encodeURIComponent(sc)}`);
    setPlans(res.items);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const run = async () => {
      try {
        if (active === "data") await loadData(mode);
        else await loadPlans(scene);
      } catch (error) {
        if (!cancelled) message.error(getApiErrorMessage(error));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [active, mode, scene, reloadTick, loadData, loadPlans]);

  const syncData = async () => {
    setSyncing(true);
    try {
      const { data: res } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(
        `/promotions/sync?mode=${encodeURIComponent(mode)}`
      );
      message.success(`同步完成：成功 ${res.ok} / 共 ${res.total} 家`);
      res.results.filter((r) => !r.ok).slice(0, 3).forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await loadData(mode);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const syncPlans = async () => {
    setSyncing(true);
    try {
      const { data: res } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/promotions/sync-plans");
      message.success(`计划同步完成：成功 ${res.ok} / 共 ${res.total} 家`);
      res.results.filter((r) => !r.ok).slice(0, 3).forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await loadPlans(scene);
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
        eyebrow="推广管理"
        title="推广管理"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => setReloadTick((t) => t + 1)}>
              刷新
            </Button>
          </Space>
        }
      />
      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        <Tabs
          activeKey={active}
          onChange={(key) => {
            setActive(String(key));
            navigate(`/promotions/${key}`, { replace: true });
          }}
          items={[
            {
              key: "data",
              label: "推广数据",
              children: <PromoDataTab data={data} mode={mode} onMode={setMode} syncing={syncing && active === "data"} onSync={syncData} />,
            },
            {
              key: "plans",
              label: "推广计划",
              children: (
                <PromoPlansTab
                  plans={plans}
                  scene={scene}
                  onScene={setScene}
                  syncing={syncing && active === "plans"}
                  onSync={syncPlans}
                  onReload={() => loadPlans(scene)}
                />
              ),
            },
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
