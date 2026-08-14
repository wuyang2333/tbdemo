import { App, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BrowserRouter } from "react-router-dom";
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { AuthProvider } from "../lib/auth";
import { BRAND } from "../lib/brand";
import { StoreProvider } from "../lib/store";

type ThemeMode = "dark" | "light";

const ThemeContext = createContext<{ mode: ThemeMode; toggle: () => void }>({
  mode: "dark",
  toggle: () => {},
});

export function useThemeMode() {
  return useContext(ThemeContext);
}

const baseFont =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const darkTokens = {
  colorPrimary: BRAND.primaryColor,
  colorInfo: BRAND.primaryColor,
  colorLink: "#ff6a24",
  colorBgBase: "#0a0c10",
  colorBgContainer: "#12151d",
  colorBgElevated: "#1a1f2b",
  colorBgLayout: "#0a0c10",
  colorBorder: "#2a2f3d",
  colorBorderSecondary: "#20242f",
  colorText: "rgba(255,255,255,0.92)",
  colorTextSecondary: "rgba(255,255,255,0.58)",
  colorTextTertiary: "rgba(255,255,255,0.4)",
  colorFillTertiary: "rgba(255,255,255,0.06)",
  borderRadius: 10,
  controlHeight: 36,
  boxShadow: "0 10px 30px rgba(0,0,0,0.35)",
  boxShadowSecondary: "0 8px 24px rgba(0,0,0,0.4)",
  fontFamily: baseFont,
};

const lightTokens = {
  colorPrimary: BRAND.primaryColor,
  colorInfo: BRAND.primaryColor,
  colorLink: "#ff5000",
  colorBgBase: "#ffffff",
  colorBgContainer: "#ffffff",
  colorBgElevated: "#ffffff",
  colorBgLayout: "#f4f6fb",
  colorBorder: "#e4e8f0",
  colorBorderSecondary: "#eef1f7",
  colorText: "rgba(15,21,40,0.92)",
  colorTextSecondary: "rgba(15,21,40,0.55)",
  colorTextTertiary: "rgba(15,21,40,0.38)",
  borderRadius: 10,
  controlHeight: 36,
  boxShadow: "0 10px 30px rgba(30,40,70,0.1)",
  boxShadowSecondary: "0 8px 24px rgba(30,40,70,0.08)",
  fontFamily: baseFont,
};

const darkComponents = {
  Layout: { siderBg: "#0d0f15", headerBg: "rgba(13,15,21,0.8)", bodyBg: "#0a0c10" },
  Menu: {
    darkItemBg: "transparent",
    darkSubMenuItemBg: "transparent",
    darkItemColor: "rgba(255,255,255,0.62)",
    darkItemHoverColor: "rgba(255,255,255,0.95)",
    darkItemHoverBg: "rgba(255,255,255,0.07)",
    darkItemSelectedBg: "rgba(255,80,0,0.16)",
    darkItemSelectedColor: "#ff7a3d",
    itemBorderRadius: 10,
    itemMarginInline: 12,
    itemHeight: 42,
    iconSize: 16,
  },
  Card: { headerBg: "transparent" },
  Button: {
    defaultShadow: "none",
    primaryShadow: "0 6px 18px rgba(255,80,0,0.35)",
  },
};

const lightComponents = {
  Layout: { siderBg: "#ffffff", headerBg: "rgba(255,255,255,0.82)", bodyBg: "#f4f6fb" },
  Menu: {
    itemColor: "rgba(15,21,40,0.62)",
    itemHoverColor: "rgba(15,21,40,0.95)",
    itemHoverBg: "rgba(15,21,40,0.05)",
    itemSelectedBg: "rgba(255,80,0,0.1)",
    itemSelectedColor: "#ff5000",
    itemBorderRadius: 10,
    itemMarginInline: 12,
    itemHeight: 42,
    iconSize: 16,
  },
  Card: { headerBg: "transparent" },
  Button: {
    defaultShadow: "none",
    primaryShadow: "0 6px 18px rgba(255,80,0,0.28)",
  },
};

export function AppProviders({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem("tb-workbench-theme");
    return saved === "light" ? "light" : "dark";
  });

  useEffect(() => {
    localStorage.setItem("tb-workbench-theme", mode);
    document.body.style.background = mode === "dark" ? "#0a0c10" : "#f4f6fb";
    document.body.dataset.theme = mode;
  }, [mode]);

  const toggle = () => setMode((current) => (current === "dark" ? "light" : "dark"));
  const isDark = mode === "dark";

  return (
    <ThemeContext.Provider value={{ mode, toggle }}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
          token: isDark ? darkTokens : lightTokens,
          components: isDark ? darkComponents : lightComponents,
        }}
      >
        <App>
          <BrowserRouter>
            <AuthProvider>
              <StoreProvider>{children}</StoreProvider>
            </AuthProvider>
          </BrowserRouter>
        </App>
      </ConfigProvider>
    </ThemeContext.Provider>
  );
}
