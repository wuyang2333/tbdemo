import { BarChartOutlined, ReloadOutlined, RobotOutlined, SettingOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, DatePicker, Drawer, Empty, Segmented, Space, Spin, Switch, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, fmtInt, fmtMoney } from "../components/analytics/analytics-ui";
import { AlertSettingsModal } from "../components/ui/alert-settings-modal";
import { useAlertConfig } from "../lib/use-alert-config";
import { HourlyPushButton } from "../components/ui/hourly-push";
import { buildRuleMessage, evalRule, ruleText } from "../lib/alert-rules";
import type { AnalyticsHourPoint, AnalyticsHours } from "../types";

const { Text } = Typography;

const QUICK_OPTIONS = [
  { label: "今日", value: "today" },
  { label: "昨日", value: "yesterday" },
  { label: "近7天", value: "7" },
];

const RANGE_PRESETS: { label: string; value: [dayjs.Dayjs, dayjs.Dayjs] }[] = [
  { label: "今日", value: [dayjs().startOf("day"), dayjs().endOf("day")] },
  { label: "昨日", value: [dayjs().subtract(1, "day").startOf("day"), dayjs().subtract(1, "day").endOf("day")] },
  { label: "过去7天", value: [dayjs().subtract(6, "day").startOf("day"), dayjs().endOf("day")] },
];

const METRIC_OPTIONS = [
  { label: "销售额", value: "sales" },
  { label: "访客", value: "visitors" },
  { label: "订单", value: "orders" },
  { label: "转化率", value: "conversion_rate" },
];

type MetricKey = "sales" | "visitors" | "orders" | "conversion_rate";

const HOURS_CFG_KEY = "analytics_hours_cfg_v1";
function readHoursConfig() {
  try {
    const raw = localStorage.getItem(HOURS_CFG_KEY);
    if (raw) {
      const c = JSON.parse(raw);
      return {
        quick: typeof c.quick === "string" ? c.quick : "today",
        metric: (["sales", "visitors", "orders", "conversion_rate"].includes(c.metric) ? c.metric : "sales") as MetricKey,
        scene: typeof c.scene === "string" ? c.scene : "all",
        compare: typeof c.compare === "boolean" ? c.compare : true,
        comparePromo: typeof c.comparePromo === "boolean" ? c.comparePromo : true,
        range: Array.isArray(c.range) && c.range.length === 2 ? (c.range as [string, string]) : null,
      };
    }
  } catch {}
  return { quick: "today", metric: "sales" as MetricKey, scene: "all", compare: true, comparePromo: true, range: null };
}

function ChangeBadge({ change }: { change: number | null | undefined }) {
  if (change == null) return <span style={{ color: "var(--ops-text-3)", fontSize: 11 }}>—</span>;
  const up = change >= 0;
  return (
    <span style={{ color: up ? "var(--ops-up)" : "var(--ops-down)", fontSize: 11, fontWeight: 600 }}>
      {up ? "+" : "-"}
      {Math.abs(change).toFixed(1)}%
    </span>
  );
}

function groupHours(hours: string[]): string[] {
  const nums = hours.map((h) => parseInt(h.slice(0, 2), 10)).sort((a, b) => a - b);
  if (!nums.length) return [];
  const ranges: string[] = [];
  let start = nums[0];
  let prev = nums[0];
  for (let i = 1; i < nums.length; i++) {
    if (nums[i] === prev + 1) {
      prev = nums[i];
      continue;
    }
    ranges.push(start === prev ? `${String(start).padStart(2, "0")}:00` : `${String(start).padStart(2, "0")}:00-${String(prev).padStart(2, "0")}:00`);
    start = nums[i];
    prev = nums[i];
  }
  ranges.push(start === prev ? `${String(start).padStart(2, "0")}:00` : `${String(start).padStart(2, "0")}:00-${String(prev).padStart(2, "0")}:00`);
  return ranges;
}

function HourChart({
  items,
  height,
  barSlots,
  tooltipFor,
  peakHours = [],
  anomaly,
}: {
  items: AnalyticsHourPoint[];
  height: number;
  barSlots: (item: AnalyticsHourPoint, idx: number) => React.ReactNode;
  tooltipFor: (item: AnalyticsHourPoint, idx: number) => React.ReactNode;
  peakHours?: string[];
  anomaly?: (item: AnalyticsHourPoint, idx: number) => React.ReactNode;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const n = items.length || 1;
  return (
    <div style={{ position: "relative", paddingTop: 12 }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 12,
          bottom: 22,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          pointerEvents: "none",
        }}
      >
        {[0, 1, 2, 3].map((i) => (
          <div key={i} style={{ borderTop: "1px solid var(--ops-border)" }} />
        ))}
      </div>
      <div style={{ position: "relative", display: "flex", alignItems: "stretch", gap: 2, height }}>
        {items.map((it, idx) => (
          <div
            key={it.hour}
            onMouseEnter={() => setHover(idx)}
            onMouseLeave={() => setHover(null)}
            style={{
              flex: 1,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 2,
              borderRadius: "var(--ops-radius-xs)",
              background: hover === idx ? "var(--ops-accent-soft)" : "transparent",
              transition: "background 0.15s",
            }}
          >
            {peakHours.includes(it.hour) && (
              <div style={{ fontSize: 9, color: peakHours[0] === it.hour ? "var(--ops-warn)" : "var(--ops-text-3)", lineHeight: 1 }}>★</div>
            )}
            {anomaly ? anomaly(it, idx) : null}
            <div style={{ width: "100%", flex: 1, display: "flex", alignItems: "flex-end", gap: 2, justifyContent: "center" }}>
              {barSlots(it, idx)}
            </div>
            <div style={{ fontSize: 9, color: "var(--ops-text-3)", whiteSpace: "nowrap" }}>{it.hour.slice(0, 2)}时</div>
          </div>
        ))}
      </div>
      {hover != null && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: `clamp(64px, calc(${(hover + 0.5) * (100 / n)}%), calc(100% - 64px))`,
            transform: "translateX(-50%)",
            background: "var(--ops-panel)",
            border: "1px solid var(--ops-border-strong)",
            borderRadius: "var(--ops-radius-sm)",
            padding: "6px 10px",
            fontSize: 12,
            lineHeight: 1.7,
            zIndex: 5,
            pointerEvents: "none",
            whiteSpace: "nowrap",
            boxShadow: "var(--ops-shadow-sm)",
          }}
        >
          {tooltipFor(items[hover], hover)}
        </div>
      )}
    </div>
  );
}

export function AnalyticsHoursPage() {
  const [data, setData] = useState<AnalyticsHours | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [cfgInit] = useState(readHoursConfig);
  const [quick, setQuick] = useState(cfgInit.quick);
  const [range, setRange] = useState<[string, string] | null>(cfgInit.range);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [compare, setCompare] = useState(cfgInit.compare);
  const [comparePromo, setComparePromo] = useState(cfgInit.comparePromo);
  const [metric, setMetric] = useState<MetricKey>(cfgInit.metric);
  const [scene, setScene] = useState(cfgInit.scene);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<{
    sections: { overall: string; highlights: string[]; conversion: string[]; risks: string[]; suggestions: string[] };
    range: string;
    recommended_hours: string[];
  } | null>(null);
  const { config: alertConfig, saveConfig: saveAlertConfig } = useAlertConfig();
  const [alertCfgOpen, setAlertCfgOpen] = useState(false);
  const [alertSaving, setAlertSaving] = useState(false);

  const load = useCallback(
    async (sid?: number) => {
      setLoading(true);
      try {
        let s: string;
        let e: string;
        if (range) {
          s = range[0];
          e = range[1];
        } else if (quick === "yesterday") {
          const y = dayjs().subtract(1, "day");
          s = y.format("YYYY-MM-DD");
          e = y.format("YYYY-MM-DD");
        } else if (quick === "7") {
          s = dayjs().subtract(6, "day").format("YYYY-MM-DD");
          e = dayjs().format("YYYY-MM-DD");
        } else {
          s = dayjs().format("YYYY-MM-DD");
          e = dayjs().format("YYYY-MM-DD");
        }
        const params = new URLSearchParams({ start: s, end: e });
        if (sid) params.set("store_id", String(sid));
        const { data: res } = await http.get<AnalyticsHours>(`/analytics/hours?${params.toString()}`);
        setData(res);
      setLastUpdated(dayjs().format("HH:mm:ss"));
      } catch (error) {
        message.error(getApiErrorMessage(error));
        setData(null);
      } finally {
        setLoading(false);
      }
    },
    [range, quick]
  );

  useEffect(() => {
    load(storeId);
  }, [load, storeId]);
  useAutoRefresh(() => load(storeId));
  useEffect(() => {
    try {
      localStorage.setItem(HOURS_CFG_KEY, JSON.stringify({ quick, range, metric, scene, compare, comparePromo }));
    } catch {}
  }, [quick, range, metric, scene, compare, comparePromo]);

  const syncHourly = async () => {
    setSyncing(true);
    try {
      const h = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/stores/sync-hourly");
      const p = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/promotions/sync?mode=realtime");
      showSyncFeedback("分时同步", [
        { ok: h.data.ok, total: h.data.total, results: h.data.results },
        { ok: p.data.ok, total: p.data.total, results: p.data.results },
      ]);
      await load(storeId);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const runAI = async () => {
    setAiOpen(true);
    setAiLoading(true);
    setAiResult(null);
    try {
      let s: string;
      let e: string;
      if (range) {
        s = range[0];
        e = range[1];
      } else if (quick === "yesterday") {
        const y = dayjs().subtract(1, "day");
        s = y.format("YYYY-MM-DD");
        e = y.format("YYYY-MM-DD");
      } else if (quick === "7") {
        s = dayjs().subtract(6, "day").format("YYYY-MM-DD");
        e = dayjs().format("YYYY-MM-DD");
      } else {
        s = dayjs().format("YYYY-MM-DD");
        e = dayjs().format("YYYY-MM-DD");
      }
      const params = new URLSearchParams({ start: s, end: e });
      if (storeId) params.set("store_id", String(storeId));
      const { data: res } = await http.post(`/analytics/hours/insight?${params.toString()}`, undefined, { timeout: 120000 });
      setAiResult(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiLoading(false);
    }
  };

  const items = data?.items ?? [];
  const sceneMap = data?.promo_by_scene ?? {};
  const sceneOptions = [
    { label: "全部", value: "all" },
    ...Object.keys(sceneMap).map((k) => ({ label: sceneMap[k].scene_name || k, value: k })),
  ];
  const promoItems = items.map((it) => {
    if (scene === "all" || !sceneMap[scene]) return it;
    const si = sceneMap[scene].items[it.hour] || { spend: 0, sales: 0, roi: 0 };
    return { ...it, promo_spend: si.spend, promo_sales: si.sales, promo_roi: si.roi };
  });

  const maxVisitors = Math.max(1, ...items.map((p) => p.visitors));
  const maxSales = Math.max(1, ...items.map((p) => p.sales));
  const maxOrders = Math.max(1, ...items.map((p) => p.orders));
  const maxConv = Math.max(0.01, ...items.map((p) => p.conversion_rate));
  const maxRoi = Math.max(0.01, ...promoItems.map((p) => p.promo_roi));
  const maxPrevRoi = Math.max(0.01, ...(data?.prev_promo_items ?? []).map((p) => (p.spend ? p.sales / p.spend : 0)));

  const metricValue = (it: AnalyticsHourPoint) =>
    metric === "sales" ? it.sales : metric === "visitors" ? it.visitors : metric === "orders" ? it.orders : it.conversion_rate;
  const metricMax = metric === "sales" ? maxSales : metric === "visitors" ? maxVisitors : metric === "orders" ? maxOrders : maxConv;
  const metricPrev = (idx: number) => {
    const p = data?.prev_items?.[idx];
    if (!p) return 0;
    return metric === "sales" ? p.sales : metric === "visitors" ? p.visitors : metric === "orders" ? p.orders : p.conversion_rate;
  };
  const maxPrevMetric = Math.max(1, ...(data?.prev_items ?? []).map((_, idx) => metricPrev(idx)));
  const metricCycle = (it: AnalyticsHourPoint) =>
    metric === "sales" ? it.sales_cycle : metric === "visitors" ? it.visitors_cycle : metric === "orders" ? it.orders_cycle : it.conversion_cycle;
  const metricLabel = ({ sales: "销售额", visitors: "访客", orders: "订单", conversion_rate: "转化率" } as Record<MetricKey, string>)[metric];
  const fmtMetric = (v: number) => (metric === "sales" ? fmtMoney(v) : metric === "conversion_rate" ? `${v.toFixed(2)}%` : fmtInt(v));
  const saveAlertCfg = async (patch: Parameters<typeof saveAlertConfig>[0]) => {
    setAlertSaving(true);
    try {
      await saveAlertConfig(patch);
      message.success("预警条件已保存");
      setAlertCfgOpen(false);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAlertSaving(false);
    }
  };
  const topMetricHours = [...items].sort((a, b) => metricValue(b) - metricValue(a)).slice(0, 3).map((p) => p.hour);
  const topRoiHours = [...promoItems].filter((p) => p.promo_roi > 0).sort((a, b) => b.promo_roi - a.promo_roi).slice(0, 3).map((p) => p.hour);
  const badHours = items.filter((p) => p.promo_spend > 0 && p.promo_roi < alertConfig.hour.roi_low).map((p) => p.hour);
  const hourAlerts: { level: string; type: string; message: string }[] = [];
  const recHours = items.filter((p) => p.promo_spend > 0 && p.promo_roi >= alertConfig.hour.roi_high).map((p) => p.hour);
  groupHours(recHours).forEach((r) => {
    hourAlerts.push({ level: "success", type: "建议投放", message: `${r} 推广ROI≥${alertConfig.hour.roi_high}，值得加大投放` });
  });
  groupHours(badHours).forEach((r) => {
    hourAlerts.push({ level: "error", type: "ROI 偏低", message: `${r} 推广ROI<${alertConfig.hour.roi_low}，建议停投` });
  });
  for (const rule of alertConfig.rules.filter((r) => r.module === "hour")) {
    for (const hp of items) {
      if (evalRule(rule, hp as unknown as Record<string, unknown>)) {
        hourAlerts.push({ level: "warning", type: `自定义·${ruleText(rule)}`, message: buildRuleMessage(rule, hp as unknown as Record<string, unknown>, hp.hour) });
        if (hourAlerts.length >= 20) break;
      }
    }
    if (hourAlerts.length >= 20) break;
  }

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="时段分析"
        extra={
          <Space wrap>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<RobotOutlined />} onClick={runAI}>
              AI 时段解读
            </Button>
            <HourlyPushButton scope="hours" />
            <Button icon={<ReloadOutlined />} onClick={() => load(storeId)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncHourly}>
              同步分时数据
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented
          options={QUICK_OPTIONS}
          value={range ? undefined : quick}
          onChange={(v) => {
            setRange(null);
            setQuick(String(v));
          }}
        />
        <DatePicker.RangePicker
          presets={RANGE_PRESETS}
          value={range ? [dayjs(range[0]), dayjs(range[1])] : null}
          onChange={(dates) => {
            if (dates && dates[0] && dates[1]) setRange([dates[0].format("YYYY-MM-DD"), dates[1].format("YYYY-MM-DD")]);
            else setRange(null);
          }}
          allowClear
          placeholder={["开始日期", "结束日期"]}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          当前范围：{data?.label ?? "今日"}
          {data?.peak_hour && data.peak_sales > 0 ? ` · 销售高峰 ${data.peak_hour}（${fmtMoney(data.peak_sales)}）` : ""}
        </Text>
        <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
      </Space>

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description="暂无分时数据，点「同步分时数据」抓取" />
        </Card>
      ) : (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
            {[
              { label: "访客", value: fmtInt(data.summary.visitors) },
              { label: "浏览量", value: fmtInt(data.summary.pv) },
              { label: "销售额", value: fmtMoney(data.summary.sales) },
              { label: "订单", value: fmtInt(data.summary.orders) },
              { label: "推广花费", value: fmtMoney(data.summary.promo_spend) },
              { label: "推广成交", value: fmtMoney(data.summary.promo_sales) },
              { label: "推广ROI", value: data.summary.promo_roi.toFixed(2) },
            ].map((m) => (
              <div
                key={m.label}
                style={{
                  flex: "1 1 140px",
                  minWidth: 130,
                  padding: "10px 14px",
                  borderRadius: "var(--ops-radius)",
                  background: "var(--ops-card-bg-2)",
                  border: "1px solid var(--ops-border)",
                }}
              >
                <div style={{ fontSize: 12, color: "var(--ops-text-secondary)", marginBottom: 2 }}>{m.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{m.value}</div>
              </div>
            ))}
          </div>

          {items.length > 0 && hourAlerts.length > 0 && (
            <Card
              variant="borderless"
              title="时段预警"
              style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}
              extra={
                <Button size="small" icon={<SettingOutlined />} onClick={() => setAlertCfgOpen(true)}>预警设置</Button>
              }
            >
              <div style={{ maxHeight: 170, overflowY: "auto", paddingRight: 4 }}>
                <div style={{ display: "grid", gap: 4 }}>
                  {hourAlerts.map((a, i) => (
                    <div key={i} style={{ fontSize: 13, color: a.level === "error" ? "var(--ops-danger)" : a.level === "success" ? "var(--ops-success)" : "var(--ops-warn)" }}>
                      {a.level === "error" ? "⚠️ " : a.level === "success" ? "✅ " : "❗ "}
                      [{a.type}] {a.message}
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          )}
{items.length > 0 && hourAlerts.length === 0 && (
            <Card
              variant="borderless"
              title="时段预警"
              style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}
              extra={
                <Button size="small" icon={<SettingOutlined />} onClick={() => setAlertCfgOpen(true)}>预警设置</Button>
              }
            >
              <div style={{ fontSize: 13, color: "var(--ops-text-3)" }}>
                暂无时段预警（未达到 建议投放ROI≥{alertConfig.hour.roi_high}、或 ROI低于{alertConfig.hour.roi_low} 的条件）
              </div>
            </Card>
          )}

          <Card
            variant="borderless"
            title={`24 小时 ${metricLabel}分布`}
            style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}
            extra={
              <Space wrap>
                <Segmented size="small" options={METRIC_OPTIONS} value={metric} onChange={(v) => setMetric(String(v) as MetricKey)} />
                <Switch checked={compare} onChange={setCompare} checkedChildren="对比上一周期" unCheckedChildren="不对比" />
              </Space>
            }
          >
            <HourChart
              items={items}
              height={190}
              peakHours={topMetricHours}
              anomaly={(it) => {
                const c = it.sales_cycle;
                if (c == null) return null;
                if (c <= -alertConfig.hour.drop_pct) return <div title={`销售额环比 ${c.toFixed(1)}%`} style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--ops-down)", marginBottom: 1 }} />;
                if (c >= alertConfig.hour.surge_pct) return <div title={`销售额环比 +${c.toFixed(1)}%`} style={{ width: 7, height: 7, borderRadius: "50%", background: "var(--ops-warn)", marginBottom: 1 }} />;
                return null;
              }}
              barSlots={(it, idx) => {
                const prev = metricPrev(idx);
                return (
                  <>
                    {compare && (
                      <div style={{ width: "40%", height: `${(prev / maxPrevMetric) * 100}%`, background: "var(--ops-text-3)", borderRadius: "4px 4px 0 0", minHeight: prev ? 2 : 0 }} />
                    )}
                    <div style={{ width: "40%", height: `${(metricValue(it) / metricMax) * 100}%`, background: "linear-gradient(180deg, var(--ops-accent-light), var(--ops-accent))", borderRadius: "4px 4px 0 0", minHeight: metricValue(it) ? 2 : 0 }} />
                  </>
                );
              }}
              tooltipFor={(it, idx) => (
                <>
                  <b>{it.hour}</b>
                  <div>
                    {metricLabel} {fmtMetric(metricValue(it))}
                  </div>
                  {compare && <div>上期 {metricLabel} {fmtMetric(metricPrev(idx))}</div>}
                  <div>
                    环比 <ChangeBadge change={metricCycle(it)} />
                  </div>
                </>
              )}
            />
            <Space style={{ marginTop: 8 }}>
              <Tag color="orange">{metricLabel}</Tag>
              {compare && <Tag>上期{metricLabel}</Tag>}
              <Tag color="orange">★ 前3高峰</Tag>
              <Tag color="green">● 环比骤降≥50%</Tag>
              <Tag color="orange">● 环比暴涨≥100%</Tag>
            </Space>
          </Card>

          <Card
            variant="borderless"
            title="24 小时 推广ROI（柱高=ROI）"
            style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}
            extra={
              <Space wrap>
                <Segmented size="small" options={sceneOptions} value={scene} onChange={(v) => setScene(String(v))} />
                <Switch checked={comparePromo} onChange={setComparePromo} checkedChildren="对比上一周期" unCheckedChildren="不对比" />
              </Space>
            }
          >
            <HourChart
              items={promoItems}
              height={170}
              peakHours={topRoiHours}
              barSlots={(it, idx) => {
                const prev = data?.prev_promo_items?.[idx];
                const prevRoi = prev && prev.spend ? prev.sales / prev.spend : 0;
                const roi = it.promo_roi;
                const roiColor = roi >= 2 ? "var(--ops-success)" : roi >= 1 ? "var(--ops-warn)" : "var(--ops-danger)";
                return (
                  <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end" }}>
                    <div style={{ fontSize: 9, fontWeight: 600, color: roi > 0 ? roiColor : "var(--ops-text-3)" }}>
                      {roi > 0 ? roi.toFixed(1) : ""}
                    </div>
                    <div style={{ flex: 1, display: "flex", alignItems: "flex-end", gap: 2, justifyContent: "center", width: "100%" }}>
                      {comparePromo && (
                        <div style={{ width: "28%", height: `${(prevRoi / maxPrevRoi) * 100}%`, background: "var(--ops-text-3)", borderRadius: "4px 4px 0 0", minHeight: prevRoi ? 2 : 0 }} />
                      )}
                      <div style={{ width: "28%", height: `${(roi / maxRoi) * 100}%`, background: roiColor, borderRadius: "4px 4px 0 0", minHeight: roi ? 2 : 0 }} />
                    </div>
                  </div>
                );
              }}
              tooltipFor={(it, idx) => (
                <>
                  <b>{it.hour}</b>
                  <div>花费 {fmtMoney(it.promo_spend)}</div>
                  <div>成交 {fmtMoney(it.promo_sales)}</div>
                  {comparePromo && (
                    <div>
                      上期ROI{" "}
                      {(() => { const p = data?.prev_promo_items?.[idx]; return p && p.spend ? (p.sales / p.spend).toFixed(2) : "—"; })()}
                    </div>
                  )}
                  <div>ROI {it.promo_roi.toFixed(2)}</div>
                </>
              )}
            />
            <Space style={{ marginTop: 8 }}>
              <Tag color="green">ROI≥2 绿</Tag>
              <Tag color="orange">ROI 1~2 橙</Tag>
              <Tag color="red">ROI&lt;1 红</Tag>
              {comparePromo && <Tag>上期ROI 灰</Tag>}
              <Tag color="orange">★ ROI 前3</Tag>
            </Space>
          </Card>

          <Card variant="borderless" title="时段分组（凌晨/上午/下午/晚间/深夜）" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
              {data.segments.map((seg) => (
                <div key={seg.name} style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ fontSize: 13 }}>
                    {seg.name} <Text type="secondary" style={{ fontSize: 11 }}>{seg.hours}</Text>
                  </Text>
                  <div style={{ fontSize: 12, marginTop: 6, lineHeight: 1.9, color: "var(--ops-text-secondary)" }}>
                    销售 {fmtMoney(seg.sales)}（占{seg.sales_pct}%）
                    <br />
                    访客 {fmtInt(seg.visitors)}（占{seg.visitors_pct}%）· 订单 {seg.orders}
                    <br />
                    推广花费 {fmtMoney(seg.promo_spend)} · ROI {seg.promo_roi.toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card variant="borderless" title="分时明细（环比 = 较上一周期同时段）" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(155px, 1fr))", gap: 8 }}>
              {items.map((p) => (
                <div key={p.hour} style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius-sm)", padding: "8px 10px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <Text strong style={{ fontSize: 13 }}>{p.hour}</Text>
                    <ChangeBadge change={p.sales_cycle} />
                  </div>
                  <div style={{ fontSize: 12, marginTop: 4, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>
                    访客 {fmtInt(p.visitors)} · 销售 {fmtMoney(p.sales)}
                    <br />
                    订单 {p.orders} · 转化 {p.conversion_rate.toFixed(2)}%
                    <br />
                    推广 {fmtMoney(p.promo_spend)} · ROI {p.promo_roi.toFixed(2)}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      <Drawer
        title="AI 时段解读"
        width={520}
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        destroyOnHidden
      >
        {aiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="AI 正在分析时段数据…" />
          </div>
        ) : aiResult ? (
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
              解读范围：{aiResult.range}
            </Text>
            {aiResult.recommended_hours.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>建议投放时段（推广ROI≥2）</div>
                <Space wrap>
                  {aiResult.recommended_hours.map((h) => (
                    <Tag key={h} color="green">
                      {h}
                    </Tag>
                  ))}
                </Space>
              </div>
            )}
            {aiResult.sections.overall && (
              <div style={{ padding: "12px 14px", borderRadius: "var(--ops-radius)", background: "var(--ops-accent-soft)", borderLeft: "3px solid var(--ops-accent)", marginBottom: 10 }}>
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{aiResult.sections.overall}</Text>
              </div>
            )}
            <div style={{ display: "grid", gap: 8 }}>
              {aiResult.sections.highlights.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-success)" }}>销售时段规律</Text>
                  {aiResult.sections.highlights.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.conversion.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-accent)" }}>流量与转化</Text>
                  {aiResult.sections.conversion.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.risks.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-danger)" }}>风险提醒</Text>
                  {aiResult.sections.risks.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.suggestions.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-accent-light)" }}>投放建议</Text>
                  {aiResult.sections.suggestions.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <Empty description="生成失败或暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 40 }} />
        )}
      </Drawer>
      <AlertSettingsModal
        open={alertCfgOpen}
        title="时段预警条件设置"
        module="hour"
        config={alertConfig}
        rules={alertConfig.rules}
        onCancel={() => setAlertCfgOpen(false)}
        onSave={saveAlertCfg}
        saving={alertSaving}
        fields={[
          { group: "hour", key: "roi_high", label: "建议投放 ROI 门槛", hint: "达到该 ROI 的小时提示建议投放", min: 0.1, max: 100, step: 0.1 },
          { group: "hour", key: "roi_low", label: "建议停投 ROI 门槛", hint: "低于该 ROI 且在投的小时提示停投", min: 0.1, max: 100, step: 0.1 },
          { group: "hour", key: "drop_pct", label: "异常骤降阈值 %", hint: "销售额环比下跌超过该百分比标红", min: 1, max: 500, step: 5 },
          { group: "hour", key: "surge_pct", label: "异常暴涨阈值 %", hint: "销售额环比上涨超过该百分比标橙", min: 1, max: 500, step: 5 },
        ]}
      />
    </div>
  );
}
