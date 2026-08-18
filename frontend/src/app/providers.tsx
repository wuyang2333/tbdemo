import { App, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BrowserRouter } from "react-router-dom";
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { AuthProvider } from "../lib/auth";
import { BRAND } from "../lib/brand";
import { StoreProvider } from "../lib/store";
import { DEFAULT_MODE, applyTokens, antdTokens, themeComponents } from "../lib/theme";
import type { ThemeMode } from "../lib/theme";

const ThemeContext = createContext<{ mode: ThemeMode; toggle: () => void }>({
  mode: DEFAULT_MODE,
  toggle: () => {},
});

export function useThemeMode() {
  return useContext(ThemeContext);
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<ThemeMode>(() => {
    const saved = localStorage.getItem("tb-workbench-theme");
    if (saved === "dark" || saved === "light") return saved;
    return DEFAULT_MODE;
  });

  // 单一真相源：主题切换即把 token 写入 :root / body（global.css 与各组件统一引用 var(--ops-*)）
  useEffect(() => {
    localStorage.setItem("tb-workbench-theme", mode);
    applyTokens(mode);
  }, [mode]);

  const toggle = () => setMode((current) => (current === "dark" ? "light" : "dark"));
  const isDark = mode === "dark";

  return (
    <ThemeContext.Provider value={{ mode, toggle }}>
      <ConfigProvider
        locale={zhCN}
        theme={{
          algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
          token: { ...antdTokens(mode), colorPrimary: BRAND.primaryColor || undefined },
          components: themeComponents(mode),
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
