import {
  BarChartOutlined,
  BellOutlined,
  DashboardOutlined,
  EyeOutlined,
  FileTextOutlined,
  HistoryOutlined,
  IdcardOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  ProfileOutlined,
  RobotOutlined,
  RocketOutlined,
  ScheduleOutlined,
  SearchOutlined,
  SettingOutlined,
  ShopOutlined,
  ShoppingOutlined,
  SunOutlined,
  TeamOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Dropdown, Input, Layout, Menu, Select, Space, Tooltip, Typography } from "antd";
import type { MenuProps } from "antd";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useThemeMode } from "../../app/providers";
import { useAuth } from "../../lib/auth";
import { BRAND } from "../../lib/brand";
import { canAccessModule, FOOTER_MODULES, getModule, MAIN_MODULES, MODULES } from "../../lib/modules";
import { useStores } from "../../lib/store";
import type { ModuleMeta } from "../../types";

const { Sider, Header, Content } = Layout;
const { Text } = Typography;

const ICONS: Record<string, ReactNode> = {
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
  profile: <IdcardOutlined />,
  accounts: <UserSwitchOutlined />,
  logs: <HistoryOutlined />,
};

function toItems(modules: ModuleMeta[]): MenuProps["items"] {
  return modules.map((module) => ({
    key: `/${module.id}`,
    icon: ICONS[module.icon],
    label: module.name,
  }));
}

function useBackendStatus(): boolean | null {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/health", { method: "GET" })
      .then((response) => response.ok)
      .then((value) => {
        if (!cancelled) setOk(value);
      })
      .catch(() => {
        if (!cancelled) setOk(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return ok;
}

export function AppShell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { mode: themeMode, toggle: toggleTheme } = useThemeMode();
  const { user, logout } = useAuth();
  const { stores, currentStore, setCurrent } = useStores();
  const [collapsed, setCollapsed] = useState(false);
  const [keyword, setKeyword] = useState("");
  const backendOk = useBackendStatus();

  const current = getModule(location.pathname.replace(/^\//, ""));
  const selectedKeys = [location.pathname];
  const siderWidth = collapsed ? 72 : 236;
  const displayName = user?.nickname || user?.username || "运营者";

  const mainItems = toItems(MAIN_MODULES.filter((module) => canAccessModule(user, module.id)));
  const footerItems = toItems(FOOTER_MODULES.filter((module) => canAccessModule(user, module.id)));

  const handleMenuClick: MenuProps["onClick"] = ({ key }) => navigate(key);

  const statusClass = backendOk === null ? "wait" : backendOk ? "ok" : "err";
  const statusLabel = backendOk === null ? "连接中" : backendOk ? "服务正常" : "服务离线";

  const handleSearch = () => {
    const query = keyword.trim().toLowerCase();
    if (!query) return;
    const target = MODULES.find(
      (module) =>
        module.name.toLowerCase().includes(query) ||
        module.description.toLowerCase().includes(query) ||
        module.id.includes(query)
    );
    if (target && canAccessModule(user, target.id)) {
      setKeyword("");
      navigate(`/${target.id}`);
    }
  };

  const userMenu: MenuProps["items"] = [
    {
      key: "profile",
      icon: <IdcardOutlined />,
      label: "个人中心",
      onClick: () => navigate("/profile"),
    },
    { type: "divider" },
    {
      key: "logout",
      icon: <LogoutOutlined />,
      label: "退出登录",
      danger: true,
      onClick: () => {
        logout();
        navigate("/login", { replace: true });
      },
    },
  ];

  const darkSider = themeMode === "dark";
  const borderColor = darkSider ? "rgba(255,255,255,0.08)" : "rgba(18,24,45,0.08)";
  const secondaryText = darkSider ? "rgba(255,255,255,0.45)" : "rgba(18,24,45,0.5)";

  return (
    <Layout style={{ minHeight: "100vh", background: "transparent" }}>
      <Sider
        collapsed={collapsed}
        width={236}
        collapsedWidth={72}
        theme={darkSider ? "dark" : "light"}
        trigger={null}
        style={{
          height: "100vh",
          position: "fixed",
          left: 0,
          top: 0,
          bottom: 0,
          overflow: "hidden",
          background: darkSider ? "#0d0f15" : "#ffffff",
          borderRight: `1px solid ${borderColor}`,
          zIndex: 20,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          <div
            style={{
              height: 64,
              display: "flex",
              alignItems: "center",
              justifyContent: collapsed ? "center" : "space-between",
              padding: collapsed ? "0" : "0 16px",
              borderBottom: `1px solid ${borderColor}`,
              cursor: "pointer",
              flexShrink: 0,
            }}
            onClick={() => navigate("/dashboard")}
          >
            <Space size={11} align="center" style={{ minWidth: 0 }}>
              <span
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: 10,
                  background: BRAND.gradient,
                  color: "#fff",
                  fontWeight: 800,
                  fontSize: 17,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  boxShadow: "0 6px 16px rgba(255,80,0,0.4)",
                }}
              >
                {BRAND.logoText}
              </span>
              {!collapsed && (
                <span style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 15,
                      fontWeight: 700,
                      lineHeight: "19px",
                      color: darkSider ? "rgba(255,255,255,0.94)" : "rgba(18,24,45,0.92)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {BRAND.name}
                  </div>
                  <div
                    style={{
                      fontSize: 10,
                      letterSpacing: 1.5,
                      color: secondaryText,
                      lineHeight: "14px",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {BRAND.eyebrow}
                  </div>
                </span>
              )}
            </Space>
            {!collapsed && (
              <Button
                type="text"
                size="small"
                icon={<MenuFoldOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  setCollapsed(true);
                }}
                style={{ color: secondaryText }}
              />
            )}
          </div>

          <div
            style={{
              flex: 1,
              overflowY: "auto",
              overflowX: "hidden",
              padding: "10px 0 4px",
            }}
          >
            {!collapsed && <div className="ops-sider-label">工作台</div>}
            <Menu
              theme={darkSider ? "dark" : "light"}
              mode="inline"
              selectedKeys={selectedKeys}
              onClick={handleMenuClick}
              items={mainItems}
              className="ops-sider-menu"
              style={{ background: "transparent", borderRight: 0 }}
            />
            {!collapsed && <div className="ops-sider-label">系统</div>}
            <Menu
              theme={darkSider ? "dark" : "light"}
              mode="inline"
              selectedKeys={selectedKeys}
              onClick={handleMenuClick}
              items={footerItems}
              className="ops-sider-menu"
              style={{ background: "transparent", borderRight: 0 }}
            />
          </div>

          <div
            style={{
              flexShrink: 0,
              borderTop: `1px solid ${borderColor}`,
              padding: "10px 14px 12px",
            }}
          >
            {!collapsed && (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 10px",
                  borderRadius: 12,
                  background: darkSider ? "rgba(255,255,255,0.05)" : "rgba(18,24,45,0.04)",
                  marginBottom: 8,
                }}
              >
                <Avatar
                  size={30}
                  src={user?.avatar_url || undefined}
                  style={{ background: BRAND.gradient, fontWeight: 700, flexShrink: 0 }}
                >
                  {displayName.slice(0, 1)}
                </Avatar>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: darkSider ? "rgba(255,255,255,0.92)" : "rgba(18,24,45,0.9)",
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {displayName}
                  </div>
                  <div style={{ fontSize: 11, color: secondaryText }}>
                    {user?.role === "admin" ? "管理员" : "运营账号"}
                  </div>
                </div>
                <Tooltip title="退出登录">
                  <Button
                    type="text"
                    size="small"
                    icon={<LogoutOutlined style={{ fontSize: 14 }} />}
                    onClick={() => {
                      logout();
                      navigate("/login", { replace: true });
                    }}
                    style={{ color: secondaryText }}
                  />
                </Tooltip>
              </div>
            )}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <Button
                type="text"
                size="small"
                icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                onClick={() => setCollapsed((value) => !value)}
                style={{ color: secondaryText }}
              >
                {!collapsed && "收起侧栏"}
              </Button>
              {!collapsed && <span style={{ fontSize: 11, color: secondaryText }}>v0.1.0</span>}
            </div>
          </div>
        </div>
      </Sider>

      <Layout
        style={{
          marginLeft: siderWidth,
          transition: "margin-left .2s",
          background: "transparent",
        }}
      >
        <Header
          style={{
            height: 64,
            lineHeight: "64px",
            padding: "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 16,
            background: darkSider ? "rgba(10,12,16,0.72)" : "rgba(255,255,255,0.75)",
            backdropFilter: "blur(14px)",
            WebkitBackdropFilter: "blur(14px)",
            borderBottom: `1px solid ${borderColor}`,
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, minWidth: 0 }}>
            <Text strong style={{ fontSize: 18, whiteSpace: "nowrap" }}>
              {current?.name ?? "总览"}
            </Text>
            {!collapsed && current?.description && (
              <Text
                type="secondary"
                style={{
                  fontSize: 12,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  maxWidth: 300,
                }}
              >
                {current.description}
              </Text>
            )}
          </div>

          <Space size={14} align="center">
            {canAccessModule(user, "stores") && stores.length > 0 && (
              <Select
                value={currentStore?.id ?? undefined}
                placeholder="当前店铺"
                onChange={(value) => setCurrent(value)}
                options={stores.map((store) => ({ value: store.id, label: store.name }))}
                style={{ width: 190 }}
              />
            )}
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onPressEnter={handleSearch}
              prefix={<SearchOutlined style={{ color: "var(--ops-text-secondary)" }} />}
              placeholder="搜索模块，回车直达"
              allowClear
              style={{ width: 220, borderRadius: 999 }}
            />
            <span className="ops-pill">
              <span className={`ops-dot ops-dot--${statusClass}`} />
              {statusLabel}
            </span>
            <Tooltip title={themeMode === "dark" ? "切换为浅色模式" : "切换为暗色模式"}>
              <Button
                type="text"
                icon={
                  themeMode === "dark" ? (
                    <SunOutlined style={{ fontSize: 16 }} />
                  ) : (
                    <MoonOutlined style={{ fontSize: 16 }} />
                  )
                }
                onClick={toggleTheme}
                style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
              />
            </Tooltip>
            <Tooltip title="通知">
              <Button
                type="text"
                icon={<BellOutlined style={{ fontSize: 16 }} />}
                style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
              />
            </Tooltip>
            <div style={{ width: 1, height: 24, background: borderColor }} />
            <Dropdown menu={{ items: userMenu }} placement="bottomRight" trigger={["click"]}>
              <Space size={9} align="center" style={{ cursor: "pointer" }}>
                <Avatar
                  size={32}
                  src={user?.avatar_url || undefined}
                  style={{ background: BRAND.gradient, fontWeight: 700 }}
                >
                  {displayName.slice(0, 1)}
                </Avatar>
                <Text style={{ fontSize: 13 }}>{displayName}</Text>
              </Space>
            </Dropdown>
          </Space>
        </Header>

        <Content
          style={{
            padding: 24,
            minHeight: "calc(100vh - 64px)",
            overflow: "auto",
            maxWidth: 1560,
            margin: "0 auto",
            width: "100%",
          }}
        >
          <div className="ops-fade-in">
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
