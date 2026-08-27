import { AlertOutlined, BarChartOutlined, ReloadOutlined, SyncOutlined, WarningOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Progress, Row, Segmented, Select, Space, Spin, Table, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "../components/ui/page-header";
import { LineChart, fmtMoney } from "../components/promotions/promotions-ui";
import http, { getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { useStores } from "../lib/store";
import type { PromoData, PromoPlan } from "../types";
import { useNavigate } from "react-router-dom";

const { Text } = Typography;

type PromoAlert = { level?: string; type: string; message: string; plan_id?: number; store_id?: number };

export function PromotionsOverviewPage() {
  const navigate = useNavigate();
  const { currentStore } = useStores();
  const [data, setData] = useState<PromoData | null>(null);
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [alerts, setAlerts] = useState<PromoAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState("");
  const [mode, setMode] = useState<"realtime" | "yesterday" | "7d">("realtime");
  const [scene, setScene] = useState("");

  const scope = currentStore ? `&store_id=${currentStore.id}` : "";
  const modeTitle = mode === "realtime" ? "今日实时" : mode === "yesterday" ? "昨日" : "近七天";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [dataRes, plansRes, alertsRes] = await Promise.all([
        http.get<PromoData>(`/promotions/data?mode=${mode}${scene ? `&scene=${encodeURIComponent(scene)}` : ""}${scope}`),
        http.get<{ items: PromoPlan[] }>(`/promotions/plans?mode=${mode}${scene ? `&scene=${encodeURIComponent(scene)}` : ""}${scope}`),
        http.get<{ items: PromoAlert[] }>(`/promotions/alerts${currentStore ? `?store_id=${currentStore.id}` : ""}`),
      ]);
      setData(dataRes.data);
      setPlans(plansRes.data.items || []);
      setAlerts(alertsRes.data.items || []);
      setUpdatedAt(dayjs().format("MM-DD HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
      setPlans([]);
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id, mode, scene, scope]);

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

  const summary = data?.summary;
  const chartLabels = (data?.trend || []).map((item) => item.label);
  const topPlans = useMemo(() => [...plans].sort((left, right) => right.spend - left.spend).slice(0, 8), [plans]);
  const budgetProgress = useMemo(() => {
    const dailyBudget = plans.reduce((sum, plan) => sum + (plan.day_budget || 0), 0);
    const spend = plans.reduce((sum, plan) => sum + (plan.spend || 0), 0);
    const budgetDays = mode === "7d" ? 7 : 1;
    const budget = dailyBudget * budgetDays;
    const now = new Date();
    const elapsedMinutes = Math.max(30, now.getHours() * 60 + now.getMinutes());
    const forecast = mode === "realtime" ? spend / elapsedMinutes * 1440 : spend;
    return {
      budget,
      spend,
      forecast,
      percent: budget > 0 ? Math.min(100, Math.round((spend / budget) * 100)) : 0,
      forecastPercent: budget > 0 ? Math.round((forecast / budget) * 100) : 0,
    };
  }, [mode, plans]);
  const allAlerts: PromoAlert[] = [...(data?.alerts || []).map((item) => ({ level: "warn", ...item })), ...alerts];
  const sceneOptions = [{ value: "", label: "全部场景" }, ...(data?.scenes || []).map((item) => ({ value: item.scene, label: item.scene_name }))];

  return (
    <div>
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

      <Space wrap style={{ marginBottom: 16 }}>
        <Segmented
          options={[{ label: "今日实时", value: "realtime" }, { label: "昨日", value: "yesterday" }, { label: "近七天", value: "7d" }]}
          value={mode}
          onChange={(value) => setMode(value as typeof mode)}
        />
        <Select value={scene} options={sceneOptions} onChange={setScene} style={{ minWidth: 150 }} aria-label="推广场景" />
        <Text type="secondary" style={{ fontSize: 12 }}>
          数据截至 {data?.last_sync ? dayjs(data.last_sync).format("MM-DD HH:mm") : "—"} · {modeTitle}
        </Text>
      </Space>

      {loading && !data ? <div style={{ textAlign: "center", padding: 80 }}><Spin size="large" /></div> : null}
      {!loading && !data ? <Card variant="borderless"><Empty description="暂无推广数据，请先绑定店铺并同步万相台数据" /></Card> : null}

      {data && summary ? (
        <>
          <Row gutter={[12, 12]}>
            {[
              { label: "今日花费", value: fmtMoney(summary.spend), hint: data.compare.spend == null ? "暂无昨日对比" : `较昨日 ${data.compare.spend >= 0 ? "上涨" : "下降"} ${Math.abs(data.compare.spend)}%` },
              { label: "今日成交", value: fmtMoney(summary.sales), hint: data.compare.sales == null ? "暂无昨日对比" : `较昨日 ${data.compare.sales >= 0 ? "上涨" : "下降"} ${Math.abs(data.compare.sales)}%` },
              { label: "推广 ROI", value: summary.roi.toFixed(2), hint: "平台归因口径" },
              { label: "真实 ROI", value: summary.real_roi?.toFixed(2) ?? "—", hint: "结合店铺成交" },
              { label: "广告占比", value: `${summary.ad_share ?? 0}%`, hint: "推广花费 / 店铺成交" },
              { label: "获客成本", value: summary.cost_per_order ? `¥${summary.cost_per_order.toFixed(2)}` : "—", hint: `${summary.orders.toLocaleString()} 个订单` },
            ].map((item) => (
              <Col xs={12} sm={8} xl={4} key={item.label}>
                <Card variant="borderless" style={{ height: "100%" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
                  <div style={{ fontSize: 22, fontWeight: 700, margin: "5px 0" }}>{item.value}</div>
                  <Text type="secondary" style={{ fontSize: 11 }}>{item.hint}</Text>
                </Card>
              </Col>
            ))}
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={15}>
              <Card variant="borderless" title="花费与成交趋势">
                <LineChart
                  labels={chartLabels}
                  series={[
                    { name: "花费", color: "var(--ops-chart-accent)", values: (data.trend || []).map((item) => item.spend), format: fmtMoney },
                    { name: "成交", color: "var(--ops-success)", values: (data.trend || []).map((item) => item.sales), format: fmtMoney },
                  ]}
                />
              </Card>
            </Col>
            <Col xs={24} lg={9}>
              <Card variant="borderless" title={`${modeTitle}预算进度`} extra={<Tag color={budgetProgress.forecastPercent >= 100 ? "red" : budgetProgress.percent >= 90 ? "orange" : "blue"}>{budgetProgress.percent}%</Tag>}>
                {budgetProgress.budget > 0 ? (
                  <>
                    <Progress percent={budgetProgress.percent} status={budgetProgress.percent >= 100 ? "exception" : "active"} />
                    <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                      <Text>已消耗 ¥{budgetProgress.spend.toLocaleString()} / ¥{budgetProgress.budget.toLocaleString()}</Text>
                      {mode === "realtime" ? <Text type="secondary" style={{ fontSize: 12 }}>按当前消耗速度预计全天 ¥{budgetProgress.forecast.toFixed(0)}（约 {budgetProgress.forecastPercent}%）。</Text> : <Text type="secondary" style={{ fontSize: 12 }}>{mode === "7d" ? "周期预算按当前日预算 × 7 估算，仅作参考。" : "预算进度按当前日预算估算，仅作参考。"}</Text>}
                    </Space>
                  </>
                ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无计划预算" />}
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={10}>
              <Card variant="borderless" title={<Space><AlertOutlined />重点预警</Space>} extra={<Tag color={allAlerts.length ? "red" : "green"}>{allAlerts.length} 条</Tag>}>
                {allAlerts.length ? (
                  <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                    {allAlerts.slice(0, 8).map((item, index) => (
                      <Alert
                        key={`${item.type}-${index}`}
                        type={item.level === "error" ? "error" : "warning"}
                        showIcon
                        title={item.type}
                        description={item.message}
                        action={<Button type="link" size="small" onClick={() => navigate(`/promotions/plans?todo=alerts${item.store_id ? `&store_id=${item.store_id}` : ""}${item.plan_id ? `&plan_id=${item.plan_id}` : ""}`)}>查看计划</Button>}
                      />
                    ))}
                  </Space>
                ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无重点预警" />}
              </Card>
            </Col>
            <Col xs={24} lg={14}>
              <Card variant="borderless" title={<Space><WarningOutlined />计划排行</Space>} extra={<Text type="secondary">按今日花费</Text>}>
                <Table<PromoPlan>
                  rowKey="id"
                  size="small"
                  dataSource={topPlans}
                  pagination={false}
                  locale={{ emptyText: "暂无推广计划" }}
                  onRow={(record) => ({
                    onClick: () => navigate(`/promotions/plans?mode=${mode}${record.scene ? `&scene=${encodeURIComponent(record.scene)}` : ""}${record.store_id ? `&store_id=${record.store_id}` : ""}`),
                    style: { cursor: "pointer" },
                  })}
                  columns={[
                    { title: "计划", dataIndex: "plan_name", ellipsis: true },
                    { title: "场景", dataIndex: "scene_name", width: 90, render: (value: string) => <Tag>{value}</Tag> },
                    { title: "花费", dataIndex: "spend", align: "right", width: 90, render: (value: number) => fmtMoney(value) },
                    { title: "成交", dataIndex: "sales", align: "right", width: 90, render: (value: number) => fmtMoney(value) },
                    { title: "ROI", dataIndex: "roi", align: "right", width: 65, render: (value: number) => <Text type={value >= 2 ? "success" : value > 0 ? "warning" : "danger"}>{value.toFixed(2)}</Text> },
                  ]}
                />
              </Card>
            </Col>
          </Row>
        </>
      ) : null}
    </div>
  );
}
