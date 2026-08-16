import { BarChartOutlined, ReloadOutlined, RobotOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, DatePicker, Drawer, Empty, Segmented, Space, Spin, Switch, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, fmtInt, fmtMoney } from "../components/analytics/analytics-ui";
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

function ChangeBadge({ change }: { change: number | null | undefined }) {
  if (change == null) return <span style={{ color: "rgba(128,128,128,0.55)", fontSize: 11 }}>—</span>;
  const up = change >= 0;
  return (
    <span style={{ color: up ? "#ff4d4f" : "#52c41a", fontSize: 11, fontWeight: 600 }}>
      {up ? "+" : "-"}
      {Math.abs(change).toFixed(1)}%
    </span>
  );
}

function HourChart({
  items,
  height,
  barSlots,
  tooltipFor,
  peakHour,
}: {
  items: AnalyticsHourPoint[];
  height: number;
  barSlots: (item: AnalyticsHourPoint, idx: number) => React.ReactNode;
  tooltipFor: (item: AnalyticsHourPoint, idx: number) => React.ReactNode;
  peakHour?: string;
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
              borderRadius: 4,
              background: hover === idx ? "var(--ops-accent-soft)" : "transparent",
              transition: "background 0.15s",
            }}
          >
            {peakHour === it.hour && <div style={{ fontSize: 9, color: "#fa8c16", lineHeight: 1 }}>★</div>}
            <div style={{ width: "100%", flex: 1, display: "flex", alignItems: "flex-end", gap: 2, justifyContent: "center" }}>
              {barSlots(it, idx)}
            </div>
            <div style={{ fontSize: 9, color: "rgba(128,128,128,0.8)", whiteSpace: "nowrap" }}>{it.hour.slice(0, 2)}时</div>
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
            background: "rgba(18,21,29,0.96)",
            border: "1px solid var(--ops-border-strong)",
            borderRadius: 8,
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
  const [quick, setQuick] = useState("today");
  const [range, setRange] = useState<[string, string] | null>(null);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [compare, setCompare] = useState(true);
  const [comparePromo, setComparePromo] = useState(true);
  const [metric, setMetric] = useState<MetricKey>("sales");
  const [scene, setScene] = useState("all");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<{
    sections: { overall: string; highlights: string[]; conversion: string[]; risks: string[]; suggestions: string[] };
    range: string;
    recommended_hours: string[];
  } | null>(null);

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

  const syncHourly = async () => {
    setSyncing(true);
    try {
      const h = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/stores/sync-hourly");
      const p = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/promotions/sync?mode=realtime");
      message.success(`分时同步完成：店铺分时 ${h.data.ok}/${h.data.total} 家，推广分时 ${p.data.ok}/${p.data.total} 家`);
      [...h.data.results, ...p.data.results]
        .filter((r) => !r.ok)
        .slice(0, 3)
        .forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
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
  const metricPeakHour = items.length ? items.reduce((a, b) => (metricValue(b) > metricValue(a) ? b : a)).hour : undefined;
  const metricLabel = ({ sales: "销售额", visitors: "访客", orders: "订单", conversion_rate: "转化率" } as Record<MetricKey, string>)[metric];
  const fmtMetric = (v: number) => (metric === "sales" ? fmtMoney(v) : metric === "conversion_rate" ? `${v.toFixed(2)}%` : fmtInt(v));

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
                  borderRadius: 10,
                  background: "var(--ops-card-bg-2)",
                  border: "1px solid var(--ops-border)",
                }}
              >
                <div style={{ fontSize: 12, color: "var(--ops-text-secondary)", marginBottom: 2 }}>{m.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{m.value}</div>
              </div>
            ))}
          </div>

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
              peakHour={metricPeakHour}
              barSlots={(it, idx) => {
                const prev = metricPrev(idx);
                return (
                  <>
                    {compare && (
                      <div style={{ width: "40%", height: `${(prev / maxPrevMetric) * 100}%`, background: "rgba(128,128,128,0.4)", borderRadius: "4px 4px 0 0", minHeight: prev ? 2 : 0 }} />
                    )}
                    <div style={{ width: "40%", height: `${(metricValue(it) / metricMax) * 100}%`, background: "linear-gradient(180deg, #ff8a3d, #ff5000)", borderRadius: "4px 4px 0 0", minHeight: metricValue(it) ? 2 : 0 }} />
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
              <Tag color="var(--ops-accent)">{metricLabel}</Tag>
              {compare && <Tag>上期{metricLabel}</Tag>}
              <Tag color="#fa8c16">★ {metricLabel}最高</Tag>
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
              peakHour={promoItems.find((it) => it.promo_roi > 0 && it.promo_roi >= maxRoi)?.hour}
              barSlots={(it, idx) => {
                const prev = data?.prev_promo_items?.[idx];
                const prevRoi = prev && prev.spend ? prev.sales / prev.spend : 0;
                const roi = it.promo_roi;
                const roiColor = roi >= 2 ? "#52c41a" : roi >= 1 ? "#fa8c16" : "#ff4d4f";
                return (
                  <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "flex-end" }}>
                    <div style={{ fontSize: 9, fontWeight: 600, color: roi > 0 ? roiColor : "rgba(128,128,128,0.6)" }}>
                      {roi > 0 ? roi.toFixed(1) : ""}
                    </div>
                    <div style={{ flex: 1, display: "flex", alignItems: "flex-end", gap: 2, justifyContent: "center", width: "100%" }}>
                      {comparePromo && (
                        <div style={{ width: "28%", height: `${(prevRoi / maxPrevRoi) * 100}%`, background: "rgba(128,128,128,0.4)", borderRadius: "4px 4px 0 0", minHeight: prevRoi ? 2 : 0 }} />
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
              <Tag color="#52c41a">ROI≥2 绿</Tag>
              <Tag color="#fa8c16">ROI 1~2 橙</Tag>
              <Tag color="#ff4d4f">ROI&lt;1 红</Tag>
              {comparePromo && <Tag>上期ROI 灰</Tag>}
              <Tag color="#fa8c16">★ ROI 最高</Tag>
            </Space>
          </Card>

          <Card variant="borderless" title="时段分组（凌晨/上午/下午/晚间/深夜）" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
              {data.segments.map((seg) => (
                <div key={seg.name} style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
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
                <div key={p.hour} style={{ border: "1px solid var(--ops-border)", borderRadius: 8, padding: "8px 10px" }}>
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
        destroyOnClose
      >
        {aiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin tip="AI 正在分析时段数据…" />
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
              <div style={{ padding: "12px 14px", borderRadius: 10, background: "var(--ops-accent-soft)", borderLeft: "3px solid var(--ops-accent)", marginBottom: 10 }}>
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{aiResult.sections.overall}</Text>
              </div>
            )}
            <div style={{ display: "grid", gap: 8 }}>
              {aiResult.sections.highlights.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "#52c41a" }}>销售时段规律</Text>
                  {aiResult.sections.highlights.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.conversion.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "#1677ff" }}>流量与转化</Text>
                  {aiResult.sections.conversion.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.risks.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "#ff4d4f" }}>风险提醒</Text>
                  {aiResult.sections.risks.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.suggestions.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
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
    </div>
  );
}
