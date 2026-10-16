import { BarChartOutlined, CopyOutlined, DownloadOutlined, ExclamationCircleOutlined, HolderOutlined, LineChartOutlined, PauseCircleOutlined, PlayCircleOutlined, ProfileOutlined, ReloadOutlined, RobotOutlined, SearchOutlined, SendOutlined, SettingOutlined, SyncOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Col, Drawer, Empty, Input, InputNumber, Modal, Popover, Row, Segmented, Select, Space, Spin, Table, Tag, Tooltip, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import http, { TOKEN_KEY, getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { AlertSettingsModal } from "../components/ui/alert-settings-modal";
import { useAlertConfig } from "../lib/use-alert-config";
import { HourlyPushButton } from "../components/ui/hourly-push";
import { buildRuleMessage, evalRule, ruleText } from "../lib/alert-rules";
import { PageHeader } from "../components/ui/page-header";
import { DecisionBand, MetricRail, WorkspacePage, WorkspaceToolbar } from "../components/ui/workspace-template";
import { MODE_OPTIONS, LineChart, PlanNoteCell, PlanTagCell, SCENE_OPTIONS, fmtInt, fmtMoney } from "../components/promotions/promotions-ui";
import { PROMOTION_CHANNELS, PromotionChannelTag, getPromotionChannel } from "../components/promotions/promotion-channel";
import type { PromoPlan } from "../types";
import { useStores } from "../lib/store";

const { Text } = Typography;

const PLAN_COL_KEY = "promo_plans_cols_v3";
const DEFAULT_HIDDEN_COLUMNS = ["channel", "scene_name", "item", "status", "day_budget", "bid", "clicks", "tag", "note"];
type ActionView = "today" | "stop_loss" | "scale" | "observe" | "all";

// 详细数据抽屉：展示抓取到的全部字段
const PLAN_DETAIL_FIELDS: { key: string; label: string; fmt: "money" | "percent" | "num" | "int" }[] = [
  { key: "charge", label: "花费", fmt: "money" },
  { key: "alipayInshopAmt", label: "总成交金额", fmt: "money" },
  { key: "alipayDirAmt", label: "直接成交金额", fmt: "money" },
  { key: "alipayIndirAmt", label: "间接成交金额", fmt: "money" },
  { key: "retainedAlipayInshopAmt", label: "留存成交金额(净)", fmt: "money" },
  { key: "refundDirAmt", label: "直接退款金额", fmt: "money" },
  { key: "refundIndirAmt", label: "间接退款金额", fmt: "money" },
  { key: "roi", label: "ROI(站内)", fmt: "num" },
  { key: "real_roi", label: "真实ROI", fmt: "num" },
  { key: "retainedRoi", label: "净实际投产比", fmt: "num" },
  { key: "adPv", label: "展现量", fmt: "int" },
  { key: "click", label: "点击", fmt: "int" },
  { key: "ctr", label: "点击率", fmt: "percent" },
  { key: "cvr", label: "转化率", fmt: "percent" },
  { key: "ecpc", label: "点击成本", fmt: "money" },
  { key: "ecpm", label: "千次展现成本", fmt: "money" },
  { key: "alipayInshopNum", label: "成交件数", fmt: "int" },
  { key: "alipayDirNum", label: "直接成交件数", fmt: "int" },
  { key: "alipayIndirNum", label: "间接成交件数", fmt: "int" },
  { key: "cartInshopNum", label: "加购件数", fmt: "int" },
  { key: "cartDirNum", label: "直接加购件数", fmt: "int" },
  { key: "cartIndirNum", label: "间接加购件数", fmt: "int" },
  { key: "refundDirNum", label: "直接退款笔数", fmt: "int" },
  { key: "refundIndirNum", label: "间接退款笔数", fmt: "int" },
  { key: "retainedAlipayInshopNum", label: "留存成交件数", fmt: "int" },
];
const BUILTIN_COL_ORDER = ["channel", "scene_name", "plan_name", "item", "status", "delivery", "day_budget", "bid", "spend", "sales", "roi", "real_roi", "diag", "clicks", "op", "tag", "note"];

function ChangeBadge({ change, unit = "%", comparison = "上期", detail }: { change: number | null | undefined; unit?: string; comparison?: string; detail?: string }) {
  if (change == null) return <span style={{ color: "var(--ops-text-3)", fontSize: 11 }}>—</span>;
  const up = change >= 0;
  const color = up ? "var(--ops-up)" : "var(--ops-down)";
  return (
    <span title={`较${comparison}：${up ? "+" : ""}${change.toFixed(2)}${unit}${detail ? `；${detail}` : ""}`} style={{ color, fontSize: 11, fontWeight: 600 }}>
      {up ? "+" : ""}
      {change.toFixed(2)}
      {unit}
    </span>
  );
}

function parseSuccessCriteria(value: string | null): Record<string, number> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    return Object.fromEntries(Object.entries(parsed).filter((entry): entry is [string, number] => typeof entry[1] === "number"));
  } catch {
    return {};
  }
}

function successCriteriaText(criteria: Record<string, number>): string {
  const labels: Record<string, string> = { target_roi_min: "最终 ROI≥", roi_change_min: "ROI 提升≥", sales_change_pct_min: "日均成交变化≥", spend_change_pct_max: "日均花费变化≤" };
  return Object.entries(criteria).map(([key, value]) => `${labels[key] || key}${value}${key.includes("pct") ? "%" : ""}`).join("；");
}

function planIsPlatformMissing(plan: PromoPlan) {
  return plan.platform_presence === "missing" || plan.status === "平台已失效";
}


export function PromotionsPlansPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { currentStore } = useStores();
  const todoStoreId = Number(searchParams.get("store_id")) || undefined;
  const todoPlanId = Number(searchParams.get("plan_id")) || undefined;
  const initialChannel = searchParams.get("channel") || "";
  const draftFieldParam = searchParams.get("draft_field");
  const draftPctParam = Number(searchParams.get("draft_pct"));
  const draftDecisionId = searchParams.get("decision_id") || "";
  const draftDecisionRecordId = Number(searchParams.get("decision_record_id")) || undefined;
  const draftStrategyId = Number(searchParams.get("strategy_id")) || undefined;
  const draftReason = searchParams.get("draft_reason") || "";
  const draftExpected = searchParams.get("draft_expected") || "";
  const draftObservationHours = Number(searchParams.get("draft_observation_hours")) || 48;
  const draftSuccessCriteria = parseSuccessCriteria(searchParams.get("draft_success_criteria"));
  const draftRollbackCondition = searchParams.get("draft_rollback_condition") || "";
  const draftTier = searchParams.get("draft_tier") || "";
  const alertCardRef = useRef<HTMLDivElement>(null);
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [lastUpdated, setLastUpdated] = useState("");
  const [compareLabel, setCompareLabel] = useState("上期");
  const [compareNote, setCompareNote] = useState("");
  const [scene, setScene] = useState(searchParams.get("scene") || "");
  const [channel, setChannel] = useState(initialChannel);
  const [mode, setMode] = useState(searchParams.get("mode") || "realtime");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [alerts, setAlerts] = useState<{ level: string; type: string; message: string }[]>([]);
  const [planItems, setPlanItems] = useState<Record<string, { item_id: string; item_title: string; image?: string }>>({});
  const [itemsLoaded, setItemsLoaded] = useState(false);
  const [diagFilter, setDiagFilter] = useState("");
  const [actionView, setActionView] = useState<ActionView>("today");
  const [alertsExpanded, setAlertsExpanded] = useState(false);
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
  const [selectedPlanIds, setSelectedPlanIds] = useState<number[]>([]);
  const [batchStatus, setBatchStatus] = useState<"pause" | "start" | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjustField, setAdjustField] = useState<"day_budget" | "bid_value">("day_budget");
  const [adjustPct, setAdjustPct] = useState(10);
  const [adjustTargetValue, setAdjustTargetValue] = useState<number | null>(null);
  const [adjustTargetSource, setAdjustTargetSource] = useState<"percent" | "target">("percent");
  const [adjustPreview, setAdjustPreview] = useState<{
    field: string;
    change_pct: number;
    valid_count: number;
    items: { plan_id: number; plan_name?: string; status?: string; ok: boolean; old_value?: number; new_value?: number; risks?: string[]; error?: string; can_execute?: boolean; block_reason?: string }[];
  } | null>(null);
  const [adjustLoading, setAdjustLoading] = useState(false);
  const [adjustError, setAdjustError] = useState("");
  const adjustPreviewRequestRef = useRef(0);
  const [adjustExecuteLoading, setAdjustExecuteLoading] = useState(false);
  const [actionRecording, setActionRecording] = useState(false);
  const [executionReceipt, setExecutionReceipt] = useState<{ tone: "success" | "warning"; title: string; detail: string; actionId?: number } | null>(null);
  const executionKeyRef = useRef("");
  const actionRecordKeyRef = useRef("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createBizCode, setCreateBizCode] = useState("onebpSite");
  const [createPayload, setCreatePayload] = useState("[{\n  \"campaign\": {\n    \"campaignName\": \"新计划\",\n    \"dayBudget\": 100,\n    \"bidType\": \"custom_bid\",\n    \"constraintType\": \"roi\",\n    \"constraintValue\": 2\n  },\n  \"adgroupList\": []\n}]");
  const appliedDraftKeyRef = useRef("");
  const [writeCapabilities, setWriteCapabilities] = useState<{
    day_budget: { read: boolean; write: boolean; message: string };
    bid_value: { read: boolean; write: boolean; message: string };
  } | null>(null);
  const { config: alertConfig, saveConfig: saveAlertConfig } = useAlertConfig();
  const [alertCfgOpen, setAlertCfgOpen] = useState(false);
  const [alertSaving, setAlertSaving] = useState(false);
  const [hiddenByMode, setHiddenByMode] = useState<Record<string, string[]>>({
    realtime: DEFAULT_HIDDEN_COLUMNS,
    yesterday: DEFAULT_HIDDEN_COLUMNS,
    week: DEFAULT_HIDDEN_COLUMNS,
  });
  const [colOrders, setColOrders] = useState<Record<string, string[]>>({});
  const [dragCol, setDragCol] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [hoverKey, setHoverKey] = useState<number | null>(null);
  const [trendOpen, setTrendOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailPlan, setDetailPlan] = useState<PromoPlan | null>(null);
  const [detailFunnel, setDetailFunnel] = useState<{
    item: { item_id: string; item_title: string; image?: string } | null;
    links: { type: string; label: string; status: string }[];
    timeline: { action: string; detail: string; username: string; created_at: string }[];
  } | null>(null);
  const [detailFunnelLoading, setDetailFunnelLoading] = useState(false);
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
      const scopedStoreId = todoStoreId ?? currentStore?.id;
      const scope = scopedStoreId ? `&store_id=${scopedStoreId}` : "";
      const { data } = await http.get<{ items: PromoPlan[]; compare_label?: string; compare_note?: string }>(`/promotions/plans?scene=${encodeURIComponent(sc)}&mode=${encodeURIComponent(m)}${channel ? `&channel=${encodeURIComponent(channel)}` : ""}${scope}`);
      setPlans(data.items);
      setCompareLabel(data.compare_label || "上期");
      setCompareNote(data.compare_note || "");
      setLastUpdated(dayjs().format("HH:mm:ss"));
      try {
        const { data: al } = await http.get<{ items: { level: string; type: string; message: string }[] }>(`/promotions/alerts${currentStore ? `?store_id=${currentStore.id}` : ""}`);
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
  }, [channel, currentStore?.id, todoStoreId]);

  useEffect(() => {
    load(scene, mode);
  }, [channel, scene, mode, load]);
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
      const response = await fetch(`/api/promotions/plans/export?mode=${encodeURIComponent(mode)}${currentStore ? `&store_id=${currentStore.id}` : ""}`, {
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
  const diagReason = (p: PromoPlan) => {
    if (!p.spend) return "暂无花费，先确认计划是否已开始投放";
    if (p.roi >= 2) return "ROI 达到健康线，可继续观察并考虑放量";
    if (p.roi >= 1) return "ROI 处于关注区间，建议检查出价、素材和转化";
    return "ROI 低于 1，建议优先检查成本并考虑暂停";
  };
  const filteredPlans = plans.filter((p) => {
    if (channel && getPromotionChannel(p) !== channel) return false;
    if (diagFilter && diag(p).label !== diagFilter) return false;
    if (actionView === "today" && !(p.spend >= 20 && (p.roi < 1.5 || (p.roi >= 2 && p.spend < Math.max(50, (p.day_budget || 0) * 0.3))))) return false;
    if (actionView === "stop_loss" && !(p.spend >= 20 && p.roi < 1)) return false;
    if (actionView === "scale" && !(p.roi >= 2 && p.spend < Math.max(50, (p.day_budget || 0) * 0.3))) return false;
    if (actionView === "observe" && !(p.spend < 20 || (p.roi >= 1 && p.roi < 2))) return false;
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      if (!p.plan_name.toLowerCase().includes(q) && !p.campaign_id.toLowerCase().includes(q)) return false;
    }
    return true;
  });
  useEffect(() => {
    if (!todoPlanId || plans.length === 0) return;
    const target = plans.find((plan) => plan.id === todoPlanId);
    if (!target) return;
    if (!search.trim()) setSearch(target.plan_name);
    window.setTimeout(() => {
      document.querySelector(`[data-row-key="${todoPlanId}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
  }, [plans, search, todoPlanId]);
  useEffect(() => {
    if (!todoPlanId || plans.length === 0 || !["day_budget", "bid_value"].includes(draftFieldParam || "")) return;
    const target = plans.find((plan) => plan.id === todoPlanId);
    if (!target) return;
    const draftKey = `${todoPlanId}:${draftDecisionRecordId || ""}:${draftDecisionId}:${draftFieldParam}:${draftPctParam}`;
    if (appliedDraftKeyRef.current === draftKey) return;
    appliedDraftKeyRef.current = draftKey;
    setSelectedPlanIds((current) => current.includes(todoPlanId) ? current : [todoPlanId]);
    setAdjustField(draftFieldParam as "day_budget" | "bid_value");
    if (Number.isFinite(draftPctParam)) setAdjustPct(draftPctParam);
    if (!adjustOpen) void openAdjustPanel();
  }, [draftDecisionId, draftDecisionRecordId, draftFieldParam, draftPctParam, plans, todoPlanId]);
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
  const groupedAlerts = useMemo(() => {
    const groups = new Map<string, { planName: string; messages: string[]; levels: string[]; types: string[] }>();
    for (const alert of allPlanAlerts) {
      const quoted = alert.message.match(/[「“"]([^」”"]+)[」”"]/);
      const colon = alert.message.match(/^(?:[^：]+·)?([^：]{2,80})：/);
      const planName = quoted?.[1] || colon?.[1] || "其他计划";
      const current = groups.get(planName) || { planName, messages: [], levels: [], types: [] };
      current.messages.push(alert.message);
      current.levels.push(alert.level);
      if (!current.types.includes(alert.type)) current.types.push(alert.type);
      groups.set(planName, current);
    }
    return [...groups.values()].sort((left, right) => right.messages.length - left.messages.length);
  }, [allPlanAlerts]);
  useEffect(() => {
    if (searchParams.get("todo") === "alerts" && allPlanAlerts.length > 0) {
      window.setTimeout(() => alertCardRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }), 100);
    }
  }, [alerts.length, ruleAlerts.length, searchParams]);
  const runAI = async () => {
    setAiOpen(true);
    setAiLoading(true);
    setAiResult(null);
    try {
      const { data } = await http.post(`/promotions/insight?mode=${encodeURIComponent(mode)}${currentStore ? `&store_id=${currentStore.id}` : ""}`, undefined, { timeout: 120000 });
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
        `/promotions/sync-plans?mode=${encodeURIComponent(mode)}${currentStore ? `&store_id=${currentStore.id}` : ""}`
      );
      showSyncFeedback("计划同步", [{ ok: data.ok, total: data.total, results: data.results }]);
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
  const openDetail = (row: PromoPlan) => {
    setDetailPlan(row);
    setDetailFunnel(null);
    setDetailOpen(true);
  };
  useEffect(() => {
    if (!detailPlan) return;
    let cancelled = false;
    setDetailFunnelLoading(true);
    http.get<typeof detailFunnel>(`/promotions/plans/${detailPlan.id}/funnel`)
      .then(({ data }) => { if (!cancelled) setDetailFunnel(data); })
      .catch(() => { if (!cancelled) setDetailFunnel(null); })
      .finally(() => { if (!cancelled) setDetailFunnelLoading(false); });
    return () => { cancelled = true; };
  }, [detailPlan]);
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
      setExecutionReceipt({ tone: "success", title: "平台执行成功", detail: `计划「${opPlan.plan_name}」已${opStatus === "pause" ? "暂停" : "开启"}，万相台回执包含 ${data.count} 个投放单元。` });
      setOpPlan(null);
      await load(scene, mode);
    } catch (error) {
      setExecutionReceipt({ tone: "warning", title: "平台执行失败", detail: getApiErrorMessage(error) });
      message.error(getApiErrorMessage(error));
    } finally {
      setOpLoading(false);
    }
  };

  const runBatchStatus = async () => {
    if (!batchStatus || selectedPlanIds.length === 0) return;
    setBatchLoading(true);
    try {
      const { data } = await http.post<{ ok: number; total: number; items: { plan_id: number; ok: boolean; error?: string }[] }>(
        "/promotions/plans/batch-status",
        { plan_ids: selectedPlanIds, status: batchStatus, execute: true },
        { timeout: 120000 },
      );
      const failed = data.items.filter((item) => !item.ok);
      setBatchStatus(null);
      setSelectedPlanIds([]);
      if (failed.length === 0) {
        message.success(`已${batchStatus === "pause" ? "暂停" : "开启"} ${data.ok} 个推广计划`);
        setExecutionReceipt({ tone: "success", title: "批量执行成功", detail: `${data.ok}/${data.total} 个计划已收到万相台成功回执。` });
      } else {
        message.warning(`已完成 ${data.ok}/${data.total} 个计划，${failed.length} 个计划未执行`);
        setExecutionReceipt({ tone: "warning", title: "批量执行部分失败", detail: `${data.ok}/${data.total} 个计划成功；失败原因：${failed.map((item) => item.error || `计划 ${item.plan_id} 未执行`).slice(0, 3).join("；")}` });
      }
      await load(scene, mode);
    } catch (error) {
      setExecutionReceipt({ tone: "warning", title: "批量执行失败", detail: getApiErrorMessage(error) });
      message.error(getApiErrorMessage(error));
    } finally {
      setBatchLoading(false);
    }
  };

  const runAdjustPreview = async () => {
    if (selectedPlanIds.length === 0) return;
    const requestId = ++adjustPreviewRequestRef.current;
    setAdjustLoading(true);
    setAdjustError("");
    try {
      const { data } = await http.post<typeof adjustPreview>(
        "/promotions/plans/batch-adjust-preview",
        {
          plan_ids: selectedPlanIds,
          field: adjustField,
          change_pct: adjustPct,
          target_value: selectedPlanIds.length === 1 && adjustTargetSource === "target" ? adjustTargetValue : undefined,
        },
      );
      if (requestId === adjustPreviewRequestRef.current) setAdjustPreview(data);
    } catch (error) {
      if (requestId === adjustPreviewRequestRef.current) {
        const detail = getApiErrorMessage(error);
        setAdjustError(detail);
        message.error(detail);
      }
    } finally {
      if (requestId === adjustPreviewRequestRef.current) setAdjustLoading(false);
    }
  };

  const executeAdjustments = () => {
    if (!adjustPreview || adjustPreview.valid_count === 0 || adjustExecuteLoading) return;
    const blocked = adjustPreview.items.filter((item) => item.ok && item.can_execute === false);
    if (blocked.length) {
      message.warning(blocked[0].block_reason || "最新数据不足，暂时不能执行调整");
      return;
    }
    const executionKey = `${selectedPlanIds.slice().sort((left, right) => left - right).join(",")}:${adjustField}:${adjustPct}:${adjustTargetSource}:${adjustTargetValue ?? ""}:${adjustPreview.items.map((item) => `${item.plan_id}:${item.old_value}:${item.new_value}`).join("|")}`;
    if (executionKeyRef.current === executionKey) {
      message.info("这份调整方案已经提交，请等待平台回执或重新校验");
      return;
    }
    Modal.confirm({
      title: "确认写入万相台？",
      content: (
        <Space orientation="vertical" size={6}>
          <Text>{adjustTargetSource === "target" && selectedPlanIds.length === 1 ? `将${adjustField === "day_budget" ? "日预算" : "出价"}调整至 ${adjustTargetValue}` : `将${adjustField === "day_budget" ? "日预算" : "出价"}调整 ${adjustPct > 0 ? "+" : ""}${adjustPct}%`}，并立即影响 {adjustPreview.valid_count} 个计划。</Text>
          <Text type="secondary">调整前值已作为回退快照保留；提交后请等待平台回执，不要重复点击。</Text>
          {draftRollbackCondition ? <Text type="warning">触发以下条件时应回退：{draftRollbackCondition}</Text> : null}
        </Space>
      ),
      okText: "确认写入",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        executionKeyRef.current = executionKey;
        setAdjustExecuteLoading(true);
        try {
          const { data } = await http.post<{ ok: number; total: number; items: { plan_id: number; ok: boolean; error?: string }[] }>(
            "/promotions/plans/batch-adjust",
            {
              plan_ids: selectedPlanIds,
              field: adjustField,
              change_pct: adjustPct,
              target_value: selectedPlanIds.length === 1 && adjustTargetSource === "target" ? adjustTargetValue : undefined,
              execute: true,
            },
            { timeout: 120000 },
          );
          const failed = data.items.filter((item) => !item.ok).length;
          const successfulPlanIds = data.items.filter((item) => item.ok).map((item) => item.plan_id);
          const failedReasons = data.items
            .filter((item) => !item.ok)
            .map((item) => item.error || `计划 ${item.plan_id} 未返回失败原因`)
            .slice(0, 3)
            .join("；");
          if (failed) {
            message.warning(`已写入 ${data.ok}/${data.total} 个计划，${failed} 个失败`);
            setExecutionReceipt({ tone: "warning", title: "调整写入部分失败", detail: `${data.ok}/${data.total} 个计划成功；失败原因：${failedReasons || "平台未返回失败原因"}` });
          } else {
            message.success(`已写入 ${data.ok} 个计划，并同步本地数据`);
            setExecutionReceipt({ tone: "success", title: "调整写入成功", detail: `${data.ok} 个计划已写入万相台；调整前值已保留在动作记录中，可按观察结果回退。` });
          }
          if (successfulPlanIds.length > 0) {
            await createAdjustmentRecords(successfulPlanIds);
          } else {
            executionKeyRef.current = "";
            actionRecordKeyRef.current = "";
            message.info("没有计划写入成功，未建立观察任务；修正问题后可以重新校验并尝试");
            setExecutionReceipt({ tone: "warning", title: "写入失败，未建立观察任务", detail: `失败原因：${failedReasons || "平台未返回失败原因"}。本次没有计划成功写入万相台，因此没有创建观察任务。` });
          }
          setAdjustOpen(false);
          await load(scene, mode);
        } catch (error) {
          executionKeyRef.current = "";
          setExecutionReceipt({ tone: "warning", title: "调整写入失败", detail: getApiErrorMessage(error) });
          message.error(getApiErrorMessage(error));
        } finally {
          setAdjustExecuteLoading(false);
        }
      },
    });
  };

  const createPlan = async () => {
    let solutionList: unknown;
    try {
      solutionList = JSON.parse(createPayload);
    } catch {
      message.error("solutionList 不是有效 JSON");
      return;
    }
    if (!Array.isArray(solutionList) || solutionList.length === 0) {
      message.error("至少需要一个方案");
      return;
    }
    Modal.confirm({
      title: "确认新建万相台计划？",
      content: "该操作会直接在万相台创建计划，创建后请刷新计划列表确认结果。",
      okText: "确认创建",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        setCreateLoading(true);
        try {
          await http.post("/promotions/plans/create", { biz_code: createBizCode, solution_list: solutionList }, { timeout: 120000 });
          message.success("万相台计划创建请求已提交");
          setCreateOpen(false);
          await load(scene, mode);
        } catch (error) {
          message.error(getApiErrorMessage(error));
        } finally {
          setCreateLoading(false);
        }
      },
    });
  };

  const openAdjustPanel = async (planId?: number) => {
    if (planId != null) setSelectedPlanIds([planId]);
    adjustPreviewRequestRef.current += 1;
    setAdjustPreview(null);
    setAdjustError("");
    setAdjustTargetValue(null);
    setAdjustTargetSource("percent");
    executionKeyRef.current = "";
    actionRecordKeyRef.current = "";
    setAdjustOpen(true);
    try {
      const { data } = await http.get<typeof writeCapabilities>("/promotions/plans/write-capabilities");
      setWriteCapabilities(data);
    } catch {
      setWriteCapabilities(null);
    }
  };

  const createAdjustmentRecords = async (successfulPlanIds?: number[]) => {
    if (!adjustPreview || actionRecording) return;
    const validItems = adjustPreview.items.filter((item) => item.ok && item.new_value != null && (!successfulPlanIds || successfulPlanIds.includes(item.plan_id)));
    if (validItems.length === 0) return;
    const recordKey = `${validItems.map((item) => `${item.plan_id}:${item.new_value}`).join("|")}:${draftDecisionRecordId || draftDecisionId}`;
    if (actionRecordKeyRef.current === recordKey) {
      message.info("这份方案已经建立观察任务，请勿重复提交");
      return;
    }
    actionRecordKeyRef.current = recordKey;
    setActionRecording(true);
    let created = 0;
    try {
      for (const item of validItems) {
        const plan = plans.find((candidate) => candidate.id === item.plan_id);
        const actionType = adjustField === "day_budget"
          ? (adjustPct >= 0 ? "增加预算/放量" : "降低预算/止损")
          : (adjustPct >= 0 ? "提高出价" : "降低出价/控成本");
        const createdRecord = await http.post<{ id: number }>("/promotions/action-records", {
          plan_id: item.plan_id,
          action_type: actionType,
          description: draftReason || `确认${adjustField === "day_budget" ? "日预算" : "出价"}调整 ${adjustPct > 0 ? "+" : ""}${adjustPct}%；执行后进入观察窗口`,
          after_value: item.new_value,
          expected: draftExpected || (adjustPct >= 0 ? "成交增长且 ROI 保持稳定" : "ROI 改善并减少无效花费"),
          observation_hours: draftObservationHours,
          decision_id: draftDecisionId || undefined,
          decision_record_id: draftDecisionRecordId,
          decision_tier: draftTier,
          decision_field: adjustField,
          change_pct: item.old_value ? Number((((item.new_value || 0) - item.old_value) / item.old_value * 100).toFixed(2)) : adjustPct,
          strategy_id: draftStrategyId,
          success_criteria: Object.keys(draftSuccessCriteria).length ? draftSuccessCriteria : adjustPct >= 0
            ? { target_roi_min: Math.max(1, Number(((plan?.roi || 0) * 0.85).toFixed(2))), sales_change_pct_min: 5 }
            : { roi_change_min: 0.1, spend_change_pct_max: -5 },
          rollback_condition: draftRollbackCondition,
        });
        if (!executionReceipt?.actionId && createdRecord.data.id) {
          setExecutionReceipt((current) => ({
            tone: current?.tone || "success",
            title: current?.title || "观察任务已建立",
            detail: current?.detail || "动作已记录；下一步进入观察验证并确认执行时间。",
            actionId: createdRecord.data.id,
          }));
        }
        created += 1;
      }
      message.success(`已建立 ${created} 个${successfulPlanIds ? "观察任务" : "待执行观察任务"}`);
      setAdjustOpen(false);
    } catch (error) {
      actionRecordKeyRef.current = created ? recordKey : "";
      message.error(created ? `已建立 ${created} 个任务，后续任务创建失败` : getApiErrorMessage(error));
    } finally {
      setActionRecording(false);
    }
  };

  const columns: TableColumnsType<PromoPlan> = [
    { title: "渠道", key: "channel", width: 108, render: (_, row) => <PromotionChannelTag item={row} /> },
    { title: "场景", key: "scene_name", dataIndex: "scene_name", width: 110, sorter: (a, b) => a.scene_name.localeCompare(b.scene_name, "zh") },
    {
      title: "计划名",
      key: "plan_name",
      dataIndex: "plan_name",
      width: 300,
      render: (name: string, row: PromoPlan) => {
        const hovered = hoverKey === row.id;
        const item = planItems[row.campaign_id];
        const itemTitle = item?.item_title || "暂未关联商品";
        return (
          <div className="ops-plan-name-cell">
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
              <button type="button" className="phb-btn" onClick={() => openDetail(row)}>
                <ProfileOutlined /> 详细数据
              </button>
            </div>
            <div className="ops-plan-name-cell__main">
              {item?.image ? <img src={item.image} alt="" className="ops-plan-name-cell__image" /> : <span className="ops-plan-name-cell__image is-empty" aria-hidden="true" />}
              <div className="ops-plan-name-cell__copy">
                <Tooltip title={name}>
                  <div className="ops-plan-name-cell__title" onClick={() => openTrend(row)}>{name}</div>
                </Tooltip>
                <Tooltip title={itemTitle}>
                  <div className="ops-plan-name-cell__product">{itemTitle}</div>
                </Tooltip>
                <div className="ops-plan-name-cell__meta">
                  <Tag color={row.status === "在投" ? "green" : "default"}>{planIsPlatformMissing(row) ? "平台已失效" : row.status || "—"}</Tag>
                  <span>计划 ID {row.campaign_id || "未同步"}</span>
                  <span>宝贝 ID {item?.item_id || "未同步"}</span>
                  <span>{row.scene_name || "未分类"}</span>
                </div>
              </div>
            </div>
          </div>
        );
      },
    },
    {
      title: "商品",
      key: "item",
      width: 210,
      render: (_, row: PromoPlan) => {
        const it = planItems[row.campaign_id];
        const title = it?.item_title || "—";
        const loadingCell = !it && !itemsLoaded;
        return (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {it?.image ? (
              <img src={it.image} alt="" style={{ width: 40, height: 40, borderRadius: "var(--ops-radius-xs)", objectFit: "cover", flexShrink: 0 }} />
            ) : (
              <div style={{ width: 40, height: 40, borderRadius: "var(--ops-radius-xs)", background: "var(--ops-card-bg-2)", flexShrink: 0 }} />
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
    { title: "状态", key: "status", dataIndex: "status", width: 96, sorter: (a, b) => a.status.localeCompare(b.status, "zh"), render: (_: string, row) => (row.status === "在投" ? <Tag color="green">在投</Tag> : <Tag>{planIsPlatformMissing(row) ? "平台已失效" : row.status || "状态未知"}</Tag>) },
    {
      title: "投放设置",
      key: "delivery",
      width: 125,
      render: (_, row: PromoPlan) => (
        <div className="ops-plan-delivery">
          <span><Text type="secondary">预算</Text><Text>{row.day_budget ? fmtMoney(row.day_budget) : "—"}</Text></span>
          <span><Text type="secondary">出价</Text><Text>{row.bid_value ? `${row.bid_value}${row.bid_type === "roi" ? " ROI" : ""}` : row.bid_type || "—"}</Text></span>
        </div>
      ),
    },
    { title: "日预算", key: "day_budget", dataIndex: "day_budget", align: "right", width: 84, sorter: (a, b) => a.day_budget - b.day_budget, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "出价", key: "bid", width: 96, sorter: (a, b) => (a.bid_value || 0) - (b.bid_value || 0), render: (_, row) => (row.bid_value ? `${row.bid_value}${row.bid_type === "roi" ? " ROI" : ""}` : row.bid_type || "—") },
    { title: "花费", key: "spend", dataIndex: "spend", align: "right", width: 110, sorter: (a, b) => a.spend - b.spend, render: (v: number, row: PromoPlan) => (
      <div style={{ textAlign: "right" }}>
        <div>{v ? fmtMoney(v) : "—"}</div>
        <ChangeBadge change={row.spend_cycle} comparison={compareLabel} detail={row.spend_cycle == null ? "计划级同周期基准不可用" : `当前 ${fmtMoney(row.spend)} · 对比 ${fmtMoney(row.prev_spend || 0)}`} />
      </div>
    ) },
    { title: "成交", key: "sales", dataIndex: "sales", align: "right", width: 116, sorter: (a, b) => a.sales - b.sales, render: (v: number, row: PromoPlan) => (
      <div style={{ textAlign: "right" }}>
        <div>{v ? fmtMoney(v) : "—"}</div>
        <ChangeBadge change={row.sales_cycle} comparison={compareLabel} detail={row.sales_cycle == null ? "计划级同周期基准不可用" : `当前 ${fmtMoney(row.sales)} · 对比 ${fmtMoney(row.prev_sales || 0)}`} />
      </div>
    ) },
    {
      title: mode === "realtime" ? "净投产比" : "ROI",
      key: "roi",
      dataIndex: "roi",
      align: "right",
      width: 84,
      sorter: (a, b) => a.roi - b.roi,
      render: (v: number, row: PromoPlan) => {
        const d = diag(row);
        const color = d.color === "green" ? "var(--ops-success)" : d.color === "orange" ? "var(--ops-warn)" : d.color === "red" ? "var(--ops-danger)" : undefined;
        return (
          <div style={{ textAlign: "right" }}>
            <div style={{ color, fontWeight: 600 }}>{v ? v.toFixed(2) : "—"}</div>
            <ChangeBadge change={row.roi_cycle} comparison={compareLabel} detail={row.roi_cycle == null ? "计划级同周期基准不可用" : `当前 ${row.roi.toFixed(2)} · 对比 ${(row.prev_roi || 0).toFixed(2)}`} />
          </div>
        );
      },
    },
    {
      title: "真实ROI",
      key: "real_roi",
      dataIndex: "real_roi",
      align: "right",
      width: 92,
      sorter: (a, b) => (a.real_roi ?? -1) - (b.real_roi ?? -1),
      render: (v: number | null | undefined, row: PromoPlan) => (
        <Tooltip title="该宝贝实际成交额 ÷ 该计划推广花费；— 表示对应时间范围的宝贝成交数据尚未同步">
          <div style={{ textAlign: "right" }}>
            <div style={{ color: v == null ? "var(--ops-text-3)" : "var(--ops-accent)", fontWeight: 600 }}>{v == null ? "—" : v.toFixed(2)}</div>
            {v != null && row.spend ? <Text type="secondary" style={{ fontSize: 11 }}>店铺实际口径</Text> : null}
          </div>
        </Tooltip>
      ),
    },
    {
      title: "诊断",
      key: "diag",
      width: 90,
      render: (_, row: PromoPlan) => {
        const d = diag(row);
        return <Tooltip title={diagReason(row)}><Tag color={d.color}>{d.label}</Tag></Tooltip>;
      },
    },
    { title: "点击", key: "clicks", dataIndex: "clicks", align: "right", width: 82, sorter: (a, b) => a.clicks - b.clicks, render: (v: number) => (v ? fmtInt(v) : "—") },
    {
      title: "操作",
      key: "op",
      width: 118,
      render: (_, row: PromoPlan) =>
        planIsPlatformMissing(row) ? (
          <Tooltip title="平台当前计划列表已不再返回此计划，历史数据仅供复盘"><Text type="secondary" style={{ fontSize: 12 }}>仅历史</Text></Tooltip>
        ) : row.scene === "content" ? (
          <Text type="secondary" style={{ fontSize: 12 }}>不支持</Text>
        ) : row.status === "在投" ? (
          <Space size={4} wrap>
            <Button size="small" danger icon={<PauseCircleOutlined />} onClick={() => askPlanStatus(row, "pause")}>
              暂停
            </Button>
            <Button size="small" icon={<SettingOutlined />} onClick={() => void openAdjustPanel(row.id)}>
              调整投放
            </Button>
          </Space>
        ) : (
          <Space size={4} wrap>
            <Button size="small" type="primary" ghost icon={<PlayCircleOutlined />} onClick={() => askPlanStatus(row, "start")}>
              开启
            </Button>
            <Button size="small" icon={<SettingOutlined />} onClick={() => void openAdjustPanel(row.id)}>
              调整投放
            </Button>
          </Space>
        ),
    },
    { title: "标记", key: "tag", width: 130, render: (_, row) => <PlanTagCell plan={row} onSaved={() => load(scene, mode)} /> },
    { title: "备注", key: "note", width: 180, render: (_, row) => <PlanNoteCell plan={row} onSaved={() => load(scene, mode)} /> },
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
  const decisionTitle = counts.low > 0
    ? `先检查 ${counts.low} 个建议暂停的计划，避免继续无效消耗`
    : counts.mid > 0
      ? `${counts.mid} 个计划需要关注，先确认转化与投放节奏`
      : "当前计划整体健康，可以寻找稳健放量机会";
  const adjustTargets = selectedPlanIds.map((planId) => plans.find((plan) => plan.id === planId)).filter((plan): plan is PromoPlan => Boolean(plan));
  const adjustPrimaryPlan = adjustTargets[0];
  const adjustPrimaryItem = adjustPrimaryPlan ? planItems[adjustPrimaryPlan.campaign_id] : undefined;
  const adjustCurrentValue = adjustPrimaryPlan ? Number(adjustPrimaryPlan[adjustField] || 0) : 0;
  const adjustPreviewStats = useMemo(() => {
    if (!adjustPreview) return null;
    const valid = adjustPreview.items.filter((item) => item.ok).length;
    const executable = adjustPreview.items.filter((item) => item.ok && item.can_execute === true).length;
    return { valid, executable, blocked: valid - executable, invalid: adjustPreview.items.length - valid };
  }, [adjustPreview]);
  useEffect(() => {
    if (!adjustOpen || adjustTargetValue != null || adjustTargets.length !== 1 || !adjustPrimaryPlan) return;
            setAdjustTargetValue(Number((adjustCurrentValue * (1 + adjustPct / 100)).toFixed(2)));
            setAdjustTargetSource("percent");
  }, [adjustCurrentValue, adjustOpen, adjustPct, adjustPrimaryPlan, adjustTargetValue, adjustTargets.length]);

  return (
    <WorkspacePage kind="management">
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="计划执行中心"
        description="勾选计划后可批量修改预算/出价，也可在表格右侧按单个计划修改；真实执行动作会进入观察验证。"
        extra={
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
            <Button icon={<RobotOutlined />} onClick={runAI}>
              AI 推广解读
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={sync}>
              同步{periodTitle}计划
            </Button>
          </Space>
        }
      />

      <DecisionBand
        ariaLabel="计划执行结论"
        eyebrow="执行结论 · 优先动作"
        title={decisionTitle}
        description="所有预算、出价与启停调整都会被记录，并进入观察验证。"
        action={<Button type="primary" onClick={() => setActionView(counts.low > 0 ? "stop_loss" : counts.mid > 0 ? "today" : "scale")}>查看建议计划</Button>}
      />

      <WorkspaceToolbar>
        <Segmented options={MODE_OPTIONS} value={mode} onChange={(value) => setMode(String(value))} />
        <Select
          aria-label="推广渠道"
          style={{ width: 150 }}
          value={channel}
          onChange={(value) => { setChannel(value); setScene(""); setSelectedPlanIds([]); }}
          options={[{ value: "", label: "全部渠道" }, ...PROMOTION_CHANNELS]}
        />
        <Select style={{ width: 150 }} value={scene} onChange={setScene} options={SCENE_OPTIONS} />
        <Input
          allowClear
          prefix={<SearchOutlined style={{ color: "var(--ops-text-3)" }} />}
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
                    borderRadius: "var(--ops-radius-xs)",
                    cursor: "grab",
                    padding: "2px 6px",
                    background: dragCol === o.value ? "var(--ops-accent-soft)" : "transparent",
                  }}
                >
                  <HolderOutlined style={{ color: "var(--ops-text-3)", fontSize: 12 }} />
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
        <Button icon={<ReloadOutlined />} onClick={() => load(scene, mode)}>刷新</Button>
        <Button icon={<DownloadOutlined />} onClick={exportPlans}>导出</Button>
        <Button onClick={() => setCreateOpen(true)}>新建计划</Button>
        <HourlyPushButton scope="promotions" />
        <span className="ops-filter-bar__meta">共 {plans.length} 个计划 · 显示{periodTitle}数据</span>
      </WorkspaceToolbar>

      <WorkspaceToolbar tone="action">
        <Text strong>行动视图</Text>
        <Segmented
          aria-label="计划行动视图"
          value={actionView}
          onChange={(value) => { setActionView(value as ActionView); setSelectedPlanIds([]); }}
          options={[
            { label: "今天必须处理", value: "today" },
            { label: "止损", value: "stop_loss" },
            { label: "放量", value: "scale" },
            { label: "等待观察", value: "observe" },
            { label: "全部计划", value: "all" },
          ]}
        />
        <span className="ops-filter-bar__meta">当前显示 {filteredPlans.length}/{plans.length} 个计划</span>
      </WorkspaceToolbar>

      <MetricRail columns={4} items={[
          { label: "计划总数", value: plans.length, tone: "var(--ops-text-primary)", hint: "当前筛选范围" },
          { label: "健康计划", value: counts.high, tone: "var(--ops-success)", hint: "ROI ≥ 2" },
          { label: "需要关注", value: counts.mid, tone: "var(--ops-warn)", hint: "1 ≤ ROI < 2" },
          { label: "建议暂停", value: counts.low, tone: "var(--ops-danger)", hint: "ROI < 1" },
        ]} />
      {selectedPlanIds.length > 0 && (
        <Card size="small" variant="borderless" style={{ marginBottom: 14, background: "var(--ops-accent-soft)" }}>
          <Space wrap>
            <Text strong>已选择 {selectedPlanIds.length} 个计划</Text>
            <Button size="small" danger onClick={() => setBatchStatus("pause")}>批量暂停</Button>
            <Button size="small" type="primary" ghost onClick={() => setBatchStatus("start")}>批量开启</Button>
            <Button size="small" onClick={() => void openAdjustPanel()}>修改预算/出价</Button>
            <Button size="small" type="link" onClick={() => setSelectedPlanIds([])}>清空选择</Button>
          </Space>
        </Card>
      )}
      {executionReceipt ? (
        <Alert
          type={executionReceipt.tone}
          showIcon
          closable
          title={executionReceipt.title}
          description={executionReceipt.detail}
          action={executionReceipt.actionId ? <Button size="small" type="primary" onClick={() => {
            const params = new URLSearchParams(searchParams);
            params.set("action_id", String(executionReceipt.actionId));
            navigate(`/promotions/validation?${params.toString()}`);
          }}>进入观察验证</Button> : undefined}
          onClose={() => setExecutionReceipt(null)}
          style={{ marginBottom: 14 }}
        />
      ) : null}
      <Text type="secondary" style={{ fontSize: 11, marginBottom: 8, display: "block" }}>
        环比口径：当前数据较{compareLabel}（{compareNote || "按上期数据比较"}；涨红跌绿，红色=上涨；对比基准为 0 时显示“—”）
      </Text>

      {allPlanAlerts.length > 0 && (
        <section ref={alertCardRef} id="promotion-alerts" className="ops-plan-alerts" aria-labelledby="promotion-alerts-title">
          <div className="ops-plan-alerts__head">
            <div className="ops-plan-alerts__heading">
              <span className="ops-plan-alerts__icon" aria-hidden="true"><ExclamationCircleOutlined /></span>
              <div>
                <Text strong id="promotion-alerts-title">需要关注的计划</Text>
                <Text type="secondary">{groupedAlerts.length} 个计划 · {allPlanAlerts.length} 条预警</Text>
              </div>
            </div>
            <Space size={4}>
              <Button type="text" size="small" onClick={() => setAlertsExpanded((value) => !value)}>
                {alertsExpanded ? "收起" : "查看全部"}
              </Button>
              <Button type="text" size="small" icon={<SettingOutlined />} onClick={() => setAlertCfgOpen(true)}>设置</Button>
            </Space>
          </div>
          <div className="ops-plan-alerts__list">
            {groupedAlerts.slice(0, alertsExpanded ? groupedAlerts.length : 3).map((group) => {
              const severe = group.levels.includes("error");
              return (
                <div className={`ops-plan-alerts__row${severe ? " is-error" : ""}`} key={group.planName}>
                  <span className="ops-plan-alerts__marker" aria-hidden="true" />
                  <div className="ops-plan-alerts__content">
                    <div className="ops-plan-alerts__title-line">
                      <Text strong ellipsis={{ tooltip: group.planName }}>{group.planName}</Text>
                      <span className="ops-plan-alerts__count">{group.messages.length} 条</span>
                    </div>
                    {alertsExpanded ? (
                      <div className="ops-plan-alerts__details">
                        {group.messages.map((item, index) => <Text key={`${group.planName}-${index}`} type="secondary">{item}</Text>)}
                      </div>
                    ) : (
                      <Text type="secondary" ellipsis={{ tooltip: group.types.join("、") }} className="ops-plan-alerts__summary">
                        {group.types.slice(0, 3).join("、")}{group.types.length > 3 ? "等" : ""}
                      </Text>
                    )}
                  </div>
                  <Button size="small" type="text" onClick={() => { setSearch(group.planName === "其他计划" ? "" : group.planName); setActionView("all"); }}>查看计划</Button>
                </div>
              );
            })}
          </div>
          {!alertsExpanded && groupedAlerts.length > 3 ? (
            <button type="button" className="ops-plan-alerts__more" onClick={() => setAlertsExpanded(true)}>
              还有 {groupedAlerts.length - 3} 个预警计划，展开查看
            </button>
          ) : null}
        </section>
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
        <Card variant="borderless" className="ops-plan-table-card ops-management-table">
          <Table<PromoPlan>
            className="ops-plan-table"
            rowKey="id"
            size="small"
            tableLayout="fixed"
            columns={visibleColumns}
            dataSource={filteredPlans}
            rowSelection={{
              selectedRowKeys: selectedPlanIds,
              onChange: (keys) => setSelectedPlanIds(keys.map((key) => Number(key))),
            }}
            onRow={(record) => ({
              onMouseEnter: () => setHoverKey(record.id),
              onMouseLeave: () => setHoverKey((k) => (k === record.id ? null : k)),
            })}
            rowClassName={(record) => (record.id === todoPlanId ? "ops-promo-target-row" : "")}
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
        size="large"
        open={aiOpen}
        onClose={() => setAiOpen(false)}
        destroyOnHidden
      >
        {aiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="AI 正在分析推广数据…" />
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
              <div style={{ padding: "12px 14px", borderRadius: "var(--ops-radius)", background: "var(--ops-accent-soft)", borderLeft: "3px solid var(--ops-accent)", marginBottom: 10 }}>
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{aiResult.sections.overall}</Text>
              </div>
            )}
            <div style={{ display: "grid", gap: 8 }}>
              {aiResult.sections.highlights.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-success)" }}>亮点</Text>
                  {aiResult.sections.highlights.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.risks.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-danger)" }}>风险</Text>
                  {aiResult.sections.risks.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {aiResult.sections.suggestions.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
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
        size="large"
        open={trendOpen}
        onClose={() => setTrendOpen(false)}
        destroyOnHidden
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
            <Spin description="加载趋势数据…" />
          </div>
        ) : trendData.length ? (
          <div>
            <LineChart
              labels={trendData.map((d) => d.date.slice(5))}
              series={[
                { name: "花费", color: "var(--ops-warn)", values: trendData.map((d) => d.spend), format: (v: number) => fmtMoney(v) },
                { name: "成交", color: "var(--ops-success)", values: trendData.map((d) => d.sales), format: (v: number) => fmtMoney(v) },
              ]}
              sharedScale
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
        size="large"
        open={planAiOpen}
        onClose={() => setPlanAiOpen(false)}
        destroyOnHidden
      >
        {planAiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="AI 正在分析该计划…" />
          </div>
        ) : planAiResult ? (
          <div>
            {planAiResult.sections.overall && (
              <div style={{ padding: "12px 14px", borderRadius: "var(--ops-radius)", background: "var(--ops-accent-soft)", borderLeft: "3px solid var(--ops-accent)", marginBottom: 10 }}>
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{planAiResult.sections.overall}</Text>
              </div>
            )}
            <div style={{ display: "grid", gap: 8 }}>
              {planAiResult.sections.highlights.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-success)" }}>亮点</Text>
                  {planAiResult.sections.highlights.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {planAiResult.sections.risks.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
                  <Text strong style={{ color: "var(--ops-danger)" }}>风险</Text>
                  {planAiResult.sections.risks.map((it, i) => (
                    <div key={i} style={{ fontSize: 13, lineHeight: 1.8, color: "var(--ops-text-secondary)" }}>{it}</div>
                  ))}
                </div>
              )}
              {planAiResult.sections.suggestions.length > 0 && (
                <div style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "10px 12px", background: "var(--ops-card-bg-2)" }}>
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
                      borderRadius: "var(--ops-radius)",
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
        destroyOnHidden
      >
        {opPlan && (
          <div>
            <p style={{ marginBottom: 8 }}>
              将{opStatus === "pause" ? "暂停" : "开启"}计划：
              <Text strong>{opPlan.plan_name}</Text>
            </p>
            <p style={{ color: "var(--ops-warn)", fontSize: 13, marginBottom: 0, lineHeight: 1.8 }}>
              ⚠️ 此操作会直接修改万相台后台：{opStatus === "pause" ? "暂停后该计划立即停止投放、不再扣费" : "开启后该计划立即恢复投放"}。
              <br />
              确认继续吗？
            </p>
          </div>
        )}
      </Modal>
      <Modal
        title={batchStatus === "pause" ? "批量暂停推广计划" : "批量开启推广计划"}
        open={!!batchStatus}
        onCancel={() => setBatchStatus(null)}
        onOk={runBatchStatus}
        okText={batchStatus === "pause" ? "确认批量暂停" : "确认批量开启"}
        cancelText="再想想"
        confirmLoading={batchLoading}
        okButtonProps={{ danger: batchStatus === "pause" }}
        destroyOnHidden
      >
        <p>将{batchStatus === "pause" ? "暂停" : "开启"}以下 {selectedPlanIds.length} 个计划：</p>
        <Space orientation="vertical" size={4} style={{ width: "100%" }}>
          {selectedPlanIds.slice(0, 8).map((planId) => {
            const plan = plans.find((item) => item.id === planId);
            return <Text key={planId}>· {plan?.plan_name || `计划 ${planId}`}</Text>;
          })}
          {selectedPlanIds.length > 8 ? <Text type="secondary">还有 {selectedPlanIds.length - 8} 个计划未展开</Text> : null}
        </Space>
        <p style={{ color: "var(--ops-warn)", fontSize: 13, marginTop: 12, marginBottom: 0 }}>此操作会直接修改万相台投放状态，请确认选择无误。</p>
      </Modal>
      <Modal
        title={null}
        open={adjustOpen}
        onCancel={() => setAdjustOpen(false)}
        footer={null}
        width={640}
        className="ops-adjust-modal"
        destroyOnHidden
      >
        <div className="ops-adjust-modal__head">
          <div className="ops-adjust-modal__product-image">
            {adjustPrimaryItem?.image ? <img src={adjustPrimaryItem.image} alt="" /> : <ProfileOutlined aria-hidden="true" />}
          </div>
          <div className="ops-adjust-modal__identity">
            <Text className="ops-adjust-modal__eyebrow">调整投放</Text>
            <h2>{adjustPrimaryPlan?.plan_name || (selectedPlanIds.length ? `已选 ${selectedPlanIds.length} 个计划` : "未选择计划")}</h2>
            <Space wrap size={[6, 4]}>
              {adjustPrimaryPlan ? <Tag color="blue">{adjustPrimaryPlan.scene_name || "推广计划"}</Tag> : null}
              {adjustPrimaryPlan ? <Tag color={adjustPrimaryPlan.status === "在投" ? "green" : "default"}>{adjustPrimaryPlan.status || "状态未知"}</Tag> : null}
              {adjustPrimaryPlan ? <Text type="secondary">平台计划 ID {adjustPrimaryPlan.campaign_id}</Text> : null}
              {selectedPlanIds.length > 1 ? <Tag color="orange">共 {selectedPlanIds.length} 个计划</Tag> : null}
            </Space>
          </div>
        </div>
        <div className="ops-adjust-modal__notice ops-adjust-modal__notice--info">
          <div className="ops-adjust-modal__notice-title">{draftDecisionId ? "来自 AI 决策草案的执行前校验" : "先校验，再决定是否执行"}</div>
          <div>{draftReason || "校验不会修改本地数据或万相台；确认后可以写入平台，也可以只建立观察任务。"}{draftExpected ? ` 预期：${draftExpected}` : ""}</div>
        </div>
        <div className="ops-adjust-modal__section">
          <div className="ops-adjust-modal__section-head">
            <div><Text strong>调整项目</Text><Text type="secondary">选择要修改的投放参数</Text></div>
            {writeCapabilities ? <Space wrap size={4}>
              <Tag color={writeCapabilities.day_budget.write ? "green" : "orange"}>预算写入 {writeCapabilities.day_budget.write ? "已支持" : "待接入"}</Tag>
              <Tag color={writeCapabilities.bid_value.write ? "green" : "orange"}>出价写入 {writeCapabilities.bid_value.write ? "已支持" : "待接入"}</Tag>
            </Space> : null}
          </div>
          <Segmented
            block
            value={adjustField}
            onChange={(value) => { setAdjustField(value as "day_budget" | "bid_value"); setAdjustPreview(null); setAdjustError(""); setAdjustTargetValue(null); setAdjustTargetSource("percent"); }}
            options={[{ value: "day_budget", label: "日预算" }, { value: "bid_value", label: "出价" }]}
          />
          <div className="ops-adjust-modal__value-row">
            <div className="ops-adjust-modal__value-box">
              <Text type="secondary">当前值</Text>
              <strong>{adjustTargets.length === 1 ? (adjustCurrentValue ? (adjustField === "day_budget" ? fmtMoney(adjustCurrentValue) : adjustCurrentValue.toFixed(2)) : "—") : `${adjustTargets.length} 个计划`}</strong>
              <Text type="secondary">{adjustTargets.length === 1 ? "平台当前配置" : "各计划按自身当前值计算"}</Text>
            </div>
            <span className="ops-adjust-modal__arrow" aria-hidden="true">→</span>
            <div className="ops-adjust-modal__target-box">
              <Text type="secondary">调整幅度</Text>
            <InputNumber
              value={adjustPct}
              onChange={(value) => {
                  const nextPct = value ?? 0;
                  setAdjustPct(nextPct);
                  setAdjustPreview(null);
                  setAdjustError("");
                  if (adjustTargets.length === 1) {
                    setAdjustTargetValue(Number((adjustCurrentValue * (1 + nextPct / 100)).toFixed(2)));
                    setAdjustTargetSource("percent");
                  }
                }}
                min={-90}
                max={300}
                precision={1}
                addonAfter="%"
                controls
              />
              <Text type="secondary">{adjustPct === 0 ? "保持原值，仅建立观察任务" : `${adjustPct > 0 ? "增加" : "减少"} ${Math.abs(adjustPct)}%`}</Text>
            </div>
            <span className="ops-adjust-modal__arrow" aria-hidden="true">→</span>
            <div className="ops-adjust-modal__target-box ops-adjust-modal__target-box--final">
              <Text type="secondary">目标值</Text>
              <InputNumber
                value={adjustTargets.length === 1 ? adjustTargetValue : null}
                disabled={adjustTargets.length !== 1}
                onChange={(value) => {
                  setAdjustTargetValue(value);
                  setAdjustTargetSource(value == null ? "percent" : "target");
                  setAdjustPreview(null);
                  setAdjustError("");
                  if (adjustTargets.length === 1 && value != null && adjustCurrentValue > 0) {
                    setAdjustPct(Number(((value / adjustCurrentValue - 1) * 100).toFixed(1)));
                  }
                }}
                min={adjustCurrentValue > 0 ? Number((adjustCurrentValue * 0.1).toFixed(2)) : 0}
                max={adjustCurrentValue > 0 ? Number((adjustCurrentValue * 4).toFixed(2)) : undefined}
                precision={2}
                addonAfter={adjustField === "day_budget" ? "元" : ""}
                controls
                placeholder={adjustTargets.length === 1 ? "输入目标值" : "按各计划计算"}
              />
              <Text type="secondary">{adjustTargets.length === 1 ? "输入目标值可反算调整幅度" : "批量计划按各自当前值计算"}</Text>
            </div>
          </div>
          <div className={`ops-adjust-modal__delta${adjustPct === 0 ? " is-neutral" : adjustPct > 0 ? " is-up" : " is-down"}`}>
            {adjustTargetSource === "target" && selectedPlanIds.length === 1 && adjustTargetValue != null
              ? `最终以目标值 ${adjustTargetValue} 执行`
              : adjustPct === 0 ? "不改变平台配置" : `${adjustField === "day_budget" ? "日预算" : "出价"}将${adjustPct > 0 ? "增加" : "减少"} ${Math.abs(adjustPct)}%`}
          </div>
        </div>
        {draftDecisionId && (Object.keys(draftSuccessCriteria).length || draftRollbackCondition) ? <div className="ops-adjust-modal__guard">
          <div className="ops-adjust-modal__guard-title">{draftTier === "aggressive" ? "激进" : draftTier === "balanced" ? "平衡" : "稳健"}方案 · 验证边界</div>
          <div className="ops-adjust-modal__guard-grid">
            <div><Text type="secondary">成功标准</Text><Text>{successCriteriaText(draftSuccessCriteria) || "按默认标准"}</Text></div>
            <div><Text type="secondary">回退条件</Text><Text type="warning">{draftRollbackCondition || "待人工补充"}</Text></div>
          </div>
        </div> : null}
        <div className="ops-adjust-modal__notice ops-adjust-modal__notice--warning">
          <div className="ops-adjust-modal__notice-title">执行前请确认</div>
          <div>校验中的旧值会作为回退快照保存；真实写入后将记录动作和平台回执，并建立观察验证。</div>
        </div>
        <div className="ops-adjust-modal__section-head ops-adjust-modal__preview-head">
          <div>
            <Text strong>执行前校验</Text>
            <Text type="secondary">
              {adjustError
                ? `校验失败：${adjustError}`
                : adjustPreview && adjustPreviewStats
                ? `已检查 ${adjustPreview.items.length} 个计划 · 方案有效 ${adjustPreviewStats.valid} · 可执行 ${adjustPreviewStats.executable} · 被拦截 ${adjustPreviewStats.blocked}`
                : adjustTargets.length === 1
                  ? "填写完成后，点击执行前校验检查当前计划"
                  : "填写调整参数后，点击校验批量调整检查每个计划"}
            </Text>
          </div>
          <Button
            type="primary"
            danger={Boolean(adjustError)}
            loading={adjustLoading}
            disabled={adjustExecuteLoading || selectedPlanIds.length === 0}
            onClick={() => void runAdjustPreview()}
          >
            {adjustError ? "重试校验" : adjustTargets.length > 1 ? "校验批量调整" : "执行前校验"}
          </Button>
        </div>
        {adjustPreview ? (
          <Space orientation="vertical" size={8} style={{ width: "100%" }}>
            {adjustPreview.items.map((item) => (
              <div className="ops-adjust-preview-item" key={item.plan_id}>
                <Space orientation="vertical" size={2} style={{ width: "100%" }}>
                  <Text strong>{item.plan_name || `计划 ${item.plan_id}`}</Text>
                  {item.ok ? (
                    <Space orientation="vertical" size={1}>
                      <Text>{adjustField === "day_budget" ? "日预算" : "出价"}：{item.old_value} → <Text strong>{item.new_value}</Text></Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>回退值：{item.old_value} · 实际变化：{item.old_value ? `${(((item.new_value || 0) - item.old_value) / item.old_value * 100).toFixed(2)}%` : "—"}</Text>
                    </Space>
                  ) : <Text type="danger">{item.error || "无法完成校验"}</Text>}
                  {item.ok && item.can_execute === false ? <Alert type="warning" showIcon title="当前不能执行" description={item.block_reason || "请先同步最新推广数据"} /> : null}
                  {item.risks?.map((risk) => <Tag color="orange" key={risk}>{risk}</Tag>)}
                </Space>
              </div>
            ))}
          </Space>
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={adjustError ? "校验失败，请重试或先检查推广数据同步状态" : adjustTargets.length === 1 ? (adjustLoading ? "正在校验当前计划..." : "填写调整参数后，点击执行前校验") : "点击右上角校验批量调整"} imageStyle={{ height: 46 }} />}
        {adjustPreview && adjustPreviewStats?.valid ? <Space orientation="vertical" style={{ width: "100%" }} size={8}>
          {writeCapabilities?.[adjustField]?.write ? <Button type="primary" danger block loading={adjustExecuteLoading} disabled={actionRecording || adjustPreview.items.some((item) => item.ok && item.can_execute === false)} onClick={executeAdjustments} style={{ marginTop: 16 }}>
            立即写入万相台（{adjustPreviewStats.executable} 个）
          </Button> : null}
          {adjustPreview.items.some((item) => item.ok && item.can_execute === false) ? <Text type="warning">执行入口已锁定：请先按上方提示同步最新数据，再重新校验。</Text> : null}
          <Button block loading={actionRecording} disabled={adjustExecuteLoading} onClick={() => void createAdjustmentRecords()}>
            只建立观察任务（不写入平台）
          </Button>
        </Space> : null}
      </Modal>
      <Modal
        title="新建万相台计划"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => void createPlan()}
        okText="确认创建"
        cancelText="取消"
        confirmLoading={createLoading}
        destroyOnHidden
      >
        <Alert type="warning" showIcon title="需要使用万相台 solutionList 原始结构" description="平台字段因场景而异；可先在万相台创建页准备方案 JSON，再粘贴到这里。提交会直接创建平台计划。" style={{ marginBottom: 12 }} />
        <Space orientation="vertical" style={{ width: "100%" }} size={10}>
          <Select value={createBizCode} onChange={setCreateBizCode} options={[{ value: "onebpSite", label: "货品全站推广" }, { value: "onebpSearch", label: "关键词推广" }, { value: "onebpDisplay", label: "人群推广" }, { value: "onebpShortVideo", label: "内容营销" }]} />
          <Input.TextArea value={createPayload} onChange={(event) => setCreatePayload(event.target.value)} autoSize={{ minRows: 10, maxRows: 18 }} />
        </Space>
      </Modal>
      <Drawer
        title={detailPlan ? `详细数据：${detailPlan.plan_name}` : "详细数据"}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        size="large"
      >
        {detailPlan ? (
          <div>
            <Alert
              type="info"
              showIcon
              title="计划档案已集中整理趋势、归因和调整验证记录"
              description="当前抽屉保留快速查看；进入完整档案可以连续判断计划表现、历史动作和观察结果。"
              action={<Button type="primary" size="small" onClick={() => navigate(`/promotions/plans/${detailPlan.id}`)}>打开完整档案</Button>}
              style={{ marginBottom: 14 }}
            />
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 14 }}>
              <Tag>{detailPlan.scene_name || "未分类"}</Tag>
              <PromotionChannelTag item={detailPlan} />
              <Tag color={detailPlan.status === "在投" ? "green" : "default"}>{detailPlan.status || "—"}</Tag>
              <Text type="secondary" style={{ fontSize: 12 }}>计划ID {detailPlan.campaign_id}</Text>
            </div>
            <Row gutter={[10, 10]}>
              <Col xs={12} sm={8}>
                <div style={{ background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius)", padding: "10px 12px" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>日预算</Text>
                  <div style={{ fontSize: 18, fontWeight: 700, marginTop: 2 }}>{detailPlan.day_budget ? fmtMoney(detailPlan.day_budget) : "—"}</div>
                </div>
              </Col>
              {PLAN_DETAIL_FIELDS.map((f) => {
                const full: Record<string, number | null | undefined> = {
                  ...(detailPlan.extra ?? {}),
                  spend: detailPlan.spend,
                  sales: detailPlan.sales,
                  roi: detailPlan.roi,
                  clicks: detailPlan.clicks,
                  charge: detailPlan.extra?.charge ?? detailPlan.spend,
                  alipayInshopAmt: detailPlan.extra?.alipayInshopAmt ?? detailPlan.sales,
                  retainedRoi: detailPlan.extra?.retainedRoi ?? detailPlan.retained_roi ?? 0,
                  real_roi: detailPlan.real_roi,
                };
                const v = full[f.key];
                if (v == null || v === undefined) return null;
                const value = f.fmt === "money" ? fmtMoney(v) : f.fmt === "percent" ? `${(v * 100).toFixed(2)}%` : f.fmt === "int" ? fmtInt(v) : v.toFixed(2);
                return (
                  <Col xs={12} sm={8} key={f.key}>
                    <div style={{ background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius)", padding: "10px 12px" }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>{f.label}</Text>
                      <div style={{ fontSize: 16, fontWeight: 700, marginTop: 2, color: f.key === "retainedRoi" ? "var(--ops-accent)" : undefined }}>{value}</div>
                    </div>
                  </Col>
                );
              })}
            </Row>
            <Card size="small" title="投放链路" style={{ marginTop: 14, background: "var(--ops-panel-2)" }} loading={detailFunnelLoading}>
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  {(detailFunnel?.links || [
                    { type: "item", label: "商品", status: "empty" },
                    { type: "keyword", label: "关键词", status: "pending" },
                    { type: "crowd", label: "人群", status: "pending" },
                    { type: "creative", label: "素材", status: "pending" },
                  ]).map((link) => (
                    <Tag color={link.status === "ready" ? "green" : link.status === "empty" ? "default" : "orange"} key={link.type}>
                      {link.label} · {link.status === "ready" ? "已关联" : link.status === "empty" ? "暂无" : "待接入"}
                    </Tag>
                  ))}
                </Space>
                {detailFunnel?.item ? <Text type="secondary">关联商品：{detailFunnel.item.item_title || detailFunnel.item.item_id}</Text> : <Text type="secondary">暂未找到关联商品</Text>}
              </Space>
            </Card>
            <Card size="small" title="操作与复盘时间线" style={{ marginTop: 12, background: "var(--ops-panel-2)" }}>
              {detailFunnel?.timeline?.length ? (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {detailFunnel.timeline.map((event, index) => (
                    <div key={`${event.created_at}-${index}`} style={{ borderLeft: "2px solid var(--ops-accent)", paddingLeft: 10 }}>
                      <Space size={6} wrap>
                        <Tag color="blue">{event.action}</Tag>
                        <Text type="secondary" style={{ fontSize: 11 }}>{dayjs(event.created_at).format("MM-DD HH:mm")}</Text>
                        <Text type="secondary" style={{ fontSize: 11 }}>{event.username}</Text>
                      </Space>
                      <div style={{ fontSize: 12, marginTop: 3 }}>{event.detail || "—"}</div>
                    </div>
                  ))}
                </Space>
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无计划操作记录" />}
            </Card>
          </div>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />
        )}
      </Drawer>
    </WorkspacePage>
  );
}
