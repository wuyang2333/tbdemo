import { Empty, Input, Select, Space, Table, Tag, message } from "antd";
import { useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../../lib/api";
import type { TableColumnsType } from "antd";
import type { PromoPlan, PromoSceneAgg } from "../../types";

export const MODE_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "昨天", value: "yesterday" },
  { label: "近七天", value: "7d" },
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
  return `¥${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function fmtInt(value: number): string {
  return value.toLocaleString("zh-CN");
}

export type LineSeries = {
  name: string;
  color: string;
  values: number[];
  format?: (value: number) => string;
};

export function LineChart({ labels, series, height = 200 }: { labels: string[]; series: LineSeries[]; height?: number }) {
  const width = 720;
  const pad = 14;
  if (!labels.length) return <Empty description="暂无数据，先点「同步数据」" style={{ padding: 24 }} />;
  const n = labels.length;
  const xs = labels.map((_, i) => (n === 1 ? width / 2 : pad + (i * (width - pad * 2)) / (n - 1)));
  const paths = series.map((s) => {
    const max = Math.max(1, ...s.values);
    const pts = s.values.map((v, i) => `${xs[i]},${height - pad - (v / max) * (height - pad * 2)}`);
    return { ...s, path: pts.join(" ") };
  });
  return (
    <div>
      <Space style={{ marginBottom: 8 }} wrap>
        {series.map((s) => {
          const latest = s.values.length ? s.values[s.values.length - 1] : 0;
          return (
            <Tag key={s.name} color={s.color}>
              {s.name} · 最新 {s.format ? s.format(latest) : latest}
            </Tag>
          );
        })}
      </Space>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height, display: "block" }}>
        {paths.map((s) => (
          <polyline key={s.name} points={s.path} fill="none" stroke={s.color} strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
        ))}
        <text x={pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)">
          {labels[0]}
        </text>
        <text x={width - pad} y={height - 4} fontSize={10} fill="rgba(128,128,128,0.85)" textAnchor="end">
          {labels[n - 1]}
        </text>
      </svg>
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
