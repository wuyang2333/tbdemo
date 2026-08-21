/**
 * 淘宝运营工作台 · 设计系统 token（单一真相源）
 * ----------------------------------------------------------------
 * 所有视觉决策集中于此：AntD token、CSS 变量、组件内联引用统一读这里。
 * - applyTokens(mode)    把 token 写入 :root / body（global.css 与组件统一引用 var(--ops-*)）
 * - antdTokens(mode)     供 AntD ConfigProvider 派生，与 CSS 变量同源
 * - themeComponents(mode) AntD 组件级 token
 * 默认主题：深色（极光 · 淘宝橙）。
 */

export type ThemeMode = "dark" | "light";

export const DEFAULT_MODE: ThemeMode = "dark";

export interface Tokens {
  bg: string;
  panel: string;
  panel2: string;
  border: string;
  borderStrong: string;
  text: string;
  text2: string;
  text3: string;
  accent: string;
  accentLight: string;
  accentSoft: string;
  accentGrad: string;
  series: string;
  warn: string;
  cat0: string;
  cat1: string;
  cat2: string;
  cat3: string;
  cat4: string;
  cat5: string;
  up: string;
  down: string;
  success: string;
  danger: string;
  radius: string;
  radiusSm: string;
  radiusXs: string;
  radiusLg: string;
  shadow: string;
  shadowSm: string;
  shadowCard: string;
  // 旧命名别名（供既有组件平滑迁移）
  cardBg: string;
  cardBg2: string;
  textSecondary: string;
  hoverbarBg: string;
  hoverbarBorder: string;
  hoverbarText: string;
  hoverbarTextHover: string;
  hoverbarBtnHover: string;
  siderBg: string;
  headerBg: string;
  auroraA: string;
  auroraB: string;
  chartAccent: string;
  chartSeries: string;
  chartUp: string;
  chartDown: string;
}

export const TOKENS: Record<ThemeMode, Tokens> = {
  dark: {
    bg: "#0a0b0f",
    panel: "#14161b",
    panel2: "#101216",
    border: "rgba(255,255,255,0.09)",
    borderStrong: "rgba(255,255,255,0.16)",
    text: "#f6f7f8",
    text2: "#a7adb8",
    text3: "#6f7782",
    accent: "#5e6ad2",
    accentLight: "#828fff",
    accentSoft: "rgba(94,106,210,0.16)",
    accentGrad: "linear-gradient(135deg,#828fff,#5e6ad2)",
    series: "#5e6ad2",
    warn: "#ffb061",
    cat0: "#5e6ad2",
    cat1: "#5b8def",
    cat2: "#b18cff",
    cat3: "#37c871",
    cat4: "#3dd0d9",
    cat5: "#ff6b9d",
    up: "#ff5b5b",
    down: "#37c871",
    success: "#37c871",
    danger: "#ff5b5b",
    radius: "12px",
    radiusSm: "8px",
    radiusXs: "6px",
    radiusLg: "16px",
    shadow: "0 1px 2px rgba(0,0,0,0.4), 0 8px 24px rgba(0,0,0,0.18)",
    shadowSm: "0 1px 2px rgba(0,0,0,0.35)",
    shadowCard: "0 1px 2px rgba(0,0,0,0.4), 0 10px 28px rgba(0,0,0,0.2)",
    cardBg: "#14161b",
    cardBg2: "#101216",
    textSecondary: "#a7adb8",
    hoverbarBg: "rgba(10,11,15,0.96)",
    hoverbarBorder: "rgba(255,255,255,0.12)",
    hoverbarText: "#f6f7f8",
    hoverbarTextHover: "#828fff",
    hoverbarBtnHover: "rgba(94,106,210,0.16)",
    siderBg: "#0d0e13",
    headerBg: "rgba(10,11,15,0.92)",
    auroraA: "rgba(94,106,210,0.14)",
    auroraB: "rgba(94,106,210,0.08)",
    chartAccent: "#5e6ad2",
    chartSeries: "#5e6ad2",
    chartUp: "#ff5b5b",
    chartDown: "#37c871",
  },
  light: {
    bg: "#f7f8fa",
    panel: "rgba(255,255,255,0.66)",
    panel2: "rgba(255,255,255,0.5)",
    border: "rgba(18,24,45,0.10)",
    borderStrong: "rgba(18,24,45,0.18)",
    text: "#1b1d22",
    text2: "#525a66",
    text3: "#6b7280",
    accent: "#5e6ad2",
    accentLight: "#828fff",
    accentSoft: "rgba(94,106,210,0.12)",
    accentGrad: "linear-gradient(135deg,#828fff,#5e6ad2)",
    series: "#5e6ad2",
    warn: "#fa8c16",
    cat0: "#5e6ad2",
    cat1: "#5b8def",
    cat2: "#7c5ce0",
    cat3: "#16a34a",
    cat4: "#0e9fae",
    cat5: "#e04d7a",
    up: "#dc2626",
    down: "#16a34a",
    success: "#16a34a",
    danger: "#dc2626",
    radius: "12px",
    radiusSm: "8px",
    radiusXs: "6px",
    radiusLg: "16px",
    shadow: "0 1px 2px rgba(18,24,45,0.06), 0 8px 24px rgba(18,24,45,0.06)",
    shadowSm: "0 1px 2px rgba(18,24,45,0.05)",
    shadowCard: "0 1px 2px rgba(18,24,45,0.06), 0 10px 28px rgba(18,24,45,0.07)",
    cardBg: "#ffffff",
    cardBg2: "#f2f3f6",
    textSecondary: "#525a66",
    hoverbarBg: "rgba(255,255,255,0.92)",
    hoverbarBorder: "rgba(18,24,45,0.12)",
    hoverbarText: "#1b1d22",
    hoverbarTextHover: "#5e6ad2",
    hoverbarBtnHover: "rgba(94,106,210,0.12)",
    siderBg: "#ffffff",
    headerBg: "rgba(247,248,250,0.92)",
    auroraA: "rgba(94,106,210,0.12)",
    auroraB: "rgba(94,106,210,0.06)",
    chartAccent: "#5e6ad2",
    chartSeries: "#5e6ad2",
    chartUp: "#dc2626",
    chartDown: "#16a34a",
  },
};

const CSS_VAR_MAP: Record<keyof Tokens, string> = {
  bg: "--ops-bg",
  panel: "--ops-panel",
  panel2: "--ops-panel-2",
  border: "--ops-border",
  borderStrong: "--ops-border-strong",
  text: "--ops-text",
  text2: "--ops-text-2",
  text3: "--ops-text-3",
  accent: "--ops-accent",
  accentLight: "--ops-accent-light",
  accentSoft: "--ops-accent-soft",
  accentGrad: "--ops-accent-grad",
  series: "--ops-series",
  warn: "--ops-warn",
  cat0: "--ops-cat-0",
  cat1: "--ops-cat-1",
  cat2: "--ops-cat-2",
  cat3: "--ops-cat-3",
  cat4: "--ops-cat-4",
  cat5: "--ops-cat-5",
  up: "--ops-up",
  down: "--ops-down",
  success: "--ops-success",
  danger: "--ops-danger",
  radius: "--ops-radius",
  radiusSm: "--ops-radius-sm",
  radiusXs: "--ops-radius-xs",
  radiusLg: "--ops-radius-lg",
  shadow: "--ops-shadow",
  shadowSm: "--ops-shadow-sm",
  shadowCard: "--ops-shadow-card",
  cardBg: "--ops-card-bg",
  cardBg2: "--ops-card-bg-2",
  textSecondary: "--ops-text-secondary",
  hoverbarBg: "--ops-hoverbar-bg",
  hoverbarBorder: "--ops-hoverbar-border",
  hoverbarText: "--ops-hoverbar-text",
  hoverbarTextHover: "--ops-hoverbar-text-hover",
  hoverbarBtnHover: "--ops-hoverbar-btn-hover",
  siderBg: "--ops-sider-bg",
  headerBg: "--ops-header-bg",
  auroraA: "--ops-aurora-a",
  auroraB: "--ops-aurora-b",
  chartAccent: "--ops-chart-accent",
  chartSeries: "--ops-chart-series",
  chartUp: "--ops-chart-up",
  chartDown: "--ops-chart-down",
};

/** 把当前主题 token 写入 :root / body，供 CSS 与组件通过 var(--ops-*) 引用。 */
export function applyTokens(mode: ThemeMode): void {
  const t = TOKENS[mode];
  const root = document.documentElement;
  root.dataset.theme = mode;
  document.body.dataset.theme = mode;
  root.style.colorScheme = mode;
  (Object.keys(CSS_VAR_MAP) as (keyof Tokens)[]).forEach((key) => {
    root.style.setProperty(CSS_VAR_MAP[key], t[key]);
  });
}

/** 供 AntD ConfigProvider 派生的 token，与 CSS 变量同源。 */
export function antdTokens(mode: ThemeMode) {
  const t = TOKENS[mode];
  return {
    colorPrimary: t.accent,
    colorInfo: t.accent,
    colorLink: t.accent,
    colorBgBase: mode === "dark" ? "#0a0b0f" : "#f7f8fa",
    colorBgContainer: t.panel,
    colorBgElevated: t.panel,
    colorBgLayout: t.bg,
    colorBorder: t.border,
    colorBorderSecondary: t.border,
    colorText: t.text,
    colorTextSecondary: t.text2,
    colorTextTertiary: t.text3,
    colorFillTertiary: mode === "dark" ? "rgba(255,255,255,0.06)" : "rgba(18,24,45,0.05)",
    borderRadius: 8,
    controlHeight: 40,
    fontSize: 14,
    fontFamily:
      'Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
  };
}

/** AntD 组件级 token（Linear 专业深色 · 发丝边框）。 */
export function themeComponents(mode: ThemeMode) {
  const t = TOKENS[mode];
  const dark = mode === "dark";
  return {
    Layout: {
      siderBg: t.siderBg,
      headerBg: t.headerBg,
      bodyBg: t.bg,
    },
    Menu: {
      itemColor: t.text2,
      itemHoverColor: t.text,
      itemHoverBg: dark ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.7)",
      itemSelectedBg: dark ? "rgba(94,106,210,0.18)" : "rgba(94,106,210,0.14)",
      itemSelectedColor: dark ? "#c9d1ff" : "#4c56c9",
      itemBorderRadius: 8,
      itemMarginInline: 10,
      itemHeight: 42,
      iconSize: 17,
    },
    Card: { headerBg: "transparent" },
    Button: { fontWeight: 500, primaryShadow: "none", defaultShadow: "none" },
    Table: { headerBg: t.panel2, headerColor: t.text2 },
    Modal: { contentBg: dark ? "rgba(20,21,26,0.95)" : "rgba(255,255,255,0.94)" },
  };
}
