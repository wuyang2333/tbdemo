import {
  ApiOutlined,
  ArrowRightOutlined,
  BarChartOutlined,
  CarOutlined,
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
  UserSwitchOutlined,
} from "@ant-design/icons";
import { Button, Col, Row, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import http from "../lib/api";
import { useAuth } from "../lib/auth";
import { BRAND } from "../lib/brand";
import { canAccessModule, MAIN_MODULES, MODULES } from "../lib/modules";

const { Title, Text } = Typography;

type DashboardStats = {
  store_count?: number;
  product_count?: number;
  today_orders?: number;
  today_sales?: number;
  today_visitors?: number;
  pending_shipments?: number;
};

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

type KpiDef = {
  key: keyof DashboardStats;
  label: string;
  icon: ReactNode;
  color: string;
  format: (value: number) => string;
};

const KPI_CARDS: KpiDef[] = [
  { key: "today_sales", label: "今日销售额", icon: <MoneyCollectOutlined />, color: "#ff5000", format: formatMoney },
  { key: "today_orders", label: "今日订单", icon: <ShoppingCartOutlined />, color: "#1677ff", format: formatNumber },
  { key: "pending_shipments", label: "待发货", icon: <CarOutlined />, color: "#722ed1", format: formatNumber },
  { key: "product_count", label: "在售商品", icon: <ShoppingOutlined />, color: "#52c41a", format: formatNumber },
  { key: "today_visitors", label: "今日访客", icon: <EyeOutlined />, color: "#13c2c2", format: formatNumber },
];

const LIVE_MODULES = new Set(["dashboard", "profile", "accounts"]);

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

  const displayName = user?.nickname || user?.username || "运营者";
  const quickModules = MAIN_MODULES.filter((module) => canAccessModule(user, module.id));

  useEffect(() => {
    let cancelled = false;
    http
      .get<DashboardStats>("/dashboard")
      .then((response) => {
        if (!cancelled) setStats(response.data);
      })
      .catch(() => {
        if (!cancelled) setStatsFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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

  const today = now.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" });
  const clock = now.toLocaleTimeString("zh-CN", { hour12: false });
  const statusClass = backendOk === null ? "wait" : backendOk ? "ok" : "err";
  const statusLabel = backendOk === null ? "检测中" : backendOk ? "运行中" : "离线";

  return (
    <div>
      <div className="ops-hero" style={{ borderRadius: 18, padding: "30px 34px" }}>
        <Row align="middle" justify="space-between" gutter={[24, 20]}>
          <Col xs={24} lg={16}>
            <Space size={8} align="center">
              <Text style={{ fontSize: 12, letterSpacing: 2, color: "#ff8a4d", fontWeight: 600 }}>
                {BRAND.eyebrow}
              </Text>
              <span style={{ width: 3, height: 3, borderRadius: "50%", background: "rgba(255,138,77,0.6)" }} />
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
              <span className="ops-pill" style={{ background: "rgba(255,255,255,0.06)" }}>
                <ClockCircleOutlined style={{ color: "#ff8a4d" }} />
                <Text strong style={{ fontSize: 14, fontVariantNumeric: "tabular-nums" }}>
                  {clock}
                </Text>
              </span>
              <Text type="secondary" style={{ fontSize: 13 }}>
                {today}
              </Text>
              <Tag color="orange" style={{ borderRadius: 999, marginInlineEnd: 0 }}>
                框架占位数据
              </Tag>
            </div>
          </Col>
        </Row>
      </div>

      <Row gutter={[16, 16]} style={{ marginTop: 18 }}>
        {KPI_CARDS.map((item) => {
          const raw = stats ? stats[item.key] : undefined;
          const value = typeof raw === "number" ? raw : 0;
          return (
            <Col key={item.key} xs={24} sm={12} md={8} xl={4}>
              <div
                className="ops-kpi-card"
                style={{ "--ops-kpi-color": item.color } as CSSProperties}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span
                    className="ops-kpi-icon"
                    style={{
                      background: `${item.color}1f`,
                      color: item.color,
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
                    较昨日
                  </Text>
                  <Text style={{ fontSize: 12, fontWeight: 600, color: item.color }}>+0.0%</Text>
                </div>
              </div>
            </Col>
          );
        })}
      </Row>

      <Row gutter={[16, 16]} style={{ marginTop: 18 }}>
        <Col xs={24} lg={14}>
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

        <Col xs={24} lg={10}>
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
                  <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer">
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
                  <span className="ops-module-icon" style={{ width: 30, height: 30, borderRadius: 8, fontSize: 14 }}>
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
              borderRadius: 14,
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
    </div>
  );
}
