import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { AppShell } from "../components/layout/app-shell";
import { useAuth } from "../lib/auth";
import { canAccessModule } from "../lib/modules";
import { AccountsPage } from "../pages/accounts-page";
import { AiPage } from "../pages/ai-page";
import { AnalyticsPage } from "../pages/analytics-page";
import { ContentPage } from "../pages/content-page";
import { CustomersPage } from "../pages/customers-page";
import { DashboardPage } from "../pages/dashboard-page";
import { LoginPage } from "../pages/login-page";
import { LogsPage } from "../pages/logs-page";
import { ModelConfigsPage } from "../pages/model-configs-page";
import { MonitoringPage } from "../pages/monitoring-page";
import { GiftsPage } from "../pages/gifts-page";
import { ProfilePage } from "../pages/profile-page";
import { ProductsPage } from "../pages/products-page";
import { PromotionsPage } from "../pages/promotions-page";
import { RegisterPage } from "../pages/register-page";
import { SettingsPage } from "../pages/settings-page";
import { StoresPage } from "../pages/stores-page";
import { TasksPage } from "../pages/tasks-page";

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
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
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
        <Route
          path="/analytics/:tab"
          element={
            <RequireModule id="analytics">
              <AnalyticsPage />
            </RequireModule>
          }
        />
        <Route path="/promotions" element={<Navigate to="/promotions/data" replace />} />
        <Route
          path="/promotions/:tab"
          element={
            <RequireModule id="promotions">
              <PromotionsPage />
            </RequireModule>
          }
        />
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
  );
}
