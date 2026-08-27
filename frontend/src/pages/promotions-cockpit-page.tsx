import {
  AlertOutlined,
  ArrowRightOutlined,
  ClockCircleOutlined,
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
import { PageHeader } from "../components/ui/page-header";
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
  store_id: number;
  store_name: string;
  source_path: string;
  due_at?: string | null;
  owner_name?: string;
  updated_at?: string;
};

type CockpitCase = {
  plan_id: number;
  plan_name: string;
  store_id: number;
  store_name: string;
  scene_name: string;
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
  collaboration_count: number;
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
  };
  queue: QueueItem[];
  cases: CockpitCase[];
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
    scene_name?: string;
    status?: string;
    spend?: number;
    sales?: number;
    roi?: number;
    updated_at?: string;
  };
  decisions: Array<Record<string, unknown> & { id: number; selected_tier?: string; feedback_status?: string; workflow_status?: string; updated_at?: string }>;
  actions: Array<Record<string, unknown> & { id: number; action_type?: string; status?: string; result?: string; confidence?: string; executed_at?: string; verified_at?: string }>;
  collaboration_tasks: Array<Record<string, unknown> & { id: number; title?: string; owner_name?: string; execution_status?: string; approval_status?: string; updated_at?: string }>;
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
  approval_pending: "待审批",
  verification_overdue: "验证逾期",
  verification_due_soon: "即将验证",
  pending_verification: "待验证",
  needs_rollback: "需回退",
  owner_unassigned: "未分配",
};

const stageMeta: Record<CockpitCase["chain_stage"], { label: string; color: string }> = {
  decision: { label: "决策确认", color: "purple" },
  execution: { label: "执行中", color: "gold" },
  validation: { label: "观察验证", color: "blue" },
  rollback: { label: "回退评估", color: "red" },
  completed: { label: "已闭环", color: "green" },
};

function formatTime(value?: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("MM-DD HH:mm") : "—";
}

function statusText(value?: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  const labels: Record<string, string> = {
    selected: "已确认",
    planned: "待执行",
    executed: "已执行",
    observing: "观察中",
    verified: "已验证",
    success: "成功",
    partial: "部分有效",
    failed: "失败",
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

export function PromotionsCockpitPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { currentStore } = useStores();
  const targetPlanId = Number(searchParams.get("plan_id")) || null;
  const [data, setData] = useState<CockpitData | null>(null);
  const [loading, setLoading] = useState(true);
  const [priority, setPriority] = useState<"all" | Priority>("all");
  const [kind, setKind] = useState("all");
  const [detail, setDetail] = useState<PlanDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [targetError, setTargetError] = useState("");
  const [openedTargetScope, setOpenedTargetScope] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await http.get<CockpitData>(`/promotions/cockpit${currentStore ? `?store_id=${currentStore.id}` : ""}`);
      setData(response.data);
    } catch (error) {
      setData(null);
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id]);

  useEffect(() => { void load(); }, [load]);

  const openDetail = async (planId: number) => {
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

  const filteredQueue = useMemo(() => (data?.queue || []).filter((item) => (
    (priority === "all" || item.priority === priority) && (kind === "all" || item.kind === kind)
  )), [data?.queue, kind, priority]);

  const kindOptions = useMemo(() => {
    const values = Array.from(new Set((data?.queue || []).map((item) => item.kind)));
    return [{ value: "all", label: "全部类型" }, ...values.map((value) => ({ value, label: kindLabels[value] || value }))];
  }, [data?.queue]);

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
    { title: "计划", key: "plan", width: 190, render: (_value, item) => <Space orientation="vertical" size={1}><Text>{item.plan_name}</Text><Text type="secondary" style={{ fontSize: 12 }}>{item.store_name || "未标注店铺"} · {item.scene_name}</Text></Space> },
    { title: "负责人 / 时间", key: "owner", width: 140, render: (_value, item) => <Space orientation="vertical" size={1}><Text>{item.owner_name || "未分配"}</Text><Text type="secondary" style={{ fontSize: 12 }}>{formatTime(item.due_at)}</Text></Space> },
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
    { title: "计划", key: "plan", render: (_value, item) => <Space orientation="vertical" size={2}><Text strong>{item.plan_name}</Text><Text type="secondary" style={{ fontSize: 12 }}>{item.store_name || "未标注店铺"} · {item.scene_name}</Text></Space> },
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
        { title: "人工反馈", dataIndex: "feedback_status", width: 110, render: statusText },
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
      ]} />,
    },
    {
      key: "collaboration",
      label: `协同 ${detail.collaboration_tasks.length}`,
      children: <Table rowKey="id" size="small" pagination={false} dataSource={detail.collaboration_tasks} scroll={{ x: 620 }} columns={[
        { title: "任务", dataIndex: "title", ellipsis: true },
        { title: "负责人", dataIndex: "owner_name", width: 100, render: (value) => String(value || "未分配") },
        { title: "审批", dataIndex: "approval_status", width: 100, render: statusText },
        { title: "执行状态", dataIndex: "execution_status", width: 100, render: statusText },
        { title: "更新时间", dataIndex: "updated_at", width: 120, render: formatTime },
      ]} />,
    },
  ] : [];

  return (
    <div>
      <PageHeader
        icon={<SafetyCertificateOutlined />}
        eyebrow="推广管理"
        title="推广闭环作战台"
        description="集中处理推广决策、执行、验证和回退待办，并查看每个计划的完整闭环链路。"
        updatedAt={data?.generated_at || null}
        extra={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新作战台</Button>}
      />

      <Alert
        type="info"
        showIcon
        title="作战台只聚合真实业务记录，不会自动修改万相台"
        description="点击“处理”会进入对应工作区；预算、出价和计划状态仍需在计划执行中心人工确认。"
        style={{ marginBottom: 16 }}
      />
      {targetError ? <Alert type="error" showIcon title={targetError} style={{ marginBottom: 16 }} /> : null}

      {loading && !data ? <div style={{ minHeight: 320, display: "flex", alignItems: "center", justifyContent: "center" }}><Spin size="large" /></div> : null}
      {!loading && !data ? <Card variant="borderless"><Empty description="暂时无法加载推广作战台"><Button type="primary" onClick={() => void load()}>重新加载</Button></Empty></Card> : null}

      {data ? (
        <>
          <Row gutter={[12, 12]}>
            {[
              { label: "全部待办", value: data.summary.total, hint: "当前需要运营跟进的事项", color: "var(--ops-text)" },
              { label: "紧急回退", value: data.summary.needs_rollback, hint: "验证失败，需人工评估", color: "var(--ops-danger)" },
              { label: "待诊断", value: data.summary.diagnostic_count, hint: "紧急或高风险异常", color: "var(--ops-danger)" },
              { label: "待执行", value: data.summary.pending_execution, hint: "已确认但尚未执行", color: "var(--ops-warn)" },
              { label: "待验证", value: data.summary.pending_verification, hint: "观察到期或即将到期", color: "var(--ops-info)" },
              { label: "活跃链路", value: data.data_health.active_case_count, hint: "已有决策或动作的计划", color: "var(--ops-success)" },
            ].map((item) => (
              <Col xs={12} sm={8} xl={4} key={item.label}>
                <Card variant="borderless" style={{ height: "100%" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
                  <div style={{ color: item.color, fontSize: 24, fontWeight: 700, margin: "5px 0" }}>{item.value}</div>
                  <Text type="secondary" style={{ fontSize: 11 }}>{item.hint}</Text>
                </Card>
              </Col>
            ))}
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} xl={16}>
              <Card
                variant="borderless"
                title={<Space><ClockCircleOutlined />今日待办</Space>}
                extra={<Space wrap><Segmented aria-label="待办优先级" value={priority} onChange={(value) => setPriority(value as typeof priority)} options={[{ label: "全部", value: "all" }, { label: "紧急", value: "urgent" }, { label: "优先", value: "high" }, { label: "关注", value: "medium" }]} /><Select aria-label="待办类型" value={kind} options={kindOptions} onChange={setKind} style={{ minWidth: 120 }} /></Space>}
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
              <Card variant="borderless" title={<Space><AlertOutlined />今日处理建议</Space>}>
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
        </>
      ) : null}

      <Drawer
        open={detailOpen}
        title={detail ? `完整链路 · ${detail.plan.plan_name}` : "推广计划完整链路"}
        size="large"
        onClose={() => setDetailOpen(false)}
        destroyOnHidden
        extra={detail ? <Button onClick={() => navigate(`/promotions/plans?plan_id=${detail.plan.id}`)}>进入计划执行中心</Button> : null}
      >
        {detailLoading ? <div style={{ minHeight: 240, display: "flex", alignItems: "center", justifyContent: "center" }} aria-busy="true"><Spin /></div> : null}
        {!detailLoading && !detail ? <Empty description="未能加载计划链路" /> : null}
        {detail ? (
          <>
            <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
              { key: "store", label: "店铺", children: String(detail.plan.store_name || "—") },
              { key: "scene", label: "推广场景", children: String(detail.plan.scene_name || "—") },
              { key: "status", label: "计划状态", children: String(detail.plan.status || "—") },
              { key: "updated", label: "数据更新时间", children: formatTime(detail.plan.updated_at) },
              { key: "spend", label: "当前花费", children: fmtMoney(Number(detail.plan.spend || 0)) },
              { key: "sales", label: "当前成交", children: fmtMoney(Number(detail.plan.sales || 0)) },
              { key: "roi", label: "当前 ROI", children: Number(detail.plan.roi || 0).toFixed(2) },
              { key: "records", label: "闭环记录", children: `${detail.decisions.length} 决策 · ${detail.actions.length} 动作 · ${detail.collaboration_tasks.length} 协同` },
            ]} />
            <Tabs items={detailTabs} defaultActiveKey="timeline" style={{ marginTop: 16 }} />
          </>
        ) : null}
      </Drawer>
    </div>
  );
}
