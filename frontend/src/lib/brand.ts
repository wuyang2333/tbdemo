/** 品牌配置：默认值 + 支持设置中心动态覆盖（localStorage tb-brand）。 */
const DEFAULTS = {
  name: "淘宝运营工作台",
  shortName: "TB Ops",
  logoText: "淘",
  logoUrl: "",
  tagline: "淘宝店铺运营中台",
  eyebrow: "TAOBAO OPS",
  primaryColor: "#ff7a1f",
  primaryLight: "#ffb061",
  gradient: "linear-gradient(135deg, #ffb061 0%, #ff5a1f 100%)",
};

export const BRAND: Record<string, string> = { ...DEFAULTS };

try {
  const raw = localStorage.getItem("tb-brand");
  if (raw) {
    const saved = JSON.parse(raw);
    Object.keys(DEFAULTS).forEach((k) => {
      if (saved[k]) BRAND[k] = saved[k];
    });
  }
} catch {
  /* 保持默认 */
}