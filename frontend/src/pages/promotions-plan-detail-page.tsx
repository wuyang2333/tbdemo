import {
  ArrowLeftOutlined,
  BarChartOutlined,
  BulbOutlined,
  ClockCircleOutlined,
  ExperimentOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, InputNumber, Modal, Result, Row, Segmented, Space, Spin, Tabs, Tag, Timeline, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { LineChart, fmtInt, fmtMoney } from "../components/promotions/promotions-ui";
import { PromotionChannelTag } from "../components/promotions/promotion-channel";
import { PromotionStatusTag } from "../components/promotions/promotion-status";
import { PageHeader } from "../components/ui/page-header";
import { DecisionBand, MetricRail, WorkspacePage, WorkspaceToolbar } from "../components/ui/workspace-template";
import http, { getApiErrorMessage } from "../lib/api";

const { Text, Title } = Typography;

type MetricSet = { spend: number; sales: number; roi: number; clicks: number };
type AdjustmentField = "day_budget" | "bid_value";
type AdjustmentPreview = {
  ok: boolean;
  execute: false;
  plan_id: number;
  field: AdjustmentField;
  old_value: number;
  new_value: number;
  can_execute: boolean;
  block_reason: string;
};
type Workspace = {
  plan: {
    id: number;
    plan_name: string;
    campaign_id: string;
    store_name?: string;
    scene_name?: string;
    channel?: string;
    channel_name?: string;
    status?: string;
    platform_presence?: "active" | "missing";
    platform_last_seen_at?: string | null;
    platform_missing_at?: string | null;
    day_budget?: number;
    bid_type?: string;
    bid_value?: number;
    updated_at?: string;
  };
  metrics: {
    current: MetricSet;
    yesterday: MetricSet;
    seven_days: MetricSet;
    change_vs_yesterday: { spend: number | null; sales: number | null; roi: number | null };
  };
  trend: Array<{ date: string; spend: number; sales: number; roi: number; clicks: number; has_data: boolean }>;
  attribution: Array<{ dimension: string; label: string; status: string; items: Array<Record<string, unknown>>; message: string }>;
  timeline: Array<{
    id: string;
    kind: string;
    title: string;
    summary: string;
    status: string;
    occurred_at?: string;
    before_value?: number | null;
    after_value?: number | null;
    confidence?: string;
    rollback_condition?: string;
  }>;
  observing: Array<{ id: number; action_type: string; status: string; executed_at?: string; observation_hours: number; rollback_condition?: string }>;
  decision_summary: { title: string; reason: string; recommended_action: string; avoid_action: string; review_at: string; rollback_condition: string; source: string };
  execution_check: { action_id: number | null; action_type: string; action_status: string; platform_status: string; platform_submitted_at?: string; platform_checked_at?: string; platform_check_note?: string; can_check: boolean };
  data_quality: { status: "fresh" | "stale" | "missing"; source: string; updated_at?: string; age_hours?: number | null; trend_days_with_data: number; trend_days_total: number };
};

function changeText(value: number | null) {
  if (value == null) return "暂无昨日基线";
  return `较昨日 ${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function changeTone(value: number | null, positiveIsGood = true) {
  if (value == null || value === 0) return undefined;
  return (value > 0) === positiveIsGood ? "var(--ops-up)" : "var(--ops-down)";
}

export function PromotionsPlanDetailPage() {
  const { planId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [days, setDays] = useState(7);
  const [trendMetric, setTrendMetric] = useState<"business" | "roi">("business");
  const [platformChecking, setPlatformChecking] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjustField, setAdjustField] = useState<AdjustmentField>("day_budget");
  const [adjustValue, setAdjustValue] = useState<number | null>(null);
  const [adjustPreview, setAdjustPreview] = useState<AdjustmentPreview | null>(null);
  const [adjustChecking, setAdjustChecking] = useState(false);
  const [adjustExecuting, setAdjustExecuting] = useState(false);

  const load = useCallback(async () => {
    if (!planId || !/^\d+$/.test(planId)) {
      setError("计划编号无效");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await http.get<Workspace>(`/promotions/plans/${planId}/workspace`);
      setData(response.data);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [planId]);

  useEffect(() => { void load(); }, [load]);

  const trend = useMemo(() => (data?.trend || []).slice(-days), [data?.trend, days]);
  const actionDates = useMemo(() => new Set((data?.timeline || []).filter((item) => item.kind === "execution" && item.occurred_at).map((item) => dayjs(item.occurred_at).format("YYYY-MM-DD"))), [data?.timeline]);

  if (loading && !data) {
    return <div style={{ minHeight: "55vh", display: "grid", placeItems: "center" }}><Spin size="large" description="正在整理计划档案" /></div>;
  }
  if (error && !data) {
    return <Result status="warning" title="计划档案暂时无法加载" subTitle={error} extra={<Space><Button onClick={() => navigate("/promotions/plans")}>返回计划列表</Button><Button type="primary" icon={<ReloadOutlined />} onClick={() => void load()}>重新加载</Button></Space>} />;
  }
  if (!data) return null;

  const quality = data.data_quality;
  const latestAdjustment = data.timeline.find((item) => item.kind === "execution" && (item.before_value != null || item.after_value != null));
  const metricCards = [
    { label: "今日/实时花费", value: fmtMoney(data.metrics.current.spend), change: data.metrics.change_vs_yesterday.spend, good: false },
    { label: "今日/实时成交", value: fmtMoney(data.metrics.current.sales), change: data.metrics.change_vs_yesterday.sales, good: true },
    { label: "今日/实时 ROI", value: data.metrics.current.roi.toFixed(2), change: data.metrics.change_vs_yesterday.roi, good: true },
    { label: "今日/实时点击", value: fmtInt(data.metrics.current.clicks), change: null, good: true },
  ];
  const platformMeta: Record<string, { label: string; color: string; detail: string }> = {
    not_submitted: { label: "尚未提交平台", color: "default", detail: "系统只有本地动作记录，尚未确认写入平台。" },
    submitted: { label: "已提交平台", color: "blue", detail: "已记录提交，等待回查平台实际值。" },
    effective: { label: "平台已生效", color: "cyan", detail: "回查确认平台值与目标值一致。" },
    manual_confirmed: { label: "人工确认生效", color: "green", detail: "运营已在万相台核对并确认生效。" },
    failed: { label: "回查失败", color: "red", detail: "平台状态暂时无法确认，需要重新同步或人工核查。" },
  };
  const updatePlatformStatus = async (status: "submitted" | "effective" | "failed" | "manual_confirmed") => {
    if (!data.execution_check.action_id || platformChecking) return;
    setPlatformChecking(true);
    try {
      await http.post(`/promotions/action-records/${data.execution_check.action_id}/platform-status`, { status });
      await load();
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setPlatformChecking(false);
    }
  };
  const adjustmentCurrentValue = Number(data.plan[adjustField] || 0);
  const adjustmentDelta = adjustValue == null ? null : adjustValue - adjustmentCurrentValue;
  const adjustmentPct = adjustmentDelta == null || adjustmentCurrentValue === 0
    ? null
    : adjustmentDelta / adjustmentCurrentValue * 100;
  const adjustmentPctText = adjustmentPct == null
    ? ""
    : Math.abs(adjustmentPct) < 0.1
      ? "幅度 <0.1%"
      : `${adjustmentPct > 0 ? "+" : ""}${adjustmentPct.toFixed(1)}%`;
  const adjustmentLabel = adjustField === "day_budget" ? "日预算" : "出价";
  const adjustmentReady = adjustValue != null && adjustValue >= 0 && Math.abs(adjustValue - adjustmentCurrentValue) >= 0.001;
  const platformMissing = data.plan.platform_presence === "missing" || data.plan.status === "平台已失效";

  const openAdjustment = () => {
    setAdjustField("day_budget");
    setAdjustValue(Number(data.plan.day_budget || 0));
    setAdjustPreview(null);
    setAdjustOpen(true);
  };

  const changeAdjustmentField = (field: AdjustmentField) => {
    setAdjustField(field);
    setAdjustValue(Number(data.plan[field] || 0));
    setAdjustPreview(null);
  };

  const checkAdjustment = async () => {
    if (!adjustmentReady || adjustValue == null) return;
    setAdjustChecking(true);
    try {
      const response = await http.post<AdjustmentPreview>(`/promotions/plans/${data.plan.id}/adjust`, {
        field: adjustField,
        value: adjustValue,
        execute: false,
      });
      setAdjustPreview(response.data);
    } catch (requestError) {
      message.error(getApiErrorMessage(requestError));
    } finally {
      setAdjustChecking(false);
    }
  };

  const executeAdjustment = () => {
    if (!adjustPreview?.can_execute || adjustValue == null || adjustExecuting) return;
    Modal.confirm({
      title: `确认修改${adjustmentLabel}？`,
      content: (
        <Space orientation="vertical" size={6}>
          <Text>计划：{data.plan.plan_name}</Text>
          <Text>{adjustmentLabel}将从 <Text strong>{adjustPreview.old_value}</Text> 调整为 <Text strong>{adjustPreview.new_value}</Text>。</Text>
          <Text type="secondary">确认后将立即写入万相台，并自动建立 48 小时观察任务。</Text>
        </Space>
      ),
      okText: "确认写入",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        setAdjustExecuting(true);
        try {
          await http.post(`/promotions/plans/${data.plan.id}/adjust`, {
            field: adjustField,
            value: adjustValue,
            execute: true,
          }, { timeout: 120000 });
          message.success(`${adjustmentLabel}已写入万相台，观察任务已建立`);
          setAdjustOpen(false);
          setAdjustPreview(null);
          await load();
        } catch (requestError) {
          message.error(getApiErrorMessage(requestError));
          throw requestError;
        } finally {
          setAdjustExecuting(false);
        }
      },
    });
  };

  return (
    <WorkspacePage kind="analysis">
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="PROMOTION PLAN FILE"
        title={data.plan.plan_name || `推广计划 ${data.plan.id}`}
        description={`${data.plan.store_name || "未标注店铺"} · ${data.plan.scene_name || "未标注场景"}`}
        source={quality.source}
        updatedAt={quality.updated_at ? dayjs(quality.updated_at).format("MM-DD HH:mm") : undefined}
        stale={quality.status !== "fresh"}
        extra={<Space wrap><Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/promotions/plans")}>计划列表</Button><Button disabled={platformMissing} onClick={() => navigate(`/promotions/decisions?plan_id=${data.plan.id}`)}>生成 AI 决策</Button><Button disabled={platformMissing} type="primary" icon={<SettingOutlined />} onClick={openAdjustment}>调整计划</Button></Space>}
        stackActions
      />
      <DecisionBand
        eyebrow="当前行动结论"
        title={data.decision_summary.title}
        description={`${data.decision_summary.reason} · 最早复查 ${data.decision_summary.review_at}`}
        action={<Button size="small" onClick={() => navigate(`/promotions/diagnostics?plan_id=${data.plan.id}&channel=${data.plan.channel || ""}`)}>查看诊断</Button>}
        ariaLabel="推广计划当前结论"
      />

      {error ? <Alert type="warning" showIcon title="刷新失败，当前展示上一次成功数据" description={error} action={<Button size="small" onClick={() => void load()}>重试</Button>} style={{ marginBottom: 16 }} /> : null}
      {platformMissing ? <Alert type="info" showIcon title="该计划已不在万相台当前计划列表中" description={`历史数据和操作记录仍保留，但不能再执行启停、预算、出价或 AI 决策。${data.plan.platform_last_seen_at ? ` 最后在平台出现于 ${dayjs(data.plan.platform_last_seen_at).format("YYYY-MM-DD HH:mm")}。` : ""}`} style={{ marginBottom: 16 }} /> : null}
      {quality.status !== "fresh" ? <Alert type="warning" showIcon title={quality.status === "missing" ? "缺少可靠的更新时间" : `计划数据约 ${quality.age_hours ?? "—"} 小时未更新`} description="先同步推广数据，再据此执行调整；历史档案仍可正常查看。" action={<Button size="small" onClick={() => navigate("/promotions/plans")}>前往同步</Button>} style={{ marginBottom: 16 }} /> : null}
      <Card variant="borderless" title={<Space><BulbOutlined />执行要点</Space>} extra={<Tag>{data.decision_summary.source}</Tag>} style={{ marginBottom: 16 }}>
        <Row gutter={[18, 14]}>
          <Col xs={24} md={12}><Text type="secondary">现在应该做</Text><Text strong style={{ display: "block", marginTop: 5 }}>{data.decision_summary.recommended_action}</Text><Text type="secondary" style={{ display: "block", marginTop: 10 }}>最早复查</Text><Text style={{ display: "block", marginTop: 3 }}>{data.decision_summary.review_at}</Text></Col>
          <Col xs={24} md={12}><Text type="secondary">暂时不要做</Text><Text style={{ display: "block", marginTop: 5 }}>{data.decision_summary.avoid_action}</Text><Text type="secondary" style={{ display: "block", marginTop: 10 }}>回退条件</Text><Text type="warning" style={{ display: "block", marginTop: 3 }}>{data.decision_summary.rollback_condition}</Text></Col>
        </Row>
      </Card>

      {data.execution_check.action_id ? <Card variant="borderless" title={<Space><SafetyCertificateOutlined />平台执行回查</Space>} style={{ marginBottom: 16 }}>
        <Row gutter={[16, 12]} align="middle">
          <Col xs={24} lg={8}><Text type="secondary">最近动作</Text><Text strong style={{ display: "block", marginTop: 4 }}>{data.execution_check.action_type || "推广调整"}</Text><Text type="secondary">动作状态：<PromotionStatusTag status={data.execution_check.action_status} /></Text></Col>
          <Col xs={24} lg={8}><Text type="secondary">平台状态</Text><div style={{ margin: "5px 0" }}><Tag color={(platformMeta[data.execution_check.platform_status] || platformMeta.not_submitted).color}>{(platformMeta[data.execution_check.platform_status] || platformMeta.not_submitted).label}</Tag></div><Text type="secondary">{(platformMeta[data.execution_check.platform_status] || platformMeta.not_submitted).detail}</Text></Col>
          <Col xs={24} lg={8}><Space wrap><Button loading={platformChecking} disabled={!data.execution_check.can_check} onClick={() => void updatePlatformStatus("submitted")}>标记已提交</Button><Button loading={platformChecking} disabled={!data.execution_check.can_check} type="primary" onClick={() => void updatePlatformStatus("manual_confirmed")}>人工确认生效</Button><Button loading={platformChecking} disabled={!data.execution_check.can_check} danger onClick={() => void updatePlatformStatus("failed")}>记录回查失败</Button></Space>{!data.execution_check.can_check ? <Text type="warning" style={{ display: "block", marginTop: 8 }}>请先在观察验证中确认动作已经执行。</Text> : null}</Col>
        </Row>
      </Card> : null}

      <Card variant="borderless" style={{ marginBottom: 16 }}>
        <WorkspaceToolbar>
          <PromotionChannelTag item={data.plan} />
          <Tag color={data.plan.status === "在投" ? "green" : "default"}>{platformMissing ? "平台已失效" : data.plan.status || "状态未知"}</Tag>
          <Tag>计划 ID {data.plan.campaign_id}</Tag>
          <Tag color={quality.trend_days_with_data >= 7 ? "blue" : "orange"}>近30天有数据 {quality.trend_days_with_data} 天</Tag>
          {data.observing.length ? <Tag color="gold">{data.observing.length} 个动作观察中</Tag> : <Tag>暂无观察中动作</Tag>}
        </WorkspaceToolbar>
        <MetricRail columns={4} items={metricCards.map((item) => ({ key: item.label, label: item.label, value: item.value, hint: changeText(item.change), tone: changeTone(item.change, item.good) }))} style={{ marginTop: 12 }} />
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={16}>
          <Card variant="borderless" title={<Space><BarChartOutlined />投放趋势</Space>} extra={<Space wrap><Segmented size="small" value={trendMetric} onChange={(value) => setTrendMetric(value as "business" | "roi")} options={[{ label: "花费/成交", value: "business" }, { label: "ROI", value: "roi" }]} /><Segmented size="small" value={days} onChange={(value) => setDays(Number(value))} options={[{ label: "7天", value: 7 }, { label: "30天", value: 30 }]} /></Space>}>
            <LineChart
              labels={trend.map((item) => `${dayjs(item.date).format("MM-DD")}${actionDates.has(item.date) ? " · 调整" : ""}`)}
              series={trendMetric === "business" ? [
                { name: "花费", color: "#1677ff", values: trend.map((item) => item.spend), format: fmtMoney },
                { name: "成交", color: "#52c41a", values: trend.map((item) => item.sales), format: fmtMoney },
              ] : [{ name: "ROI", color: "#722ed1", values: trend.map((item) => item.roi), format: (value) => value.toFixed(2) }]}
              height={240}
              sharedScale
            />
            <Space wrap size={6} style={{ marginTop: 8 }}><Text type="secondary" style={{ fontSize: 12 }}>同一视图使用同一坐标范围，避免独立缩放造成误判。</Text>{[...actionDates].filter((date) => trend.some((item) => item.date === date)).map((date) => <Tag color="blue" key={date}>{dayjs(date).format("MM-DD")} 调整</Tag>)}</Space>
          </Card>
        </Col>
        <Col xs={24} xl={8}>
          <Card variant="borderless" title={<Space><SafetyCertificateOutlined />当前判断边界</Space>} style={{ height: "100%" }}>
            <Space orientation="vertical" size={12} style={{ width: "100%" }}>
              <Alert type={quality.status === "fresh" ? "success" : "warning"} showIcon title={quality.status === "fresh" ? "数据可用于当前判断" : "先刷新，再执行调整"} description={`趋势覆盖 ${quality.trend_days_with_data}/${quality.trend_days_total} 天。`} />
              <div><Text type="secondary">日预算（消耗上限）</Text><Title level={4} style={{ margin: "2px 0" }}>{fmtMoney(data.plan.day_budget || 0)}</Title></div>
              <div><Text type="secondary">当前出价</Text><Title level={4} style={{ margin: "2px 0" }}>{data.plan.bid_value ? `${data.plan.bid_value} ${data.plan.bid_type || ""}` : "—"}</Title></div>
              <Text type="secondary">预算和出价只代表配置，不单独证明计划好坏。调整前仍需结合流量获取、成交效率和观察中的动作。</Text>
            </Space>
          </Card>
        </Col>
      </Row>

      {latestAdjustment ? <Card variant="borderless" style={{ marginTop: 16 }}><Row gutter={[16, 12]} align="middle"><Col xs={24} lg={7}><Text type="secondary">最近一次调整</Text><Title level={5} style={{ margin: "3px 0" }}>{latestAdjustment.title}</Title><Text type="secondary">{latestAdjustment.occurred_at ? dayjs(latestAdjustment.occurred_at).format("YYYY-MM-DD HH:mm") : "时间未记录"}</Text></Col><Col xs={12} lg={5}><Text type="secondary">调整前</Text><div style={{ fontSize: 22, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{latestAdjustment.before_value ?? "—"}</div></Col><Col xs={12} lg={5}><Text type="secondary">调整后</Text><div style={{ fontSize: 22, fontWeight: 700, color: "var(--ops-accent)", fontVariantNumeric: "tabular-nums" }}>{latestAdjustment.after_value ?? "—"}</div></Col><Col xs={24} lg={7}><Text type="secondary">当前结论</Text><div style={{ marginTop: 5 }}><PromotionStatusTag status={latestAdjustment.status} showDescription /></div>{latestAdjustment.rollback_condition ? <Text type="warning" style={{ display: "block", marginTop: 5 }}>回退：{latestAdjustment.rollback_condition}</Text> : null}</Col></Row></Card> : null}

      <Card variant="borderless" title={<Space><ExperimentOutlined />商品与投放归因</Space>} style={{ marginTop: 16 }}>
        <Row gutter={[12, 12]}>
          {data.attribution.map((item) => (
            <Col xs={24} md={12} xl={6} key={item.dimension}>
              <div style={{ padding: 14, borderRadius: "var(--ops-radius)", background: "var(--ops-card-bg-2)", minHeight: 112, opacity: item.status === "pending" ? 0.68 : 1 }}>
                <Space style={{ justifyContent: "space-between", width: "100%" }}><Text strong>{item.label}</Text><Tag color={item.status === "ready" ? "green" : item.status === "empty" ? "default" : "orange"}>{item.status === "ready" ? "已关联" : item.status === "empty" ? "暂无数据" : "待接入"}</Tag></Space>
                <Text type="secondary" style={{ display: "block", marginTop: 8 }}>{item.message}</Text>
                {item.items[0]?.item_title ? <Text style={{ display: "block", marginTop: 6 }} ellipsis={{ tooltip: String(item.items[0].item_title) }}>{String(item.items[0].item_title)}</Text> : null}
                {item.dimension === "item" ? <Text type="secondary" style={{ display: "block", marginTop: 4, fontSize: 12, fontVariantNumeric: "tabular-nums" }}>宝贝 ID {String(item.items[0]?.item_id || "未同步")}</Text> : null}
              </div>
            </Col>
          ))}
        </Row>
      </Card>

      <Card variant="borderless" title={<Space><ClockCircleOutlined />决策、执行与验证档案</Space>} style={{ marginTop: 16 }}>
        <Tabs items={[
          {
            key: "timeline",
            label: `完整时间线 ${data.timeline.length}`,
            children: data.timeline.length ? <Timeline items={data.timeline.map((item) => ({
              color: item.status === "success" ? "green" : item.status === "failed" ? "red" : item.kind === "decision" ? "purple" : "blue",
              content: <Space orientation="vertical" size={2} style={{ width: "100%" }}><Space wrap><Text strong>{item.title}</Text><PromotionStatusTag status={item.status} showDescription /><Text type="secondary">{item.occurred_at ? dayjs(item.occurred_at).format("YYYY-MM-DD HH:mm") : "时间未记录"}</Text></Space><Text>{item.summary}</Text>{item.before_value != null || item.after_value != null ? <Text type="secondary">调整值：{item.before_value ?? "—"} → {item.after_value ?? "—"}</Text> : null}{item.rollback_condition ? <Text type="warning">回退条件：{item.rollback_condition}</Text> : null}</Space>,
            }))} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无决策或调整记录" />,
          },
          {
            key: "observing",
            label: `观察中 ${data.observing.length}`,
            children: data.observing.length ? <Space orientation="vertical" size={10} style={{ width: "100%" }}>{data.observing.map((item) => <Alert key={item.id} type="info" showIcon icon={<BulbOutlined />} title={item.action_type} description={<Space orientation="vertical" size={2}><Text>观察窗口：{item.observation_hours} 小时 · {item.executed_at ? dayjs(item.executed_at).format("MM-DD HH:mm") : "尚未确认执行"}</Text><Text type="secondary">回退条件：{item.rollback_condition || "尚未填写"}</Text><Button type="link" style={{ padding: 0, width: "fit-content" }} onClick={() => navigate(`/promotions/validation?action_id=${item.id}&plan_id=${data.plan.id}`)}>进入观察验证</Button></Space>} />)}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有观察中的动作" />,
          },
        ]} />
      </Card>

      <Modal
        title="调整计划"
        open={adjustOpen}
        onCancel={() => { if (!adjustExecuting) setAdjustOpen(false); }}
        width={560}
        destroyOnHidden
        footer={(
          <Space>
            <Button onClick={() => setAdjustOpen(false)} disabled={adjustExecuting}>取消</Button>
            {adjustPreview?.can_execute ? (
              <Button type="primary" danger loading={adjustExecuting} onClick={executeAdjustment}>确认写入万相台</Button>
            ) : (
              <Button type="primary" loading={adjustChecking} disabled={!adjustmentReady || quality.status !== "fresh"} onClick={() => void checkAdjustment()}>检查调整</Button>
            )}
          </Space>
        )}
      >
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <div style={{ paddingBottom: 14, borderBottom: "1px solid var(--ops-border)" }}>
            <Text strong style={{ display: "block", fontSize: 16 }}>{data.plan.plan_name}</Text>
            <Space wrap size={6} style={{ marginTop: 7 }}>
              <PromotionChannelTag item={data.plan} />
              <Tag color={data.plan.status === "在投" ? "green" : "default"}>{data.plan.status || "状态未知"}</Tag>
              <Text type="secondary">平台计划 ID {data.plan.campaign_id}</Text>
            </Space>
          </div>

          {data.observing.length ? <Alert type="warning" showIcon title={`已有 ${data.observing.length} 个动作正在观察`} description="再次调整会改变验证条件。确认确有必要后再继续，并在复盘时注明干扰因素。" /> : null}
          {quality.status !== "fresh" ? <Alert type="warning" showIcon title="当前数据不能用于执行" description="请先返回计划执行中心同步最新数据，再进行调整。" /> : null}

          <div>
            <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>调整项目</Text>
            <Segmented
              block
              value={adjustField}
              options={[{ label: "日预算", value: "day_budget" }, { label: "出价", value: "bid_value" }]}
              onChange={(value) => changeAdjustmentField(value as AdjustmentField)}
            />
          </div>

          <Row gutter={16} align="bottom">
            <Col span={10}>
              <Text type="secondary" style={{ display: "block", marginBottom: 7 }}>当前{adjustmentLabel}</Text>
              <div style={{ minHeight: 40, display: "flex", alignItems: "center", fontSize: 24, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{adjustmentCurrentValue}</div>
            </Col>
            <Col span={14}>
              <Text type="secondary" style={{ display: "block", marginBottom: 7 }}>目标{adjustmentLabel}</Text>
              <InputNumber
                aria-label={`目标${adjustmentLabel}`}
                value={adjustValue}
                min={0}
                precision={2}
                style={{ width: "100%" }}
                onChange={(value) => { setAdjustValue(value); setAdjustPreview(null); }}
              />
            </Col>
          </Row>

          {adjustmentDelta != null && adjustmentReady ? (
            <Text type={adjustmentDelta > 0 ? "warning" : "success"}>
              变化 {adjustmentDelta > 0 ? "+" : ""}{adjustmentDelta.toFixed(2)}{adjustmentPctText ? `（${adjustmentPctText}）` : ""}
            </Text>
          ) : <Text type="secondary">输入与当前值不同的目标值后，先检查再写入平台。</Text>}

          {adjustPreview ? (
            <Alert
              type={adjustPreview.can_execute ? "success" : "warning"}
              showIcon
              title={adjustPreview.can_execute ? "检查通过，可以写入" : "当前不能执行"}
              description={adjustPreview.can_execute ? "已核对计划身份、最新数据和平台写入条件。" : adjustPreview.block_reason}
            />
          ) : null}

          <Text type="secondary" style={{ fontSize: 12 }}>写入成功后，系统会保留调整前值作为回退依据，并从当前时间开始观察 48 小时。</Text>
        </Space>
      </Modal>
    </WorkspacePage>
  );
}
