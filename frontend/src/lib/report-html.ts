// 经营日报 PDF：生成一份专门设计的报告 HTML（与网页布局分开，打印用）
import type { AnalyticsReport } from "../types";

function pct(cur: number, prev: number): string {
  if (!prev) return "—";
  const c = ((cur - prev) / prev) * 100;
  return `${c >= 0 ? "+" : ""}${c.toFixed(1)}%`;
}
function fmt(v: number): string {
  return `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtInt(v: number): string {
  return v.toLocaleString("zh-CN");
}
function esc(s: string): string {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function chgCls(s: string): string {
  return s.startsWith("-") ? "down" : "up";
}

export function buildReportHtml(data: AnalyticsReport): string {
  const t = data.today;
  const y = data.yesterday;
  const now = new Date();
  const nowStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")} ${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;

  const pt = data.promo_today;
  const py = data.promo_yesterday;
  const metrics = [
    { label: "访客", value: fmtInt(t.visitors), chg: pct(t.visitors, y.visitors) },
    { label: "销售额", value: fmt(t.sales), chg: pct(t.sales, y.sales) },
    { label: "订单", value: fmtInt(t.orders), chg: pct(t.orders, y.orders) },
    { label: "转化率", value: `${t.conversion_rate}%`, chg: pct(t.conversion_rate, y.conversion_rate) },
    { label: "客单价", value: fmt(t.avg_order_value), chg: pct(t.avg_order_value, y.avg_order_value) },
    { label: "真实ROI", value: `${pt.spend > 0 ? (t.sales / pt.spend).toFixed(2) : "—"}`, chg: pct(t.sales / pt.spend, y.sales / py.spend) },
  ];
  const metricHtml = metrics
    .map(
      (m) => `
      <div class="metric">
        <div class="metric-label">${m.label}</div>
        <div class="metric-value">${m.value}</div>
        <div class="metric-chg ${chgCls(m.chg)}">较前日 ${m.chg}</div>
      </div>`
    )
    .join("");

  const sceneRows = data.promo_today_scenes
    .map(
      (s) => `
      <tr>
        <td>${esc(s.scene_name)}</td>
        <td class="num">${fmt(s.spend)}</td>
        <td class="num">${fmt(s.sales)}</td>
        <td class="num">${s.roi.toFixed(2)}</td>
      </tr>`
    )
    .join("");

  const topRows = data.top_today
    .map(
      (it, i) => `
      <tr>
        <td class="rank ${i < 3 ? "rank-top" : ""}">${i + 1}</td>
        <td>${esc(it.item_title)}</td>
        <td class="num">${fmt(it.sales)}</td>
        <td class="num">${fmtInt(it.orders)}</td>
      </tr>`
    )
    .join("");


  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>经营日报 ${data.date}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; color: #1f2430; background: #fff; padding: 42px 48px; font-size: 13px; line-height: 1.6; }
  .report-header { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 3px solid #ff5000; padding-bottom: 14px; margin-bottom: 26px; }
  .report-header h1 { font-size: 26px; font-weight: 800; letter-spacing: 3px; color: #14161a; }
  .report-header .sub { color: #9aa4b4; font-size: 11px; letter-spacing: 2px; margin-top: 4px; }
  .report-header .meta { text-align: right; }
  .report-header .meta .date { font-size: 20px; font-weight: 800; color: #ff5000; font-variant-numeric: tabular-nums; }
  .report-header .meta .who { color: #9aa4b4; font-size: 12px; margin-top: 2px; }
  .section { margin-bottom: 26px; }
  .section-title { display: flex; align-items: center; gap: 9px; font-size: 15px; font-weight: 700; color: #14161a; margin-bottom: 14px; }
  .section-title::before { content: ""; width: 4px; height: 16px; background: #ff5000; border-radius: 2px; }
  .metric-strip { display: flex; gap: 12px; }
  .metric { flex: 1; border: 1px solid #edf0f5; border-radius: 12px; padding: 14px 16px; background: linear-gradient(180deg, #fbfcfe, #f6f8fc); }
  .metric-label { font-size: 12px; color: #8a94a6; }
  .metric-value { font-size: 21px; font-weight: 800; color: #14161a; margin-top: 3px; font-variant-numeric: tabular-nums; }
  .metric-chg { font-size: 12px; margin-top: 3px; font-weight: 600; }
  .up { color: #ff5000; }
  .down { color: #17a34a; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #edf0f5; padding: 10px 12px; text-align: left; }
  th { background: #fafbfe; color: #5a6472; font-weight: 600; font-size: 12px; }
  td { color: #1f2430; font-size: 13px; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .rank { width: 32px; color: #9aa4b4; font-weight: 600; }
  .rank-top { color: #ff5000; font-weight: 800; }
  .alert-item { display: flex; gap: 8px; align-items: flex-start; padding: 9px 13px; border-radius: 8px; margin-bottom: 7px; font-size: 13px; }
  .alert-ico { flex-shrink: 0; }
  .alert-error { background: #fff2f0; color: #d4380d; }
  .alert-warn { background: #fffbe6; color: #d48806; }
  .goal { display: flex; justify-content: space-between; align-items: center; border: 1px solid #edf0f5; border-radius: 12px; padding: 14px 18px; background: linear-gradient(90deg, #fff6f1, #fff); }
  .goal .g-label { font-size: 12px; color: #8a94a6; }
  .goal .g-value { font-size: 16px; font-weight: 800; color: #14161a; margin-top: 3px; }
  .goal .g-pct { font-size: 15px; font-weight: 800; color: #ff5000; }
  .foot { margin-top: 30px; padding-top: 14px; border-top: 1px solid #edf0f5; color: #a5adbb; font-size: 11px; text-align: center; }
</style>
</head>
<body>
  <div class="report-header">
    <div>
      <h1>经营日报</h1>
      <div class="sub">TAOBAO OPS DAILY REPORT</div>
    </div>
    <div class="meta">
      <div class="date">${data.date}</div>
      <div class="who">数据分析报告</div>
    </div>
  </div>

  <div class="section">
    <div class="section-title">核心指标</div>
    <div class="metric-strip">${metricHtml}</div>
  </div>

  <div class="section">
    <div class="section-title">推广表现</div>
    <table>
      <tr><th>场景</th><th class="num">花费</th><th class="num">成交</th><th class="num">ROI</th></tr>
      ${sceneRows || '<tr><td colspan="4">暂无推广数据</td></tr>'}
    </table>
    <div style="margin-top:8px;color:#5a6472;font-size:13px;">合计：花费 ${fmt(pt.spend)} · 成交 ${fmt(pt.sales)} · ROI ${pt.roi.toFixed(2)}</div>
  </div>

  <div class="section">
    <div class="section-title">TOP 商品</div>
    <table>
      <tr><th>#</th><th>商品</th><th class="num">销售额</th><th class="num">订单</th></tr>
      ${topRows || '<tr><td colspan="4">暂无商品数据</td></tr>'}
    </table>
  </div>

  ${data.goal ? `<div class="section">
    <div class="section-title">月度目标</div>
    <div class="goal">
      <div>
        <div class="g-label">${data.month} 目标</div>
        <div class="g-value">${fmt(data.goal)} · 已达成 ${fmt(data.month_sales)}</div>
      </div>
      <div class="g-pct">${data.goal ? ((data.month_sales / data.goal) * 100).toFixed(1) : "0"}%</div>
    </div>
  </div>` : ""}

  <div class="foot">生成时间 ${nowStr} · 数据来源：生意参谋 / 万相台</div>
</body>
</html>`;
}
