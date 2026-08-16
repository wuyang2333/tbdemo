import { BarChartOutlined, DownloadOutlined, ReloadOutlined, RobotOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Drawer, Empty, Segmented, Select, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { TOKEN_KEY, getApiErrorMessage } from "../lib/api";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { MODE_OPTIONS, PlanNoteCell, PlanTagCell, SCENE_OPTIONS, fmtInt, fmtMoney } from "../components/promotions/promotions-ui";
import type { PromoPlan } from "../types";

const { Text } = Typography;

export function PromotionsPlansPage() {
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [lastUpdated, setLastUpdated] = useState("");
  const [scene, setScene] = useState("");
  const [mode, setMode] = useState("realtime");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [alerts, setAlerts] = useState<{ level: string; type: string; message: string }[]>([]);
  const [planItems, setPlanItems] = useState<Record<string, { item_id: string; item_title: string }>>({});
  const [diagFilter, setDiagFilter] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<{
    sections: { overall: string; highlights: string[]; risks: string[]; suggestions: string[] };
    mode: string;
    summary: { total_spend: number; total_sales: number; total_roi: number; high_count: number; mid_count: number; low_count: number };
  } | null>(null);

  const load = useCallback(async (sc: string, m: string) => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: PromoPlan[] }>(`/promotions/plans?scene=${encodeURIComponent(sc)}&mode=${encodeURIComponent(m)}`);
      setPlans(data.items);
      setLastUpdated(dayjs().format("HH:mm:ss"));
      try {
        const { data: al } = await http.get<{ items: { level: string; type: string; message: string }[] }>("/promotions/alerts");
        setAlerts(al.items);
      } catch {
        setAlerts([]);
      }
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setPlans([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(scene, mode);
  }, [scene, mode, load]);
  useAutoRefresh(() => load(scene, mode));

  useEffect(() => {
    http
      .get<{ items: Record<string, { item_id: string; item_title: string }> }>("/promotions/plan-items")
      .then(({ data }) => setPlanItems(data.items))
      .catch(() => {});
  }, []);

  const exportPlans = async () => {
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch(`/api/promotions/plans/export?mode=${encodeURIComponent(mode)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error("导出失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `推广计划_${mode}_${dayjs().format("YYYYMMDD")}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      message.success("已导出 Excel");
    } catch {
      message.error("导出失败，请重试");
    }
  };

  const periodTitle = mode === "realtime" ? "实时" : mode === "yesterday" ? "昨天" : "近七天";
  const diag = (p: PromoPlan) => {
    if (!p.spend) return { label: "未投放", color: "default" as const };
    if (p.roi >= 2) return { label: "健康", color: "green" as const };
    if (p.roi >= 1) return { label: "关注", color: "orange" as const };
    return { label: "建议暂停", color: "red" as const };
  };
  const filteredPlans = plans.filter((p) => !diagFilter || diag(p).label === diagFilter);
  const counts = {
    high: plans.filter((p) => diag(p).label === "健康").length,
    mid: plans.filter((p) => diag(p).label === "关注").length,
    low: plans.filter((p) => diag(p).label === "建议暂停").length,
  };
  const runAI = async () => {
    setAiOpen(true);
    setAiLoading(true);
    setAiResult(null);
    try {
      const { data } = await http.post(`/promotions/insight?mode=${encodeURIComponent(mode)}`, undefined, { timeout: 120000 });
      setAiResult(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiLoading(false);
    }
  };
  const sync = async () => {
    setSyncing(true);
    try {
      const { data } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(
        `/promotions/sync-plans?mode=${encodeURIComponent(mode)}`
      );
      message.success(`计划同步完成：成功 ${data.ok} / 共 ${data.total} 家`);
      data.results.filter((r) => !r.ok).slice(0, 3).forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await load(scene, mode);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const columns: TableColumnsType<PromoPlan> = [
    { title: "场景", dataIndex: "scene_name", width: 120 },
    { title: "计划名", dataIndex: "plan_name", width: 200, ellipsis: true },
    { title: "商品", key: "item", width: 200, ellipsis: true, render: (_, row: PromoPlan) => planItems[row.campaign_id]?.item_title || "—" },
    { title: "状态", dataIndex: "status", width: 80, render: (status: string) => (status === "在投" ? <Tag color="green">在投</Tag> : <Tag>暂停</Tag>) },
    { title: "日预算", dataIndex: "day_budget", align: "right", width: 90, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "出价", key: "bid", width: 110, render: (_, row) => (row.bid_value ? `${row.bid_value}${row.bid_type === "roi" ? " ROI" : ""}` : row.bid_type || "—") },
    { title: "花费", dataIndex: "spend", align: "right", width: 110, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "成交", dataIndex: "sales", align: "right", width: 120, render: (v: number) => (v ? fmtMoney(v) : "—") },
    {
      title: "ROI",
      dataIndex: "roi",
      align: "right",
      width: 80,
      render: (v: number, row: PromoPlan) => {
        const d = diag(row);
        const color = d.color === "green" ? "#52c41a" : d.color === "orange" ? "#fa8c16" : d.color === "red" ? "#ff4d4f" : undefined;
        return <span style={{ color, fontWeight: 600 }}>{v ? v.toFixed(2) : "—"}</span>;
      },
    },
    {
      title: "诊断",
      key: "diag",
      width: 100,
      render: (_, row: PromoPlan) => {
        const d = diag(row);
        return <Tag color={d.color}>{d.label}</Tag>;
      },
    },
    { title: "点击", dataIndex: "clicks", align: "right", width: 90, render: (v: number) => (v ? fmtInt(v) : "—") },
    { title: "标记", key: "tag", width: 130, render: (_, row) => <PlanTagCell plan={row} onSaved={() => load(scene, mode)} /> },
    { title: "备注", key: "note", width: 200, render: (_, row) => <PlanNoteCell plan={row} onSaved={() => load(scene, mode)} /> },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="推广计划"
        extra={
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
            <Button icon={<RobotOutlined />} onClick={runAI}>
              AI 推广解读
            </Button>
            <Button icon={<DownloadOutlined />} onClick={exportPlans}>
              导出
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => load(scene, mode)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={sync}>
              同步{periodTitle}计划
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented options={MODE_OPTIONS} value={mode} onChange={(value) => setMode(String(value))} />
        <Select style={{ width: 150 }} value={scene} onChange={setScene} options={SCENE_OPTIONS} />
        <Select
          style={{ width: 130 }}
          value={diagFilter}
          onChange={setDiagFilter}
          options={[
            { value: "", label: "全部计划" },
            { value: "健康", label: "健康" },
            { value: "关注", label: "关注" },
            { value: "建议暂停", label: "建议暂停" },
            { value: "未投放", label: "未投放" },
          ]}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {plans.length} 个计划 · <Tag color="green">健康 {counts.high}</Tag> <Tag color="orange">关注 {counts.mid}</Tag>{" "}
          <Tag color="red">建议暂停 {counts.low}</Tag> · 显示{periodTitle}数据
        </Text>
      </Space>

      {alerts.length > 0 && (
        <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 12 }}>
          <Space direction="vertical" style={{ width: "100%" }} size={4}>
            {alerts.slice(0, 6).map((a, i) => (
              <div key={i} style={{ fontSize: 13, color: a.level === "error" ? "#ff4d4f" : "#fa8c16" }}>
                {a.level === "error" ? "⚠️ " : "❗ "}
                [{a.type}] {a.message}
              </div>
            ))}
            {alerts.length > 6 && (
              <Text type="secondary" style={{ fontSize: 12 }}>…还有 {alerts.length - 6} 条预警</Text>
            )}
          </Space>
        </Card>
      )}

      {loading && plans.length === 0 ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : plans.length === 0 ? (
        <Card variant="borderless">
          <Empty description="暂无推广计划，点「同步推广计划」从万相台抓取" />
        </Card>
      ) : (
        <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
          <Table<PromoPlan>
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={filteredPlans}
            pagination={{ pageSize: 20, showTotal: (c) => `共 ${c} 个计划` }}
            scroll={{ x: 1250 }}
          />
        </Card>
      )}
      <Drawer
        title="AI 推广解读"
        width={520}
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        destroyOnClose
      >
        {aiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin tip="AI 正在分析推广数据…" />
          </div>
        ) : aiResult ? (
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
              范围：{aiResult.mode}
            </Text>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
              <Tag>花费 {fmtMoney(aiResult.summary.total_spend)}</Tag>
              <Tag>成交 {fmtMoney(aiResult.summary.total_sales)}</Tag>
              <Tag>ROI {aiResult.summary.total_roi.toFixed(2)}</Tag>
              <Tag color="green">健康 {aiResult.summary.high_count}</Tag>
              <Tag color="orange">关注 {aiResult.summary.mid_count}</Tag>
              <Tag color="red">建议暂停 {aiResult.summary.low_count}</Tag>
            </div>
            {aiResult.sections.overall && (
              <div style={{ padding: "12px 14px", borderRadius: 10, background: "var(--ops-accent-soft)", borderLeft: "3px solid var(--ops-accent)", marginBottom: 10 }}>
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{aiResult.sections.overall}</Text>
              </div>
            )}
            <div style={{ display: "grid", gap: 8 }}>
              {aiResult.sections.highlights.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "#52c41a" }}>亮点</Text>
                  {aiResult.sections.highlights.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.risks.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "#ff4d4f" }}>风险</Text>
                  {aiResult.sections.risks.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.suggestions.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-accent-light)" }}>建议</Text>
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
