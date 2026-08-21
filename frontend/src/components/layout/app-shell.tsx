import {
  ApiOutlined,
  BarChartOutlined,
  BellOutlined,
  CloseOutlined,
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
  StarFilled,
  StarOutlined,
  TeamOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import { Alert, Avatar, Badge, Button, Drawer, Dropdown, Input, Layout, Menu, Popover, Select, Space, Tag, Tooltip, Typography } from "antd";
import type { MenuProps } from "antd";
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useThemeMode } from "../../app/providers";
import { useAuth } from "../../lib/auth";
import { BRAND } from "../../lib/brand";
import { canAccessModule, FOOTER_MODULES, getModule, MAIN_MODULES, MODULES } from "../../lib/modules";
import http from "../../lib/api";
import { useStores } from "../../lib/store";
import type { ModuleMeta } from "../../types";
import { ErrorBoundary } from "../ui/page-state";

const { Sider, Header, Content } = Layout;
const { Text } = Typography;

const ICONS: Record<string, ReactNode> = {
  dashboard: <DashboardOutlined />,
  shop: <ShopOutlined />,
  team: <TeamOutlined />,
  product: <ShoppingOutlined />,
  order: <ProfileOutlined />,
  customer: <TeamOutlined />,
  analytics: <BarChartOutlined />,
  promotion: <RocketOutlined />,
  content: <FileTextOutlined />,
  monitor: <EyeOutlined />,
  task: <ScheduleOutlined />,
  model: <RobotOutlined />,
  robot: <RobotOutlined />,
  api: <ApiOutlined />,
  settings: <SettingOutlined />,
  profile: <IdcardOutlined />,
  accounts: <UserSwitchOutlined />,
  logs: <HistoryOutlined />,
};

const ANALYTICS_CHILDREN = [
  { key: "/analytics/overview", label: "今日总览" },
  { key: "/analytics/report", label: "经营日报" },
  { key: "/analytics/insight", label: "AI 解读" },
  { key: "/analytics/hours", label: "时段分析" },
  { key: "/analytics/products", label: "商品分析" },
  { key: "/analytics/glossary", label: "数据口径" },
];

const PROMOTIONS_CHILDREN = [
  { key: "/promotions/data", label: "推广数据" },
  { key: "/promotions/plans", label: "推广计划" },
];

const SUBMENU_ITEMS: Record<string, { key: string; label: string }[]> = {
  analytics: ANALYTICS_CHILDREN,
  promotions: PROMOTIONS_CHILDREN,
};

const FAVORITE_KEYS = "tb-sider-favs";

function buildLabelMap(): Map<string, string> {
  const map = new Map<string, string>();
  MAIN_MODULES.concat(FOOTER_MODULES).forEach((m) => map.set(`/${m.id}`, m.name));
  Object.values(SUBMENU_ITEMS)
    .flat()
    .forEach((c) => map.set(c.key, c.label));
  return map;
}
const LABEL_BY_KEY = buildLabelMap();

function toItems(modules: ModuleMeta[]): MenuProps["items"] {
  return modules.map((module) => {
    const children = SUBMENU_ITEMS[module.id];
    if (children) {
      return {
        key: `/${module.id}`,
        icon: ICONS[module.icon],
        label: module.name,
        children,
      };
    }
    return {
      key: `/${module.id}`,
      icon: ICONS[module.icon],
      label: module.name,
    };
  });
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
  const [mobile, setMobile] = useState(() => window.innerWidth < 768);
  const [drawerOpen, setDrawerOpen] = useState(false);
  useEffect(() => {
    const onResize = () => setMobile(window.innerWidth < 768);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const [keyword, setKeyword] = useState("");
  const [notifCount, setNotifCount] = useState(0);
  const [notifItems, setNotifItems] = useState<{ id: string; date_label: string; level: string; message: string }[]>([]);
  const [notifOpen, setNotifOpen] = useState(false);
  const loadNotifs = useCallback(async () => {
    try {
      const { data } = await http.get<{ count: number; items: { id: string; date_label: string; level: string; message: string }[] }>(
        "/analytics/alerts/summary"
      );
      setNotifCount(data.count);
      setNotifItems(data.items);
    } catch {
      setNotifCount(0);
      setNotifItems([]);
    }
  }, []);
  useEffect(() => {
    loadNotifs();
    const timer = setInterval(loadNotifs, 60000);
    return () => clearInterval(timer);
  }, [loadNotifs]);

  const [announcements, setAnnouncements] = useState<{ id: number; title: string; content: string }[]>([]);
  const loadAnnouncements = useCallback(async () => {
    try {
      const { data } = await http.get<{ items: { id: number; title: string; content: string }[] }>("/announcements/active");
      setAnnouncements(data.items);
    } catch {
      setAnnouncements([]);
    }
  }, []);
  useEffect(() => {
    loadAnnouncements();
  }, [loadAnnouncements]);
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const seg = location.pathname.split("/")[1];
    return seg === "analytics" || seg === "promotions" ? [seg] : [];
  });
  const [favs, setFavs] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(FAVORITE_KEYS);
      return raw ? (JSON.parse(raw) as string[]) : [];
    } catch {
      return [];
    }
  });
  useEffect(() => {
    localStorage.setItem(FAVORITE_KEYS, JSON.stringify(favs));
  }, [favs]);
  const toggleFav = (key: string) =>
    setFavs((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  const isFav = favs.includes(location.pathname);
  const visibleFavs = favs.filter((k) => LABEL_BY_KEY.has(k));
  const backendOk = useBackendStatus();

  const current = getModule(location.pathname.split("/")[1] || "");
  const currentChild = Object.values(SUBMENU_ITEMS)
    .flat()
    .find((c) => c.key === location.pathname);
  const selectedKeys = [location.pathname];
  useEffect(() => {
    const seg = location.pathname.split("/")[1];
    if (seg === "analytics" || seg === "promotions") {
      setOpenKeys((keys) => (keys.includes(seg) ? keys : [...keys, seg]));
    }
  }, [location.pathname]);
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);
  const siderWidth = collapsed ? 72 : 236;
  const displayName = user?.nickname || user?.username || "运营者";

  const mainItems = toItems(MAIN_MODULES.filter((module) => canAccessModule(user, module.id))) ?? [];
  if (user?.role !== "member" || !user?.parent_id) {
    mainItems.push({ key: "/team", icon: ICONS.team, label: "我的团队" });
  }
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
  const borderColor = "var(--ops-border)";
  const secondaryText = "var(--ops-text-3)";

  return (
    <Layout style={{ minHeight: "100vh", background: "transparent" }}>
      <Sider
        collapsed={mobile || collapsed}
        width={236}
        collapsedWidth={mobile ? 0 : 72}
        theme={darkSider ? "dark" : "light"}
        trigger={null}
        style={{
          height: "100vh",
          position: "fixed",
          left: 0,
          top: 0,
          bottom: 0,
          overflow: "hidden",
          background: "var(--ops-sider-bg)",
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
                  borderRadius: "var(--ops-radius)",
                  background: BRAND.logoUrl ? "transparent" : BRAND.gradient,
                  color: "#fff",
                  fontWeight: 800,
                  fontSize: 17,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  boxShadow: "0 6px 16px rgba(94,106,210,0.45)",
                }}
              >
                {BRAND.logoUrl ? (
                  <img src={BRAND.logoUrl} alt="" style={{ width: "100%", height: "100%", borderRadius: "var(--ops-radius)", objectFit: "cover", display: "block" }} />
                ) : (
                  (BRAND.name || "淘").slice(0, 1)
                )}
              </span>
              {!collapsed && (
                <span style={{ minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: 15,
                      fontWeight: 700,
                      lineHeight: "19px",
                      color: "var(--ops-text)",
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
                aria-label="收起侧栏"
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
            {!collapsed && visibleFavs.length > 0 && (
              <div style={{ padding: "4px 12px 6px" }}>
                <div className="ops-sider-label" style={{ padding: "6px 12px 4px" }}>常用</div>
                {visibleFavs.map((key) => (
                  <div
                    key={key}
                    className="ops-fav-item"
                    onClick={() => navigate(key)}
                    title={LABEL_BY_KEY.get(key) ?? key}
                    style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 10px", borderRadius: "var(--ops-radius-sm)", cursor: "pointer", color: "var(--ops-text-2)", fontSize: 13, marginBottom: 2 }}
                  >
                    <StarFilled style={{ color: "var(--ops-warn)", fontSize: 12, flexShrink: 0 }} />
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{LABEL_BY_KEY.get(key) ?? key}</span>
                    <Button type="text" size="small" aria-label="取消收藏" icon={<CloseOutlined style={{ fontSize: 11 }} />} onClick={(e) => { e.stopPropagation(); toggleFav(key); }} className="ops-fav-remove" />
                  </div>
                ))}
              </div>
            )}
            {!collapsed && <div className="ops-sider-label">工作台</div>}
            <Menu
              theme={darkSider ? "dark" : "light"}
              mode="inline"
              selectedKeys={selectedKeys}
              openKeys={collapsed ? undefined : openKeys}
              onOpenChange={(keys) => setOpenKeys(keys as string[])}
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
                  borderRadius: "var(--ops-radius)",
                  background: "var(--ops-panel-2)",
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
                      color: "var(--ops-text)",
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
                    aria-label="退出登录"
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
          marginLeft: mobile ? 0 : siderWidth,
          transition: "margin-left .2s",
          background: "transparent",
        }}
      >
        <Header
          style={{
            height: 64,
            lineHeight: "64px",
            padding: mobile ? "0 12px" : "0 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: mobile ? 8 : 16,
            background: "var(--ops-header-bg)",
            borderBottom: `1px solid ${borderColor}`,
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: mobile ? 4 : 12, minWidth: 0 }}>
            {mobile && (<Button type="text" aria-label="打开菜单" icon={<MenuUnfoldOutlined style={{ fontSize: 16 }} />} onClick={() => setDrawerOpen(true)} style={{ display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }} />)}
            <Text strong style={{ fontSize: mobile ? 16 : 18, whiteSpace: "nowrap" }}>
              {current?.name ?? "总览"}
              {currentChild ? <span style={{ color: "var(--ops-text-2)", fontWeight: 500 }}> / {currentChild.label}</span> : null}
            </Text>
            <Tooltip title={isFav ? "取消收藏" : "收藏到常用"}>
              <Button
                type="text"
                size="small"
                aria-label={isFav ? "取消收藏" : "收藏本页"}
                icon={isFav ? <StarFilled style={{ color: "var(--ops-warn)" }} /> : <StarOutlined />}
                onClick={() => toggleFav(location.pathname)}
              />
            </Tooltip>
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
                style={{ width: mobile ? 130 : 190 }}
              />
            )}
{!mobile && (<Input value={keyword} onChange={(event) => setKeyword(event.target.value)} onPressEnter={handleSearch} prefix={<SearchOutlined style={{ color: "var(--ops-text-secondary)" }} />} placeholder="搜索模块，回车直达" allowClear style={{ width: 220, borderRadius: 999 }} />)}
{!mobile && (<span className="ops-pill"><span className={`ops-dot ops-dot--${statusClass}`} />{statusLabel}</span>)}
            <Tooltip title={themeMode === "dark" ? "切换为浅色模式" : "切换为暗色模式"}>
              <Button
                type="text"
                aria-label="切换主题"
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
            <Popover
              placement="bottomRight"
              trigger="click"
              open={notifOpen}
              onOpenChange={setNotifOpen}
              content={
                <div style={{ width: 320 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <Text strong>异常提醒</Text>
                    <a
                      onClick={() => {
                        setNotifOpen(false);
                        navigate("/analytics/overview");
                      }}
                    >
                      查看全部
                    </a>
                  </div>
                  {notifItems.length === 0 ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>暂无异常提醒</Text>
                  ) : (
                    notifItems.map((item) => (
                      <div key={item.id} style={{ padding: "6px 0", borderBottom: "1px solid var(--ops-border)", fontSize: 12, lineHeight: 1.6 }}>
                        <Tag color={item.level === "error" ? "red" : item.level === "warn" ? "orange" : "default"} style={{ marginRight: 6 }}>
                          {item.date_label}
                        </Tag>
                        {item.message}
                      </div>
                    ))
                  )}
                </div>
              }
            >
              <Tooltip title="通知">
                <Badge count={notifCount} size="small" offset={[-4, 4]}>
                  <Button
                    type="text"
                    aria-label="通知"
                    icon={<BellOutlined style={{ fontSize: 16 }} />}
                    style={{ display: "flex", alignItems: "center", justifyContent: "center" }}
                  />
                </Badge>
              </Tooltip>
            </Popover>
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
            padding: mobile ? 12 : 24,
            minHeight: "calc(100vh - 64px)",
            overflow: "auto",
            maxWidth: 1560,
            margin: "0 auto",
            width: "100%",
          }}
        >
          {announcements.length > 0 && (
            <Alert
              type="info"
              showIcon
              closable
              message={announcements[0].title}
              description={announcements[0].content || undefined}
              style={{ marginBottom: 16 }}
            />
          )}
          <div className="ops-fade-in">
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </div>
        </Content>
      </Layout>
      <Drawer placement="left" width={280} open={mobile && drawerOpen} onClose={() => setDrawerOpen(false)} styles={{ body: { padding: 0 } }}>
        <div style={{ height: 64, display: "flex", alignItems: "center", gap: 11, padding: "0 20px", borderBottom: "1px solid var(--ops-border)" }}>
          <span style={{ width: 34, height: 34, borderRadius: "var(--ops-radius)", background: BRAND.logoUrl ? "transparent" : BRAND.gradient, color: "#fff", fontWeight: 800, fontSize: 17, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>{BRAND.logoUrl ? <img src={BRAND.logoUrl} alt="" style={{ width: "100%", height: "100%", borderRadius: "var(--ops-radius)", objectFit: "cover", display: "block" }} /> : (BRAND.name || "淘").slice(0, 1)}</span>
          <span style={{ fontSize: 15, fontWeight: 700, color: "var(--ops-text)" }}>{BRAND.name}</span>
        </div>
        <div style={{ padding: "10px 0 4px" }}>
          <div className="ops-sider-label">工作台</div>
          <Menu mode="inline" selectedKeys={selectedKeys} openKeys={openKeys} onOpenChange={(keys) => setOpenKeys(keys as string[])} onClick={(event) => { handleMenuClick(event); setDrawerOpen(false); }} items={mainItems} className="ops-sider-menu" style={{ borderRight: 0, background: "transparent" }} />
          <div className="ops-sider-label">系统</div>
          <Menu mode="inline" selectedKeys={selectedKeys} onClick={(event) => { handleMenuClick(event); setDrawerOpen(false); }} items={footerItems} className="ops-sider-menu" style={{ borderRight: 0, background: "transparent" }} />
        </div>
      </Drawer>
    </Layout>
  );
}



