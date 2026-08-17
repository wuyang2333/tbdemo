import { Spin } from "antd";
import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "../components/layout/app-shell";
import { useAuth } from "../lib/auth";
import { canAccessModule } from "../lib/modules";

// 页面路由全部懒加载：首屏只加载当前页面，降低初始 bundle 体积
const AccountsPage = lazy(() => import("../pages/accounts-page").then((m) => ({ default: m.AccountsPage })));
const AiPage = lazy(() => import("../pages/ai-page").then((m) => ({ default: m.AiPage })));
const AnalyticsAlertsPage = lazy(() => import("../pages/analytics-alerts-page").then((m) => ({ default: m.AnalyticsAlertsPage })));
const AnalyticsHoursPage = lazy(() => import("../pages/analytics-hours-page").then((m) => ({ default: m.AnalyticsHoursPage })));
const AnalyticsInsightPage = lazy(() => import("../pages/analytics-insight-page").then((m) => ({ default: m.AnalyticsInsightPage })));
const AnalyticsOverviewPage = lazy(() => import("../pages/analytics-overview-page").then((m) => ({ default: m.AnalyticsOverviewPage })));
const AnalyticsProductsPage = lazy(() => import("../pages/analytics-products-page").then((m) => ({ default: m.AnalyticsProductsPage })));
const AnalyticsReportPage = lazy(() => import("../pages/analytics-report-page").then((m) => ({ default: m.AnalyticsReportPage })));
const BoardPage = lazy(() => import("../pages/board-page").then((m) => ({ default: m.BoardPage })));
const ContentPage = lazy(() => import("../pages/content-page").then((m) => ({ default: m.ContentPage })));
const CustomersPage = lazy(() => import("../pages/customers-page").then((m) => ({ default: m.CustomersPage })));
const DashboardPage = lazy(() => import("../pages/dashboard-page").then((m) => ({ default: m.DashboardPage })));
const GiftsPage = lazy(() => import("../pages/gifts-page").then((m) => ({ default: m.GiftsPage })));
const LoginPage = lazy(() => import("../pages/login-page").then((m) => ({ default: m.LoginPage })));
const LogsPage = lazy(() => import("../pages/logs-page").then((m) => ({ default: m.LogsPage })));
const ModelConfigsPage = lazy(() => import("../pages/model-configs-page").then((m) => ({ default: m.ModelConfigsPage })));
const MonitoringPage = lazy(() => import("../pages/monitoring-page").then((m) => ({ default: m.MonitoringPage })));
const ProductsPage = lazy(() => import("../pages/products-page").then((m) => ({ default: m.ProductsPage })));
const ProfilePage = lazy(() => import("../pages/profile-page").then((m) => ({ default: m.ProfilePage })));
const PromotionsDataPage = lazy(() => import("../pages/promotions-data-page").then((m) => ({ default: m.PromotionsDataPage })));
const PromotionsPlansPage = lazy(() => import("../pages/promotions-plans-page").then((m) => ({ default: m.PromotionsPlansPage })));
const RegisterPage = lazy(() => import("../pages/register-page").then((m) => ({ default: m.RegisterPage })));
const SettingsPage = lazy(() => import("../pages/settings-page").then((m) => ({ default: m.SettingsPage })));
const StoresPage = lazy(() => import("../pages/stores-page").then((m) => ({ default: m.StoresPage })));
const TeamPage = lazy(() => import("../pages/team-page").then((m) => ({ default: m.TeamPage })));
const TasksPage = lazy(() => import("../pages/tasks-page").then((m) => ({ default: m.TasksPage })));

function PageFallback() {
  return (
    <div style={{ minHeight: "60vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Spin size="large" />
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
}

function RequireModule({ id, children }: { id: string; children: ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  if (!canAccessModule(user, id)) {
    return <Navigate to="/dashboard" replace />;
  }
  return <>{children}</>;
}

export function AppRouter() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route
          path="/board"
          element={
            <RequireAuth>
              <BoardPage />
            </RequireAuth>
          }
        />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route
            path="/stores"
            element={
              <RequireModule id="stores">
                <StoresPage />
              </RequireModule>
            }
          />
          <Route
            path="/team"
            element={
              <RequireAuth>
                <TeamPage />
              </RequireAuth>
            }
          />
          <Route
            path="/products"
            element={
              <RequireModule id="products">
                <ProductsPage />
              </RequireModule>
            }
          />
          <Route
            path="/gifts"
            element={
              <RequireModule id="gifts">
                <GiftsPage />
              </RequireModule>
            }
          />
          <Route path="/orders" element={<Navigate to="/gifts" replace />} />
          <Route
            path="/ai"
            element={
              <RequireModule id="ai">
                <AiPage />
              </RequireModule>
            }
          />
          <Route
            path="/customers"
            element={
              <RequireModule id="customers">
                <CustomersPage />
              </RequireModule>
            }
          />
          <Route path="/analytics" element={<Navigate to="/analytics/overview" replace />} />
          <Route path="/analytics/overview" element={<RequireModule id="analytics"><AnalyticsOverviewPage /></RequireModule>} />
          <Route path="/analytics/alerts" element={<RequireModule id="analytics"><AnalyticsAlertsPage /></RequireModule>} />
          <Route path="/analytics/report" element={<RequireModule id="analytics"><AnalyticsReportPage /></RequireModule>} />
          <Route path="/analytics/insight" element={<RequireModule id="analytics"><AnalyticsInsightPage /></RequireModule>} />
          <Route path="/analytics/hours" element={<RequireModule id="analytics"><AnalyticsHoursPage /></RequireModule>} />
          <Route path="/analytics/products" element={<RequireModule id="analytics"><AnalyticsProductsPage /></RequireModule>} />
          <Route path="/promotions" element={<Navigate to="/promotions/data" replace />} />
          <Route path="/promotions/data" element={<RequireModule id="promotions"><PromotionsDataPage /></RequireModule>} />
          <Route path="/promotions/plans" element={<RequireModule id="promotions"><PromotionsPlansPage /></RequireModule>} />
          <Route
            path="/content"
            element={
              <RequireModule id="content">
                <ContentPage />
              </RequireModule>
            }
          />
          <Route
            path="/monitoring"
            element={
              <RequireModule id="monitoring">
                <MonitoringPage />
              </RequireModule>
            }
          />
          <Route
            path="/tasks"
            element={
              <RequireModule id="tasks">
                <TasksPage />
              </RequireModule>
            }
          />
          <Route
            path="/model-configs"
            element={
              <RequireModule id="model-configs">
                <ModelConfigsPage />
              </RequireModule>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireModule id="settings">
                <SettingsPage />
              </RequireModule>
            }
          />
          <Route
            path="/accounts"
            element={
              <RequireModule id="accounts">
                <AccountsPage />
              </RequireModule>
            }
          />
          <Route
            path="/logs"
            element={
              <RequireModule id="logs">
                <LogsPage />
              </RequireModule>
            }
          />
          <Route
            path="/profile"
            element={
              <RequireModule id="profile">
                <ProfilePage />
              </RequireModule>
            }
          />
        </Route>
      </Routes>
    </Suspense>
  );
}
