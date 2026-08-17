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
  mode: "light",
  toggle: () => {},
});

export function useThemeMode() {
  return useContext(ThemeContext);
}

// DESIGN.md（Apple 风格）：单一行动蓝、白/米白画布、近黑 tile、Inter 替代 SF Pro
const baseFont =
  'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const lightTokens = {
  colorPrimary: BRAND.primaryColor, // 行动蓝 #0066cc
  colorInfo: "#0066cc",
  colorLink: "#0066cc",
  colorBgBase: "#ffffff",
  colorBgContainer: "#ffffff",
  colorBgElevated: "#ffffff",
  colorBgLayout: "#f5f5f7", // 米白画布
  colorBorder: "#e0e0e0",
  colorBorderSecondary: "#f0f0f0",
  colorText: "#1d1d1f",
  colorTextSecondary: "#333333",
  colorTextTertiary: "#7a7a7a",
  colorFillTertiary: "rgba(0,0,0,0.04)",
  borderRadius: 8,
  controlHeight: 40,
  fontSize: 14,
  fontFamily: baseFont,
};

const darkTokens = {
  colorPrimary: "#2997ff", // 暗色用 Sky Link Blue
  colorInfo: "#2997ff",
  colorLink: "#2997ff",
  colorBgBase: "#272729",
  colorBgContainer: "#2a2a2c",
  colorBgElevated: "#2a2a2c",
  colorBgLayout: "#1d1d1f",
  colorBorder: "#3f3f42",
  colorBorderSecondary: "#353538",
  colorText: "rgba(255,255,255,0.94)",
  colorTextSecondary: "#cccccc",
  colorTextTertiary: "rgba(255,255,255,0.45)",
  borderRadius: 8,
  controlHeight: 40,
  fontSize: 14,
  fontFamily: baseFont,
};

const lightComponents = {
  Layout: { siderBg: "#f5f5f7", headerBg: "rgba(245,245,247,0.8)", bodyBg: "#f5f5f7" },
  Menu: {
    itemColor: "#1d1d1f",
    itemHoverColor: "#1d1d1f",
    itemHoverBg: "rgba(0,0,0,0.04)",
    itemSelectedBg: "rgba(0,102,204,0.08)",
    itemSelectedColor: "#0066cc",
    itemBorderRadius: 8,
    itemMarginInline: 12,
    itemHeight: 40,
    iconSize: 16,
  },
  Card: { headerBg: "transparent" },
  Button: {
    fontWeight: 400,
    primaryShadow: "none",
    defaultShadow: "none",
  },
  Table: { headerBg: "#fafafc", headerColor: "#333333" },
  Modal: { contentBg: "#ffffff" },
};

const darkComponents = {
  Layout: { siderBg: "#272729", headerBg: "rgba(29,29,31,0.8)", bodyBg: "#1d1d1f" },
  Menu: {
    itemColor: "#cccccc",
    itemHoverColor: "#ffffff",
    itemHoverBg: "rgba(255,255,255,0.06)",
    itemSelectedBg: "rgba(41,151,255,0.18)",
    itemSelectedColor: "#2997ff",
    itemBorderRadius: 8,
    itemMarginInline: 12,
    itemHeight: 40,
    iconSize: 16,
  },
  Card: { headerBg: "transparent" },
  Button: {
    fontWeight: 400,
    primaryShadow: "none",
    defaultShadow: "none",
  },
  Table: { headerBg: "#2a2a2c", headerColor: "#cccccc" },
  Modal: { contentBg: "#2a2a2c" },
};

export function AppProviders({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem("tb-workbench-theme");
    return saved === "dark" ? "dark" : "light";
  });

  useEffect(() => {
    localStorage.setItem("tb-workbench-theme", mode);
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
