import { Spin } from "antd";
import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { Alert, Button, Space } from "antd";
import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { AppShell } from "../components/layout/app-shell";
import { useAuth } from "../lib/auth";
import { canAccessModule } from "../lib/modules";

// 页面路由全部懒加载：首屏只加载当前页面，降低初始 bundle 体积
const AccountsPage = lazy(() => import("../pages/accounts-page").then((m) => ({ default: m.AccountsPage })));
const AiPage = lazy(() => import("../pages/ai-page").then((m) => ({ default: m.AiPage })));
const AnalyticsHoursPage = lazy(() => import("../pages/analytics-hours-page").then((m) => ({ default: m.AnalyticsHoursPage })));
const AnalyticsInsightPage = lazy(() => import("../pages/analytics-insight-page").then((m) => ({ default: m.AnalyticsInsightPage })));
const AnalyticsOverviewPage = lazy(() => import("../pages/analytics-overview-page").then((m) => ({ default: m.AnalyticsOverviewPage })));
const AnalyticsProductsPage = lazy(() => import("../pages/analytics-products-page").then((m) => ({ default: m.AnalyticsProductsPage })));
const AnalyticsReportPage = lazy(() => import("../pages/analytics-report-page").then((m) => ({ default: m.AnalyticsReportPage })));
const AnalyticsGlossaryPage = lazy(() => import("../pages/analytics-glossary-page").then((m) => ({ default: m.AnalyticsGlossaryPage })));
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
const PromotionsPlansPage = lazy(() => import("../pages/promotions-plans-page").then((m) => ({ default: m.PromotionsPlansPage })));
const PromotionsPlanDetailPage = lazy(() => import("../pages/promotions-plan-detail-page").then((m) => ({ default: m.PromotionsPlanDetailPage })));
const PromotionsOverviewPage = lazy(() => import("../pages/promotions-overview-page").then((m) => ({ default: m.PromotionsOverviewPage })));
const PromotionsWorkflowPage = lazy(() => import("../pages/promotions-workflow-page").then((m) => ({ default: m.PromotionsWorkflowPage })));
const PromotionsExtensionsPage = lazy(() => import("../pages/promotions-extensions-page").then((m) => ({ default: m.PromotionsExtensionsPage })));
const PromotionsReviewPage = lazy(() => import("../pages/promotions-review-page").then((m) => ({ default: m.PromotionsReviewPage })));
const PromotionsCockpitPage = lazy(() => import("../pages/promotions-cockpit-page").then((m) => ({ default: m.PromotionsCockpitPage })));
const PromotionsDiagnosticsPage = lazy(() => import("../pages/promotions-diagnostics-page").then((m) => ({ default: m.PromotionsDiagnosticsPage })));
const RegisterPage = lazy(() => import("../pages/register-page").then((m) => ({ default: m.RegisterPage })));
const SettingsPage = lazy(() => import("../pages/settings-page").then((m) => ({ default: m.SettingsPage })));
const StoresPage = lazy(() => import("../pages/stores-page").then((m) => ({ default: m.StoresPage })));
const StrategyWorkspacePage = lazy(() => import("../pages/strategy-workspace-page").then((m) => ({ default: m.StrategyWorkspacePage })));
const TeamPage = lazy(() => import("../pages/team-page").then((m) => ({ default: m.TeamPage })));
const TasksPage = lazy(() => import("../pages/tasks-page").then((m) => ({ default: m.TasksPage })));

function PageFallback() {
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setTimedOut(true), 15000);
    return () => window.clearTimeout(timer);
  }, []);

  if (timedOut) {
    return (
      <div style={{ minHeight: "60vh", display: "grid", placeItems: "center", padding: 24 }}>
        <Alert
          type="warning"
          showIcon
          message="页面加载时间较长"
          description="后端服务或网络响应较慢，页面还没有完成加载。可以重试，或先返回上一页。"
          action={
            <Space>
              <Button size="small" onClick={() => window.history.back()}>返回上一页</Button>
              <Button size="small" type="primary" onClick={() => window.location.reload()}>重新加载</Button>
            </Space>
          }
        />
      </div>
    );
  }

  return (
    <div aria-busy="true" aria-live="polite" style={{ minHeight: "60vh", display: "flex", flexDirection: "column", gap: 12, alignItems: "center", justifyContent: "center" }}>
      <Spin size="large" />
      <span style={{ color: "var(--ops-text-3)", fontSize: 13 }}>正在打开页面…</span>
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
          <Route path="/analytics/report" element={<RequireModule id="analytics"><AnalyticsReportPage /></RequireModule>} />
          <Route path="/analytics/insight" element={<RequireModule id="analytics"><AnalyticsInsightPage /></RequireModule>} />
          <Route path="/analytics/hours" element={<RequireModule id="analytics"><AnalyticsHoursPage /></RequireModule>} />
          <Route path="/analytics/products" element={<RequireModule id="analytics"><AnalyticsProductsPage /></RequireModule>} />
<Route path="/analytics/glossary" element={<RequireModule id="analytics"><AnalyticsGlossaryPage /></RequireModule>} />
          <Route path="/promotions" element={<Navigate to="/promotions/cockpit" replace />} />
          <Route path="/promotions/cockpit" element={<RequireModule id="promotions"><PromotionsCockpitPage /></RequireModule>} />
          <Route path="/promotions/diagnostics" element={<RequireModule id="promotions"><PromotionsDiagnosticsPage /></RequireModule>} />
          <Route path="/promotions/overview" element={<RequireModule id="promotions"><PromotionsOverviewPage /></RequireModule>} />
          <Route path="/promotions/data" element={<Navigate to="/promotions/overview" replace />} />
          <Route path="/promotions/plans" element={<RequireModule id="promotions"><PromotionsPlansPage /></RequireModule>} />
          <Route path="/promotions/plans/:planId" element={<RequireModule id="promotions"><PromotionsPlanDetailPage /></RequireModule>} />
          <Route path="/promotions/budget" element={<Navigate to="/promotions/overview" replace />} />
          <Route path="/promotions/decisions" element={<RequireModule id="promotions"><PromotionsWorkflowPage section="decision" /></RequireModule>} />
          <Route path="/promotions/validation" element={<RequireModule id="promotions"><PromotionsWorkflowPage section="validation" /></RequireModule>} />
          <Route path="/promotions/strategies" element={<RequireModule id="promotions"><PromotionsWorkflowPage section="strategies" /></RequireModule>} />
          <Route path="/promotions/collaboration" element={<Navigate to="/promotions/plans" replace />} />
          <Route path="/promotions/review" element={<RequireModule id="promotions"><PromotionsReviewPage /></RequireModule>} />
          <Route path="/promotions/extensions" element={<RequireModule id="promotions"><PromotionsExtensionsPage /></RequireModule>} />
          <Route path="/promotions/assets" element={<RequireModule id="promotions"><StrategyWorkspacePage sectionId="promotion-assets" /></RequireModule>} />
          <Route path="/promotions/targets" element={<RequireModule id="promotions"><StrategyWorkspacePage sectionId="promotion-targets" /></RequireModule>} />
          <Route path="/promotions/experiments" element={<RequireModule id="promotions"><StrategyWorkspacePage sectionId="promotion-experiments" /></RequireModule>} />
          <Route path="/content" element={<Navigate to="/content/overview" replace />} />
          <Route path="/content/overview" element={<RequireModule id="content"><ContentPage sectionId="content-overview" /></RequireModule>} />
          <Route path="/content/topics" element={<RequireModule id="content"><ContentPage sectionId="content-topics" /></RequireModule>} />
          <Route path="/content/calendar" element={<RequireModule id="content"><ContentPage sectionId="content-calendar" /></RequireModule>} />
          <Route path="/content/assets" element={<RequireModule id="content"><ContentPage sectionId="content-assets" /></RequireModule>} />
          <Route path="/content/studio" element={<RequireModule id="content"><ContentPage sectionId="content-studio" /></RequireModule>} />
          <Route path="/content/performance" element={<RequireModule id="content"><ContentPage sectionId="content-performance" /></RequireModule>} />
          <Route path="/monitoring" element={<Navigate to="/monitoring/overview" replace />} />
          <Route path="/monitoring/overview" element={<RequireModule id="monitoring"><MonitoringPage sectionId="monitoring-overview" /></RequireModule>} />
          <Route path="/monitoring/shops" element={<RequireModule id="monitoring"><MonitoringPage sectionId="competitor-shops" /></RequireModule>} />
          <Route path="/monitoring/products" element={<RequireModule id="monitoring"><MonitoringPage sectionId="competitor-products" /></RequireModule>} />
          <Route path="/monitoring/pricing" element={<RequireModule id="monitoring"><MonitoringPage sectionId="competitor-pricing" /></RequireModule>} />
          <Route path="/monitoring/radar" element={<RequireModule id="monitoring"><MonitoringPage sectionId="competitor-radar" /></RequireModule>} />
          <Route path="/monitoring/reports" element={<RequireModule id="monitoring"><MonitoringPage sectionId="competitor-reports" /></RequireModule>} />
          <Route path="/market" element={<Navigate to="/market/opportunities" replace />} />
          <Route path="/market/opportunities" element={<RequireModule id="market"><StrategyWorkspacePage sectionId="opportunities" /></RequireModule>} />
          <Route path="/market/keywords" element={<RequireModule id="market"><StrategyWorkspacePage sectionId="keywords" /></RequireModule>} />
          <Route path="/market/radar" element={<RequireModule id="market"><StrategyWorkspacePage sectionId="radar" /></RequireModule>} />
          <Route path="/growth-lab" element={<Navigate to="/growth-lab/products" replace />} />
          <Route path="/growth-lab/products" element={<RequireModule id="growth-lab"><StrategyWorkspacePage sectionId="products" /></RequireModule>} />
          <Route path="/growth-lab/pricing" element={<RequireModule id="growth-lab"><StrategyWorkspacePage sectionId="pricing" /></RequireModule>} />
          <Route path="/growth-lab/simulator" element={<RequireModule id="growth-lab"><StrategyWorkspacePage sectionId="simulator" /></RequireModule>} />
          <Route path="/growth-lab/experiments" element={<RequireModule id="growth-lab"><StrategyWorkspacePage sectionId="experiments" /></RequireModule>} />
          <Route path="/growth-lab/creative" element={<RequireModule id="growth-lab"><StrategyWorkspacePage sectionId="creative" /></RequireModule>} />
          <Route path="/ops-knowledge" element={<Navigate to="/ops-knowledge/reviews" replace />} />
          <Route path="/ops-knowledge/reviews" element={<RequireModule id="ops-knowledge"><StrategyWorkspacePage sectionId="reviews" /></RequireModule>} />
          <Route path="/ops-knowledge/decisions" element={<RequireModule id="ops-knowledge"><StrategyWorkspacePage sectionId="decisions" /></RequireModule>} />
          <Route path="/ops-knowledge/knowledge" element={<RequireModule id="ops-knowledge"><StrategyWorkspacePage sectionId="knowledge" /></RequireModule>} />
          <Route path="/ops-knowledge/automation" element={<RequireModule id="ops-knowledge"><StrategyWorkspacePage sectionId="automation" /></RequireModule>} />
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
