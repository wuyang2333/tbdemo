import { BellOutlined, PlusOutlined, ReloadOutlined, TeamOutlined, UndoOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Form, Input, Modal, Row, Segmented, Select, Space, Statistic, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/ui/page-header";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";
import type { PromoPlan } from "../types";

const { Text } = Typography;

type ExecutionStatus = "executing" | "observing" | "pending_verification" | "needs_rollback" | "completed";
type ApprovalStatus = "not_required" | "pending" | "approved" | "rejected";
type CollaborationTask = {
  id: number;
  plan_id: number;
  plan_name?: string;
  scene_name?: string;
  store_name?: string;
  title: string;
  description: string;
  owner_name: string;
  planned_at?: string | null;
  approval_status: ApprovalStatus;
  execution_status: ExecutionStatus;
  rollback_reason: string;
  reminder_count: number;
  action_record_id?: number | null;
  updated_at: string;
};
type CollaborationSummary = Record<ExecutionStatus, number> & { total: number; approval_pending: number };
type TaskForm = { plan_id: number; title: string; description?: string; owner_name?: string; planned_at?: string; approval_status: ApprovalStatus };
type NoteForm = { message: string; remind_at?: string };
type RollbackForm = { reason: string };

const executionMeta: Record<ExecutionStatus, { label: string; color: string }> = {
  executing: { label: "待执行", color: "gold" },
  observing: { label: "观察中", color: "blue" },
  pending_verification: { label: "待验证", color: "cyan" },
  needs_rollback: { label: "需回退", color: "red" },
  completed: { label: "已完成", color: "green" },
};
const approvalMeta: Record<ApprovalStatus, { label: string; color: string }> = {
  not_required: { label: "无需审批", color: "default" },
  pending: { label: "待审批", color: "orange" },
  approved: { label: "已通过", color: "green" },
  rejected: { label: "已驳回", color: "red" },
};

function formatDate(value?: string | null): string {
  return value ? value.replace("T", " ").slice(0, 16) : "—";
}

function isFormError(error: unknown): boolean {
  return !!error && typeof error === "object" && "errorFields" in error;
}

export function PromotionsCollaborationPage() {
  const [searchParams] = useSearchParams();
  const { currentStore } = useStores();
  const targetTaskId = Number(searchParams.get("task_id")) || null;
  const [tasks, setTasks] = useState<CollaborationTask[]>([]);
  const [summary, setSummary] = useState<CollaborationSummary | null>(null);
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [filter, setFilter] = useState<"all" | ExecutionStatus>("all");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [reminderTask, setReminderTask] = useState<CollaborationTask | null>(null);
  const [rollbackTask, setRollbackTask] = useState<CollaborationTask | null>(null);
  const [taskForm] = Form.useForm<TaskForm>();
  const [reminderForm] = Form.useForm<NoteForm>();
  const [rollbackForm] = Form.useForm<RollbackForm>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const taskParams = new URLSearchParams();
      if (filter !== "all") taskParams.set("execution_status", filter);
      if (currentStore) taskParams.set("store_id", String(currentStore.id));
      const taskQuery = taskParams.size ? `?${taskParams.toString()}` : "";
      const storeQuery = currentStore ? `?store_id=${currentStore.id}` : "";
      const [taskResponse, summaryResponse, planResponse] = await Promise.all([
        http.get<{ items: CollaborationTask[] }>(`/promotions/collaboration/tasks${taskQuery}`),
        http.get<CollaborationSummary>(`/promotions/collaboration/summary${storeQuery}`),
        http.get<{ items: PromoPlan[] }>(`/promotions/plans?mode=7d${currentStore ? `&store_id=${currentStore.id}` : ""}`),
      ]);
      setTasks(taskResponse.data.items || []);
      setSummary(summaryResponse.data);
      setPlans(planResponse.data.items || []);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id, filter]);

  useEffect(() => { void load(); }, [load]);

  const createTask = async () => {
    try {
      const values = await taskForm.validateFields();
      setSaving(true);
      await http.post("/promotions/collaboration/tasks", { ...values, execution_status: "executing" });
      message.success("协同任务已创建");
      setCreateOpen(false);
      taskForm.resetFields();
      await load();
    } catch (error) {
      if (!isFormError(error)) message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const updateStatus = async (task: CollaborationTask, executionStatus: ExecutionStatus) => {
    try {
      await http.patch(`/promotions/collaboration/tasks/${task.id}`, { execution_status: executionStatus });
      message.success("任务状态已更新");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const createReminder = async () => {
    if (!reminderTask) return;
    try {
      const values = await reminderForm.validateFields();
      setSaving(true);
      await http.post(`/promotions/collaboration/tasks/${reminderTask.id}/reminders`, values);
      message.success("提醒已记录");
      setReminderTask(null);
      reminderForm.resetFields();
      await load();
    } catch (error) {
      if (!isFormError(error)) message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const recordRollback = async () => {
    if (!rollbackTask) return;
    try {
      const values = await rollbackForm.validateFields();
      setSaving(true);
      await http.post(`/promotions/collaboration/tasks/${rollbackTask.id}/rollback-suggestion`, values);
      message.warning("已记录回退建议，不会自动修改万相台");
      setRollbackTask(null);
      rollbackForm.resetFields();
      await load();
    } catch (error) {
      if (!isFormError(error)) message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const columns: TableColumnsType<CollaborationTask> = [
    { title: "任务", key: "task", width: 260, render: (_value, task) => <Space orientation="vertical" size={2}><Text strong>{task.title}</Text><Text type="secondary">{task.plan_name || `计划 ${task.plan_id}`} · {task.scene_name || "未标注场景"}</Text></Space> },
    { title: "负责人", dataIndex: "owner_name", key: "owner_name", width: 100, render: (value) => value || "未分配" },
    { title: "计划时间", dataIndex: "planned_at", key: "planned_at", width: 150, render: formatDate },
    { title: "审批", key: "approval", width: 100, render: (_value, task) => <Tag color={approvalMeta[task.approval_status].color}>{approvalMeta[task.approval_status].label}</Tag> },
    { title: "状态", key: "status", width: 145, render: (_value, task) => <Select aria-label={`更新${task.title}状态`} size="small" value={task.execution_status} disabled={!!task.action_record_id} title={task.action_record_id ? "关联动作状态由执行和验证结果自动同步" : undefined} style={{ width: 125 }} onChange={(value) => void updateStatus(task, value)} options={Object.entries(executionMeta).map(([value, meta]) => ({ value, label: meta.label }))} /> },
    { title: "提醒", key: "reminders", width: 80, render: (_value, task) => task.reminder_count || 0 },
    { title: "操作", key: "actions", fixed: "right", width: 170, render: (_value, task) => <Space size={4}><Button size="small" icon={<BellOutlined />} onClick={() => setReminderTask(task)}>提醒</Button><Button size="small" danger icon={<UndoOutlined />} disabled={!!task.action_record_id && task.execution_status !== "needs_rollback"} onClick={() => setRollbackTask(task)}>回退</Button></Space> },
  ];

  const focusedTasks = targetTaskId ? tasks.filter((task) => task.id === targetTaskId) : tasks;

  return (
    <div>
      <PageHeader icon={<TeamOutlined />} eyebrow="推广管理" title="执行协同中心" description="把已确认的推广动作分配到人、安排时间并跟踪执行、观察、验证和回退。" extra={<Space wrap><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建协同任务</Button></Space>} />
      <Alert type="info" showIcon title="协同中心只管理本地执行流程" description="回退建议、负责人和提醒不会直接修改万相台；真实投放变更仍需在计划执行中心确认。" style={{ marginBottom: 16 }} />
      {targetTaskId && !loading && focusedTasks.length === 0 ? <Alert type="error" showIcon title="目标协同任务不存在或不在当前店铺范围" style={{ marginBottom: 16 }} /> : null}
      <Row gutter={[12, 12]}>
        {[
          { label: "全部任务", value: summary?.total || 0 },
          { label: "待执行", value: summary?.executing || 0 },
          { label: "观察中", value: summary?.observing || 0 },
          { label: "待验证", value: summary?.pending_verification || 0 },
          { label: "需回退", value: summary?.needs_rollback || 0 },
          { label: "已完成", value: summary?.completed || 0 },
        ].map((item) => <Col xs={12} sm={8} lg={4} key={item.label}><Card variant="borderless"><Statistic title={item.label} value={item.value} /></Card></Col>)}
      </Row>
      <Card variant="borderless" style={{ marginTop: 16 }} title="执行任务" extra={<Segmented value={filter} onChange={(value) => setFilter(value as "all" | ExecutionStatus)} options={[{ label: "全部", value: "all" }, ...Object.entries(executionMeta).map(([value, meta]) => ({ label: meta.label, value }))]} />}>
        <Table<CollaborationTask> rowKey="id" loading={loading} dataSource={focusedTasks} columns={columns} scroll={{ x: 1050 }} pagination={{ pageSize: 20 }} locale={{ emptyText: <Empty description="暂无协同任务"><Button type="primary" onClick={() => setCreateOpen(true)}>新建第一个任务</Button></Empty> }} />
      </Card>

      <Modal open={createOpen} title="新建执行协同任务" onCancel={() => setCreateOpen(false)} onOk={() => void createTask()} okText="创建任务" confirmLoading={saving} destroyOnHidden>
        <Form form={taskForm} layout="vertical" initialValues={{ approval_status: "not_required" }}>
          <Form.Item name="plan_id" label="推广计划" rules={[{ required: true, message: "请选择推广计划" }]}><Select showSearch optionFilterProp="label" placeholder="选择计划" options={plans.map((plan) => ({ value: plan.id, label: `${plan.plan_name} · ${plan.scene_name}` }))} /></Form.Item>
          <Form.Item name="title" label="任务名称" rules={[{ required: true, message: "请填写任务名称" }]}><Input maxLength={160} placeholder="例如：执行预算下调并观察 ROI" /></Form.Item>
          <Form.Item name="owner_name" label="负责人"><Input maxLength={80} placeholder="填写负责人姓名" /></Form.Item>
          <Form.Item name="planned_at" label="计划执行时间"><Input type="datetime-local" /></Form.Item>
          <Form.Item name="approval_status" label="审批要求"><Select options={Object.entries(approvalMeta).map(([value, meta]) => ({ value, label: meta.label }))} /></Form.Item>
          <Form.Item name="description" label="执行说明"><Input.TextArea rows={3} maxLength={2000} showCount placeholder="补充执行要求、观察重点或交接信息" /></Form.Item>
        </Form>
      </Modal>

      <Modal open={!!reminderTask} title="记录任务提醒" onCancel={() => setReminderTask(null)} onOk={() => void createReminder()} okText="记录提醒" confirmLoading={saving} destroyOnHidden>
        <Form form={reminderForm} layout="vertical">
          <Form.Item name="message" label="提醒内容" rules={[{ required: true, message: "请填写提醒内容" }]}><Input.TextArea rows={3} maxLength={1000} placeholder="例如：观察窗口结束后检查 ROI 和日均成交" /></Form.Item>
          <Form.Item name="remind_at" label="提醒时间"><Input type="datetime-local" /></Form.Item>
        </Form>
      </Modal>

      <Modal open={!!rollbackTask} title="记录回退建议" onCancel={() => setRollbackTask(null)} onOk={() => void recordRollback()} okText="确认记录" okButtonProps={{ danger: true }} confirmLoading={saving} destroyOnHidden>
        <Alert type="warning" showIcon title="这里只记录回退建议，不会执行平台操作" style={{ marginBottom: 12 }} />
        <Form form={rollbackForm} layout="vertical">
          <Form.Item name="reason" label="回退原因" rules={[{ required: true, message: "请填写回退原因" }]}><Input.TextArea rows={4} maxLength={1000} showCount placeholder="说明未达标指标、风险和建议恢复值" /></Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
