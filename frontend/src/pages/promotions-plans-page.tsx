import { BarChartOutlined, CopyOutlined, DownloadOutlined, HolderOutlined, LineChartOutlined, PauseCircleOutlined, PlayCircleOutlined, ReloadOutlined, RobotOutlined, SearchOutlined, SendOutlined, SettingOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Checkbox, Drawer, Empty, Input, Modal, Popover, Segmented, Select, Space, Spin, Table, Tag, Tooltip, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { TOKEN_KEY, getApiErrorMessage } from "../lib/api";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { AlertSettingsModal } from "../components/ui/alert-settings-modal";
import { useAlertConfig } from "../lib/use-alert-config";
import { buildRuleMessage, evalRule, ruleText } from "../lib/alert-rules";
import { PageHeader } from "../components/ui/page-header";
import { MODE_OPTIONS, LineChart, PlanNoteCell, PlanTagCell, SCENE_OPTIONS, fmtInt, fmtMoney } from "../components/promotions/promotions-ui";
import type { PromoPlan } from "../types";

const { Text } = Typography;

const PLAN_COL_KEY = "promo_plans_cols_v1";
const BUILTIN_COL_ORDER = ["scene_name", "plan_name", "item", "status", "day_budget", "bid", "spend", "sales", "roi", "diag", "clicks", "op", "tag", "note"];

function ChangeBadge({ change, unit = "%" }: { change: number | null | undefined; unit?: string }) {
  if (change == null) return <span style={{ color: "rgba(128,128,128,0.45)", fontSize: 11 }}>—</span>;
  const up = change >= 0;
  const color = up ? "#ff4d4f" : "#52c41a";
  return (
    <span style={{ color, fontSize: 11, fontWeight: 600 }}>
      {up ? "+" : ""}
      {change.toFixed(2)}
      {unit}
    </span>
  );
}


export function PromotionsPlansPage() {
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [lastUpdated, setLastUpdated] = useState("");
  const [scene, setScene] = useState("");
  const [mode, setMode] = useState("realtime");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [alerts, setAlerts] = useState<{ level: string; type: string; message: string }[]>([]);
  const [planItems, setPlanItems] = useState<Record<string, { item_id: string; item_title: string; image?: string }>>({});
  const [itemsLoaded, setItemsLoaded] = useState(false);
  const [diagFilter, setDiagFilter] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<{
    sections: { overall: string; highlights: string[]; risks: string[]; suggestions: string[] };
    mode: string;
    summary: { total_spend: number; total_sales: number; total_roi: number; high_count: number; mid_count: number; low_count: number };
  } | null>(null);

  const [opPlan, setOpPlan] = useState<PromoPlan | null>(null);
  const [opStatus, setOpStatus] = useState<"pause" | "start">("pause");
  const [opLoading, setOpLoading] = useState(false);
  const { config: alertConfig, saveConfig: saveAlertConfig } = useAlertConfig();
  const [alertCfgOpen, setAlertCfgOpen] = useState(false);
  const [alertSaving, setAlertSaving] = useState(false);
  const [hiddenByMode, setHiddenByMode] = useState<Record<string, string[]>>({});
  const [colOrders, setColOrders] = useState<Record<string, string[]>>({});
  const [dragCol, setDragCol] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [hoverKey, setHoverKey] = useState<number | null>(null);
  const [trendOpen, setTrendOpen] = useState(false);
  const [trendPlan, setTrendPlan] = useState<PromoPlan | null>(null);
  const [trendDays, setTrendDays] = useState(7);
  const [trendData, setTrendData] = useState<{ date: string; spend: number; sales: number; roi: number; clicks: number }[]>([]);
  const [trendLoading, setTrendLoading] = useState(false);
  const [planAiOpen, setPlanAiOpen] = useState(false);
  const [planAiPlan, setPlanAiPlan] = useState<PromoPlan | null>(null);
  const [planAiResult, setPlanAiResult] = useState<{
    sections: { overall: string; highlights: string[]; risks: string[]; suggestions: string[] };
    reply: string;
    plan: { id: number; plan_name: string; campaign_id: string };
  } | null>(null);
  const [planAiLoading, setPlanAiLoading] = useState(false);
  const [planAiChat, setPlanAiChat] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [planAiChatInput, setPlanAiChatInput] = useState("");
  const [planAiChatLoading, setPlanAiChatLoading] = useState(false);

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
      .get<{ items: Record<string, { item_id: string; item_title: string; image?: string }> }>("/promotions/plan-items")
      .then(({ data }) => setPlanItems(data.items))
      .catch(() => {})
      .finally(() => setItemsLoaded(true));
  }, []);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(PLAN_COL_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed.hiddenByMode && typeof parsed.hiddenByMode === "object") setHiddenByMode(parsed.hiddenByMode);
        if (parsed.orders && typeof parsed.orders === "object") setColOrders(parsed.orders);
      }
    } catch {}
  }, []);
  useEffect(() => {
    try {
      localStorage.setItem(PLAN_COL_KEY, JSON.stringify({ hiddenByMode, orders: colOrders }));
    } catch {}
  }, [hiddenByMode, colOrders]);

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
  const filteredPlans = plans.filter((p) => {
    if (diagFilter && diag(p).label !== diagFilter) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      if (!p.plan_name.toLowerCase().includes(q) && !p.campaign_id.toLowerCase().includes(q)) return false;
    }
    return true;
  });
  const counts = {
    high: plans.filter((p) => diag(p).label === "健康").length,
    mid: plans.filter((p) => diag(p).label === "关注").length,
    low: plans.filter((p) => diag(p).label === "建议暂停").length,
  };
  const ruleAlerts: { level: string; type: string; message: string }[] = [];
  for (const rule of alertConfig.rules.filter((r) => r.module === "plan")) {
    for (const p of plans) {
      if (evalRule(rule, p as unknown as Record<string, unknown>)) {
        ruleAlerts.push({ level: "warning", type: `自定义·${ruleText(rule)}`, message: buildRuleMessage(rule, p as unknown as Record<string, unknown>, p.plan_name) });
        if (ruleAlerts.length >= 20) break;
      }
    }
    if (ruleAlerts.length >= 20) break;
  }
  const allPlanAlerts = [...alerts, ...ruleAlerts];
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

  const copyPlanId = async (id: string) => {
    try {
      await navigator.clipboard.writeText(id);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = id;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    message.success(`已复制计划ID：${id}`);
  };
  const loadTrend = async (planId: number, days: number) => {
    setTrendLoading(true);
    try {
      const { data } = await http.get<{ items: { date: string; spend: number; sales: number; roi: number; clicks: number }[] }>(
        `/promotions/plans/${planId}/trend?days=${days}`,
        { timeout: 120000 }
      );
      setTrendData(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTrendLoading(false);
    }
  };
  const openTrend = (row: PromoPlan) => {
    setTrendPlan(row);
    setTrendOpen(true);
    setTrendData([]);
    loadTrend(row.id, trendDays);
  };
  const changeTrendDays = (d: number) => {
    setTrendDays(d);
    if (trendPlan) loadTrend(trendPlan.id, d);
  };
  const openPlanAI = async (row: PromoPlan) => {
    setPlanAiPlan(row);
    setPlanAiOpen(true);
    setPlanAiResult(null);
    setPlanAiChat([]);
    setPlanAiLoading(true);
    try {
      const { data } = await http.post<{
        sections: { overall: string; highlights: string[]; risks: string[]; suggestions: string[] };
        reply: string;
        plan: { id: number; plan_name: string; campaign_id: string };
      }>(`/promotions/plans/${row.id}/insight`, {}, { timeout: 120000 });
      setPlanAiResult(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setPlanAiLoading(false);
    }
  };
  const sendPlanAiChat = async () => {
    const q = planAiChatInput.trim();
    if (!q || !planAiPlan || !planAiResult) return;
    const next = [...planAiChat, { role: "user" as const, content: q }];
    setPlanAiChat(next);
    setPlanAiChatInput("");
    setPlanAiChatLoading(true);
    try {
      const { data } = await http.post<{ reply: string }>(
        `/promotions/plans/${planAiPlan.id}/insight/chat`,
        { messages: next },
        { timeout: 120000 }
      );
      setPlanAiChat([...next, { role: "assistant", content: data.reply }]);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setPlanAiChatLoading(false);
    }
  };
  const saveAlertCfg = async (patch: Parameters<typeof saveAlertConfig>[0]) => {
    setAlertSaving(true);
    try {
      await saveAlertConfig(patch);
      message.success("预警条件已保存");
      setAlertCfgOpen(false);
      await load(scene, mode);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAlertSaving(false);
    }
  };
  const askPlanStatus = (plan: PromoPlan, status: "pause" | "start") => {
    setOpPlan(plan);
    setOpStatus(status);
  };
  const runPlanStatus = async () => {
    if (!opPlan) return;
    setOpLoading(true);
    try {
      const { data } = await http.post<{ ok: boolean; count: number; execute: boolean }>(
        `/promotions/plans/${opPlan.id}/status`,
        { status: opStatus, execute: true },
        { timeout: 120000 }
      );
      message.success(`已${opStatus === "pause" ? "暂停" : "开启"}计划「${opPlan.plan_name}」（${data.count} 个投放单元），万相台同步完成`);
      setOpPlan(null);
      await load(scene, mode);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setOpLoading(false);
    }
  };

  const columns: TableColumnsType<PromoPlan> = [
    { title: "场景", key: "scene_name", dataIndex: "scene_name", width: 120, sorter: (a, b) => a.scene_name.localeCompare(b.scene_name, "zh") },
    {
      title: "计划名",
      key: "plan_name",
      dataIndex: "plan_name",
      width: 220,
      render: (name: string, row: PromoPlan) => {
        const hovered = hoverKey === row.id;
        return (
          <div style={{ position: "relative", paddingTop: hovered ? 28 : 0, transition: "padding-top 0.16s ease" }}>
            <div className={`product-hover-bar${hovered ? " visible" : ""}`} onClick={(e) => e.stopPropagation()}>
              <button type="button" className="phb-btn" onClick={() => copyPlanId(row.campaign_id)}>
                <CopyOutlined /> 复制
              </button>
              <button type="button" className="phb-btn" onClick={() => openPlanAI(row)}>
                <RobotOutlined /> AI分析
              </button>
              <button type="button" className="phb-btn" onClick={() => openTrend(row)}>
                <LineChartOutlined /> 趋势
              </button>
            </div>
            <Tooltip title={name}>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", cursor: "pointer" }} onClick={() => openTrend(row)}>
                {name}
              </div>
            </Tooltip>
          </div>
        );
      },
    },
    {
      title: "商品",
      key: "item",
      width: 230,
      render: (_, row: PromoPlan) => {
        const it = planItems[row.campaign_id];
        const title = it?.item_title || "—";
        const loadingCell = !it && !itemsLoaded;
        return (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {it?.image ? (
              <img src={it.image} alt="" style={{ width: 40, height: 40, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} />
            ) : (
              <div style={{ width: 40, height: 40, borderRadius: 6, background: "var(--ops-card-bg-2)", flexShrink: 0 }} />
            )}
            <div style={{ minWidth: 0, flex: 1 }}>
              {loadingCell ? (
                <Text type="secondary" style={{ fontSize: 12 }}>加载中…</Text>
              ) : (
                <Tooltip title={title}>
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
                </Tooltip>
              )}
            </div>
          </div>
        );
      },
    },
    { title: "状态", key: "status", dataIndex: "status", width: 80, sorter: (a, b) => a.status.localeCompare(b.status, "zh"), render: (status: string) => (status === "在投" ? <Tag color="green">在投</Tag> : <Tag>暂停</Tag>) },
    { title: "日预算", key: "day_budget", dataIndex: "day_budget", align: "right", width: 90, sorter: (a, b) => a.day_budget - b.day_budget, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "出价", key: "bid", width: 110, sorter: (a, b) => (a.bid_value || 0) - (b.bid_value || 0), render: (_, row) => (row.bid_value ? `${row.bid_value}${row.bid_type === "roi" ? " ROI" : ""}` : row.bid_type || "—") },
    { title: "花费", key: "spend", dataIndex: "spend", align: "right", width: 120, sorter: (a, b) => a.spend - b.spend, render: (v: number, row: PromoPlan) => (
      <div style={{ textAlign: "right" }}>
        <div>{v ? fmtMoney(v) : "—"}</div>
        <ChangeBadge change={row.spend_cycle} />
      </div>
    ) },
    { title: "成交", key: "sales", dataIndex: "sales", align: "right", width: 130, sorter: (a, b) => a.sales - b.sales, render: (v: number, row: PromoPlan) => (
      <div style={{ textAlign: "right" }}>
        <div>{v ? fmtMoney(v) : "—"}</div>
        <ChangeBadge change={row.sales_cycle} />
      </div>
    ) },
    {
      title: "ROI",
      key: "roi",
      dataIndex: "roi",
      align: "right",
      width: 90,
      sorter: (a, b) => a.roi - b.roi,
      render: (v: number, row: PromoPlan) => {
        const d = diag(row);
        const color = d.color === "green" ? "#52c41a" : d.color === "orange" ? "#fa8c16" : d.color === "red" ? "#ff4d4f" : undefined;
        return (
          <div style={{ textAlign: "right" }}>
            <div style={{ color, fontWeight: 600 }}>{v ? v.toFixed(2) : "—"}</div>
            <ChangeBadge change={row.roi_cycle} />
          </div>
        );
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
    { title: "点击", key: "clicks", dataIndex: "clicks", align: "right", width: 90, sorter: (a, b) => a.clicks - b.clicks, render: (v: number) => (v ? fmtInt(v) : "—") },
    {
      title: "操作",
      key: "op",
      width: 96,
      render: (_, row: PromoPlan) =>
        row.scene === "content" ? (
          <Text type="secondary" style={{ fontSize: 12 }}>不支持</Text>
        ) : row.status === "在投" ? (
          <Button size="small" danger icon={<PauseCircleOutlined />} onClick={() => askPlanStatus(row, "pause")}>
            暂停
          </Button>
        ) : (
          <Button size="small" type="primary" ghost icon={<PlayCircleOutlined />} onClick={() => askPlanStatus(row, "start")}>
            开启
          </Button>
        ),
    },
    { title: "标记", key: "tag", width: 130, render: (_, row) => <PlanTagCell plan={row} onSaved={() => load(scene, mode)} /> },
    { title: "备注", key: "note", width: 200, render: (_, row) => <PlanNoteCell plan={row} onSaved={() => load(scene, mode)} /> },
  ];

  const viewKey = mode;
  const hiddenCols = hiddenByMode[viewKey] ?? [];
  const effectiveOrder = colOrders[viewKey] ?? BUILTIN_COL_ORDER;
  const reorderCols = (from: string, to: string) => {
    if (!from || from === to) return;
    setColOrders((prev) => {
      const base = prev[viewKey] ?? BUILTIN_COL_ORDER;
      const next = base.filter((k) => k !== from);
      const idx = next.indexOf(to);
      next.splice(idx >= 0 ? idx : next.length, 0, from);
      return { ...prev, [viewKey]: next };
    });
  };
  const toggleCol = (key: string, checked: boolean) => {
    setHiddenByMode((prev) => {
      const cur = prev[viewKey] ?? [];
      return { ...prev, [viewKey]: checked ? cur.filter((k) => k !== key) : [...cur, key] };
    });
  };
  const visibleColumns = columns
    .filter((col) => {
      const k = (col.key as string) ?? ((col as { dataIndex?: string }).dataIndex as string);
      return !k || !hiddenCols.includes(k);
    })
    .sort((a, b) => {
      const ka = (a.key as string) ?? ((a as { dataIndex?: string }).dataIndex as string) ?? "";
      const kb = (b.key as string) ?? ((b as { dataIndex?: string }).dataIndex as string) ?? "";
      const ia = effectiveOrder.indexOf(ka);
      const ib = effectiveOrder.indexOf(kb);
      return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    });
  const settingsOptions = columns
    .map((col) => ({
      label: col.title as string,
      value: String((col.key as string) ?? ((col as { dataIndex?: string }).dataIndex as string) ?? ""),
    }))
    .filter((o) => o.value);
  const tableX = visibleColumns.reduce((sum, col) => sum + ((col.width as number) || 90), 0);

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
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: "rgba(128,128,128,0.5)" }} />}
          placeholder="搜计划名 / ID"
          style={{ width: 180 }}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
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
        <Popover
          trigger="click"
          placement="bottomRight"
          content={
            <div style={{ width: 240 }}>
              <div style={{ fontWeight: 600, marginBottom: 8, paddingLeft: 6 }}>字段设置（{periodTitle}）</div>
              {settingsOptions.map((o) => (
                <div
                  key={o.value}
                  draggable
                  onDragStart={() => setDragCol(o.value)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => reorderCols(dragCol ?? "", o.value)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    borderRadius: 6,
                    cursor: "grab",
                    padding: "2px 6px",
                    background: dragCol === o.value ? "var(--ops-accent-soft)" : "transparent",
                  }}
                >
                  <HolderOutlined style={{ color: "rgba(128,128,128,0.6)", fontSize: 12 }} />
                  <Checkbox checked={!hiddenCols.includes(o.value)} onChange={(e) => toggleCol(o.value, e.target.checked)}>
                    {o.label}
                  </Checkbox>
                </div>
              ))}
              <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 6, paddingLeft: 6 }}>
                拖动调整列顺序 · 勾选控制显示
              </Text>
            </div>
          }
        >
          <Button icon={<SettingOutlined />}>字段设置</Button>
        </Popover>
        <Text type="secondary" style={{ fontSize: 12 }}>
          共 {plans.length} 个计划 · <Tag color="green">健康 {counts.high}</Tag> <Tag color="orange">关注 {counts.mid}</Tag>{" "}
          <Tag color="red">建议暂停 {counts.low}</Tag> · 显示{periodTitle}数据
        </Text>
      </Space>
      <Text type="secondary" style={{ fontSize: 11, marginBottom: 8, display: "block" }}>
        环比口径：实时较昨日全天 · 昨天较前天 · 近7天较上一周（涨红跌绿，红色=上涨）
      </Text>

      {allPlanAlerts.length > 0 && (
        <Card
          variant="borderless"
          title="推广预警"
          style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 12 }}
          extra={
            <Button size="small" icon={<SettingOutlined />} onClick={() => setAlertCfgOpen(true)}>预警设置</Button>
          }
        >
          <div style={{ maxHeight: 240, overflowY: "auto", paddingRight: 4 }}>
            <Space direction="vertical" style={{ width: "100%" }} size={4}>
              {allPlanAlerts.map((a, i) => (
                <div key={i} style={{ fontSize: 13, color: a.level === "error" ? "#ff4d4f" : "#fa8c16" }}>
                  {a.level === "error" ? "⚠️ " : "❗ "}
                  [{a.type}] {a.message}
                </div>
              ))}
            </Space>
          </div>
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
            tableLayout="fixed"
            columns={visibleColumns}
            dataSource={filteredPlans}
            onRow={(record) => ({
              onMouseEnter: () => setHoverKey(record.id),
              onMouseLeave: () => setHoverKey((k) => (k === record.id ? null : k)),
            })}
            pagination={{
              defaultPageSize: 20,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (c) => `共 ${c} 个计划`,
            }}
            scroll={{ x: tableX }}
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
      <Drawer
        title={trendPlan ? `趋势：${trendPlan.plan_name}` : "计划趋势"}
        width={640}
        open={trendOpen}
        onClose={() => setTrendOpen(false)}
        destroyOnClose
      >
        {trendPlan && (
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              ID {trendPlan.campaign_id} · {trendPlan.scene_name} · 日预算 {trendPlan.day_budget ? fmtMoney(trendPlan.day_budget) : "—"}
            </Text>
          </div>
        )}
        <Segmented
          options={[7, 14, 30].map((d) => ({ label: `近${d}天`, value: d }))}
          value={trendDays}
          onChange={(v) => changeTrendDays(Number(v))}
          style={{ marginBottom: 12 }}
        />
        {trendLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin tip="加载趋势数据…" />
          </div>
        ) : trendData.length ? (
          <div>
            <LineChart
              labels={trendData.map((d) => d.date.slice(5))}
              series={[
                { name: "花费", color: "#fa8c16", values: trendData.map((d) => d.spend), format: (v: number) => fmtMoney(v) },
                { name: "成交", color: "#52c41a", values: trendData.map((d) => d.sales), format: (v: number) => fmtMoney(v) },
              ]}
            />
            <Table
              rowKey="date"
              size="small"
              style={{ marginTop: 12 }}
              columns={[
                { title: "日期", dataIndex: "date", width: 110 },
                { title: "花费", dataIndex: "spend", align: "right", render: (v: number) => (v ? fmtMoney(v) : "—") },
                { title: "成交", dataIndex: "sales", align: "right", render: (v: number) => (v ? fmtMoney(v) : "—") },
                { title: "ROI", dataIndex: "roi", align: "right", render: (v: number) => (v ? v.toFixed(2) : "—") },
                { title: "点击", dataIndex: "clicks", align: "right", render: (v: number) => (v ? fmtInt(v) : "—") },
              ]}
              dataSource={trendData}
              pagination={false}
            />
          </div>
        ) : (
          <Empty description="暂无趋势数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 40 }} />
        )}
      </Drawer>
      <Drawer
        title={planAiPlan ? `AI 分析：${planAiPlan.plan_name}` : "AI 分析"}
        width={560}
        open={planAiOpen}
        onClose={() => setPlanAiOpen(false)}
        destroyOnClose
      >
        {planAiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin tip="AI 正在分析该计划…" />
          </div>
        ) : planAiResult ? (
          <div>
            {planAiResult.sections.overall && (
              <div style={{ padding: "12px 14px", borderRadius: 10, background: "var(--ops-accent-soft)", borderLeft: "3px solid var(--ops-accent)", marginBottom: 10 }}>
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{planAiResult.sections.overall}</Text>
              </div>
            )}
            <div style={{ display: "grid", gap: 8 }}>
              {planAiResult.sections.highlights.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "#52c41a" }}>亮点</Text>
                  {planAiResult.sections.highlights.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {planAiResult.sections.risks.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "#ff4d4f" }}>风险</Text>
                  {planAiResult.sections.risks.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {planAiResult.sections.suggestions.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: 10, padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-accent-light)" }}>建议</Text>
                  {planAiResult.sections.suggestions.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
            </div>
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--ops-border)" }}>
              <div style={{ fontWeight: 600, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <RobotOutlined style={{ color: "var(--ops-accent-light)" }} /> 追问 AI
              </div>
              <div style={{ maxHeight: 220, overflowY: "auto", display: "grid", gap: 8, marginBottom: 10 }}>
                {planAiChat.map((m, i) => (
                  <div
                    key={i}
                    style={{
                      alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                      maxWidth: "90%",
                      padding: "8px 12px",
                      borderRadius: 10,
                      background: m.role === "user" ? "var(--ops-accent-soft)" : "var(--ops-card-bg-2)",
                      fontSize: 13,
                      lineHeight: 1.7,
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {m.content}
                  </div>
                ))}
                {planAiChatLoading && <Spin size="small" />}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <Input.TextArea
                  value={planAiChatInput}
                  onChange={(e) => setPlanAiChatInput(e.target.value)}
                  placeholder="继续追问，例如：为什么这个计划 ROI 下降了？"
                  autoSize={{ minRows: 1, maxRows: 3 }}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      sendPlanAiChat();
                    }
                  }}
                />
                <Button type="primary" icon={<SendOutlined />} loading={planAiChatLoading} onClick={sendPlanAiChat}>
                  发送
                </Button>
              </div>
            </div>
          </div>
        ) : (
          <Empty description="生成失败或暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 40 }} />
        )}
      </Drawer>
      <AlertSettingsModal
        open={alertCfgOpen}
        title="推广预警条件设置"
        module="plan"
        config={alertConfig}
        rules={alertConfig.rules}
        onCancel={() => setAlertCfgOpen(false)}
        onSave={saveAlertCfg}
        saving={alertSaving}
        fields={[
          { group: "plan", key: "budget_over", label: "预算超限比例", hint: "花费/日预算 ≥ 该比例时红色提醒（1=刚好超预算）", min: 0.5, max: 3, step: 0.05 },
          { group: "plan", key: "budget_warn", label: "接近预算比例", hint: "花费/日预算 ≥ 该比例时橙色提醒", min: 0.1, max: 1, step: 0.05 },
          { group: "plan", key: "roi_drop_ratio", label: "ROI 下滑提醒比例", hint: "今日ROI < 昨日ROI × 该比例时提醒（0.6=下滑40%）", min: 0.1, max: 1, step: 0.05 },
          { group: "plan", key: "roi_low", label: "ROI 偏低阈值", hint: "今日实时ROI低于该值提醒（默认1=保本线）", min: 0.1, max: 10, step: 0.1 },
        ]}
      />
      <Modal
        title={opStatus === "pause" ? "暂停推广计划" : "开启推广计划"}
        open={!!opPlan}
        onCancel={() => setOpPlan(null)}
        onOk={runPlanStatus}
        okText={opStatus === "pause" ? "确认暂停" : "确认开启"}
        cancelText="再想想"
        confirmLoading={opLoading}
        okButtonProps={{ danger: opStatus === "pause" }}
        destroyOnClose
      >
        {opPlan && (
          <div>
            <p style={{ marginBottom: 8 }}>
              将{opStatus === "pause" ? "暂停" : "开启"}计划：
              <Text strong>{opPlan.plan_name}</Text>
            </p>
            <p style={{ color: "#fa8c16", fontSize: 13, marginBottom: 0, lineHeight: 1.8 }}>
              ⚠️ 此操作会直接修改万相台后台：{opStatus === "pause" ? "暂停后该计划立即停止投放、不再扣费" : "开启后该计划立即恢复投放"}。
              <br />
              确认继续吗？
            </p>
          </div>
        )}
      </Modal>
    </div>
  );
}
