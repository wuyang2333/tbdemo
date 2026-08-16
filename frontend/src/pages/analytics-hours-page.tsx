import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, DatePicker, Empty, Segmented, Space, Spin, Switch, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, fmtInt, fmtMoney } from "../components/analytics/analytics-ui";
import type { AnalyticsHours } from "../types";

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

export function AnalyticsHoursPage() {
  const [data, setData] = useState<AnalyticsHours | null>(null);
  const [quick, setQuick] = useState("today");
  const [range, setRange] = useState<[string, string] | null>(null);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [compare, setCompare] = useState(true);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

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

  const items = data?.items ?? [];
  const maxVisitors = Math.max(1, ...items.map((p) => p.visitors));
  const maxSales = Math.max(1, ...items.map((p) => p.sales));
  const maxPrev = Math.max(1, ...(data?.prev_items ?? []).map((p) => p.sales));
  const maxPromo = Math.max(1, ...items.map((p) => p.promo_spend));
  const maxRoi = Math.max(0, ...items.map((p) => p.promo_roi));

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="时段分析"
        extra={
          <Space wrap>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
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
          {data?.peak_hour ? ` · 销售高峰 ${data.peak_hour}（${fmtMoney(data.peak_sales)}）` : ""}
        </Text>
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
            title="24 小时 访客 / 销售额分布"
            style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}
            extra={
              <Switch checked={compare} onChange={setCompare} checkedChildren="对比上一周期" unCheckedChildren="不对比" />
            }
          >
            <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 190 }}>
              {items.map((p, idx) => {
                const prev = data?.prev_items?.[idx]?.sales ?? 0;
                return (
                  <div
                    key={p.hour}
                    style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}
                    title={`${p.hour} 访客 ${p.visitors} / 销售 ${fmtMoney(p.sales)}${compare ? ` / 上期 ${fmtMoney(prev)}` : ""}`}
                  >
                    <div style={{ width: "100%", flex: 1, display: "flex", alignItems: "flex-end", gap: 2, justifyContent: "center" }}>
                      {compare && (
                        <div style={{ width: "26%", height: `${(prev / maxPrev) * 100}%`, background: "rgba(128,128,128,0.45)", borderRadius: "3px 3px 0 0", minHeight: prev ? 2 : 0 }} />
                      )}
                      <div style={{ width: "26%", height: `${(p.visitors / maxVisitors) * 100}%`, background: "var(--ops-accent)", borderRadius: "3px 3px 0 0", minHeight: p.visitors ? 2 : 0 }} />
                      <div style={{ width: "26%", height: `${(p.sales / maxSales) * 100}%`, background: "#52c41a", borderRadius: "3px 3px 0 0", minHeight: p.sales ? 2 : 0 }} />
                    </div>
                    <div style={{ fontSize: 9, color: "rgba(128,128,128,0.8)", whiteSpace: "nowrap" }}>{p.hour.slice(0, 2)}时</div>
                  </div>
                );
              })}
            </div>
            <Space style={{ marginTop: 8 }}>
              <Tag color="var(--ops-accent)">访客</Tag>
              <Tag color="#52c41a">销售额</Tag>
              {compare && <Tag>上期销售额</Tag>}
            </Space>
          </Card>

          <Card variant="borderless" title="24 小时 推广花费 / ROI" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 170 }}>
              {items.map((p) => {
                const roi = p.promo_roi;
                const isTop = roi > 0 && roi >= maxRoi;
                return (
                  <div
                    key={p.hour}
                    style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}
                    title={`${p.hour} 花费 ${fmtMoney(p.promo_spend)} / ROI ${roi}`}
                  >
                    <div style={{ fontSize: 9, fontWeight: 600, color: roi > 0 ? (roi >= 2 ? "#52c41a" : roi >= 1 ? "#fa8c16" : "#ff4d4f") : "rgba(128,128,128,0.6)" }}>
                      {isTop ? "★" : ""}
                      {roi > 0 ? roi.toFixed(1) : ""}
                    </div>
                    <div style={{ width: "70%", height: `${(p.promo_spend / maxPromo) * 100}%`, background: isTop ? "#fa8c16" : "#4096ff", borderRadius: "3px 3px 0 0", minHeight: p.promo_spend ? 2 : 0 }} />
                    <div style={{ fontSize: 9, color: "rgba(128,128,128,0.8)", whiteSpace: "nowrap" }}>{p.hour.slice(0, 2)}时</div>
                  </div>
                );
              })}
            </div>
            <Space style={{ marginTop: 8 }}>
              <Tag color="#4096ff">推广花费</Tag>
              <Tag color="#fa8c16">ROI 最高时段 ★</Tag>
              <Tag color="#52c41a">ROI≥2</Tag>
              <Tag color="#ff4d4f">ROI&lt;1</Tag>
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
                    销售 {fmtMoney(seg.sales)}
                    <br />
                    访客 {fmtInt(seg.visitors)} · 订单 {seg.orders}
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
    </div>
  );
}
