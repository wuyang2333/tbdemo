import { BarChartOutlined, CloudSyncOutlined, DownOutlined, ReloadOutlined, SyncOutlined, UpOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Progress, Row, Segmented, Select, Space, Spin, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "../components/ui/page-header";
import { MetricRail, WorkspacePage, WorkspaceToolbar } from "../components/ui/workspace-template";
import { LineChart, fmtMoney } from "../components/promotions/promotions-ui";
import { PROMOTION_CHANNELS, PromotionChannelTag, getPromotionChannel, getPromotionChannelName } from "../components/promotions/promotion-channel";
import http, { getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { useStores } from "../lib/store";
import type { PromoData, PromoPlan } from "../types";

const { Text } = Typography;

type PromotionHealthDataset = {
  dataset: string;
  name: string;
  source: string;
  freshness: "fresh" | "stale" | "missing";
  completeness: "complete" | "partial" | "missing";
  completeness_rate: number;
  business_data_at?: string | null;
  last_sync_at?: string | null;
  freshness_basis: "business_data_at" | "last_sync_at";
  retryable: boolean;
  retry_url: string;
  sync: { status: string; ok: number; total: number; failed: number; failures: Array<{ store_name?: string; error: string }> };
};
type PromotionHealth = { status: "healthy" | "degraded" | "unavailable"; trustworthy: boolean; business_data_at?: string | null; last_sync_at?: string | null; datasets: PromotionHealthDataset[]; generated_at: string };

const freshnessLabel = { fresh: "数据及时", stale: "业务数据已过期", missing: "缺少业务数据" } as const;
const datasetFreshnessLabel = (dataset: PromotionHealthDataset) =>
  dataset.business_data_at ? freshnessLabel[dataset.freshness] : dataset.freshness === "fresh" ? "业务时间待确认" : freshnessLabel[dataset.freshness];
const syncStatusLabel: Record<string, string> = { success: "同步成功", partial: "部分同步成功", failed: "同步失败", never: "尚未同步" };
export function PromotionsOverviewPage() {
  const { currentStore } = useStores();
  const [data, setData] = useState<PromoData | null>(null);
  const [overviewPlans, setOverviewPlans] = useState<PromoPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState("");
  const [mode, setMode] = useState<"realtime" | "yesterday" | "7d">("realtime");
  const [channel, setChannel] = useState("");
  const [scene, setScene] = useState("");
  const [health, setHealth] = useState<PromotionHealth | null>(null);
  const [healthExpanded, setHealthExpanded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [retryingDataset, setRetryingDataset] = useState("");

  const scope = currentStore ? `&store_id=${currentStore.id}` : "";
  const modeTitle = mode === "realtime" ? "今日实时" : mode === "yesterday" ? "昨日" : "近七天";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const overviewPlansRequest = http.get<{ items: PromoPlan[] }>(`/promotions/plans?mode=${mode}${scope}`);
      const [dataResult, healthResult, overviewPlansResult] = await Promise.allSettled([
        http.get<PromoData>(`/promotions/data?mode=${mode}${channel ? `&channel=${encodeURIComponent(channel)}` : ""}${scene ? `&scene=${encodeURIComponent(scene)}` : ""}${scope}`),
        http.get<PromotionHealth>(`/promotions/health${currentStore ? `?store_id=${currentStore.id}` : ""}`),
        overviewPlansRequest,
      ]);
      if (dataResult.status === "fulfilled") setData(dataResult.value.data);
      if (overviewPlansResult.status === "fulfilled") setOverviewPlans(overviewPlansResult.value.data.items || []);
      if (healthResult.status === "fulfilled") setHealth(healthResult.value.data);
      const failures = [dataResult, overviewPlansResult].filter((result) => result.status === "rejected");
      setLoadError(failures.length ? `${failures.length} 项推广数据加载失败，当前保留上一次成功结果。` : "");
      setUpdatedAt(dayjs().format("MM-DD HH:mm:ss"));
    } catch (error) {
      setLoadError(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [channel, currentStore?.id, mode, scene, scope]);

  useEffect(() => {
    void load();
  }, [load]);

  useAutoRefresh(() => load());

  const sync = async () => {
    setSyncing(true);
    try {
      const response = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(
        `/promotions/sync?mode=realtime${currentStore ? `&store_id=${currentStore.id}` : ""}`,
      );
      showSyncFeedback("推广数据同步", [{ ok: response.data.ok, total: response.data.total, results: response.data.results }]);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const retryDataset = async (dataset: PromotionHealthDataset) => {
    setRetryingDataset(dataset.dataset);
    try {
      const target = dataset.retry_url.replace(/^\/api/, "");
      await http.post(target);
      message.success(`${dataset.name}已重新同步`);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setRetryingDataset("");
    }
  };

  const summary = data?.summary;
  const chartTrend = (data?.trend || []).filter((item) => {
    if (mode !== "realtime") return true;
    const hour = item.label.match(/^(\d{1,2}):/)?.[1];
    return hour == null || Number(hour) <= new Date().getHours();
  });
  const chartLabels = chartTrend.map((item) => item.label);
  const channelRows = useMemo(() => {
    const result = new Map<string, { channel: string; channel_name: string; spend: number; sales: number; clicks: number; plans: number }>();
    for (const plan of overviewPlans) {
      const key = getPromotionChannel(plan);
      const current = result.get(key) || { channel: key, channel_name: getPromotionChannelName(plan), spend: 0, sales: 0, clicks: 0, plans: 0 };
      current.spend += plan.spend || 0;
      current.sales += plan.sales || 0;
      current.clicks += plan.clicks || 0;
      current.plans += 1;
      result.set(key, current);
    }
    return [...result.values()].sort((left, right) => right.spend - left.spend);
  }, [overviewPlans]);
  const selectedChannelName = channelRows.find((item) => item.channel === channel)?.channel_name;
  const sceneOptions = [{ value: "", label: "全部场景" }, ...(data?.scenes || []).map((item) => ({ value: item.scene, label: item.scene_name }))];

  return (
    <WorkspacePage kind="analysis">
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="推广数据中心"
        description="按渠道、场景和计划下钻查看推广数据，先看清事实，再进入决策和执行。"
        extra={(
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>更新于 {updatedAt || "—"}</Text>
            <Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={() => void sync()}>同步今日数据</Button>
          </Space>
        )}
      />

      {loadError ? <Alert type="warning" showIcon title="部分数据暂时不可用" description={loadError} action={<Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>重新加载</Button>} style={{ marginBottom: 16 }} /> : null}

      {health ? (
        <Card
          variant="borderless"
          title={<Space><CloudSyncOutlined />数据可信度</Space>}
          extra={(
            <Space size={6}>
              <Tag color={health.status === "healthy" ? "green" : health.status === "degraded" ? "orange" : "red"}>{health.status === "healthy" ? "可用于决策" : health.status === "degraded" ? "部分降级" : "数据不可用"}</Tag>
              <Button
                type="text"
                size="small"
                icon={healthExpanded ? <UpOutlined /> : <DownOutlined />}
                aria-expanded={healthExpanded}
                aria-controls="promotion-health-details"
                onClick={() => setHealthExpanded((expanded) => !expanded)}
              >
                {healthExpanded ? "收起" : "展开详情"}
              </Button>
            </Space>
          )}
          className="ops-health-panel"
        >
          {healthExpanded ? (
            <div id="promotion-health-details">
              <Row gutter={[10, 10]}>
                {health.datasets.map((dataset) => (
                  <Col xs={24} md={12} xl={6} key={dataset.dataset}>
                    <div style={{ padding: "12px 14px", minHeight: 128, borderRadius: "var(--ops-radius)", background: "var(--ops-card-bg-2)" }}>
                      <Space style={{ justifyContent: "space-between", width: "100%" }}>
                        <Text strong>{dataset.name}</Text>
                        <Tag color={dataset.business_data_at && dataset.freshness === "fresh" && dataset.completeness === "complete" ? "green" : dataset.freshness === "missing" ? "red" : "orange"}>
                          {datasetFreshnessLabel(dataset)}
                        </Tag>
                      </Space>
                      <Text type="secondary" style={{ display: "block", fontSize: 12, marginTop: 6 }}>{dataset.source}</Text>
                      <Progress percent={dataset.completeness_rate} size="small" status={dataset.completeness === "missing" ? "exception" : "normal"} />
                      <Text type="secondary" style={{ display: "block", fontSize: 11 }}>
                        业务数据截至 {dataset.business_data_at ? dayjs(dataset.business_data_at).format("MM-DD HH:mm") : "暂无"}
                      </Text>
                      <Space style={{ justifyContent: "space-between", width: "100%" }}>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {dataset.last_sync_at ? `最近同步 ${dayjs(dataset.last_sync_at).format("MM-DD HH:mm")}` : "尚未同步"}
                          {dataset.sync.total > 0 ? ` · ${dataset.sync.ok}/${dataset.sync.total} 家成功` : ""}
                        </Text>
                        {dataset.retryable ? <Button type="link" size="small" loading={retryingDataset === dataset.dataset} onClick={() => void retryDataset(dataset)}>重试</Button> : null}
                      </Space>
                      <Text type={dataset.sync.status === "failed" ? "danger" : "secondary"} style={{ display: "block", fontSize: 11 }}>
                        {syncStatusLabel[dataset.sync.status] || "同步状态未知"} · {datasetFreshnessLabel(dataset)}
                      </Text>
                    </div>
                  </Col>
                ))}
              </Row>
            </div>
          ) : null}
        </Card>
      ) : null}

      <WorkspaceToolbar>
        <Segmented
          options={[{ label: "今日实时", value: "realtime" }, { label: "昨日", value: "yesterday" }, { label: "近七天", value: "7d" }]}
          value={mode}
          onChange={(value) => setMode(value as typeof mode)}
        />
        <Select value={scene} options={sceneOptions} onChange={setScene} style={{ minWidth: 150 }} aria-label="推广场景" />
        <Select
          value={channel}
          options={[{ value: "", label: "全部渠道" }, ...PROMOTION_CHANNELS]}
          onChange={(value) => { setChannel(value); setScene(""); }}
          style={{ minWidth: 150 }}
          aria-label="推广渠道"
        />
        <Text className="ops-filter-bar__meta">
          业务数据截至 {data?.business_data_at ? dayjs(data.business_data_at).format("MM-DD HH:mm") : "—"} · 最近同步 {data?.last_sync_at ? dayjs(data.last_sync_at).format("MM-DD HH:mm") : "—"} · {modeTitle}
        </Text>
      </WorkspaceToolbar>

      {loading && !data ? <div style={{ textAlign: "center", padding: 80 }}><Spin size="large" /></div> : null}
      {!loading && !data ? <Card variant="borderless"><Empty description="暂无推广数据，请先绑定店铺并同步万相台数据" /></Card> : null}

      {data && summary ? (
        <>
          <MetricRail items={[
              { label: "今日花费", value: fmtMoney(summary.spend), hint: data.compare.spend == null ? "暂无昨日对比" : `较昨日 ${data.compare.spend >= 0 ? "上涨" : "下降"} ${Math.abs(data.compare.spend)}%` },
              { label: "今日成交", value: fmtMoney(summary.sales), hint: data.compare.sales == null ? "暂无昨日对比" : `较昨日 ${data.compare.sales >= 0 ? "上涨" : "下降"} ${Math.abs(data.compare.sales)}%` },
              { label: "推广 ROI", value: summary.roi.toFixed(2), hint: "平台归因口径" },
              { label: "真实 ROI", value: summary.real_roi?.toFixed(2) ?? "—", hint: "结合店铺成交" },
              { label: "广告占比", value: `${summary.ad_share ?? 0}%`, hint: "推广花费 / 店铺成交" },
              { label: "获客成本", value: summary.cost_per_order ? `¥${summary.cost_per_order.toFixed(2)}` : "—", hint: `${summary.orders.toLocaleString()} 个订单` },
            ]} />

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24}>
              <Card
                variant="borderless"
                title="渠道经营概览"
                extra={<Text type="secondary">点击渠道筛选，再次点击当前渠道可取消</Text>}
              >
                {channelRows.length ? (
                  <Row gutter={[12, 12]}>
                    {channelRows.map((item) => (
                      <Col xs={24} sm={12} xl={6} key={item.channel}>
                        <button
                          type="button"
                          className={channel === item.channel ? "ops-channel-overview-card is-selected" : "ops-channel-overview-card"}
                          aria-pressed={channel === item.channel}
                          aria-label={`查看${item.channel_name}数据`}
                          onClick={() => {
                            setChannel((current) => current === item.channel ? "" : item.channel);
                            setScene("");
                          }}
                        >
                          <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                            <PromotionChannelTag item={item} />
                            <Space style={{ width: "100%", justifyContent: "space-between" }}>
                              <Text strong style={{ fontVariantNumeric: "tabular-nums" }}>{fmtMoney(item.spend)}</Text>
                              <Text type="secondary" style={{ fontSize: 12 }}>{item.plans} 个计划</Text>
                            </Space>
                            <Text type="secondary" style={{ fontSize: 12, fontVariantNumeric: "tabular-nums" }}>成交 {fmtMoney(item.sales)} · ROI {item.spend ? (item.sales / item.spend).toFixed(2) : "—"}</Text>
                          </Space>
                          {channel === item.channel ? <span className="ops-channel-overview-card__state">当前查看</span> : null}
                        </button>
                      </Col>
                    ))}
                  </Row>
                ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前范围暂无渠道数据"><Button onClick={() => void sync()}>同步推广数据</Button></Empty>}
                {channel && selectedChannelName ? <Text type="secondary" className="ops-channel-overview-card__hint">当前下方数据范围：{selectedChannelName}</Text> : null}
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={15}>
              <Card variant="borderless" title="花费与成交趋势">
                <LineChart
                  labels={chartLabels}
                  series={[
                    { name: "花费", color: "var(--ops-chart-accent)", values: chartTrend.map((item) => item.spend), format: fmtMoney },
                    { name: "成交", color: "var(--ops-success)", values: chartTrend.map((item) => item.sales), format: fmtMoney },
                  ]}
                  sharedScale
                />
              </Card>
            </Col>
          </Row>

        </>
      ) : null}
    </WorkspacePage>
  );
}
