import {
  ArrowRightOutlined,
  CarOutlined,
  DownOutlined,
  CheckCircleOutlined,
  EyeOutlined,
  FundOutlined,
  MoneyCollectOutlined,
  SettingOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  UpOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Col, message, Modal, Row, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { StoreBars } from "../components/analytics/analytics-ui";
import { DecisionBand, WorkspacePage } from "../components/ui/workspace-template";
import http, { getApiErrorMessage } from "../lib/api";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { useAuth } from "../lib/auth";
import { useStores } from "../lib/store";
import type { AnalyticsStoreAgg } from "../types";

const { Text } = Typography;

type DashboardStats = {
  store_count?: number;
  product_count?: number;
  today_orders?: number;
  today_sales?: number;
  today_visitors?: number;
  yesterday_orders?: number;
  yesterday_sales?: number;
  yesterday_visitors?: number;
  today_real_roi?: number | null;
  yesterday_real_roi?: number | null;
  pending_shipments?: number;
  data_date?: string | null;
  hour_until?: string | null;
  compare_mode?: string;
  operational_updated_at?: string | null;
  operational_stale?: boolean;
};

type DashboardTodo = {
  key: string;
  module: string;
  category: "礼品单" | "评价" | "推广" | "店铺" | "系统";
  severity: "critical" | "warning" | "info";
  title: string;
  description: string;
  count: number;
  route: string;
  external_url: string;
  retryable: boolean;
  retry_task: string;
  store_id: number | null;
  store_name: string;
  updated_at: string | null;
  snoozed: boolean;
  snoozed_until: string | null;
};
type DashboardTodoResponse = {
  items: DashboardTodo[];
  summary: { urgent: number; pending: number; snoozed: number };
};
function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatMoney(value: number): string {
  return "¥" + value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatNumber(value: number): string {
  return value.toLocaleString("zh-CN");
}

function formatChange(current: number | undefined, previous: number | undefined): string {
  if (typeof current !== "number" || typeof previous !== "number" || previous === 0) {
    return current ? "新增" : "—";
  }
  const pct = ((current - previous) / previous) * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}

function greetingForHour(hour: number): string {
  if (hour < 6) return "夜深了";
  if (hour < 11) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

type KpiDef = {
  key: keyof DashboardStats;
  label: string;
  icon: ReactNode;
  format: (value: number) => string;
  compareKey?: "yesterday_sales" | "yesterday_orders" | "yesterday_visitors" | "yesterday_real_roi";
  ratio?: boolean;
};

const KPI_CARDS: KpiDef[] = [
  { key: "today_sales", label: "销售额", icon: <MoneyCollectOutlined />, format: formatMoney, compareKey: "yesterday_sales" },
  { key: "today_orders", label: "订单数", icon: <ShoppingCartOutlined />, format: formatNumber, compareKey: "yesterday_orders" },
  { key: "pending_shipments", label: "待发货", icon: <CarOutlined />, format: formatNumber },
  { key: "product_count", label: "在售商品", icon: <ShoppingOutlined />, format: formatNumber },
  { key: "today_visitors", label: "访客数", icon: <EyeOutlined />, format: formatNumber, compareKey: "yesterday_visitors" },
  { key: "today_real_roi", label: "真实ROI", icon: <FundOutlined />, format: (value) => (value > 0 ? value.toFixed(2) : "—"), compareKey: "yesterday_real_roi", ratio: true },
];

type WidgetId = "actions" | "kpis" | "stores";
const DEFAULT_WIDGETS: WidgetId[] = ["actions", "kpis"];
const WIDGET_OPTIONS: { id: WidgetId; label: string }[] = [
  { id: "actions", label: "今日待办中心" },
  { id: "kpis", label: "核心指标卡" },
  { id: "stores", label: "按店铺汇总" },
];

export function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { currentStore } = useStores();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [statsFailed, setStatsFailed] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const [widgets, setWidgets] = useState<WidgetId[] | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [storeSummary, setStoreSummary] = useState<AnalyticsStoreAgg[] | null>(null);
  const [todos, setTodos] = useState<DashboardTodo[]>([]);
  const [todoSummary, setTodoSummary] = useState({ urgent: 0, pending: 0, snoozed: 0 });
  const [todoCategory, setTodoCategory] = useState("全部");
  const [showAllTodos, setShowAllTodos] = useState(false);
  const [todoBusy, setTodoBusy] = useState<string | null>(null);

  const widgetOrder = (id: WidgetId) => {
    const list = widgets ?? DEFAULT_WIDGETS;
    const index = list.indexOf(id);
    return index < 0 ? 99 : index;
  };
  const widgetOn = (id: WidgetId) => !widgets || widgets.includes(id);
  const toggleWidget = (id: WidgetId, checked: boolean) => {
    setWidgets((current) => {
      const list = current ?? [...DEFAULT_WIDGETS];
      if (checked) return list.includes(id) ? list : [...list, id];
      return list.filter((widget) => widget !== id);
    });
  };
  const moveWidget = (id: WidgetId, dir: -1 | 1) => {
    setWidgets((current) => {
      const list = [...(current ?? [...DEFAULT_WIDGETS])];
      const index = list.indexOf(id);
      const next = index + dir;
      if (index < 0 || next < 0 || next >= list.length) return list;
      [list[index], list[next]] = [list[next], list[index]];
      return list;
    });
  };
  const resetWidgets = () => setWidgets([...DEFAULT_WIDGETS]);
  const saveWidgets = async () => {
    if (!widgets) return;
    try {
      await http.put("/dashboard/config", { widgets });
      message.success("看板配置已保存");
      setConfigOpen(false);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const loadStats = useCallback(async () => {
    try {
      const { data } = await http.get<DashboardStats>("/dashboard");
      setStats(data);
    } catch {
      setStatsFailed(true);
    }
  }, [currentStore?.id]);
  useAutoRefresh(loadStats);
  const loadConfig = useCallback(async () => {
    try {
      const { data } = await http.get<{ widgets: WidgetId[] }>("/dashboard/config");
      const supported = new Set<WidgetId>(WIDGET_OPTIONS.map((item) => item.id));
      const migrated = data.widgets.filter((item): item is WidgetId => supported.has(item));
      setWidgets(migrated.includes("actions") ? migrated : ["actions", ...migrated]);
    } catch {
      setWidgets([...DEFAULT_WIDGETS]);
    }
  }, []);
  useEffect(() => {
    loadConfig();
  }, [loadConfig]);
  useEffect(() => {
    if (widgets?.includes("stores")) {
      http
        .get<{ by_store: AnalyticsStoreAgg[] }>("/analytics/summary?days=14")
        .then(({ data }) => setStoreSummary(data.by_store))
        .catch(() => setStoreSummary([]));
    } else {
      setStoreSummary(null);
    }
  }, [widgets]);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const loadTodos = useCallback(async () => {
    try {
      const { data } = await http.get<DashboardTodoResponse>("/dashboard/todos");
      setTodos(data.items);
      setTodoSummary(data.summary);
    } catch {
      setTodos([]);
      setTodoSummary({ urgent: 0, pending: 0, snoozed: 0 });
    }
  }, [currentStore?.id]);
  useEffect(() => {
    void loadTodos();
    const timer = window.setInterval(() => void loadTodos(), 60000);
    return () => window.clearInterval(timer);
  }, [loadTodos]);

  const snoozeTodo = async (todo: DashboardTodo) => {
    setTodoBusy(todo.key);
    try {
      await http.post(`/dashboard/todos/${encodeURIComponent(todo.key)}/snooze`, { minutes: 60 });
      message.success("已稍后 1 小时提醒");
      await loadTodos();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTodoBusy(null);
    }
  };

  const retryTodo = async (todo: DashboardTodo) => {
    if (!todo.retry_task) return;
    setTodoBusy(todo.key);
    try {
      const scope = currentStore?.id && todo.retry_task !== "inspect" ? `?store_id=${currentStore.id}` : "";
      await http.post(`/system/loops/${todo.retry_task}/retry${scope}`, {}, { timeout: 240000 });
      message.success("后台任务重试成功");
      await loadTodos();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTodoBusy(null);
    }
  };

  const today = now.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
  const displayName = user?.nickname || user?.username || "运营者";
  const todoCategories = ["全部", "礼品单", "评价", "推广", "店铺", "系统", "已稍后"];
  const filteredTodos = todos.filter((todo) => {
    if (todoCategory === "已稍后") return todo.snoozed;
    if (todo.snoozed) return false;
    return todoCategory === "全部" || todo.category === todoCategory;
  });
  const visibleTodos = showAllTodos ? filteredTodos : filteredTodos.slice(0, 5);
  const primaryTodo = todos.find((todo) => !todo.snoozed);
  const decisionTitle = primaryTodo
    ? `今天先处理：${primaryTodo.title}`
    : statsFailed
      ? "经营数据暂不可用，建议先检查数据同步"
      : "当前没有高优先级异常，可以按计划推进经营动作";
  const decisionDescription = primaryTodo?.description
    || `今日销售 ${formatMoney(stats?.today_sales ?? 0)}，真实 ROI ${stats?.today_real_roi?.toFixed(2) ?? "—"}，待发货 ${stats?.pending_shipments ?? 0} 单。`;

  return (
    <WorkspacePage kind="cockpit" className="ops-dashboard-v2">
      <header className="ops-dashboard-v2__head">
        <div className="ops-dashboard-v2__intro">
          <span className="ops-dashboard-v2__eyebrow">经营总览</span>
          <h1 className="ops-dashboard-v2__welcome">{greetingForHour(now.getHours())}，{displayName}</h1>
          <p className="ops-dashboard-v2__subtitle">欢迎回来。先看清今天的经营重点，再开始处理。</p>
          <div className="ops-dashboard-v2__meta">
            <span>{today}</span>
            <span aria-hidden="true">·</span>
            <span>数据截至 {stats?.data_date ? `${stats.data_date}${stats.hour_until ? ` ${stats.hour_until}` : ""}` : "暂无数据"}</span>
          </div>
        </div>
        {widgets ? <Button icon={<SettingOutlined />} onClick={() => setConfigOpen(true)}>配置页面</Button> : null}
      </header>

      <DecisionBand
        ariaLabel="今日经营结论"
        eyebrow="经营结论 · 优先动作"
        title={decisionTitle}
        description={decisionDescription}
        action={primaryTodo && (primaryTodo.route || primaryTodo.external_url) ? (
          <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => primaryTodo.external_url ? window.open(primaryTodo.external_url, "_blank", "noopener,noreferrer") : navigate(primaryTodo.route)}>
            处理首要事项
          </Button>
        ) : <Button onClick={() => navigate("/analytics/overview")}>查看经营数据</Button>}
      />

      <div style={{ display: "flex", flexDirection: "column" }}>
      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("actions"), display: widgetOn("actions") ? undefined : "none" }}>
        <Col span={24}>
          <div className="ops-action-center">
            <div className="ops-action-center__head">
              <Text strong style={{ fontSize: 16 }}>今日待办</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>未解决事项持续保留，按风险优先处理</Text>
              <div style={{ flex: 1 }} />
              <Tag color={todoSummary.urgent > 0 ? "red" : "default"}>紧急 {todoSummary.urgent}</Tag>
              <Tag color={todoSummary.pending > 0 ? "orange" : "green"}>待处理 {todoSummary.pending}</Tag>
              <Tag color="blue">已稍后 {todoSummary.snoozed}</Tag>
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", padding: "2px 18px 12px" }}>
              {todoCategories.map((category) => (
                <Button key={category} size="small" type={todoCategory === category ? "primary" : "default"} onClick={() => { setTodoCategory(category); setShowAllTodos(false); }}>
                  {category}
                </Button>
              ))}
            </div>
            {visibleTodos.length === 0 ? (
              <div style={{ padding: "18px", borderTop: "1px solid var(--ops-border)" }}>
                <Space><CheckCircleOutlined style={{ color: "var(--ops-success)" }} /><Text type="secondary">{todoCategory === "已稍后" ? "当前没有稍后提醒" : "当前没有需要处理的事项"}</Text></Space>
              </div>
            ) : visibleTodos.map((todo) => (
              <div className="ops-action-item" key={todo.key}>
                <span className={`ops-action-item__signal is-${todo.severity}`} aria-label={todo.severity === "critical" ? "紧急" : todo.severity === "warning" ? "关注" : "提醒"} />
                <div style={{ minWidth: 0 }}>
                  <Space size={6} wrap>
                    <Text strong>{todo.title}</Text>
                    <Tag>{todo.category}</Tag>
                    {todo.store_name ? <Tag color="blue">{todo.store_name}</Tag> : null}
                    {todo.snoozed_until ? <Tag color="cyan">提醒于 {fmtTime(todo.snoozed_until)}</Tag> : null}
                  </Space>
                  <Text type="secondary" style={{ display: "block", fontSize: 12 }}>{todo.description}</Text>
                  <Text type="secondary" style={{ display: "block", fontSize: 11 }}>最近检查 {fmtTime(todo.updated_at)}</Text>
                </div>
                <Space size={6} wrap style={{ justifyContent: "flex-end" }}>
                  {todo.retryable ? <Button size="small" loading={todoBusy === todo.key} onClick={() => void retryTodo(todo)}>立即重试</Button> : null}
                  {!todo.snoozed ? <Button size="small" loading={todoBusy === todo.key} onClick={() => void snoozeTodo(todo)}>稍后提醒</Button> : null}
                  {(todo.route || todo.external_url) ? (
                    <Button
                      size="small"
                      type="primary"
                      icon={<ArrowRightOutlined />}
                      onClick={() => todo.external_url ? window.open(todo.external_url, "_blank", "noopener,noreferrer") : navigate(todo.route)}
                    >
                      去处理
                    </Button>
                  ) : null}
                </Space>
              </div>
            ))}
            {filteredTodos.length > 5 ? (
              <div style={{ padding: "10px 18px", borderTop: "1px solid var(--ops-border)", textAlign: "center" }}>
                <Button type="link" size="small" onClick={() => setShowAllTodos((value) => !value)}>{showAllTodos ? "收起" : `查看全部 ${filteredTodos.length} 项`}</Button>
              </div>
            ) : null}
          </div>
        </Col>
      </Row>
      <div className="ops-metric-rail" style={{ marginTop: 16, order: widgetOrder("kpis"), display: widgetOn("kpis") ? undefined : "none" }}>
        {KPI_CARDS.map((item) => {
          const raw = stats ? stats[item.key] : undefined;
          const value = typeof raw === "number" ? raw : 0;
          const prev = item.compareKey && stats ? stats[item.compareKey] : undefined;
          const change = statsFailed
            ? "—"
            : item.ratio && (value <= 0 || typeof prev !== "number" || prev <= 0)
              ? "—"
              : formatChange(value, typeof prev === "number" ? prev : undefined);
          const isUp = change.startsWith("+");
          const isDown = change.startsWith("-");
          const isOperational = item.key === "pending_shipments" || item.key === "product_count";
          const changeColor = isUp ? "var(--ops-up)" : isDown ? "var(--ops-down)" : "var(--ops-text-secondary)";
          return (
            <div className="ops-metric-rail__item" key={item.key}>
              <span className="ops-metric-rail__label">{item.label}</span>
              <span className="ops-metric-rail__value">{statsFailed ? "—" : item.format(value)}</span>
              {isOperational && stats?.operational_stale && stats.operational_updated_at ? (
                <span className="ops-metric-rail__hint" style={{ color: "var(--ops-warn)" }}>数据可能已过期</span>
              ) : (
                <span className="ops-metric-rail__hint">{item.compareKey ? "较昨日 " : ""}<b style={{ color: changeColor }}>{change}</b></span>
              )}
            </div>
          );
        })}
      </div>

      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("stores"), display: widgetOn("stores") ? undefined : "none" }}>
        <Col span={24}>
          <div className="ops-kpi-card" style={{ padding: "20px 22px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <Text strong style={{ fontSize: 16 }}>按店铺汇总</Text>
              <Text type="secondary" style={{ fontSize: 12 }}>各店铺累计销售额 / 订单 / 访客</Text>
            </div>
            {storeSummary ? (
              storeSummary.length > 0 ? (
                <StoreBars items={storeSummary} />
              ) : (
                <Text type="secondary">暂无店铺数据</Text>
              )
            ) : (
              <Text type="secondary">加载中…</Text>
            )}
          </div>
        </Col>
      </Row>

      </div>

      <Modal title="自定义看板" open={configOpen} onCancel={() => { setConfigOpen(false); loadConfig(); }} onOk={saveWidgets} okText="保存" width={440}>
        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
          {(widgets ?? []).map((id, index) => (
            <div key={id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 10px", border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)" }}>
              <Checkbox checked onChange={(event) => toggleWidget(id, event.target.checked)} />
              <Text style={{ flex: 1 }}>{WIDGET_OPTIONS.find((widget) => widget.id === id)?.label ?? id}</Text>
              <Button size="small" type="text" icon={<UpOutlined />} disabled={index === 0} onClick={() => moveWidget(id, -1)} />
              <Button size="small" type="text" icon={<DownOutlined />} disabled={index === (widgets?.length ?? 0) - 1} onClick={() => moveWidget(id, 1)} />
            </div>
          ))}
          <Button size="small" type="link" onClick={resetWidgets} style={{ alignSelf: "flex-start", paddingInline: 6 }}>
            恢复默认
          </Button>
        </Space>
      </Modal>
    </WorkspacePage>
  );
}

