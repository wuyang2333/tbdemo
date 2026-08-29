import {
  AlertOutlined,
  ArrowRightOutlined,
  ClockCircleOutlined,
  CopyOutlined,
  ExclamationCircleOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Timeline,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { fmtMoney } from "../components/promotions/promotions-ui";
import { PROMOTION_CHANNELS, PromotionChannelTag } from "../components/promotions/promotion-channel";
import { PageHeader } from "../components/ui/page-header";
import { MetricRail, WorkspacePage, WorkspaceToolbar } from "../components/ui/workspace-template";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";

const { Text } = Typography;

type Priority = "urgent" | "high" | "medium";
type QueueItem = {
  id: string;
  kind: string;
  source_id: number;
  priority: Priority;
  title: string;
  reason: string;
  plan_id: number;
  plan_name: string;
  scene_name: string;
  channel?: string;
  channel_name?: string;
  store_id: number;
  store_name: string;
  source_path: string;
  due_at?: string | null;
  updated_at?: string;
};

type PatrolStatus = "pending" | "completed" | "skipped";
type PatrolItem = QueueItem & {
  patrol_type: "diagnosis" | "decision" | "execution" | "stop_loss" | "scale" | "observing" | "verification" | "insufficient";
};
type PatrolRecord = {
  status: PatrolStatus;
  reason?: string;
  updated_at: string;
};
type PatrolState = {
  date: string;
  current_id?: string;
  records: Record<string, PatrolRecord>;
};

type CockpitCase = {
  plan_id: number;
  plan_name: string;
  store_id: number;
  store_name: string;
  scene_name: string;
  channel?: string;
  channel_name?: string;
  status: string;
  spend: number;
  sales: number;
  roi: number;
  risk_level: Priority | "normal";
  chain_stage: "decision" | "execution" | "validation" | "rollback" | "completed";
  open_work_count: number;
  decision_count: number;
  action_count: number;
  verified_count: number;
  data_status: "fresh" | "stale" | "missing";
  data_updated_at?: string;
  latest_activity_at?: string;
};

type CockpitData = {
  summary: {
    total: number;
    urgent: number;
    high: number;
    medium: number;
    pending_execution: number;
    pending_verification: number;
    needs_rollback: number;
    diagnostic_count: number;
    scale_opportunities?: number;
    yesterday_success?: number;
    yesterday_failed?: number;
  };
  queue: QueueItem[];
  cases: CockpitCase[];
  today_ai_actions?: Array<{ title: string; reason: string; source_path: string; plan_id?: number; plan_name?: string }>;
  data_health: {
    visible_plan_count: number;
    active_case_count: number;
    stale_plan_count: number;
    missing_due_count: number;
    low_confidence_count: number;
    last_plan_update?: string;
  };
  generated_at?: string;
};

type PlanDetail = {
  plan: Record<string, unknown> & {
    id: number;
    plan_name: string;
    store_name?: string;
    channel?: string;
    channel_name?: string;
    scene?: string;
    scene_name?: string;
    status?: string;
    spend?: number;
    sales?: number;
    roi?: number;
    updated_at?: string;
  };
  decisions: Array<Record<string, unknown> & { id: number; selected_tier?: string; feedback_status?: string; workflow_status?: string; updated_at?: string }>;
  actions: Array<Record<string, unknown> & { id: number; action_type?: string; status?: string; result?: string; confidence?: string; executed_at?: string; verified_at?: string }>;
  timeline: Array<{ id: string; kind: string; title: string; summary: string; status: string; occurred_at?: string }>;
};

const priorityMeta: Record<Priority | "normal", { label: string; color: string }> = {
  urgent: { label: "紧急", color: "red" },
  high: { label: "优先", color: "orange" },
  medium: { label: "关注", color: "gold" },
  normal: { label: "正常", color: "green" },
};

const kindLabels: Record<string, string> = {
  diagnostic: "异常诊断",
  decision_action: "建立动作",
  pending_execution: "待执行",
  verification_overdue: "验证逾期",
  verification_due_soon: "即将验证",
  pending_verification: "待验证",
  needs_rollback: "需回退",
};

const stageMeta: Record<CockpitCase["chain_stage"], { label: string; color: string }> = {
  decision: { label: "决策确认", color: "purple" },
  execution: { label: "执行中", color: "gold" },
  validation: { label: "观察验证", color: "blue" },
  rollback: { label: "回退评估", color: "red" },
  completed: { label: "已闭环", color: "green" },
};

const patrolTypeMeta: Record<PatrolItem["patrol_type"], { label: string; color: string }> = {
  diagnosis: { label: "异常诊断", color: "red" },
  decision: { label: "确认决策", color: "purple" },
  execution: { label: "待平台执行", color: "gold" },
  stop_loss: { label: "止损", color: "red" },
  scale: { label: "放量", color: "green" },
  observing: { label: "等待观察", color: "blue" },
  verification: { label: "到期验证", color: "orange" },
  insufficient: { label: "数据不可判断", color: "default" },
};

function patrolType(item: QueueItem): PatrolItem["patrol_type"] {
  const text = `${item.kind} ${item.title} ${item.reason}`;
  if (item.kind === "pending_execution") return "execution";
  if (["verification_overdue", "verification_due_soon", "pending_verification"].includes(item.kind)) return "verification";
  if (item.kind === "diagnostic") return "diagnosis";
  if (/数据不足|不可判断|缺少|未同步|过期/.test(text)) return "insufficient";
  if (item.kind === "decision_action") return /放量|高 ROI|增长/.test(text) ? "scale" : "decision";
  if (/回退|止损|暂停|低效|低 ROI|风险/.test(text)) return "stop_loss";
  if (/放量|高 ROI|增长/.test(text)) return "scale";
  return "observing";
}

function withCockpitContext(item: PatrolItem, cockpitChannel = ""): string {
  const sourcePath = item.kind === "pending_execution"
    ? `/promotions/validation?action_id=${item.source_id}&plan_id=${item.plan_id}`
    : item.source_path;
  const [path, query = ""] = sourcePath.split("?");
  const params = new URLSearchParams(query);
  params.set("from", "cockpit");
  params.set("patrol_id", item.id);
  params.set("patrol_date", dayjs().format("YYYY-MM-DD"));
  params.set("patrol_channel", cockpitChannel || "all");
  return `${path}?${params.toString()}`;
}

function formatTime(value?: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("MM-DD HH:mm") : "—";
}

function statusText(value?: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  const labels: Record<string, string> = {
    selected: "已确认",
    deferred: "暂缓观察",
    planned: "待执行",
    executed: "已执行",
    observing: "观察中",
    verified: "已验证",
    success: "改善",
    partial: "部分改善",
    failed: "恶化",
    insufficient: "数据不足",
    executing: "待执行",
    pending_verification: "待验证",
    needs_rollback: "需回退",
    completed: "已完成",
    adopted: "采纳",
    modified: "修改后采纳",
    rejected: "拒绝",
    pending: "待审批",
    approved: "已通过",
    not_required: "无需审批",
  };
  return labels[value] || value;
}

function feedbackStatusText(value?: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  return ({ adopted: "采纳", modified: "修改后采纳", rejected: "拒绝", insufficient: "暂不调整" } as Record<string, string>)[value] || value;
}

function StatisticCard({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return <Card size="small" style={{ height: "100%" }}><Text type="secondary" style={{ fontSize: 12 }}>{label}</Text><div style={{ color: tone, fontSize: 24, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{value}</div></Card>;
}

export function PromotionsCockpitPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { currentStore } = useStores();
  const targetPlanId = Number(searchParams.get("plan_id")) || null;
  const [data, setData] = useState<CockpitData | null>(null);
  const [loading, setLoading] = useState(true);
  const [priority, setPriority] = useState<"all" | Priority>("all");
  const [kind, setKind] = useState("all");
  const [channel, setChannel] = useState("");
  const [detail, setDetail] = useState<PlanDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailPlanId, setDetailPlanId] = useState<number | null>(null);
  const [targetError, setTargetError] = useState("");
  const [openedTargetScope, setOpenedTargetScope] = useState("");
  const [patrolState, setPatrolState] = useState<PatrolState>({ date: dayjs().format("YYYY-MM-DD"), records: {} });
  const [skipOpen, setSkipOpen] = useState(false);
  const [skipReason, setSkipReason] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (currentStore) params.set("store_id", String(currentStore.id));
      if (channel) params.set("channel", channel);
      const response = await http.get<CockpitData>(`/promotions/cockpit${params.size ? `?${params.toString()}` : ""}`);
      setData(response.data);
    } catch (error) {
      setData(null);
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [channel, currentStore?.id]);

  useEffect(() => { void load(); }, [load]);

  const openDetail = async (planId: number) => {
    setDetailPlanId(planId);
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const response = await http.get<PlanDetail>(`/promotions/cockpit/plans/${planId}${currentStore ? `?store_id=${currentStore.id}` : ""}`);
      setDetail(response.data);
      setTargetError("");
    } catch (error) {
      if (planId === targetPlanId) setTargetError("目标计划不存在或不在当前店铺范围");
      message.error(getApiErrorMessage(error));
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (!targetPlanId || !data) return;
    const scopeKey = `${currentStore?.id || "all"}:${targetPlanId}`;
    if (openedTargetScope === scopeKey) return;
    setOpenedTargetScope(scopeKey);
    void openDetail(targetPlanId);
  }, [currentStore?.id, data, openedTargetScope, targetPlanId]);

  const patrolStorageKey = `promotions-patrol:${dayjs().format("YYYY-MM-DD")}:${currentStore?.id || "all"}:${channel || "all"}`;

  useEffect(() => {
    try {
      const raw = localStorage.getItem(patrolStorageKey);
      setPatrolState(raw ? JSON.parse(raw) as PatrolState : { date: dayjs().format("YYYY-MM-DD"), records: {} });
    } catch {
      setPatrolState({ date: dayjs().format("YYYY-MM-DD"), records: {} });
    }
  }, [patrolStorageKey]);

  const savePatrolState = (next: PatrolState) => {
    setPatrolState(next);
    localStorage.setItem(patrolStorageKey, JSON.stringify(next));
  };

  const filteredQueue = useMemo(() => (data?.queue || []).filter((item) => (
    !patrolState.records[item.id]
    && (priority === "all" || item.priority === priority)
    && (kind === "all" || item.kind === kind)
  )), [data?.queue, kind, patrolState.records, priority]);

  const kindOptions = useMemo(() => {
    const values = Array.from(new Set((data?.queue || []).map((item) => item.kind)));
    return [{ value: "all", label: "全部类型" }, ...values.map((value) => ({ value, label: kindLabels[value] || value }))];
  }, [data?.queue]);

  const patrolQueue = useMemo<PatrolItem[]>(() => {
    const queue = [...(data?.queue || [])];
    const queuePlans = new Set(queue.map((item) => `${item.kind}:${item.plan_id}`));
    for (const item of data?.cases || []) {
      if (item.chain_stage === "validation" && !queue.some((candidate) => candidate.plan_id === item.plan_id && ["verification_overdue", "verification_due_soon", "pending_verification"].includes(candidate.kind))) {
        queue.push({ id: `observing:${item.plan_id}`, kind: "observing", source_id: item.plan_id, priority: "medium", title: `等待观察：${item.plan_name}`, reason: "观察窗口尚未到期，保持单一变量并确认数据持续更新。", plan_id: item.plan_id, plan_name: item.plan_name, scene_name: item.scene_name, channel: item.channel, channel_name: item.channel_name, store_id: item.store_id, store_name: item.store_name, source_path: `/promotions/validation?plan_id=${item.plan_id}`, due_at: item.latest_activity_at });
      }
      if (item.data_status !== "fresh" && !queuePlans.has(`data_health:${item.plan_id}`)) {
        queue.push({ id: `data-health:${item.plan_id}`, kind: "data_health", source_id: item.plan_id, priority: item.data_status === "missing" ? "high" : "medium", title: `数据不可判断：${item.plan_name}`, reason: item.data_status === "missing" ? "计划缺少更新时间，不能可靠判断调整方向。" : "计划数据超过 24 小时未更新，先同步后再判断。", plan_id: item.plan_id, plan_name: item.plan_name, scene_name: item.scene_name, channel: item.channel, channel_name: item.channel_name, store_id: item.store_id, store_name: item.store_name, source_path: `/promotions/plans?plan_id=${item.plan_id}`, updated_at: item.data_updated_at });
      }
    }
    for (const [index, action] of (data?.today_ai_actions || []).entries()) {
      if (!action.plan_id || !/放量|增长|高 ROI/.test(`${action.title} ${action.reason}`) || queue.some((item) => item.plan_id === action.plan_id && patrolType(item) === "scale")) continue;
      const plan = data?.cases.find((item) => item.plan_id === action.plan_id);
      queue.push({ id: `ai-scale:${action.plan_id}:${index}`, kind: "decision_action", source_id: action.plan_id, priority: "medium", title: action.title, reason: action.reason, plan_id: action.plan_id, plan_name: action.plan_name || plan?.plan_name || `计划 ${action.plan_id}`, scene_name: plan?.scene_name || "未标注场景", channel: plan?.channel, channel_name: plan?.channel_name, store_id: plan?.store_id || 0, store_name: plan?.store_name || "", source_path: action.source_path });
    }
    return queue.map((item) => ({ ...item, patrol_type: patrolType(item) })).sort((left, right) => {
    const priorityOrder = { urgent: 0, high: 1, medium: 2 };
    return priorityOrder[left.priority] - priorityOrder[right.priority] || String(left.due_at || "9999").localeCompare(String(right.due_at || "9999"));
    });
  }, [data]);

  const pendingPatrol = useMemo(() => patrolQueue.filter((item) => !patrolState.records[item.id]), [patrolQueue, patrolState.records]);
  const currentPatrol = useMemo(() => pendingPatrol.find((item) => item.id === patrolState.current_id) || pendingPatrol[0] || null, [patrolState.current_id, pendingPatrol]);
  const currentCase = currentPatrol ? data?.cases.find((item) => item.plan_id === currentPatrol.plan_id) : null;
  const completedPatrol = patrolQueue.filter((item) => patrolState.records[item.id]?.status === "completed");
  const skippedPatrol = patrolQueue.filter((item) => patrolState.records[item.id]?.status === "skipped");
  const businessPatrol = patrolQueue.filter((item) => !item.id.startsWith("observing:") && !item.id.startsWith("data-health:"));
  const systemPatrol = patrolQueue.filter((item) => item.id.startsWith("observing:") || item.id.startsWith("data-health:"));

  const advancePatrol = (item: PatrolItem, status: PatrolStatus, reason = "") => {
    const nextRecords = { ...patrolState.records, [item.id]: { status, reason, updated_at: new Date().toISOString() } };
    const next = patrolQueue.find((candidate) => !nextRecords[candidate.id]);
    savePatrolState({ date: dayjs().format("YYYY-MM-DD"), current_id: next?.id, records: nextRecords });
    if (next) {
      message.success(status === "completed" ? "已记录完成，进入下一项" : "已暂时跳过，进入下一项");
    } else {
      message.success("今日巡检已完成，摘要已生成");
    }
  };

  const dailySummaryText = useMemo(() => {
    const pending = patrolQueue.filter((item) => !patrolState.records[item.id]);
    const skipped = patrolQueue.filter((item) => patrolState.records[item.id]?.status === "skipped");
    return [
      `${dayjs().format("YYYY-MM-DD")} 推广巡检`,
      `共 ${patrolQueue.length} 项，已处理 ${completedPatrol.length} 项，跳过 ${skipped.length} 项，待处理 ${pending.length} 项。`,
      pending.length ? `待处理：${pending.slice(0, 5).map((item) => item.title).join("；")}` : "待处理：无",
      skipped.length ? `遗留：${skipped.map((item) => `${item.title}（${patrolState.records[item.id]?.reason || "未填写原因"}）`).join("；")}` : "遗留：无",
    ].join("\n");
  }, [completedPatrol.length, patrolQueue, patrolState.records]);

  const copyDailySummary = async () => {
    try {
      await navigator.clipboard.writeText(dailySummaryText);
      message.success("日终摘要已复制");
    } catch {
      message.warning("复制失败，请稍后重试");
    }
  };

  const queueColumns: TableColumnsType<QueueItem> = [
    { title: "优先级", dataIndex: "priority", width: 82, render: (value: Priority) => <Tag color={priorityMeta[value].color}>{priorityMeta[value].label}</Tag> },
    {
      title: "待办事项",
      key: "work",
      render: (_value, item) => (
        <Space orientation="vertical" size={2}>
          <Space size={6} wrap><Text strong>{item.title}</Text><Tag variant="filled">{kindLabels[item.kind] || item.kind}</Tag></Space>
          <Text type="secondary" style={{ fontSize: 12 }}>{item.reason}</Text>
        </Space>
      ),
    },
    { title: "计划", key: "plan", width: 210, render: (_value, item) => <Space orientation="vertical" size={2}><Text>{item.plan_name}</Text><Space size={4} wrap><PromotionChannelTag item={item} /><Text type="secondary" style={{ fontSize: 12 }}>{item.store_name || "未标注店铺"} · {item.scene_name}</Text></Space></Space> },
    { title: "处理时间", key: "due", width: 120, render: (_value, item) => <Text type="secondary">{formatTime(item.due_at)}</Text> },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 170,
      render: (_value, item) => (
        <Space size={4}>
          <Button size="small" icon={<FileSearchOutlined />} onClick={() => void openDetail(item.plan_id)}>查看链路</Button>
          <Button size="small" type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate(item.source_path)}>处理</Button>
        </Space>
      ),
    },
  ];

  const caseColumns: TableColumnsType<CockpitCase> = [
    { title: "计划", key: "plan", render: (_value, item) => <Space orientation="vertical" size={2}><Text strong>{item.plan_name}</Text><Space size={4} wrap><PromotionChannelTag item={item} /><Text type="secondary" style={{ fontSize: 12 }}>{item.store_name || "未标注店铺"} · {item.scene_name}</Text></Space></Space> },
    { title: "当前阶段", dataIndex: "chain_stage", width: 105, render: (value: CockpitCase["chain_stage"]) => <Tag color={stageMeta[value].color}>{stageMeta[value].label}</Tag> },
    { title: "待办", dataIndex: "open_work_count", width: 70, align: "right", render: (value: number) => <Text type={value ? "warning" : "secondary"}>{value}</Text> },
    { title: "决策 / 动作 / 验证", key: "counts", width: 150, align: "center", render: (_value, item) => `${item.decision_count} / ${item.action_count} / ${item.verified_count}` },
    { title: "花费", dataIndex: "spend", width: 100, align: "right", render: fmtMoney },
    { title: "成交", dataIndex: "sales", width: 100, align: "right", render: fmtMoney },
    { title: "ROI", dataIndex: "roi", width: 70, align: "right", render: (value: number) => value.toFixed(2) },
    { title: "风险", dataIndex: "risk_level", width: 82, render: (value: CockpitCase["risk_level"]) => <Tag color={priorityMeta[value].color}>{priorityMeta[value].label}</Tag> },
    { title: "数据", dataIndex: "data_status", width: 92, render: (value: CockpitCase["data_status"]) => <Tag color={value === "fresh" ? "green" : value === "stale" ? "orange" : "default"}>{value === "fresh" ? "新鲜" : value === "stale" ? "已过期" : "缺失"}</Tag> },
    { title: "操作", key: "detail", fixed: "right", width: 95, render: (_value, item) => <Button size="small" onClick={() => void openDetail(item.plan_id)}>完整链路</Button> },
  ];

  const suggestions = useMemo(() => {
    if (!data) return [];
    const items: Array<{ title: string; description: string; type: "error" | "warning" | "info" | "success" }> = [];
    if (data.summary.needs_rollback) items.push({ title: "优先处理回退评估", description: `${data.summary.needs_rollback} 个任务验证未达标，先核对回退条件和当前平台状态。`, type: "error" });
    if (data.summary.pending_verification) items.push({ title: "完成到期验证", description: `${data.summary.pending_verification} 个动作已经到期或即将到期，先同步日报再形成结论。`, type: "warning" });
    if (data.data_health.stale_plan_count) items.push({ title: "刷新过期数据", description: `${data.data_health.stale_plan_count} 个计划超过 24 小时未更新，处理待办前建议先同步。`, type: "warning" });
    if (data.data_health.low_confidence_count) items.push({ title: "谨慎使用低可信度结论", description: `${data.data_health.low_confidence_count} 个验证样本可信度较低，不应直接放大为通用策略。`, type: "info" });
    if (!items.length) items.push({ title: "当前闭环运行正常", description: "暂无高优先级风险，继续关注新决策和观察窗口。", type: "success" });
    return items.slice(0, 4);
  }, [data]);

  const aiActions = useMemo(() => {
    if (!data) return [];
    if (data.today_ai_actions?.length) return data.today_ai_actions.slice(0, 3);
    return data.queue.filter((item) => ["diagnostic", "decision_action"].includes(item.kind)).slice(0, 3).map((item) => ({
      title: item.title,
      reason: item.reason,
      source_path: item.source_path,
      plan_id: item.plan_id,
      plan_name: item.plan_name,
    }));
  }, [data]);

  const yesterdayOutcomes = useMemo(() => {
    if (!data) return { success: 0, failed: 0 };
    if (data.summary.yesterday_success != null || data.summary.yesterday_failed != null) return { success: data.summary.yesterday_success || 0, failed: data.summary.yesterday_failed || 0 };
    const start = dayjs().subtract(1, "day").startOf("day");
    const end = start.endOf("day");
    const actions = data.cases.flatMap((item) => item.chain_stage === "completed" || item.chain_stage === "rollback" ? [item] : []);
    return {
      success: actions.filter((item) => item.chain_stage === "completed" && dayjs(item.latest_activity_at).isAfter(start) && dayjs(item.latest_activity_at).isBefore(end)).length,
      failed: actions.filter((item) => item.chain_stage === "rollback" && dayjs(item.latest_activity_at).isAfter(start) && dayjs(item.latest_activity_at).isBefore(end)).length,
    };
  }, [data]);

  const detailTabs = detail ? [
    {
      key: "timeline",
      label: `完整时间线 ${detail.timeline.length}`,
      children: detail.timeline.length ? (
        <Timeline
          items={detail.timeline.map((item) => ({
            color: item.kind === "verification" && item.status === "failed" ? "red" : item.kind === "verification" ? "green" : item.kind === "decision" ? "purple" : "blue",
            children: <div><Space wrap><Text strong>{item.title}</Text><Tag>{statusText(item.status)}</Tag><Text type="secondary">{formatTime(item.occurred_at)}</Text></Space><div><Text type="secondary">{item.summary}</Text></div></div>,
          }))}
        />
      ) : <Empty description="暂无链路记录" />,
    },
    {
      key: "decisions",
      label: `决策 ${detail.decisions.length}`,
      children: <Table rowKey="id" size="small" pagination={false} dataSource={detail.decisions} scroll={{ x: 620 }} columns={[
        { title: "时间", dataIndex: "updated_at", width: 120, render: formatTime },
        { title: "档位", dataIndex: "selected_tier", width: 90, render: statusText },
        { title: "人工反馈", dataIndex: "feedback_status", width: 110, render: feedbackStatusText },
        { title: "流程状态", dataIndex: "workflow_status", width: 100, render: statusText },
        { title: "反馈原因", dataIndex: "feedback_reason", ellipsis: true, render: (value) => String(value || "—") },
      ]} />,
    },
    {
      key: "actions",
      label: `动作验证 ${detail.actions.length}`,
      children: <Table rowKey="id" size="small" pagination={false} dataSource={detail.actions} scroll={{ x: 680 }} columns={[
        { title: "动作", dataIndex: "action_type", width: 140, ellipsis: true },
        { title: "状态", dataIndex: "status", width: 100, render: statusText },
        { title: "可信度", dataIndex: "confidence", width: 90, render: (value) => value ? <Tag>{value === "high" ? "高" : value === "medium" ? "中" : "低"}</Tag> : "—" },
        { title: "执行时间", dataIndex: "executed_at", width: 120, render: formatTime },
        { title: "验证结论", dataIndex: "result", ellipsis: true, render: (value) => String(value || "—") },
        { title: "下一步", key: "next", width: 100, render: (_value, item) => <Button size="small" danger={item.status === "failed"} onClick={() => navigate(`/promotions/validation?action_id=${item.id}&plan_id=${detail.plan.id}`)}>{item.status === "failed" ? "评估回退" : item.status === "observing" ? "查看节点" : "查看复盘"}</Button> },
      ]} />,
    },
  ] : [];

  return (
    <WorkspacePage kind="cockpit">
      <PageHeader
        icon={<SafetyCertificateOutlined />}
        eyebrow="推广管理"
        title="推广闭环作战台"
        description="面向单人运营的每日驾驶舱：按顺序完成诊断、决策、执行、观察、复盘和回退。"
        updatedAt={data?.generated_at || null}
        extra={<Space wrap><Select aria-label="推广渠道" value={channel} options={[{ value: "", label: "全部渠道" }, ...PROMOTION_CHANNELS]} onChange={setChannel} style={{ minWidth: 150 }} /><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新作战台</Button></Space>}
      />

      {currentPatrol ? (
        <section className="ops-focus-task" aria-labelledby="promotion-focus-task-title">
          <div className="ops-focus-task__head">
            <div className="ops-focus-task__context">
              <span className="ops-focus-task__eyebrow">今日只处理这一件</span>
              <div className="ops-focus-task__tags">
                <Tag color={patrolTypeMeta[currentPatrol.patrol_type].color}>{patrolTypeMeta[currentPatrol.patrol_type].label}</Tag>
                <span>第 {completedPatrol.length + skippedPatrol.length + 1} / {patrolQueue.length} 项</span>
              </div>
            </div>
            <div className="ops-focus-task__progress" aria-label={`今日已处理 ${completedPatrol.length} 项，待处理 ${pendingPatrol.length} 项`}>
              <strong>{completedPatrol.length}</strong> 已处理
              <span aria-hidden="true">·</span>
              <strong>{pendingPatrol.length}</strong> 待处理
            </div>
          </div>

          <div className="ops-focus-task__body">
            <h2 id="promotion-focus-task-title" className="ops-focus-task__title">{currentPatrol.title}</h2>
            <p className="ops-focus-task__reason"><strong>为什么现在处理：</strong>{currentPatrol.reason}</p>
          </div>

          <dl className="ops-focus-task__facts">
            <div className="ops-focus-task__fact"><dt>店铺</dt><dd>{currentPatrol.store_name || "未标注店铺"}</dd></div>
            <div className="ops-focus-task__fact"><dt>推广计划</dt><dd>{currentPatrol.plan_name}</dd></div>
            <div className="ops-focus-task__fact"><dt>渠道 / 场景</dt><dd>{currentPatrol.channel_name || "未标注渠道"} / {currentPatrol.scene_name}</dd></div>
            <div className="ops-focus-task__fact"><dt>建议处理时间</dt><dd>{formatTime(currentPatrol.due_at)}</dd></div>
            <div className="ops-focus-task__fact">
              <dt>数据状态</dt>
              <dd>
                <Tag color={currentCase?.data_status === "fresh" ? "green" : currentCase?.data_status === "stale" ? "orange" : "default"}>
                  {currentCase?.data_status === "fresh" ? "数据可用" : currentCase?.data_status === "stale" ? "数据已过期" : currentCase?.data_status === "missing" ? "数据缺失" : "待人工确认"}
                </Tag>
                <span>{formatTime(currentCase?.data_updated_at || currentPatrol.updated_at)}</span>
              </dd>
            </div>
          </dl>

          <div className="ops-focus-task__actions">
            <Button className="ops-focus-task__skip" onClick={() => setSkipOpen(true)}>暂时跳过</Button>
            {currentPatrol.kind === "pending_execution"
              ? <Text type="secondary" className="ops-focus-task__auto-note">确认执行后自动进入下一项</Text>
              : <Button onClick={() => advancePatrol(currentPatrol, "completed")}>已处理，下一项</Button>}
            <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate(withCockpitContext(currentPatrol, channel))}>进入处理</Button>
          </div>
        </section>
      ) : data && patrolQueue.length ? (
        <section className="ops-focus-task ops-focus-task--complete" aria-labelledby="promotion-day-complete-title">
          <div className="ops-focus-task__body">
            <span className="ops-focus-task__eyebrow">今日推广巡检</span>
            <h2 id="promotion-day-complete-title" className="ops-focus-task__title">今天的事项已经处理完毕</h2>
            <p className="ops-focus-task__reason">已处理 {completedPatrol.length} 项，跳过 {skippedPatrol.length} 项。建议复制摘要，作为今天的运营记录。</p>
          </div>
          <div className="ops-focus-task__actions"><Button type="primary" icon={<CopyOutlined />} onClick={() => void copyDailySummary()}>复制日终摘要</Button></div>
        </section>
      ) : data ? (
        <section className="ops-focus-task ops-focus-task--empty" aria-labelledby="promotion-day-empty-title">
          <div className="ops-focus-task__body">
            <span className="ops-focus-task__eyebrow">今日推广巡检</span>
            <h2 id="promotion-day-empty-title" className="ops-focus-task__title">当前没有需要立即处理的事项</h2>
            <p className="ops-focus-task__reason">继续观察现有计划，或生成新一轮 AI 建议。所有真实调整仍需人工确认。</p>
          </div>
          <div className="ops-focus-task__actions"><Button type="primary" onClick={() => navigate("/promotions/decisions")}>生成今日建议</Button></div>
        </section>
      ) : null}
      {targetError ? <Alert type="error" showIcon title={targetError} style={{ marginBottom: 16 }} /> : null}

      {loading && !data ? <div style={{ minHeight: 320, display: "flex", alignItems: "center", justifyContent: "center" }}><Spin size="large" /></div> : null}
      {!loading && !data ? <Card variant="borderless"><Empty description="暂时无法加载推广作战台"><Button type="primary" onClick={() => void load()}>重新加载</Button></Empty></Card> : null}

      {data ? (
        <>
          <MetricRail items={[
              { label: "待执行", value: data.summary.pending_execution, hint: "已确认但尚未执行", color: "var(--ops-warn)" },
              { label: "待验证", value: data.summary.pending_verification, hint: "观察到期或即将到期", color: "var(--ops-info)" },
              { label: "紧急回退", value: data.summary.needs_rollback, hint: "验证失败，需人工评估", color: "var(--ops-danger)" },
              { label: "待诊断", value: data.summary.diagnostic_count, hint: "紧急或高风险异常", color: "var(--ops-danger)" },
              { label: "放量机会", value: data.summary.scale_opportunities ?? data.queue.filter((item) => item.title.includes("放量")).length, hint: "优先核查高 ROI 低消耗", color: "var(--ops-success)" },
              { label: "全部待办", value: data.summary.total, hint: "当前需要运营跟进的事项", color: "var(--ops-text)" },
            ].map((item) => ({ key: item.label, label: item.label, value: item.value, hint: item.hint, tone: item.color }))} />

          <div className="ops-patrol-scope" aria-label="今日巡检口径">
            <span><strong>今日巡检 {patrolQueue.length}</strong> 项</span>
            <span>业务待办 {businessPatrol.length}</span>
            <span>系统检查 {systemPatrol.length}</span>
            <span>业务待办来自诊断、决策、执行与验证；系统检查用于数据质量和观察窗口提醒。</span>
          </div>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} xl={16}>
              <Card
                variant="borderless"
                title={<Space><ClockCircleOutlined />今日待办</Space>}
                extra={<WorkspaceToolbar><Segmented aria-label="待办优先级" value={priority} onChange={(value) => setPriority(value as typeof priority)} options={[{ label: "全部", value: "all" }, { label: "紧急", value: "urgent" }, { label: "优先", value: "high" }, { label: "关注", value: "medium" }]} /><Select aria-label="待办类型" value={kind} options={kindOptions} onChange={setKind} style={{ minWidth: 120 }} /></WorkspaceToolbar>}
              >
                <Table<QueueItem>
                  rowKey="id"
                  size="small"
                  columns={queueColumns}
                  dataSource={filteredQueue}
                  pagination={{ pageSize: 12, hideOnSinglePage: true }}
                  scroll={{ x: 980 }}
                  locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选下没有待办" /> }}
                />
              </Card>
            </Col>
            <Col xs={24} xl={8}>
              <Card variant="borderless" title="AI 今日优先动作">
                {aiActions.length ? <Space orientation="vertical" size={10} style={{ width: "100%" }}>{aiActions.map((item) => <Card size="small" key={`${item.source_path}-${item.title}`}><Space orientation="vertical" size={4} style={{ width: "100%" }}><Text strong>{item.title}</Text><Text type="secondary" style={{ fontSize: 12 }}>{item.reason}</Text><Button size="small" type="link" onClick={() => navigate(item.source_path)}>查看并判断</Button></Space></Card>)}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 AI 优先动作"><Button onClick={() => navigate("/promotions/decisions")}>生成今日建议</Button></Empty>}
              </Card>
              <Card variant="borderless" title={<Space><AlertOutlined />今日处理建议</Space>} style={{ marginTop: 16 }}>
                <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                  {suggestions.map((item) => <Alert key={item.title} type={item.type} showIcon title={item.title} description={item.description} />)}
                </Space>
              </Card>
              <Card variant="borderless" title="数据与验证健康度" style={{ marginTop: 16 }}>
                <Descriptions column={1} size="small" items={[
                  { key: "plans", label: "可见推广计划", children: data.data_health.visible_plan_count },
                  { key: "stale", label: "数据超过 24 小时", children: <Text type={data.data_health.stale_plan_count ? "warning" : "success"}>{data.data_health.stale_plan_count}</Text> },
                  { key: "missing", label: "缺少观察截止时间", children: <Text type={data.data_health.missing_due_count ? "warning" : "success"}>{data.data_health.missing_due_count}</Text> },
                  { key: "confidence", label: "低可信度验证", children: <Text type={data.data_health.low_confidence_count ? "warning" : "success"}>{data.data_health.low_confidence_count}</Text> },
                  { key: "updated", label: "计划最近更新", children: formatTime(data.data_health.last_plan_update) },
                ]} />
              </Card>
            </Col>
          </Row>

          <Card variant="borderless" title="昨日成败" extra={<Button onClick={() => navigate("/promotions/validation")}>去复盘</Button>} style={{ marginTop: 16 }}>
            <Space size="large">
              <div><Text type="secondary">验证改善</Text><div style={{ color: "var(--ops-success)", fontSize: 24, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{yesterdayOutcomes.success}</div></div>
              <div><Text type="secondary">验证恶化</Text><div style={{ color: "var(--ops-danger)", fontSize: 24, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{yesterdayOutcomes.failed}</div></div>
            </Space>
          </Card>

          <Card variant="borderless" title={<Space><ExclamationCircleOutlined />计划闭环档案</Space>} extra={<Text type="secondary">点击计划查看决策—执行—验证全过程</Text>} style={{ marginTop: 16 }}>
            <Table<CockpitCase>
              rowKey="plan_id"
              size="small"
              columns={caseColumns}
              dataSource={data.cases}
              pagination={{ pageSize: 15, hideOnSinglePage: true }}
              scroll={{ x: 1120 }}
              locale={{ emptyText: <Empty description="暂无闭环计划，先在 AI 决策中心建立一条决策" /> }}
            />
          </Card>
          {patrolQueue.length ? <Card variant="borderless" title="今日巡检摘要" extra={<Button size="small" icon={<CopyOutlined />} onClick={() => void copyDailySummary()}>复制日终摘要</Button>} style={{ marginTop: 16 }}><Row gutter={[12, 12]}><Col xs={12} sm={6}><StatisticCard label="巡检总数" value={patrolQueue.length} /></Col><Col xs={12} sm={6}><StatisticCard label="已处理" value={completedPatrol.length} tone="var(--ops-success)" /></Col><Col xs={12} sm={6}><StatisticCard label="暂时跳过" value={skippedPatrol.length} tone="var(--ops-warn)" /></Col><Col xs={12} sm={6}><StatisticCard label="完成率" value={`${Math.round(completedPatrol.length / patrolQueue.length * 100)}%`} /></Col></Row><Alert type={pendingPatrol.length ? "info" : "success"} showIcon title={pendingPatrol.length ? `还有 ${pendingPatrol.length} 项待处理` : "今天没有待处理事项"} description={pendingPatrol.length ? pendingPatrol.slice(0, 3).map((item) => item.title).join("；") : "可以结束今日推广巡检。"} style={{ marginTop: 12 }} />{skippedPatrol.length ? <Space orientation="vertical" size={4} style={{ marginTop: 12, width: "100%" }}>{skippedPatrol.map((item) => <Text type="secondary" key={item.id}>遗留 · {item.title}：{patrolState.records[item.id]?.reason || "未填写原因"}</Text>)}</Space> : null}</Card> : null}
        </>
      ) : null}

      <Modal open={skipOpen} title="暂时跳过当前事项" okText="记录并进入下一项" okButtonProps={{ disabled: !skipReason.trim() }} onCancel={() => { setSkipOpen(false); setSkipReason(""); }} onOk={() => { if (!currentPatrol || !skipReason.trim()) return; advancePatrol(currentPatrol, "skipped", skipReason.trim()); setSkipOpen(false); setSkipReason(""); }}>
        <Space orientation="vertical" size={10} style={{ width: "100%" }}>
          <Alert type="warning" showIcon title="跳过不会删除任务" description="原因会保存在今日巡检摘要中，便于下班前复核。" />
          <Input.TextArea value={skipReason} onChange={(event) => setSkipReason(event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} placeholder="请填写跳过原因，例如：等待素材、数据未同步、今天不适合调整" maxLength={200} showCount />
        </Space>
      </Modal>

      <Drawer
        open={detailOpen}
        title={detail ? `完整链路 · ${detail.plan.plan_name}` : "推广计划完整链路"}
        size="large"
        onClose={() => setDetailOpen(false)}
        destroyOnHidden
        extra={detail ? <Button onClick={() => navigate(`/promotions/plans?plan_id=${detail.plan.id}`)}>进入计划执行中心</Button> : null}
      >
        {detailLoading ? <div style={{ minHeight: 240, display: "flex", alignItems: "center", justifyContent: "center" }} aria-busy="true"><Spin /></div> : null}
        {!detailLoading && !detail ? <Empty description="未能加载计划链路"><Button type="primary" onClick={() => detailPlanId && void openDetail(detailPlanId)}>重新加载</Button></Empty> : null}
        {detail ? (
          <>
            <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
              { key: "store", label: "店铺", children: String(detail.plan.store_name || "—") },
              { key: "channel", label: "推广渠道", children: <PromotionChannelTag item={detail.plan} /> },
              { key: "scene", label: "推广场景", children: String(detail.plan.scene_name || "—") },
              { key: "status", label: "计划状态", children: String(detail.plan.status || "—") },
              { key: "updated", label: "数据更新时间", children: formatTime(detail.plan.updated_at) },
              { key: "spend", label: "当前花费", children: fmtMoney(Number(detail.plan.spend || 0)) },
              { key: "sales", label: "当前成交", children: fmtMoney(Number(detail.plan.sales || 0)) },
              { key: "roi", label: "当前 ROI", children: Number(detail.plan.roi || 0).toFixed(2) },
              { key: "records", label: "闭环记录", children: `${detail.decisions.length} 决策 · ${detail.actions.length} 动作` },
            ]} />
            <Tabs items={detailTabs} defaultActiveKey="timeline" style={{ marginTop: 16 }} />
          </>
        ) : null}
      </Drawer>
    </WorkspacePage>
  );
}
