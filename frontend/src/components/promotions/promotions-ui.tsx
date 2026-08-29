import { Empty, Input, Select, Table, message } from "antd";
import { useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../../lib/api";
import type { TableColumnsType } from "antd";
import type { PromoPlan, PromoSceneAgg } from "../../types";

export const MODE_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "昨天", value: "yesterday" },
  { label: "近七天", value: "7d" },
  { label: "自定义", value: "range" },
];

export const SCENE_OPTIONS = [
  { value: "", label: "全部场景" },
  { value: "wholesite", label: "货品全站推广" },
  { value: "keyword", label: "关键词推广" },
  { value: "crowd", label: "人群推广" },
  { value: "content", label: "内容营销" },
];

export const TAG_OPTIONS = [
  { value: "", label: "无标记" },
  { value: "重点", label: "重点关注" },
  { value: "优化", label: "待优化" },
  { value: "观察", label: "暂停观察" },
];

export function fmtMoney(value: number): string {
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function fmtInt(value: number): string {
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return v.toLocaleString("zh-CN");
}

export type LineSeries = {
  name: string;
  color: string;
  values: number[];
  format?: (value: number) => string;
};

function compactNumber(value: number, money = false): string {
  const absolute = Math.abs(value);
  const amount = absolute >= 10000 ? `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}万` : absolute >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(value < 10 && value !== 0 ? 1 : 0);
  return money ? `¥${amount}` : amount;
}

function niceMaximum(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

export function LineChart({ labels, series, height = 240, sharedScale = false }: { labels: string[]; series: LineSeries[]; height?: number; sharedScale?: boolean }) {
  const width = 720;
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  if (!labels.length) return <Empty description="暂无数据，先点「同步数据」" style={{ padding: 24 }} />;
  const cleanSeries = series.map((item) => ({ ...item, values: labels.map((_, index) => {
    const value = item.values[index];
    return typeof value === "number" && Number.isFinite(value) ? value : 0;
  }) }));
  const n = labels.length;
  const margin = { top: 14, right: sharedScale || cleanSeries.length === 1 ? 18 : 58, bottom: 30, left: 58 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const xs = labels.map((_, index) => (n === 1 ? margin.left + plotWidth / 2 : margin.left + (index * plotWidth) / (n - 1)));
  const sharedMaximum = niceMaximum(Math.max(1, ...cleanSeries.flatMap((item) => item.values)));
  const maxima = cleanSeries.map((item) => sharedScale ? sharedMaximum : niceMaximum(Math.max(1, ...item.values)));
  const paths = cleanSeries.map((item, seriesIndex) => {
    const maximum = maxima[seriesIndex];
    const points = item.values.map((value, index) => ({ x: xs[index], y: margin.top + plotHeight - (value / maximum) * plotHeight, value }));
    return { ...item, points, path: points.map((point) => `${point.x},${point.y}`).join(" ") };
  });
  const gridValues = [0, 0.25, 0.5, 0.75, 1];
  const labelStep = Math.max(1, Math.ceil(n / 6));
  const visibleLabelIndexes = labels.map((_, index) => index).filter((index) => index === 0 || index === n - 1 || index % labelStep === 0);
  const activeX = activeIndex == null ? null : xs[activeIndex];
  const firstIsMoney = Boolean(cleanSeries[0]?.format?.(1).startsWith("¥"));
  const lastSeries = cleanSeries[cleanSeries.length - 1];
  const lastIsMoney = Boolean(lastSeries?.format?.(1).startsWith("¥"));
  const chartLabel = cleanSeries.map((item) => `${item.name}最新${item.format ? item.format(item.values[n - 1] || 0) : item.values[n - 1] || 0}`).join("，");
  return (
    <div className="ops-line-chart">
      <div className="ops-line-chart__legend">
        {cleanSeries.map((item) => {
          const latest = item.values[n - 1] || 0;
          const previous = item.values[n - 2] || 0;
          const change = previous ? ((latest - previous) / previous) * 100 : null;
          return (
            <div className="ops-line-chart__legend-item" key={item.name}>
              <span className="ops-line-chart__legend-dot" style={{ background: item.color }} aria-hidden="true" />
              <span className="ops-line-chart__legend-name">{item.name}</span>
              <strong>{item.format ? item.format(latest) : latest}</strong>
              {change != null ? <span className={change >= 0 ? "is-up" : "is-down"}>{change >= 0 ? "+" : ""}{change.toFixed(1)}%</span> : null}
            </div>
          );
        })}
      </div>
      <div className="ops-line-chart__stage">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="ops-line-chart__svg"
          role="img"
          aria-label={`趋势图。${chartLabel}`}
          tabIndex={0}
          onFocus={() => setActiveIndex((current) => current ?? n - 1)}
          onBlur={() => setActiveIndex(null)}
          onMouseLeave={() => setActiveIndex(null)}
          onMouseMove={(event) => {
            const bounds = event.currentTarget.getBoundingClientRect();
            const chartX = ((event.clientX - bounds.left) / bounds.width) * width;
            const index = Math.max(0, Math.min(n - 1, Math.round(((chartX - margin.left) / plotWidth) * (n - 1))));
            setActiveIndex(index);
          }}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            setActiveIndex((current) => Math.max(0, Math.min(n - 1, (current ?? n - 1) + (event.key === "ArrowRight" ? 1 : -1))));
          }}
        >
          {gridValues.map((ratio) => {
            const y = margin.top + plotHeight * (1 - ratio);
            return (
              <g key={ratio}>
                <line x1={margin.left} x2={width - margin.right} y1={y} y2={y} className="ops-line-chart__grid" />
                <text x={margin.left - 10} y={y + 3} textAnchor="end" className="ops-line-chart__axis-label">{compactNumber(maxima[0] * ratio, firstIsMoney)}</text>
                {!sharedScale && cleanSeries.length > 1 ? <text x={width - margin.right + 10} y={y + 3} className="ops-line-chart__axis-label">{compactNumber(maxima[maxima.length - 1] * ratio, lastIsMoney)}</text> : null}
              </g>
            );
          })}
          {visibleLabelIndexes.map((index) => (
            <text key={`${labels[index]}-${index}`} x={xs[index]} y={height - 6} textAnchor={index === 0 ? "start" : index === n - 1 ? "end" : "middle"} className="ops-line-chart__axis-label">{labels[index]}</text>
          ))}
          {activeX != null ? <line x1={activeX} x2={activeX} y1={margin.top} y2={margin.top + plotHeight} className="ops-line-chart__crosshair" /> : null}
          {paths.map((item) => (
            <g key={item.name}>
              <polyline points={item.path} fill="none" stroke={item.color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
              {activeIndex != null ? <circle cx={item.points[activeIndex].x} cy={item.points[activeIndex].y} r={4} fill="var(--ops-card-bg)" stroke={item.color} strokeWidth={2.5} vectorEffect="non-scaling-stroke" /> : null}
            </g>
          ))}
        </svg>
        {activeIndex != null ? (
          <div className="ops-line-chart__tooltip" style={{ left: `${(xs[activeIndex] / width) * 100}%` }}>
            <strong>{labels[activeIndex]}</strong>
            {cleanSeries.map((item) => <span key={item.name}><i style={{ background: item.color }} />{item.name}<b>{item.format ? item.format(item.values[activeIndex]) : item.values[activeIndex]}</b></span>)}
          </div>
        ) : null}
      </div>
      <div className="ops-line-chart__hint">悬停查看明细 · 键盘方向键切换时间</div>
    </div>
  );
}

export function SceneTable({ scenes, summary }: { scenes: PromoSceneAgg[]; summary: PromoSceneAgg }) {
  const columns: TableColumnsType<PromoSceneAgg> = [
    { title: "场景", dataIndex: "scene_name", width: 130 },
    { title: "展现量", dataIndex: "impressions", align: "right", render: (v: number) => fmtInt(v) },
    { title: "点击量", dataIndex: "clicks", align: "right", render: (v: number) => fmtInt(v) },
    { title: "点击率", dataIndex: "ctr", align: "right", render: (v: number) => `${v.toFixed(2)}%` },
    { title: "花费", dataIndex: "spend", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "成交金额", dataIndex: "sales", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "ROI", dataIndex: "roi", align: "right", render: (v: number) => v.toFixed(2) },
    { title: "加购", dataIndex: "add_cart", align: "right", render: (v: number) => fmtInt(v) },
  ];
  const dataSource = [
    ...scenes,
    { scene: "", scene_name: "合计", impressions: summary.impressions, clicks: summary.clicks, ctr: summary.ctr, spend: summary.spend, sales: summary.sales, roi: summary.roi, orders: summary.orders, add_cart: summary.add_cart },
  ];
  return (
    <Table<PromoSceneAgg>
      rowKey={(row) => row.scene || "total"}
      size="small"
      columns={columns}
      dataSource={dataSource}
      pagination={false}
      scroll={{ x: 760 }}
      rowClassName={(row) => (row.scene === "" ? "ant-table-row-selected" : "")}
    />
  );
}
export function PlanNoteCell({ plan, onSaved }: { plan: PromoPlan; onSaved: () => void }) {
  const [value, setValue] = useState(plan.note);
  useEffect(() => setValue(plan.note), [plan.note]);
  const save = async (next: string) => {
    if (next === plan.note) return;
    try {
      await http.put(`/promotions/plans/${plan.id}`, { note: next, tag: plan.tag });
      message.success("备注已保存");
      onSaved();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };
  return (
    <Input size="small" value={value} onChange={(event) => setValue(event.target.value)} onBlur={() => save(value)} placeholder="写备注，失焦保存" />
  );
}

export function PlanTagCell({ plan, onSaved }: { plan: PromoPlan; onSaved: () => void }) {
  const [tag, setTag] = useState(plan.tag);
  useEffect(() => setTag(plan.tag), [plan.tag]);
  const save = async (next: string) => {
    setTag(next);
    try {
      await http.put(`/promotions/plans/${plan.id}`, { note: plan.note, tag: next });
      onSaved();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };
  return <Select size="small" style={{ width: 110 }} value={tag} options={TAG_OPTIONS} onChange={save} />;
}
