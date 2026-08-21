import {
  ApiOutlined,
  ArrowRightOutlined,
  BarChartOutlined,
  BellOutlined,
  CarOutlined,
  DownOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DashboardOutlined,
  EyeOutlined,
  FileTextOutlined,
  FundOutlined,
  MoneyCollectOutlined,
  ProfileOutlined,
  RobotOutlined,
  RocketOutlined,
  ScheduleOutlined,
  SettingOutlined,
  ShopOutlined,
  ShoppingCartOutlined,
  ShoppingOutlined,
  TeamOutlined,
  ToolOutlined,
  UpOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Col, Form, Input, message, Modal, Popconfirm, Row, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { StoreBars } from "../components/analytics/analytics-ui";
import http, { getApiErrorMessage } from "../lib/api";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { useAuth } from "../lib/auth";
import { BRAND } from "../lib/brand";
import { canAccessModule, MAIN_MODULES, MODULES } from "../lib/modules";
import type { AnalyticsStoreAgg } from "../types";

const { Title, Text } = Typography;

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
  product_date?: string | null;
};

type AnnouncementItem = { id: number; title: string; content: string; created_at: string };
type NotificationItem = { id: number; title: string; content: string; link: string; type: string; is_read: boolean; created_at: string };
type ChangelogItem = { id: number; version: string; title: string; content: string; created_at: string };
type LoopStatus = {
  name: string;
  last_run: string | null;
  last_success: string | null;
  last_error: string | null;
  error_count: number;
  run_count: number;
  last_duration: number;
  running: boolean;
  last_started: string | null;
};

const LOOP_LABELS: Record<string, string> = {
  inspect: "系统巡检",
  realtime_sync: "实时同步",
  report_push: "日报推送",
  hourly_push: "小时推送",
  promo_daily: "每日补数",
  backup: "数据库备份",
  data_cleanup: "数据清理",
  log_rotate: "日志轮转",
};

function fmtTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const MODULE_ICONS: Record<string, ReactNode> = {
  dashboard: <DashboardOutlined />,
  shop: <ShopOutlined />,
  product: <ShoppingOutlined />,
  order: <ProfileOutlined />,
  customer: <TeamOutlined />,
  analytics: <BarChartOutlined />,
  promotion: <RocketOutlined />,
  content: <FileTextOutlined />,
  monitor: <EyeOutlined />,
  task: <ScheduleOutlined />,
  model: <RobotOutlined />,
  settings: <SettingOutlined />,
  accounts: <UserSwitchOutlined />,
};

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

const LIVE_MODULES = new Set(["dashboard", "profile", "accounts"]);

type WidgetId = "kpis" | "stores" | "shortcuts" | "system" | "notice" | "tasks" | "changelog";
const DEFAULT_WIDGETS: WidgetId[] = ["kpis", "shortcuts", "system", "notice", "tasks", "changelog"];
const WIDGET_OPTIONS: { id: WidgetId; label: string }[] = [
  { id: "kpis", label: "核心指标卡" },
  { id: "stores", label: "按店铺汇总" },
  { id: "shortcuts", label: "快捷入口" },
  { id: "system", label: "系统状态" },
  { id: "notice", label: "公告与通知" },
  { id: "tasks", label: "系统健康与任务状态" },
  { id: "changelog", label: "新功能与更新日志" },
];

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 12) return "早上好";
  if (hour < 14) return "中午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

export function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [statsFailed, setStatsFailed] = useState(false);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [widgets, setWidgets] = useState<WidgetId[] | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [storeSummary, setStoreSummary] = useState<AnalyticsStoreAgg[] | null>(null);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [notices, setNotices] = useState<NotificationItem[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loops, setLoops] = useState<LoopStatus[]>([]);
  const [changelog, setChangelog] = useState<ChangelogItem[]>([]);
  const [changelogOpen, setChangelogOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [changelogSaving, setChangelogSaving] = useState(false);
  const [addChangelogForm] = Form.useForm<{ version: string; title: string; content: string }>();

  const displayName = user?.nickname || user?.username || "运营者";
  const quickModules = MAIN_MODULES.filter((module) => canAccessModule(user, module.id));
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
  }, []);
  useAutoRefresh(loadStats);
  const loadConfig = useCallback(async () => {
    try {
      const { data } = await http.get<{ widgets: WidgetId[] }>("/dashboard/config");
      setWidgets(data.widgets);
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

  useEffect(() => {
    let cancelled = false;
    fetch("/api/health")
      .then((response) => {
        if (!cancelled) setBackendOk(response.ok);
      })
      .catch(() => {
        if (!cancelled) setBackendOk(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadExtras = useCallback(async () => {
    try {
      const [ann, noti, lp, cl] = await Promise.all([
        http.get<{ items: AnnouncementItem[] }>("/announcements/active"),
        http.get<{ items: NotificationItem[]; unread_count: number }>("/notifications"),
        http.get<{ items: LoopStatus[] }>("/system/loops"),
        http.get<{ items: ChangelogItem[] }>("/changelog"),
      ]);
      setAnnouncements(ann.data.items);
      setNotices(noti.data.items);
      setUnreadCount(noti.data.unread_count);
      setLoops(lp.data.items);
      setChangelog(cl.data.items);
    } catch {
      // 卡片降级为占位文案
    }
  }, []);
  useEffect(() => {
    loadExtras();
    const timer = setInterval(loadExtras, 60000);
    return () => clearInterval(timer);
  }, [loadExtras]);

  const markNoticeRead = async (id?: number) => {
    try {
      await http.post("/notifications/read", id ? { id } : {});
      if (id) {
        setNotices((list) => list.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
        setUnreadCount((count) => Math.max(0, count - 1));
      } else {
        setNotices((list) => list.map((n) => ({ ...n, is_read: true })));
        setUnreadCount(0);
      }
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const addChangelog = async (values: { version?: string; title: string; content?: string }) => {
    setChangelogSaving(true);
    try {
      const { data } = await http.post<{ item: ChangelogItem }>("/changelog", {
        version: values.version ?? "",
        title: values.title.trim(),
        content: values.content ?? "",
      });
      setChangelog((list) => [data.item, ...list]);
      setAddOpen(false);
      message.success("更新记录已发布");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setChangelogSaving(false);
    }
  };

  const deleteChangelog = async (id: number) => {
    try {
      await http.delete(`/changelog/${id}`);
      setChangelog((list) => list.filter((item) => item.id !== id));
      message.success("已删除");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const today = now.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
  const clock = now.toLocaleTimeString("zh-CN", { hour12: false });
  const statusClass = backendOk === null ? "wait" : backendOk ? "ok" : "err";
  const statusLabel = backendOk === null ? "检测中" : backendOk ? "运行中" : "离线";

  return (
    <div>
      <div className="ops-hero" style={{ borderRadius: "var(--ops-radius-lg)", padding: "30px 34px" }}>
        <Row align="middle" justify="space-between" gutter={[24, 20]}>
          <Col xs={24} lg={16}>
            <Space size={8} align="center">
              <Text style={{ fontSize: 12, letterSpacing: 2, color: "var(--ops-text-secondary)", fontWeight: 500 }}>
                {BRAND.eyebrow}
              </Text>
              <span style={{ width: 3, height: 3, borderRadius: "50%", background: "var(--ops-border-strong)" }} />
              <Text style={{ fontSize: 12, color: "var(--ops-text-secondary)" }}>{BRAND.tagline}</Text>
            </Space>
            <Title level={2} style={{ margin: "10px 0 6px" }}>
              {greeting()}，{displayName}
            </Title>
            <Text type="secondary" style={{ fontSize: 14 }}>
              欢迎回来，今天也一起把店铺经营得更好。
            </Text>
            <div style={{ marginTop: 22 }}>
              <Space wrap>
                {canAccessModule(user, "analytics") && (
                  <Button type="primary" icon={<BarChartOutlined />} onClick={() => navigate("/analytics")}>
                    查看数据洞察
                  </Button>
                )}
                {canAccessModule(user, "promotions") && (
                  <Button icon={<RocketOutlined />} onClick={() => navigate("/promotions")}>
                    推广管理
                  </Button>
                )}
              </Space>
            </div>
          </Col>
          <Col xs={24} lg={8}>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-end",
                gap: 8,
              }}
            >
              <span className="ops-pill">
                <ClockCircleOutlined style={{ color: "var(--ops-accent)" }} />
                <Text strong style={{ fontSize: 14, fontVariantNumeric: "tabular-nums" }}>
                  {clock}
                </Text>
              </span>
              <Text type="secondary" style={{ fontSize: 13 }}>
                {today}
              </Text>
              <Tag
                color={stats?.data_date ? "green" : "default"}
                style={{ borderRadius: 999, marginInlineEnd: 0 }}
              >
                {stats?.data_date
                  ? `数据截至 ${stats.data_date}${stats.hour_until ? ` ${stats.hour_until}` : ""}`
                  : "暂无数据"}
              </Tag>
              {widgets && (
                <Button size="small" icon={<SettingOutlined />} onClick={() => setConfigOpen(true)}>
                  自定义看板
                </Button>
              )}
            </div>
          </Col>
        </Row>
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("kpis"), display: widgetOn("kpis") ? undefined : "none" }}>
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
          const changeColor = isUp ? "var(--ops-up)" : isDown ? "var(--ops-down)" : "var(--ops-text-secondary)";
          return (
            <Col key={item.key} xs={24} sm={12} md={8} xl={4}>
              <div className="ops-kpi-card">
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span
                    className="ops-kpi-icon"
                    style={{
                      background: "var(--ops-accent-soft)",
                      color: "var(--ops-accent)",
                    }}
                  >
                    {item.icon}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 21,
                        fontWeight: 800,
                        lineHeight: 1.2,
                        letterSpacing: "-0.02em",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {statsFailed ? "—" : item.format(value)}
                    </div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {item.label}
                    </Text>
                  </div>
                </div>
                <div
                  style={{
                    marginTop: 14,
                    paddingTop: 12,
                    borderTop: "1px solid var(--ops-border)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                  }}
                >
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {item.compareKey ? "较昨日" : "最新"}
                  </Text>
                  <Text style={{ fontSize: 12, fontWeight: 600, color: changeColor }}>{change}</Text>
                </div>
              </div>
            </Col>
          );
        })}
      </Row>

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

      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("shortcuts"), display: widgetOn("shortcuts") ? undefined : "none" }}>
        <Col span={24}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12 }}>
            <Text strong style={{ fontSize: 16 }}>
              快捷入口
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              常用模块一键直达
            </Text>
          </div>
          <Row gutter={[12, 12]}>
            {quickModules.map((module) => {
              const icon = MODULE_ICONS[module.icon];
              return (
                <Col key={module.id} xs={12} sm={8} md={8} lg={6}>
                  <div className="ops-module-card" onClick={() => navigate(`/${module.id}`)}>
                    <Space size={10} align="center">
                      <span className="ops-module-icon">{icon}</span>
                      <Text strong style={{ fontSize: 14 }}>
                        {module.name}
                      </Text>
                    </Space>
                    <Text
                      type="secondary"
                      style={{
                        fontSize: 12,
                        display: "block",
                        marginTop: 10,
                        lineHeight: "18px",
                        minHeight: 36,
                        paddingRight: 12,
                      }}
                    >
                      {module.description}
                    </Text>
                    <span className="ops-module-arrow">
                      <ArrowRightOutlined />
                    </span>
                  </div>
                </Col>
              );
            })}
          </Row>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("system"), display: widgetOn("system") ? undefined : "none" }}>
        <Col span={24}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 12 }}>
            <Text strong style={{ fontSize: 16 }}>
              系统状态
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              服务与运行情况
            </Text>
          </div>
          <div className="ops-kpi-card" style={{ padding: "6px 20px" }}>
            {[
              {
                icon: <ApiOutlined />,
                label: "后端服务",
                right: (
                  <span className="ops-pill">
                    <span className={`ops-dot ops-dot--${statusClass}`} />
                    {statusLabel}
                  </span>
                ),
              },
              {
                icon: <FundOutlined />,
                label: "接口文档",
                right: (
                  <a href="http://127.0.0.1:8008/docs" target="_blank" rel="noreferrer">
                    Swagger UI <ArrowRightOutlined style={{ fontSize: 11 }} />
                  </a>
                ),
              },
              {
                icon: <DashboardOutlined />,
                label: "已注册模块",
                right: <Text strong>{MODULES.length} 个</Text>,
              },
              {
                icon: <ClockCircleOutlined />,
                label: "当前时间",
                right: (
                  <Text strong style={{ fontVariantNumeric: "tabular-nums" }}>
                    {clock}
                  </Text>
                ),
              },
            ].map((row, index) => (
              <div
                key={row.label}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "14px 0",
                  borderBottom: index < 3 ? "1px solid var(--ops-border)" : "none",
                }}
              >
                <Space size={10} align="center">
                  <span className="ops-module-icon" style={{ width: 30, height: 30, borderRadius: "var(--ops-radius-sm)", fontSize: 14 }}>
                    {row.icon}
                  </span>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    {row.label}
                  </Text>
                </Space>
                {row.right}
              </div>
            ))}
          </div>

          <div style={{ display: "flex", alignItems: "baseline", gap: 10, margin: "20px 0 12px" }}>
            <Text strong style={{ fontSize: 16 }}>
              功能规划
            </Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {LIVE_MODULES.size} 个模块已上线，其余开发中
            </Text>
          </div>
          <div
            style={{
              border: "1px solid var(--ops-border)",
              borderRadius: "var(--ops-radius-lg)",
              background: "var(--ops-card-bg)",
              boxShadow: "var(--ops-shadow-sm)",
              padding: "14px 18px",
              display: "flex",
              flexWrap: "wrap",
              gap: 8,
            }}
          >
            {MODULES.map((module) => {
              const live = LIVE_MODULES.has(module.id);
              return (
                <Tag
                  key={module.id}
                  icon={live ? <CheckCircleOutlined /> : <ToolOutlined />}
                  color={live ? "success" : "default"}
                  style={{ borderRadius: 999, paddingInline: 10, marginInlineEnd: 0 }}
                >
                  {module.name}
                </Tag>
              );
            })}
          </div>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("notice"), display: widgetOn("notice") ? undefined : "none" }}>
        <Col span={24}>
          <div className="ops-kpi-card" style={{ padding: "20px 22px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <Space size={8} align="center">
                <BellOutlined style={{ color: "var(--ops-accent)" }} />
                <Text strong style={{ fontSize: 16 }}>公告与通知</Text>
              </Space>
              {unreadCount > 0 && <Tag color="red" style={{ borderRadius: 999, marginInlineEnd: 0 }}>{unreadCount} 条未读</Tag>}
              <div style={{ flex: 1 }} />
              <Button size="small" type="link" disabled={unreadCount === 0} onClick={() => markNoticeRead()}>
                全部已读
              </Button>
            </div>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>最新公告</Text>
                {announcements.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 13 }}>暂无公告</Text>
                ) : (
                  <Space direction="vertical" size={6} style={{ width: "100%" }}>
                    {announcements.slice(0, 3).map((item) => (
                      <div key={item.id} style={{ borderBottom: "1px solid var(--ops-border)", paddingBottom: 8 }}>
                        <Text strong style={{ fontSize: 13 }}>{item.title}</Text>
                        <div>
                          <Text type="secondary" style={{ fontSize: 12 }}>{item.content || "—"}</Text>
                          <Text type="secondary" style={{ fontSize: 11, marginLeft: 8 }}>{fmtTime(item.created_at)}</Text>
                        </div>
                      </div>
                    ))}
                  </Space>
                )}
              </Col>
              <Col xs={24} md={12}>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>我的通知</Text>
                {notices.length === 0 ? (
                  <Text type="secondary" style={{ fontSize: 13 }}>暂无通知</Text>
                ) : (
                  <Space direction="vertical" size={6} style={{ width: "100%" }}>
                    {notices.slice(0, 5).map((item) => (
                      <div
                        key={item.id}
                        onClick={() => { if (!item.is_read) markNoticeRead(item.id); }}
                        style={{ borderBottom: "1px solid var(--ops-border)", paddingBottom: 8, cursor: item.is_read ? "default" : "pointer" }}
                      >
                        <Space size={6} align="center">
                          {!item.is_read && <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--ops-danger)", display: "inline-block" }} />}
                          <Text strong style={{ fontSize: 13, color: item.is_read ? "var(--ops-text-secondary)" : undefined }}>{item.title}</Text>
                          <Text type="secondary" style={{ fontSize: 11 }}>{fmtTime(item.created_at)}</Text>
                        </Space>
                        {item.content ? (
                          <div style={{ paddingLeft: 12 }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>{item.content}</Text>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </Space>
                )}
              </Col>
            </Row>
          </div>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("tasks"), display: widgetOn("tasks") ? undefined : "none" }}>
        <Col span={24}>
          <div className="ops-kpi-card" style={{ padding: "20px 22px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <Space size={8} align="center">
                <ApiOutlined style={{ color: "var(--ops-accent)" }} />
                <Text strong style={{ fontSize: 16 }}>系统健康与任务状态</Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>后台任务运行情况（每 60 秒刷新）</Text>
            </div>
            <Row gutter={[12, 12]}>
              {loops.length === 0 ? (
                <Col span={24}><Text type="secondary">暂无任务数据</Text></Col>
              ) : (
                loops.map((loop) => {
                  const dotClass = loop.running ? "wait" : loop.error_count > 0 ? "err" : "ok";
                  const healthy = !loop.running && loop.error_count === 0;
                  return (
                    <Col xs={24} sm={12} lg={8} key={loop.name}>
                      <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "12px 14px" }}>
                        <Space size={8} align="center">
                          <span className={`ops-dot ops-dot--${dotClass}`} />
                          <Text strong style={{ fontSize: 13 }}>{LOOP_LABELS[loop.name] ?? loop.name}</Text>
                          {loop.running ? <Tag color="blue" style={{ borderRadius: 999, marginInlineEnd: 0 }}>运行中</Tag> : null}
                          {!healthy && loop.error_count > 0 ? <Tag color="red" style={{ borderRadius: 999, marginInlineEnd: 0 }}>异常</Tag> : null}
                        </Space>
                        <div style={{ marginTop: 8, fontSize: 12, color: "var(--ops-text-secondary)" }}>
                          最近成功 {fmtTime(loop.last_success)}
                        </div>
                        <div style={{ fontSize: 12, color: healthy ? "var(--ops-text-secondary)" : "var(--ops-danger)" }}>
                          {loop.error_count > 0
                            ? `连续失败 ${loop.error_count} 次${loop.last_error ? `：${loop.last_error}` : ""}`
                            : `运行 ${loop.run_count} 次 · 最近耗时 ${loop.last_duration}s`}
                        </div>
                      </div>
                    </Col>
                  );
                })
              )}
            </Row>
          </div>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 18, order: widgetOrder("changelog"), display: widgetOn("changelog") ? undefined : "none" }}>
        <Col span={24}>
          <div className="ops-kpi-card" style={{ padding: "20px 22px" }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
              <Space size={8} align="center">
                <RocketOutlined style={{ color: "var(--ops-accent)" }} />
                <Text strong style={{ fontSize: 16 }}>新功能与更新日志</Text>
              </Space>
              <Text type="secondary" style={{ fontSize: 12 }}>系统最近更新</Text>
              <div style={{ flex: 1 }} />
              <Button size="small" type="link" onClick={() => setChangelogOpen(true)}>查看全部</Button>
              {(user?.role === "admin" || user?.role === "super_admin") && (
                <Button size="small" icon={<RocketOutlined />} onClick={() => { addChangelogForm.resetFields(); setAddOpen(true); }}>
                  新增记录
                </Button>
              )}
            </div>
            {changelog.length === 0 ? (
              <Text type="secondary">暂无更新记录</Text>
            ) : (
              <Space direction="vertical" size={8} style={{ width: "100%" }}>
                {changelog.slice(0, 3).map((item) => (
                  <div key={item.id} style={{ borderBottom: "1px solid var(--ops-border)", paddingBottom: 10 }}>
                    <Space size={8} align="center">
                      {item.version ? <Tag color="orange" style={{ borderRadius: 999, marginInlineEnd: 0 }}>{item.version}</Tag> : null}
                      <Text strong style={{ fontSize: 14 }}>{item.title}</Text>
                      <Text type="secondary" style={{ fontSize: 11 }}>{fmtTime(item.created_at)}</Text>
                    </Space>
                    {item.content ? (
                      <div style={{ marginTop: 4, paddingLeft: item.version ? 4 : 0 }}>
                        <Text type="secondary" style={{ fontSize: 13, whiteSpace: "pre-line" }}>{item.content}</Text>
                      </div>
                    ) : null}
                  </div>
                ))}
              </Space>
            )}
          </div>
        </Col>
      </Row>
      </div>

      <Modal title="新功能与更新日志" open={changelogOpen} onCancel={() => setChangelogOpen(false)} footer={null} width={620}>
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          {changelog.length === 0 ? (
            <Text type="secondary">暂无更新记录</Text>
          ) : (
            changelog.map((item) => (
              <div key={item.id} style={{ borderBottom: "1px solid var(--ops-border)", paddingBottom: 10 }}>
                <Space size={8} align="center">
                  {item.version ? <Tag color="orange" style={{ borderRadius: 999, marginInlineEnd: 0 }}>{item.version}</Tag> : null}
                  <Text strong style={{ fontSize: 14 }}>{item.title}</Text>
                  <Text type="secondary" style={{ fontSize: 11 }}>{fmtTime(item.created_at)}</Text>
                  {(user?.role === "admin" || user?.role === "super_admin") && (
                    <Popconfirm title="删除这条更新记录？" okText="删除" okButtonProps={{ danger: true }} onConfirm={() => deleteChangelog(item.id)}>
                      <Button size="small" type="text" danger>删除</Button>
                    </Popconfirm>
                  )}
                </Space>
                {item.content ? (
                  <div style={{ marginTop: 4 }}>
                    <Text type="secondary" style={{ fontSize: 13, whiteSpace: "pre-line" }}>{item.content}</Text>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </Space>
      </Modal>

      <Modal title="新增更新记录" open={addOpen} onOk={() => addChangelogForm.submit()} onCancel={() => setAddOpen(false)} confirmLoading={changelogSaving} okText="保存">
        <Form form={addChangelogForm} layout="vertical" onFinish={addChangelog} style={{ marginTop: 8 }}>
          <Form.Item name="version" label="版本号（可选）">
            <Input placeholder="如 0.2.0" maxLength={30} />
          </Form.Item>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: "请输入标题" }, { max: 100, message: "标题不能超过 100 字" }]}>
            <Input placeholder="本次更新内容一句话" />
          </Form.Item>
          <Form.Item name="content" label="详情（可选）">
            <Input.TextArea rows={4} placeholder="详细说明，支持换行" maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>

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
    </div>
  );
}

