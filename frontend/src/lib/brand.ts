/** 品牌配置：默认值 + 支持设置中心动态覆盖（localStorage tb-brand）。 */
const DEFAULTS = {
  name: "淘宝运营工作台",
  shortName: "TB Ops",
  logoText: "淘",
  logoUrl: "",
  tagline: "淘宝店铺运营中台",
  eyebrow: "TAOBAO OPS",
  primaryColor: "#f05a1a",
  primaryLight: "#ff7a3d",
  gradient: "linear-gradient(135deg, #ff7a3d 0%, #f05a1a 100%)",
};

// 经营决策台改版一次性迁移：旧紫蓝品牌色切换为淘宝橙。
const LEGACY_PRIMARY = new Set(["#5e6ad2", "#ff7a1f", "#0066cc"]);
const LEGACY_LIGHT = new Set(["#828fff", "#ffb061", "#2997ff"]);

export const BRAND: Record<string, string> = { ...DEFAULTS };

try {
  const raw = localStorage.getItem("tb-brand");
  if (raw) {
    const saved = JSON.parse(raw) as Record<string, string>;
    let changed = false;
    if (LEGACY_PRIMARY.has(saved.primaryColor)) {
      saved.primaryColor = DEFAULTS.primaryColor;
      changed = true;
    }
    if (LEGACY_LIGHT.has(saved.primaryLight)) {
      saved.primaryLight = DEFAULTS.primaryLight;
      changed = true;
    }
    if (
      saved.gradient &&
      (saved.gradient.includes("#ffb061") ||
        saved.gradient.includes("#ff5a1f") ||
        saved.gradient.includes("#0066cc") ||
        saved.gradient.includes("#5e6ad2"))
    ) {
      saved.gradient = DEFAULTS.gradient;
      changed = true;
    }
    Object.keys(DEFAULTS).forEach((k) => {
      if (saved[k]) BRAND[k] = saved[k];
    });
    if (changed) localStorage.setItem("tb-brand", JSON.stringify(saved));
  }
} catch {
  /* 保持默认 */
}
