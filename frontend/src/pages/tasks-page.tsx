import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloudSyncOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  LoadingOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  ScheduleOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PageHeader } from "../components/ui/page-header";
import http, { getApiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useStores } from "../lib/store";

const { Text } = Typography;

type TaskStatus = {
  name: string;
  last_run: string | null;
  last_success: string | null;
  last_error: string | null;
  error_count: number;
  run_count: number;
  success_count: number;
  last_duration: number;
  running: boolean;
  last_started: string | null;
  paused: boolean;
};

type TaskRun = {
  id: number;
  name: string;
  status: "success" | "error";
  trigger: "auto" | "manual" | "resume";
  store_id: number | null;
  store_name: string | null;
  started_at: string | null;
  finished_at: string;
  duration: number;
  error: string;
};

type TaskCenterResponse = {
  tasks: TaskStatus[];
  history: TaskRun[];
  maintenance: MaintenanceState;
  summary: {
    running: number;
    abnormal: number;
    today_total: number;
    today_success: number;
    today_error: number;
    success_rate: number;
  };
};

type MaintenanceState = {
  enabled: boolean;
  reason: string;
  started_at: string | null;
  ends_at: string | null;
  created_by: string;
  pause_tasks: string[];
  resume_strategy: "next_cycle" | "run_once";
  pending_resume: string[];
  resumed_at: string | null;
};

type TaskMeta = {
  label: string;
  category: "数据同步" | "消息推送" | "系统维护";
  schedule: string;
  description: string;
  retryable?: boolean;
};

const TASK_META: Record<string, TaskMeta> = {
  realtime_sync: { label: "经营数据同步", category: "数据同步", schedule: "每 3 分钟", description: "同步店铺经营、分时、推广、退款和流量来源数据", retryable: true },
  product_catalog_sync: { label: "在售商品同步", category: "数据同步", schedule: "每 15 分钟", description: "从淘宝后台更新在售商品、价格、库存和状态", retryable: true },
  promo_daily: { label: "推广数据补录", category: "数据同步", schedule: "每日 09:00", description: "补录近 7 天推广和商品按天数据", retryable: true },
  inspect: { label: "系统巡检", category: "系统维护", schedule: "每 5 分钟", description: "检查店铺授权、登录状态与基础服务健康度", retryable: true },
  report_push: { label: "经营日报推送", category: "消息推送", schedule: "每分钟检查", description: "按配置时间生成并推送经营日报" },
  hourly_push: { label: "小时异常推送", category: "消息推送", schedule: "整点后 5 分钟", description: "检查小时指标异常并推送提醒" },
  backup: { label: "数据库备份", category: "系统维护", schedule: "每日执行", description: "备份工作台数据库并保留最近版本" },
  data_cleanup: { label: "历史数据清理", category: "系统维护", schedule: "每日执行", description: "按数据保留策略清理过期记录" },
  log_rotate: { label: "日志轮转", category: "系统维护", schedule: "每日执行", description: "归档并清理过大的服务日志" },
};

const CATEGORY_COLORS: Record<TaskMeta["category"], string> = {
  数据同步: "blue",
  消息推送: "purple",
  系统维护: "default",
};

function getTaskMeta(name: string): TaskMeta {
  return TASK_META[name] ?? { label: name, category: "系统维护", schedule: "按系统配置", description: "后台系统任务" };
}

function formatTime(value: string | null): string {
  return value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "尚未运行";
}

const DEFAULT_PAUSE_TASKS = ["inspect", "realtime_sync", "product_catalog_sync", "report_push", "hourly_push", "promo_daily", "data_cleanup"];

function taskState(task: TaskStatus): "running" | "paused" | "error" | "success" | "waiting" {
  if (task.running) return "running";
  if (task.paused) return "paused";
  if (task.error_count > 0) return "error";
  if (task.last_success) return "success";
  return "waiting";
}

function TaskStateTag({ task }: { task: TaskStatus }) {
  const state = taskState(task);
  if (state === "running") return <Tag icon={<LoadingOutlined />} color="processing">运行中</Tag>;
  if (state === "paused") return <Tag icon={<PauseCircleOutlined />} color="warning">已暂停</Tag>;
  if (state === "error") return <Tag icon={<ExclamationCircleOutlined />} color="error">异常</Tag>;
  if (state === "success") return <Tag icon={<CheckCircleOutlined />} color="success">正常</Tag>;
  return <Tag icon={<ClockCircleOutlined />}>等待首次运行</Tag>;
}

export function TasksPage() {
  const { user } = useAuth();
  const { stores, currentStore } = useStores();
  const [data, setData] = useState<TaskCenterResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [taskFilter, setTaskFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [triggerFilter, setTriggerFilter] = useState("all");
  const [storeFilter, setStoreFilter] = useState<number | "all">("all");
  const [selectedTask, setSelectedTask] = useState<TaskStatus | null>(null);
  const [selectedRun, setSelectedRun] = useState<TaskRun | null>(null);
  const [maintenanceOpen, setMaintenanceOpen] = useState(false);
  const [maintenanceSaving, setMaintenanceSaving] = useState(false);
  const [maintenanceForm] = Form.useForm();
  const requestSequence = useRef(0);
  const requestInFlight = useRef(false);

  const load = useCallback(async (silent = false) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    const requestId = ++requestSequence.current;
    if (!silent) setLoading(true);
    try {
      const { data: response } = await http.get<TaskCenterResponse>("/tasks", {
        params: { limit: 500, _ts: Date.now() },
        headers: { "Cache-Control": "no-cache" },
      });
      if (requestId !== requestSequence.current) return;
      setData(response);
      setSelectedTask((current) => current ? response.tasks.find((task) => task.name === current.name) ?? current : null);
    } catch (error) {
      if (!silent && requestId === requestSequence.current) message.error(getApiErrorMessage(error));
    } finally {
      requestInFlight.current = false;
      if (!silent && requestId === requestSequence.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const hasRunningTask = Boolean(data?.tasks.some((task) => task.running));
  useEffect(() => {
    const timer = window.setInterval(() => void load(true), hasRunningTask || retrying ? 2000 : 30000);
    return () => window.clearInterval(timer);
  }, [hasRunningTask, load, retrying]);

  const retryTask = async (task: TaskStatus) => {
    const meta = getTaskMeta(task.name);
    setRetrying(task.name);
    setData((current) => current ? {
      ...current,
      tasks: current.tasks.map((item) => item.name === task.name ? { ...item, running: true, last_started: dayjs().format("YYYY-MM-DD HH:mm:ss") } : item),
      summary: { ...current.summary, running: current.summary.running + 1 },
    } : current);
    try {
      const scope = currentStore && task.name !== "inspect" ? `?store_id=${currentStore.id}` : "";
      await http.post(`/system/loops/${task.name}/retry${scope}`, {}, { timeout: 240000 });
      message.success(`${meta.label}执行成功`);
      await load(true);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      await load(true);
    } finally {
      setRetrying(null);
    }
  };

  const openMaintenance = () => {
    const state = data?.maintenance;
    maintenanceForm.setFieldsValue({
      reason: state?.reason || "系统升级与数据维护",
      duration_minutes: state?.ends_at ? Math.max(1, dayjs(state.ends_at).diff(dayjs(), "minute")) : 60,
      pause_tasks: state?.pause_tasks?.length ? state.pause_tasks : DEFAULT_PAUSE_TASKS,
      resume_strategy: state?.resume_strategy || "next_cycle",
    });
    setMaintenanceOpen(true);
  };

  const saveMaintenance = async () => {
    try {
      const values = await maintenanceForm.validateFields();
      setMaintenanceSaving(true);
      await http.put("/system/maintenance", { enabled: true, ...values });
      message.success(data?.maintenance.enabled ? "维护设置已更新" : "已进入维护模式");
      setMaintenanceOpen(false);
      await load(true);
    } catch (error) {
      if ((error as { errorFields?: unknown }).errorFields) return;
      message.error(getApiErrorMessage(error));
    } finally {
      setMaintenanceSaving(false);
    }
  };

  const resumeMaintenance = async () => {
    try {
      setMaintenanceSaving(true);
      await http.put("/system/maintenance", {
        enabled: false,
        reason: data?.maintenance.reason || "",
        duration_minutes: 0,
        pause_tasks: data?.maintenance.pause_tasks || [],
        resume_strategy: data?.maintenance.resume_strategy || "next_cycle",
      });
      message.success(data?.maintenance.resume_strategy === "run_once" ? "维护已结束，符合条件的任务将补跑一次" : "维护已结束，任务将在下个周期恢复");
      await load(true);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setMaintenanceSaving(false);
    }
  };

  const sortedTasks = useMemo(() => [...(data?.tasks ?? [])].sort((left, right) => {
    const priority = { error: 0, running: 1, paused: 2, waiting: 3, success: 4 };
    return priority[taskState(left)] - priority[taskState(right)];
  }), [data?.tasks]);

  const filteredHistory = useMemo(() => (data?.history ?? []).filter((run) => {
    if (taskFilter !== "all" && run.name !== taskFilter) return false;
    if (statusFilter !== "all" && run.status !== statusFilter) return false;
    if (triggerFilter !== "all" && run.trigger !== triggerFilter) return false;
    if (storeFilter !== "all" && run.store_id !== storeFilter) return false;
    return true;
  }), [data?.history, statusFilter, storeFilter, taskFilter, triggerFilter]);

  const currentColumns: TableColumnsType<TaskStatus> = [
    {
      title: "任务",
      key: "task",
      width: 260,
      render: (_, task) => {
        const meta = getTaskMeta(task.name);
        return (
          <div className="ops-task-name">
            <Text strong>{meta.label}</Text>
            <Text type="secondary">{meta.description}</Text>
          </div>
        );
      },
    },
    {
      title: "类型",
      key: "category",
      width: 100,
      render: (_, task) => {
        const category = getTaskMeta(task.name).category;
        return <Tag color={CATEGORY_COLORS[category]}>{category}</Tag>;
      },
    },
    { title: "状态", key: "state", width: 120, render: (_, task) => <TaskStateTag task={task} /> },
    { title: "调度周期", key: "schedule", width: 120, render: (_, task) => getTaskMeta(task.name).schedule },
    {
      title: "最近成功",
      dataIndex: "last_success",
      width: 170,
      render: (value: string | null) => <Text type={value ? undefined : "secondary"}>{formatTime(value)}</Text>,
    },
    {
      title: "最近耗时",
      dataIndex: "last_duration",
      width: 100,
      render: (value: number) => value ? `${value}s` : "—",
    },
    {
      title: "运行统计",
      key: "count",
      width: 120,
      render: (_, task) => <Text type="secondary">成功 {task.success_count ?? 0} / 共 {task.run_count}</Text>,
    },
    {
      title: "操作",
      key: "action",
      fixed: "right",
      width: 150,
      render: (_, task) => {
        const meta = getTaskMeta(task.name);
        const scope = currentStore && task.name !== "inspect" ? currentStore.name : "全部店铺";
        return (
          <Space size={4}>
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setSelectedTask(task)}>详情</Button>
            {meta.retryable ? (
              <Popconfirm
                title={`立即执行${meta.label}？`}
                description={`执行范围：${scope}`}
                okText="立即执行"
                cancelText="取消"
                onConfirm={() => retryTask(task)}
              >
                <Tooltip title={task.paused ? `维护期间已暂停：${data?.maintenance.reason || "系统维护"}` : undefined}>
                  <span>
                    <Button type="link" size="small" icon={<ReloadOutlined />} loading={retrying === task.name} disabled={task.running || task.paused || Boolean(retrying)}>
                      执行
                    </Button>
                  </span>
                </Tooltip>
              </Popconfirm>
            ) : null}
          </Space>
        );
      },
    },
  ];

  const historyColumns: TableColumnsType<TaskRun> = [
    { title: "完成时间", dataIndex: "finished_at", width: 170, render: (value: string) => formatTime(value) },
    { title: "任务", dataIndex: "name", width: 150, render: (value: string) => getTaskMeta(value).label },
    { title: "结果", dataIndex: "status", width: 90, render: (value: TaskRun["status"]) => value === "success" ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag> },
    { title: "触发", dataIndex: "trigger", width: 100, render: (value: TaskRun["trigger"]) => <Tag>{value === "manual" ? "手动" : value === "resume" ? "维护恢复" : "自动"}</Tag> },
    { title: "执行范围", key: "scope", width: 140, render: (_, run) => run.store_name || "全部店铺" },
    { title: "耗时", dataIndex: "duration", width: 90, render: (value: number) => `${value}s` },
    {
      title: "错误信息",
      dataIndex: "error",
      ellipsis: true,
      render: (value: string) => value ? <Tooltip title={value}><Text type="danger">{value}</Text></Tooltip> : <Text type="secondary">—</Text>,
    },
    { title: "操作", key: "action", fixed: "right", width: 80, render: (_, run) => <Button type="link" size="small" onClick={() => setSelectedRun(run)}>详情</Button> },
  ];

  const selectedTaskHistory = selectedTask ? (data?.history ?? []).filter((run) => run.name === selectedTask.name).slice(0, 10) : [];
  const summary = data?.summary;
  const maintenanceState = data?.maintenance;
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";

  return (
    <div>
      <PageHeader
        icon={<ScheduleOutlined />}
        eyebrow="系统调度"
        title="系统任务"
        description="查看后台任务运行状态、执行历史与异常原因"
        extra={(
          <Space>
            {isAdmin ? maintenanceState?.enabled ? (
              <>
                <Button icon={<PauseCircleOutlined />} onClick={openMaintenance}>维护模式设置</Button>
                <Popconfirm title="确认结束维护模式？" description={maintenanceState.resume_strategy === "run_once" ? "恢复后，符合条件的任务会立即补跑一次。" : "任务将在各自下个调度周期恢复。"} onConfirm={resumeMaintenance}>
                  <Button type="primary" icon={<PlayCircleOutlined />} loading={maintenanceSaving}>恢复任务</Button>
                </Popconfirm>
              </>
            ) : <Button icon={<PauseCircleOutlined />} onClick={openMaintenance}>进入维护模式</Button> : null}
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button>
          </Space>
        )}
      />

      {maintenanceState?.enabled ? (
        <Alert
          type="warning"
          showIcon
          message={`后台任务处于维护模式：${maintenanceState.reason || "系统维护"}`}
          description={`已暂停 ${maintenanceState.pause_tasks.length} 项任务；${maintenanceState.ends_at ? `预计 ${formatTime(maintenanceState.ends_at)} 自动恢复` : "需管理员手动恢复"}；恢复后${maintenanceState.resume_strategy === "run_once" ? "符合条件的任务补跑一次" : "等待下个调度周期"}。正在执行的任务不会被中断。`}
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {summary && summary.abnormal > 0 ? (
        <Alert
          type="error"
          showIcon
          message={`${summary.abnormal} 项后台任务异常`}
          description="异常任务已置顶显示。请查看最近错误，完成登录或配置修复后再手动执行。"
          style={{ marginBottom: 16 }}
        />
      ) : null}

      <Row gutter={[14, 14]} className="ops-task-summary-grid">
        <Col xs={12} lg={6}>
          <Card variant="borderless" className="ops-task-summary-card">
            <Statistic title="运行中" value={summary?.running ?? 0} prefix={<CloudSyncOutlined />} suffix="项" />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card variant="borderless" className="ops-task-summary-card ops-task-summary-card--danger">
            <Statistic title="异常任务" value={summary?.abnormal ?? 0} prefix={<ExclamationCircleOutlined />} suffix="项" />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card variant="borderless" className="ops-task-summary-card">
            <Statistic title="今日执行" value={summary?.today_total ?? 0} prefix={<ClockCircleOutlined />} suffix="次" />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card variant="borderless" className="ops-task-summary-card ops-task-summary-card--success">
            <Statistic title="今日成功率" value={summary?.success_rate ?? 0} precision={1} suffix="%" />
          </Card>
        </Col>
      </Row>

      <Card variant="borderless" className="ops-task-panel" title="当前任务" extra={<Text type="secondary">运行中每 2 秒刷新，其余每 30 秒刷新</Text>}>
        <Table<TaskStatus>
          rowKey="name"
          size="middle"
          loading={loading && !data}
          columns={currentColumns}
          dataSource={sortedTasks}
          pagination={false}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="后台任务尚未初始化" /> }}
          scroll={{ x: 1200 }}
          rowClassName={(task) => task.error_count > 0 ? "ops-task-row--error" : ""}
        />
      </Card>

      <Card variant="borderless" className="ops-task-panel" title="执行历史">
        <div className="ops-task-filters">
          <Select
            value={taskFilter}
            onChange={setTaskFilter}
            options={[{ value: "all", label: "全部任务" }, ...Object.entries(TASK_META).map(([value, meta]) => ({ value, label: meta.label }))]}
            style={{ width: 170 }}
          />
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            options={[{ value: "all", label: "全部结果" }, { value: "success", label: "成功" }, { value: "error", label: "失败" }]}
            style={{ width: 120 }}
          />
          <Select
            value={triggerFilter}
            onChange={setTriggerFilter}
            options={[{ value: "all", label: "全部触发方式" }, { value: "auto", label: "自动" }, { value: "manual", label: "手动" }, { value: "resume", label: "维护恢复" }]}
            style={{ width: 140 }}
          />
          <Select
            value={storeFilter}
            onChange={setStoreFilter}
            options={[{ value: "all", label: "全部执行范围" }, ...stores.map((store) => ({ value: store.id, label: store.name }))]}
            style={{ width: 180 }}
          />
          <Text type="secondary">共 {filteredHistory.length} 条</Text>
        </div>
        <Table<TaskRun>
          rowKey="id"
          size="small"
          columns={historyColumns}
          dataSource={filteredHistory}
          pagination={{ defaultPageSize: 20, showSizeChanger: true, pageSizeOptions: [20, 50, 100], showTotal: (count) => `共 ${count} 条` }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无符合条件的执行记录" /> }}
          scroll={{ x: 980 }}
        />
      </Card>

      <Drawer title={selectedTask ? getTaskMeta(selectedTask.name).label : "任务详情"} width={560} open={Boolean(selectedTask)} onClose={() => setSelectedTask(null)}>
        {selectedTask ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            {selectedTask.last_error ? <Alert type="error" showIcon message="最近一次执行失败" description={<Text copyable={{ text: selectedTask.last_error }}>{selectedTask.last_error}</Text>} /> : null}
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="任务状态"><TaskStateTag task={selectedTask} /></Descriptions.Item>
              <Descriptions.Item label="任务类型">{getTaskMeta(selectedTask.name).category}</Descriptions.Item>
              <Descriptions.Item label="调度周期">{getTaskMeta(selectedTask.name).schedule}</Descriptions.Item>
              <Descriptions.Item label="任务说明">{getTaskMeta(selectedTask.name).description}</Descriptions.Item>
              <Descriptions.Item label="最近运行">{formatTime(selectedTask.last_run)}</Descriptions.Item>
              <Descriptions.Item label="最近成功">{formatTime(selectedTask.last_success)}</Descriptions.Item>
              <Descriptions.Item label="最近耗时">{selectedTask.last_duration ? `${selectedTask.last_duration}s` : "—"}</Descriptions.Item>
              <Descriptions.Item label="连续失败">{selectedTask.error_count} 次</Descriptions.Item>
              <Descriptions.Item label="累计执行">{selectedTask.run_count} 次</Descriptions.Item>
            </Descriptions>
            <Text strong>最近执行记录</Text>
            <Table<TaskRun>
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={selectedTaskHistory}
              columns={[
                { title: "完成时间", dataIndex: "finished_at", width: 170, render: (value: string) => formatTime(value) },
                { title: "结果", dataIndex: "status", width: 90, render: (value: TaskRun["status"]) => value === "success" ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag> },
                { title: "触发", dataIndex: "trigger", width: 90, render: (value: TaskRun["trigger"]) => value === "manual" ? "手动" : value === "resume" ? "维护恢复" : "自动" },
                { title: "范围", key: "scope", width: 120, render: (_, run) => run.store_name || "全部店铺" },
                { title: "耗时", dataIndex: "duration", width: 80, render: (value: number) => `${value}s` },
              ]}
              scroll={{ x: 560 }}
            />
          </Space>
        ) : null}
      </Drawer>

      <Drawer title="执行详情" width={520} open={Boolean(selectedRun)} onClose={() => setSelectedRun(null)}>
        {selectedRun ? (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            {selectedRun.error ? <Alert type="error" showIcon message="执行失败" description={<Text copyable={{ text: selectedRun.error }}>{selectedRun.error}</Text>} /> : <Alert type="success" showIcon message="执行成功" />}
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label="任务">{getTaskMeta(selectedRun.name).label}</Descriptions.Item>
              <Descriptions.Item label="执行结果">{selectedRun.status === "success" ? <Tag color="success">成功</Tag> : <Tag color="error">失败</Tag>}</Descriptions.Item>
              <Descriptions.Item label="触发方式">{selectedRun.trigger === "manual" ? "手动执行" : selectedRun.trigger === "resume" ? "维护恢复补跑" : "自动调度"}</Descriptions.Item>
              <Descriptions.Item label="执行范围">{selectedRun.store_name || "全部店铺"}</Descriptions.Item>
              <Descriptions.Item label="开始时间">{formatTime(selectedRun.started_at)}</Descriptions.Item>
              <Descriptions.Item label="完成时间">{formatTime(selectedRun.finished_at)}</Descriptions.Item>
              <Descriptions.Item label="执行耗时">{selectedRun.duration}s</Descriptions.Item>
            </Descriptions>
          </Space>
        ) : null}
      </Drawer>

      <Modal
        title={maintenanceState?.enabled ? "维护模式设置" : "进入维护模式"}
        open={maintenanceOpen}
        onCancel={() => setMaintenanceOpen(false)}
        onOk={saveMaintenance}
        okText={maintenanceState?.enabled ? "保存设置" : "确认进入维护"}
        confirmLoading={maintenanceSaving}
        width={620}
      >
        <Alert type="info" showIcon message="已在执行的任务会继续完成；维护期间不会启动新任务，也不会累计任务失败或发送失败告警。" style={{ marginBottom: 18 }} />
        <Form form={maintenanceForm} layout="vertical">
          <Form.Item name="reason" label="维护原因" rules={[{ required: true, message: "请填写维护原因" }, { max: 200, message: "最多 200 个字符" }]}>
            <Input.TextArea rows={3} placeholder="例如：升级淘宝抓取模块与数据库结构" showCount maxLength={200} />
          </Form.Item>
          <Form.Item name="duration_minutes" label="预计维护时长" rules={[{ required: true }]}>
            <Select options={[
              { value: 30, label: "30 分钟" },
              { value: 60, label: "1 小时" },
              { value: 120, label: "2 小时" },
              { value: 240, label: "4 小时" },
              { value: 0, label: "手动恢复（不自动结束）" },
            ]} />
          </Form.Item>
          <Form.Item name="pause_tasks" label="暂停范围" rules={[{ required: true, message: "请至少选择一项任务" }]}>
            <Checkbox.Group style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "10px 16px" }}>
              {Object.entries(TASK_META).map(([name, meta]) => <Checkbox key={name} value={name}>{meta.label}</Checkbox>)}
            </Checkbox.Group>
          </Form.Item>
          <Form.Item name="resume_strategy" label="恢复策略" rules={[{ required: true }]}>
            <Radio.Group>
              <Space direction="vertical">
                <Radio value="next_cycle">等待各任务的下个调度周期</Radio>
                <Radio value="run_once">立即补跑一次（数据同步、巡检、备份与清理；消息推送仍等待正常时间）</Radio>
              </Space>
            </Radio.Group>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
