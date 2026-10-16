import {
  AlertOutlined,
  ArrowRightOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Collapse,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  InputNumber,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { fmtMoney } from "../components/promotions/promotions-ui";
import { PROMOTION_CHANNELS, PromotionChannelTag, getPromotionChannel } from "../components/promotions/promotion-channel";
import { PageHeader } from "../components/ui/page-header";
import { DecisionBand, MetricRail, WorkspacePage, WorkspaceToolbar } from "../components/ui/workspace-template";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";
import { useAlertConfig } from "../lib/use-alert-config";

const { Paragraph, Text } = Typography;

type Severity = "critical" | "high" | "medium";
type Confidence = "high" | "medium" | "low";
type SignalType = "risk" | "opportunity" | "observation";
type Priority = "p0" | "p1" | "p2" | "p3";

type Evidence = {
  label: string;
  current: number | string;
  baseline: number | string | null;
  unit: string;
};

type ItemTrafficMetric = {
  item_id: string;
  item_title: string;
  mode: string;
  spend: number | null;
  sales: number | null;
  roi: number | null;
  clicks: number | null;
  orders: number | null;
  impressions: number | null;
  source: string;
  updated_at: string;
};

type ItemTraffic = {
  status: "complete" | "partial" | "missing";
  reason: string;
  item_id: string;
  metrics: ItemTrafficMetric[];
};

type Recommendation = {
  key: string;
  label: string;
  reason: string;
  path: string;
};

type Diagnostic = {
  id: string;
  rule_code: string;
  rule_explanation: string;
  signal_type: SignalType;
  category: string;
  severity: Severity;
  priority?: Priority;
  priority_reason?: string;
  title: string;
  summary: string;
  confidence: Confidence;
  confidence_reason: string;
  plan_id: number;
  plan_name: string;
  campaign_id?: string;
  item_id?: string;
  item_title?: string;
  item_image?: string;
  store_id: number;
  store_name: string;
  scene_name: string;
  scene?: string;
  channel?: string;
  channel_name?: string;
  plan_status: string;
  spend_at_risk: number;
  sales_gap: number;
  evidence: Evidence[];
  item_traffic?: ItemTraffic;
  possible_causes: string[];
  recommendations: Recommendation[];
  unknown_dimensions: string[];
  detected_at: string;
};

type DiagnosticsData = {
  summary: {
    total: number;
    risk_count: number;
    opportunity_count: number;
    observation_count: number;
    critical: number;
    high: number;
    medium: number;
    affected_plan_count: number;
    estimated_spend_at_risk: number;
  };
  items: Diagnostic[];
  categories: Array<{ category: string; count: number }>;
  data_health: {
    visible_plan_count: number;
    active_plan_count: number;
    realtime_coverage_count: number;
    realtime_coverage_rate: number;
    item_traffic_coverage_count?: number;
    item_traffic_complete_count?: number;
    item_traffic_coverage_rate?: number;
  };
  thresholds: Record<string, number | string>;
  generated_at: string;
};

type AIDiagnosis = {
  conclusion: string;
  issue_type: string;
  decision?: string;
  primary_cause?: string;
  affected_stage?: string;
  recommended_variable?: string;
  recommended_direction?: string;
  recommended_range?: string;
  observation_hours?: number;
  success_criteria?: string[];
  rollback_condition?: string;
  causes: string[];
  evidence: string[];
  missing_data: string[];
  confidence: string;
  recommend_intervention: string;
  next_step: string;
};

type AIDiagnosticResult = { ai_diagnosis: AIDiagnosis; next_path: string; input_context?: Record<string, unknown>; cached?: boolean; generated_at?: string };

function aiDiagnosisFingerprint(item: Diagnostic): string {
  const source = {
    id: item.id,
    rule_code: item.rule_code,
    plan_status: item.plan_status,
    evidence: item.evidence,
    rule_explanation: item.rule_explanation,
    confidence: item.confidence,
    possible_causes: item.possible_causes,
    unknown_dimensions: item.unknown_dimensions,
    item_traffic: item.item_traffic,
  };
  return JSON.stringify(source);
}

function aiDiagnosisCacheKey(item: Diagnostic): string {
  return `promo-ai-diagnosis:${item.id}`;
}

function readLocalAIDiagnosis(item: Diagnostic): AIDiagnosticResult | null {
  try {
    const raw = window.localStorage.getItem(aiDiagnosisCacheKey(item));
    if (!raw) return null;
    const envelope = JSON.parse(raw) as { fingerprint?: string; result?: AIDiagnosticResult };
    if (envelope.fingerprint !== aiDiagnosisFingerprint(item) || !envelope.result?.ai_diagnosis) return null;
    return { ...envelope.result, cached: true };
  } catch {
    return null;
  }
}

function writeLocalAIDiagnosis(item: Diagnostic, result: AIDiagnosticResult): void {
  try {
    window.localStorage.setItem(aiDiagnosisCacheKey(item), JSON.stringify({ fingerprint: aiDiagnosisFingerprint(item), result }));
  } catch {
    // 浏览器存储不可用时仍保留当前页面内的诊断结果。
  }
}

const confidenceMeta: Record<Confidence, { label: string; color: string }> = {
  high: { label: "高可信", color: "green" },
  medium: { label: "中可信", color: "blue" },
  low: { label: "低可信", color: "default" },
};

const signalMeta: Record<SignalType, { label: string; color: string }> = {
  risk: { label: "风险问题", color: "red" },
  opportunity: { label: "增长机会", color: "green" },
  observation: { label: "观察信号", color: "blue" },
};

const priorityMeta: Record<Priority, { label: string; color: string; description: string }> = {
  p0: { label: "P0", color: "red", description: "立即处理" },
  p1: { label: "P1", color: "orange", description: "优先核查" },
  p2: { label: "P2", color: "blue", description: "常规关注" },
  p3: { label: "P3", color: "default", description: "观察记录" },
};

const riskRuleCodes = new Set(["budget_over", "budget_near", "spend_without_sales", "roi_drop", "roi_low", "delivery_stopped", "spend_too_fast"]);

function resolveSignalType(item: Pick<Diagnostic, "rule_code" | "signal_type">): SignalType {
  if (item.signal_type) return item.signal_type;
  if (item.rule_code === "high_roi_low_spend") return "opportunity";
  return riskRuleCodes.has(item.rule_code) ? "risk" : "observation";
}

function getPriority(item: Pick<Diagnostic, "signal_type" | "severity" | "priority">): Priority {
  if ("priority" in item && item.priority && ["p0", "p1", "p2", "p3"].includes(item.priority)) return item.priority;
  if (item.signal_type === "observation") return "p3";
  if (item.signal_type === "opportunity") return "p2";
  return item.severity === "critical" ? "p0" : item.severity === "high" ? "p1" : "p2";
}

const categoryLabels: Record<string, string> = {
  budget: "预算",
  conversion: "转化",
  efficiency: "效率",
  delivery: "投放",
  pacing: "节奏",
  scale: "放量机会",
  underdelivery: "烧不满",
  growth: "放量机会",
  data: "数据",
};

function formatEvidenceValue(value: Evidence["current"], unit: string): string {
  if (typeof value === "number") return `${value.toLocaleString("zh-CN")}${unit}`;
  return `${value}${unit}`;
}

const itemTrafficModeLabels: Record<string, string> = {
  realtime: "实时",
  yesterday: "昨天",
  "7": "近 7 天",
  "14": "近 14 天",
  "30": "近 30 天",
};

const itemTrafficSourceLabels: Record<string, string> = {
  report: "商品报表",
  plan_scene: "计划归因",
  plan: "计划归因",
};

function formatItemTrafficNumber(value: number | null | undefined, suffix = ""): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("zh-CN")}${suffix}`;
}

function formatItemTrafficCount(value: number | null | undefined, metric: ItemTrafficMetric): string {
  // plan_scene rows use zero as a placeholder when the upstream report omitted a field.
  if ((value === 0 || value === null || value === undefined) && metric.source !== "report") return "—";
  return formatItemTrafficNumber(value);
}

export function PromotionsDiagnosticsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { stores, currentStore } = useStores();
  const { config: alertConfig, saveConfig: saveAlertConfig } = useAlertConfig();
  const [data, setData] = useState<DiagnosticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [storeId, setStoreId] = useState<number | "all">(currentStore?.id ?? "all");
  const [channel, setChannel] = useState(searchParams.get("channel") || "all");
  const [priority, setPriority] = useState<Priority | "all">("all");
  const [signalType, setSignalType] = useState<SignalType | "all">("all");
  const [category, setCategory] = useState("all");
  const [confidence, setConfidence] = useState<Confidence | "all">("all");
  const [selected, setSelected] = useState<Diagnostic | null>(null);
  const [aiDiagnosis, setAiDiagnosis] = useState<AIDiagnosticResult | null>(null);
  const [aiDiagnosisLoading, setAiDiagnosisLoading] = useState(false);
  const [ruleSettingsOpen, setRuleSettingsOpen] = useState(false);
  const [ruleSettingsSaving, setRuleSettingsSaving] = useState(false);
  const [ruleSettings, setRuleSettings] = useState(alertConfig.diagnostics);

  const openRuleSettings = () => {
    setRuleSettings({
      channels: { ...alertConfig.diagnostics.channels },
      rules: Object.fromEntries(Object.entries(alertConfig.diagnostics.rules).map(([code, setting]) => [code, { ...setting }])),
      thresholds: { ...alertConfig.diagnostics.thresholds },
      priority_thresholds: JSON.parse(JSON.stringify(alertConfig.diagnostics.priority_thresholds || {})),
    });
    setRuleSettingsOpen(true);
  };

  const contextualPath = (path: string, item: Diagnostic) => {
    const url = new URL(path, window.location.origin);
    url.searchParams.set("store_id", String(item.store_id));
    url.searchParams.set("channel", getPromotionChannel(item));
    url.searchParams.set("plan_id", String(item.plan_id));
    url.searchParams.set("diagnostic_id", item.id);
    url.searchParams.set("diagnostic", item.rule_code);
    url.searchParams.set("rule", item.rule_code);
    return `${url.pathname}?${url.searchParams.toString()}`;
  };

  useEffect(() => {
    setStoreId(currentStore?.id ?? "all");
  }, [currentStore?.id]);

  useEffect(() => {
    setRuleSettings(alertConfig.diagnostics);
  }, [alertConfig.diagnostics]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await http.get<DiagnosticsData>("/promotions/diagnostics", {
        params: {
          ...(storeId === "all" ? {} : { store_id: storeId }),
          ...(channel === "all" ? {} : { channel }),
        },
      });
      const items = response.data.items.map((item) => ({
        ...item,
        signal_type: resolveSignalType(item),
        rule_explanation: item.rule_explanation || "当前指标命中了系统诊断规则，请结合下方证据、计划目标和业务背景复核。",
      }));
      const riskCount = items.filter((item) => item.signal_type === "risk").length;
      const opportunityCount = items.filter((item) => item.signal_type === "opportunity").length;
      const observationCount = items.filter((item) => item.signal_type === "observation").length;
      const normalizedData: DiagnosticsData = {
        ...response.data,
        items,
        summary: {
          ...response.data.summary,
          risk_count: response.data.summary.risk_count ?? riskCount,
          opportunity_count: response.data.summary.opportunity_count ?? opportunityCount,
          observation_count: response.data.summary.observation_count ?? observationCount,
        },
      };
      setData(normalizedData);
      const targetId = searchParams.get("diagnostic_id");
      if (targetId) setSelected(items.find((item) => item.id === targetId) || null);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [channel, searchParams, storeId]);

  useEffect(() => { void load(); }, [load]);

  const openDetail = (item: Diagnostic) => {
    setSelected(item);
    const next = new URLSearchParams(searchParams);
    next.set("diagnostic_id", item.id);
    setSearchParams(next, { replace: true });
  };

  const closeDetail = () => {
    setSelected(null);
    const next = new URLSearchParams(searchParams);
    next.delete("diagnostic_id");
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    let cancelled = false;
    if (!selected) {
      setAiDiagnosis(null);
      return () => { cancelled = true; };
    }
    const localCached = readLocalAIDiagnosis(selected);
    setAiDiagnosis(localCached);
    setAiDiagnosisLoading(true);
    const params = {
      diagnostic_id: selected.id,
      plan_id: selected.plan_id,
      store_id: selected.store_id,
      channel: getPromotionChannel(selected),
      rule_code: selected.rule_code,
    };
    void http.get<AIDiagnosticResult & { cached?: boolean }>('/promotions/diagnostics/ai', { params })
      .then((response) => {
        if (!cancelled && response.data.cached && response.data.ai_diagnosis) {
          writeLocalAIDiagnosis(selected, response.data);
          setAiDiagnosis(response.data);
        }
      })
      // 缓存读取是后台预取；接口暂不可用时不打断查看异常详情，仍可手动开始诊断。
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setAiDiagnosisLoading(false);
      });
    return () => { cancelled = true; };
  }, [selected?.detected_at, selected?.id]);

  const filteredItems = useMemo(() => (data?.items || []).filter((item) => (
    (signalType === "all" || item.signal_type === signalType)
    && (priority === "all" || getPriority(item) === priority)
    && (channel === "all" || getPromotionChannel(item) === channel)
    && (category === "all" || item.category === category)
    && (confidence === "all" || item.confidence === confidence)
  )), [category, channel, confidence, data?.items, priority, signalType]);

  const opportunitySummary = useMemo(() => {
    const items = data?.items || [];
    return {
      scale: items.filter((item) => item.category === "growth" || item.category === "scale" || item.rule_code === "high_roi_low_spend").length,
      pacing: items.filter((item) => item.category === "pacing" || item.rule_code === "spend_too_fast").length,
      underdelivery: items.filter((item) => item.category === "underdelivery" || ["delivery_stopped", "delivery_slow"].includes(item.rule_code)).length,
    };
  }, [data?.items]);

  const categoryOptions = useMemo(() => [
    { value: "all", label: "全部诊断维度" },
    ...(data?.categories || []).map((item) => ({
      value: item.category,
      label: `${categoryLabels[item.category] || item.category} (${item.count})`,
    })),
  ], [data?.categories]);

  const diagnosticRuleLabels: Record<string, string> = {
    data_stale: "数据过期",
    budget_over: "预算超限",
    budget_near: "接近预算",
    spend_without_sales: "有消耗无成交",
    roi_drop: "ROI 明显下滑",
    roi_low: "ROI 偏低",
    delivery_stopped: "计划停止投放",
    no_spend: "计划无消耗",
    delivery_slow: "投放节奏偏慢",
    low_spend: "消耗偏低",
    high_roi_low_spend: "高 ROI 放量机会",
    spend_too_fast: "消耗节奏过快",
  };
  const diagnosticThresholdFields = [
    { key: "spend_without_sales_min_spend", label: "无成交最低花费", unit: "元" },
    { key: "roi_drop_min_spend", label: "ROI 下滑最低花费", unit: "元" },
    { key: "roi_drop_high_drop_pct", label: "ROI 高风险下滑幅度", unit: "%" },
    { key: "roi_drop_high_spend", label: "ROI 下滑高风险花费", unit: "元" },
    { key: "roi_low_min_spend", label: "ROI 偏低最低花费", unit: "元" },
    { key: "roi_low_high_spend", label: "ROI 偏低高风险花费", unit: "元" },
    { key: "delivery_stopped_min_yesterday_spend", label: "停止投放历史花费门槛", unit: "元" },
    { key: "delivery_slow_min_yesterday_spend", label: "节奏偏慢历史花费门槛", unit: "元" },
  ];
  const priorityMetricLabels: Record<string, { label: string; unit: string }> = {
    drop_pct: { label: "ROI 跌幅", unit: "%" },
    spend: { label: "当前花费", unit: "元" },
    budget_utilization_pct: { label: "预算消耗率", unit: "%" },
    elapsed_pct: { label: "时间进度", unit: "%" },
    yesterday_spend: { label: "昨日花费", unit: "元" },
    pace_gap_pct: { label: "节奏落差", unit: "%" },
    stale_hours: { label: "数据滞后", unit: "小时" },
  };

  const diagnosticRuleDescriptions: Record<string, string> = {
    data_stale: "指标更新时间超过诊断允许范围",
    budget_over: "计划花费已超过当日预算",
    budget_near: "计划花费接近当日预算",
    spend_without_sales: "达到最低花费但暂未产生成交",
    roi_drop: "ROI 相比基准明显下滑",
    roi_low: "ROI 低于经营目标区间",
    delivery_stopped: "计划处于停止或暂停状态但仍有历史投放",
    no_spend: "计划在观察窗口内没有有效花费",
    delivery_slow: "历史有花费但当前投放节奏偏慢",
    low_spend: "当前消耗较低，暂不建议直接调整",
    high_roi_low_spend: "ROI 健康但消耗不足，具备放量机会",
    spend_too_fast: "消耗速度明显快于计划节奏",
  };
  const diagnosticChannelOptions = PROMOTION_CHANNELS.map((item) => ({
    value: item.value,
    label: item.label,
  }));
  const priorityOptions = Object.entries(priorityMeta).map(([value, meta]) => ({
    value,
    label: `${meta.label} · ${meta.description}`,
  }));

  const handleSaveRuleSettings = async () => {
    setRuleSettingsSaving(true);
    try {
      await saveAlertConfig({ diagnostics: ruleSettings });
      message.success("诊断规则已保存");
      setRuleSettingsOpen(false);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setRuleSettingsSaving(false);
    }
  };

  const runAIDiagnosis = async () => {
    if (!selected) return;
    setAiDiagnosisLoading(true);
    try {
      const response = await http.post<AIDiagnosticResult>("/promotions/diagnostics/ai", {
        diagnostic_id: selected.id,
        plan_id: selected.plan_id,
        store_id: selected.store_id,
        channel: getPromotionChannel(selected),
        rule_code: selected.rule_code,
        evidence: selected.evidence,
        force: true,
      }, { timeout: 130000 });
      setAiDiagnosis(response.data);
      writeLocalAIDiagnosis(selected, response.data);
      message.success(response.data.cached ? "已读取上次 AI 诊断" : "AI 诊断已更新");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiDiagnosisLoading(false);
    }
  };

  const columns: TableColumnsType<Diagnostic> = [
    {
      title: "处理分组",
      dataIndex: "signal_type",
      width: 108,
      render: (value: SignalType) => <Tag color={signalMeta[value].color}>{signalMeta[value].label}</Tag>,
    },
    {
      title: "优先级",
      key: "priority",
      width: 112,
      render: (_value, item) => {
        const meta = priorityMeta[getPriority(item)];
        return <Tag color={meta.color} title={item.priority_reason || meta.description}>{meta.label}</Tag>;
      },
    },
    {
      title: "规则发现",
      key: "diagnostic",
      render: (_value, item) => (
        <Space orientation="vertical" size={2}>
          <Space size={6} wrap><Text strong>{item.title}</Text><Tag variant="filled">{categoryLabels[item.category] || item.category}</Tag></Space>
          <Text type="secondary" style={{ fontSize: 12 }}>{item.summary}</Text>
        </Space>
      ),
    },
    {
      title: "问题计划",
      key: "plan",
      width: 330,
      render: (_value, item) => (
        <div className="ops-diagnostic-plan">
          {item.item_image ? <img className="ops-diagnostic-plan__image" src={item.item_image} alt="" /> : <span className="ops-diagnostic-plan__image is-empty" aria-hidden="true" />}
          <div className="ops-diagnostic-plan__content">
            <Text strong ellipsis={{ tooltip: item.plan_name }}>{item.plan_name}</Text>
            <Text type="secondary" className="ops-diagnostic-plan__id">平台计划 ID {item.campaign_id || "未同步"}</Text>
            {item.item_title ? <Text className="ops-diagnostic-plan__product" ellipsis={{ tooltip: item.item_title }}>{item.item_title}</Text> : <Text type="warning" className="ops-diagnostic-plan__product">宝贝未同步</Text>}
            <Text type="secondary" className="ops-diagnostic-plan__id">宝贝 ID {item.item_id || "未同步"}</Text>
            <div className="ops-diagnostic-plan__scope">
              <PromotionChannelTag item={item} />
              <Text type="secondary">{item.store_name || "未标注店铺"} · {item.scene_name}</Text>
              <Button type="link" size="small" onClick={() => navigate(`/promotions/plans/${item.plan_id}`)}>计划档案</Button>
            </div>
          </div>
        </div>
      ),
    },
    {
      title: "可信度",
      dataIndex: "confidence",
      width: 92,
      render: (value: Confidence) => <Tag color={confidenceMeta[value].color}>{confidenceMeta[value].label}</Tag>,
    },
    {
      title: "风险花费",
      dataIndex: "spend_at_risk",
      width: 110,
      align: "right",
      render: (value: number) => value > 0 ? <Text type="danger">{fmtMoney(value)}</Text> : "—",
    },
    {
      title: "操作",
      key: "action",
      width: 168,
      fixed: "right",
      render: (_value, item) => (
        <Space size={4}>
          <Button size="small" icon={<FileSearchOutlined />} onClick={() => openDetail(item)}>判断依据</Button>
          {item.recommendations[0] ? <Button size="small" type="primary" onClick={() => navigate(contextualPath(item.recommendations[0].path, item))}>处理</Button> : null}
        </Space>
      ),
    },
  ];

  const coverageStatus = (data?.data_health.realtime_coverage_rate || 0) >= 90 ? "success" : "normal";

  return (
    <WorkspacePage kind="analysis">
      <PageHeader
        icon={<AlertOutlined />}
        eyebrow="推广管理"
        title="推广异常发现与诊断中心"
        description="先由规则发现异常，再用 AI 分析原因、证据和是否值得干预，最后进入 AI 决策制定具体方案。"
        updatedAt={data?.generated_at || null}
        extra={(
          <Space>
            <Button icon={<SettingOutlined />} onClick={openRuleSettings}>诊断规则设置</Button>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>重新诊断</Button>
          </Space>
        )}
      />

      <DecisionBand
        eyebrow="规则发现结论"
        title={data?.summary.critical ? `${data.summary.critical} 个紧急风险需要先处理` : data?.summary.risk_count ? `${data.summary.risk_count} 个风险问题需要核查` : data?.summary.opportunity_count ? `${data.summary.opportunity_count} 个计划值得评估放量` : "当前没有需要立即处理的风险"}
        description="风险用于处理，机会用于评估，观察信号用于补充数据或等待窗口；系统只提供依据和建议，不会自动修改万相台。"
        action={<Button type="primary" onClick={() => setSignalType(data?.summary.risk_count ? "risk" : data?.summary.opportunity_count ? "opportunity" : "all")}>{data?.summary.risk_count ? "查看风险问题" : data?.summary.opportunity_count ? "查看增长机会" : "查看全部信号"}</Button>}
        ariaLabel="推广规则发现首要结论"
      />

      {loading && !data ? <div style={{ minHeight: 320, display: "flex", alignItems: "center", justifyContent: "center" }} aria-busy="true"><Spin size="large" /></div> : null}
      {!loading && !data ? <Card variant="borderless"><Empty description="暂时无法加载异常诊断"><Button type="primary" onClick={() => void load()}>重新加载</Button></Empty></Card> : null}

      {data ? (
        <>
          <MetricRail items={[
              { label: "诊断信号", value: data.summary.total, color: "var(--ops-text)", hint: "规则命中总数，可一计划多信号" },
              { label: "风险问题", value: data.summary.risk_count, color: "var(--ops-danger)", hint: `${data.summary.critical} 个紧急 · ${data.summary.high} 个高风险`, onClick: () => setSignalType((current) => current === "risk" ? "all" : "risk"), active: signalType === "risk", ariaLabel: "筛选风险问题" },
              { label: "增长机会", value: data.summary.opportunity_count, color: "var(--ops-success)", hint: "ROI 健康但获量不足", onClick: () => setSignalType((current) => current === "opportunity" ? "all" : "opportunity"), active: signalType === "opportunity", ariaLabel: "筛选增长机会" },
              { label: "观察信号", value: data.summary.observation_count, color: "var(--ops-info)", hint: `烧不满 ${opportunitySummary.underdelivery} · 节奏 ${opportunitySummary.pacing}`, onClick: () => setSignalType((current) => current === "observation" ? "all" : "observation"), active: signalType === "observation", ariaLabel: "筛选观察信号" },
              { label: "影响计划", value: data.summary.affected_plan_count, color: "var(--ops-text)", hint: `在投计划 ${data.data_health.active_plan_count} 个` },
              { label: "预计风险花费", value: fmtMoney(data.summary.estimated_spend_at_risk), color: "var(--ops-danger)", hint: "按计划去重估算" },
            ].map((item) => ({ key: item.label, label: item.label, value: item.value, hint: item.hint, tone: item.color, onClick: item.onClick, active: item.active, ariaLabel: item.ariaLabel }))} />

          <Card
            variant="borderless"
            title="异常清单"
            extra={(
              <WorkspaceToolbar>
                <Select
                  aria-label="处理分组"
                  value={signalType}
                  style={{ minWidth: 126 }}
                  options={[{ value: "all", label: "全部处理分组" }, ...Object.entries(signalMeta).map(([value, meta]) => ({ value, label: meta.label }))]}
                  onChange={(value) => setSignalType(value)}
                />
                <Select
                  aria-label="推广渠道"
                  value={channel}
                  style={{ minWidth: 140 }}
                  options={[{ value: "all", label: "全部渠道" }, ...PROMOTION_CHANNELS]}
                  onChange={setChannel}
                />
                <Select
                  aria-label="诊断店铺范围"
                  value={storeId}
                  style={{ minWidth: 150 }}
                  options={[{ value: "all", label: "全部可见店铺" }, ...stores.map((store) => ({ value: store.id, label: store.name }))]}
                  onChange={(value) => setStoreId(value)}
                />
                <Select
                  aria-label="优先级"
                  value={priority}
                  style={{ minWidth: 112 }}
                  options={[{ value: "all", label: "全部优先级" }, ...Object.entries(priorityMeta).map(([value, meta]) => ({ value, label: `${meta.label} · ${meta.description}` }))]}
                  onChange={(value) => setPriority(value as Priority | "all")}
                />
                <Select aria-label="诊断维度" value={category} style={{ minWidth: 150 }} options={categoryOptions} onChange={setCategory} />
                <Select
                  aria-label="诊断可信度"
                  value={confidence}
                  style={{ minWidth: 112 }}
                  options={[{ value: "all", label: "全部可信度" }, ...Object.entries(confidenceMeta).map(([value, meta]) => ({ value, label: meta.label }))]}
                  onChange={(value) => setConfidence(value)}
                />
              </WorkspaceToolbar>
            )}
            style={{ marginTop: 16 }}
          >
            <Table<Diagnostic>
              rowKey="id"
              size="small"
              columns={columns}
              dataSource={filteredItems}
              pagination={{ pageSize: 15, hideOnSinglePage: true }}
              scroll={{ x: 1280 }}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选下没有异常" /> }}
            />
          </Card>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={12}>
              <Card variant="borderless" title="数据覆盖健康度" style={{ height: "100%" }}>
                <Progress
                  percent={data.data_health.realtime_coverage_rate}
                  status={coverageStatus}
                  format={(value) => `${value}% 实时覆盖`}
                />
                <Text type="secondary">可见 {data.data_health.visible_plan_count} 个计划，其中 {data.data_health.realtime_coverage_count} 个在投计划已有实时指标；{data.data_health.item_traffic_coverage_count ?? 0} 个已关联商品流量数据（完整报表 {data.data_health.item_traffic_complete_count ?? 0} 个）。</Text>
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card variant="borderless" title="当前诊断边界" style={{ height: "100%" }}>
                <Text type="secondary">已接入预算、计划花费/成交/ROI/点击，以及关联商品的流量指标与数据来源。商品库存与价格、活动、素材、人群和竞争环境仍需人工核查。</Text>
              </Card>
            </Col>
          </Row>
        </>
      ) : null}

      <Drawer
        open={Boolean(selected)}
        title="异常详情"
        size="large"
        onClose={closeDetail}
        destroyOnHidden
      >
        {selected ? (
          <>
            <Card size="small" style={{ marginBottom: 12, background: "var(--ops-panel-2)" }}>
              <Space align="start" style={{ width: "100%" }}>
                {selected.item_image ? <img src={selected.item_image} alt="" style={{ width: 52, height: 52, borderRadius: 8, objectFit: "cover", flex: "0 0 auto" }} /> : <div style={{ width: 52, height: 52, borderRadius: 8, background: "var(--ops-border)", flex: "0 0 auto" }} aria-hidden="true" />}
                <div style={{ minWidth: 0, flex: 1 }}>
                  <Space wrap size={[6, 4]} style={{ marginBottom: 3 }}>
                    <Text strong>{selected.plan_name}</Text>
                    <Tag color={signalMeta[selected.signal_type].color}>{signalMeta[selected.signal_type].label}</Tag>
                    <Tag color={priorityMeta[getPriority(selected)].color} title={selected.priority_reason || priorityMeta[getPriority(selected)].description}>{priorityMeta[getPriority(selected)].label}</Tag>
                  </Space>
                  <div><Text type="secondary" style={{ fontSize: 12 }}>计划 ID {selected.campaign_id || "未同步"} · 宝贝 ID {selected.item_id || "未同步"}</Text></div>
                  <Text type="secondary" ellipsis={{ tooltip: selected.item_title || "宝贝未同步" }} style={{ display: "block", fontSize: 12 }}>{selected.item_title || "宝贝未同步"}</Text>
                  {selected.priority_reason ? <Text type="secondary" style={{ display: "block", fontSize: 12, marginTop: 4 }}>优先级依据：{selected.priority_reason}</Text> : null}
                </div>
              </Space>
            </Card>

            <Alert
              type={selected.signal_type === "risk" ? "warning" : selected.signal_type === "opportunity" ? "success" : "info"}
              showIcon
              title={selected.title}
              description={selected.summary}
              style={{ marginBottom: 12 }}
            />

            <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
              <Col xs={12} sm={8}><Card size="small"><Text type="secondary" style={{ fontSize: 12 }}>预计风险花费</Text><div style={{ fontSize: 16, fontWeight: 650, marginTop: 3, color: selected.spend_at_risk ? "var(--ops-danger)" : undefined }}>{selected.spend_at_risk ? fmtMoney(selected.spend_at_risk) : "—"}</div></Card></Col>
              <Col xs={12} sm={8}><Card size="small"><Text type="secondary" style={{ fontSize: 12 }}>成交缺口</Text><div style={{ fontSize: 16, fontWeight: 650, marginTop: 3 }}>{selected.sales_gap ? fmtMoney(selected.sales_gap) : "—"}</div></Card></Col>
              <Col xs={24} sm={8}><Card size="small"><Text type="secondary" style={{ fontSize: 12 }}>发现时间</Text><div style={{ fontSize: 13, fontWeight: 600, marginTop: 5 }}>{dayjs(selected.detected_at).format("MM-DD HH:mm")}</div></Card></Col>
            </Row>

            <Text type="secondary" style={{ display: "block", marginBottom: 8, fontSize: 12 }}>阅读顺序：先看异常结论，再看判定依据；需要时展开 AI 诊断和下一步处理。</Text>

            <Collapse
              size="small"
              defaultActiveKey={["why"]}
              items={[
                {
                  key: "why",
                  label: "为什么判定异常",
                  children: (
                    <>
                      <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
                        { key: "store", label: "店铺 / 场景", children: `${selected.store_name || "—"} · ${selected.scene_name}` },
                        { key: "channel", label: "渠道 / 状态", children: <Space size={4}><PromotionChannelTag item={selected} /><Text>{selected.plan_status || "—"}</Text></Space> },
                        { key: "rule", label: "诊断规则", children: selected.rule_code },
                        { key: "confidence", label: "可信度", children: <Tag color={confidenceMeta[selected.confidence].color}>{confidenceMeta[selected.confidence].label}</Tag> },
                      ]} />
                      <Alert type="info" showIcon title="命中规则" description={selected.rule_explanation} style={{ marginTop: 10 }} />
                      <Row gutter={[8, 8]} style={{ marginTop: 10 }}>
                        {selected.evidence.map((item) => (
                          <Col xs={12} sm={8} key={item.label}>
                            <Card size="small" style={{ height: "100%" }}>
                              <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
                              <div style={{ fontSize: 16, fontWeight: 650, marginTop: 3 }}>{formatEvidenceValue(item.current, item.unit)}</div>
                              {item.baseline !== null ? <Text type="secondary" style={{ fontSize: 11 }}>对比 {formatEvidenceValue(item.baseline, item.unit)}</Text> : null}
                            </Card>
                          </Col>
                        ))}
                      </Row>
                      <Text type="secondary" style={{ display: "block", marginTop: 10, fontSize: 12 }}>可信度说明：{selected.confidence_reason}</Text>
                    </>
                  ),
                },
                {
                  key: "item-traffic",
                  label: "商品流量证据",
                  children: (() => {
                    const traffic = selected.item_traffic || { status: "missing" as const, reason: "商品级推广数据尚未同步", item_id: "", metrics: [] };
                    const statusMeta = traffic.status === "complete"
                      ? { label: "数据完整", color: "green" as const }
                      : traffic.status === "partial"
                        ? { label: "部分数据", color: "orange" as const }
                        : { label: "暂无数据", color: "default" as const };
                    const trafficColumns: TableColumnsType<ItemTrafficMetric> = [
                      { title: "周期", dataIndex: "mode", width: 82, render: (mode: string) => itemTrafficModeLabels[mode] || mode || "—" },
                      { title: "展现", dataIndex: "impressions", align: "right", render: (value: number | null, metric) => formatItemTrafficCount(value, metric) },
                      { title: "点击", dataIndex: "clicks", align: "right", render: (value: number | null) => formatItemTrafficNumber(value) },
                      {
                        title: "点击率",
                        key: "ctr",
                        align: "right",
                        render: (_, metric) => metric.impressions && metric.impressions > 0 ? `${((metric.clicks || 0) / metric.impressions * 100).toFixed(2)}%` : "—",
                      },
                      { title: "花费", dataIndex: "spend", align: "right", render: (value: number | null) => formatItemTrafficNumber(value, " 元") },
                      { title: "成交", dataIndex: "sales", align: "right", render: (value: number | null) => formatItemTrafficNumber(value, " 元") },
                      { title: "ROI", dataIndex: "roi", align: "right", render: (value: number | null) => formatItemTrafficNumber(value) },
                      { title: "订单", dataIndex: "orders", align: "right", render: (value: number | null, metric) => formatItemTrafficCount(value, metric) },
                      { title: "来源", dataIndex: "source", width: 86, render: (source: string) => <Tag>{itemTrafficSourceLabels[source] || source || "未知"}</Tag> },
                      { title: "更新时间", dataIndex: "updated_at", width: 128, render: (value: string) => value ? dayjs(value).format("MM-DD HH:mm") : "—" },
                    ];
                    return (
                      <>
                        <Space wrap size={[6, 4]} style={{ marginBottom: 8 }}>
                          <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
                          {traffic.item_id ? <Text type="secondary">商品 ID {traffic.item_id}</Text> : null}
                        </Space>
                        <Alert
                          type={traffic.status === "complete" ? "success" : traffic.status === "partial" ? "warning" : "info"}
                          showIcon
                          title={traffic.reason}
                          description={traffic.status === "partial" ? "计划归因数据可用于定位花费与成交，但展现量、订单等字段可能未从商品报表同步，不能按 0 解释。" : undefined}
                          style={{ marginBottom: traffic.metrics.length ? 10 : 0 }}
                        />
                        {traffic.metrics.length ? <Table<ItemTrafficMetric> size="small" rowKey={(metric) => `${metric.mode}-${metric.source}`} columns={trafficColumns} dataSource={traffic.metrics} pagination={false} scroll={{ x: 920 }} /> : null}
                      </>
                    );
                  })(),
                },
                {
                  key: "ai",
                  label: aiDiagnosis ? "AI 诊断与建议" : "AI 深度诊断（按需运行）",
                  children: (
                    <>
                      <Space align="start" style={{ width: "100%", justifyContent: "space-between", marginBottom: aiDiagnosis ? 10 : 0 }}>
                        <Paragraph type="secondary" style={{ margin: 0, fontSize: 12 }}>在规则发现之后分析最可能原因和是否值得干预，不会自动修改计划。</Paragraph>
                        <Button type="primary" ghost icon={<RobotOutlined />} loading={aiDiagnosisLoading} onClick={() => void runAIDiagnosis()}>
                          {aiDiagnosis ? "重新诊断" : "开始 AI 诊断"}
                        </Button>
                      </Space>
                      {aiDiagnosis ? (
                        <>
                          <Text type="secondary" style={{ display: "block", marginBottom: 8, fontSize: 12 }}>
                            {aiDiagnosis.cached ? "已复用上次诊断" : "本次刚完成诊断"}{aiDiagnosis.generated_at ? ` · ${dayjs(aiDiagnosis.generated_at).format("YYYY-MM-DD HH:mm")}` : ""}
                          </Text>
                          <Text type="secondary" style={{ display: "block", marginBottom: 10, fontSize: 12 }}>本次依据：规则证据、计划实时/昨日指标、商品级流量指标及数据来源、近 7 天汇总、最近动作记录和可用经验（缺失数据不会被补造）。</Text>
                          <Space wrap style={{ marginBottom: 8 }}>
                            <Tag color="purple">{aiDiagnosis.ai_diagnosis.issue_type}</Tag>
                            {aiDiagnosis.ai_diagnosis.decision ? <Tag color={aiDiagnosis.ai_diagnosis.decision === "建议干预" ? "orange" : aiDiagnosis.ai_diagnosis.decision === "建议观察" ? "blue" : "default"}>{aiDiagnosis.ai_diagnosis.decision}</Tag> : null}
                            {aiDiagnosis.ai_diagnosis.affected_stage ? <Tag>{aiDiagnosis.ai_diagnosis.affected_stage}</Tag> : null}
                            <Tag color={aiDiagnosis.ai_diagnosis.confidence === "高" ? "green" : aiDiagnosis.ai_diagnosis.confidence === "中" ? "blue" : "default"}>置信度 {aiDiagnosis.ai_diagnosis.confidence}</Tag>
                            <Tag>{aiDiagnosis.ai_diagnosis.recommend_intervention}</Tag>
                          </Space>
                          <Paragraph style={{ marginBottom: 10 }}>{aiDiagnosis.ai_diagnosis.conclusion}</Paragraph>
                          {aiDiagnosis.ai_diagnosis.primary_cause ? <Alert type="warning" showIcon title="最可能原因" description={aiDiagnosis.ai_diagnosis.primary_cause} style={{ marginBottom: 10 }} /> : null}
                          {aiDiagnosis.ai_diagnosis.recommended_variable ? (
                            <Descriptions bordered size="small" column={1} style={{ marginBottom: 10 }} items={[
                              { key: "variable", label: "建议只调整", children: aiDiagnosis.ai_diagnosis.recommended_variable },
                              { key: "direction", label: "调整方向 / 幅度", children: `${aiDiagnosis.ai_diagnosis.recommended_direction || "不调整"} · ${aiDiagnosis.ai_diagnosis.recommended_range || "不建议直接调整"}` },
                              { key: "window", label: "观察周期", children: `${aiDiagnosis.ai_diagnosis.observation_hours || 48} 小时` },
                            ]} />
                          ) : null}
                          {aiDiagnosis.ai_diagnosis.causes.length ? <><Text strong>可能原因</Text><ul style={{ margin: "6px 0 10px", paddingLeft: 20 }}>{aiDiagnosis.ai_diagnosis.causes.map((cause) => <li key={cause}>{cause}</li>)}</ul></> : null}
                          {aiDiagnosis.ai_diagnosis.evidence.length ? <><Text strong>支持证据</Text><ul style={{ margin: "6px 0 10px", paddingLeft: 20 }}>{aiDiagnosis.ai_diagnosis.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}</ul></> : null}
                          {aiDiagnosis.ai_diagnosis.missing_data.length ? <Alert type="warning" title="仍需人工确认" description={aiDiagnosis.ai_diagnosis.missing_data.join("；")} style={{ marginBottom: 10 }} /> : null}
                          {aiDiagnosis.ai_diagnosis.success_criteria?.length ? <><Text strong>成功标准</Text><ul style={{ margin: "6px 0 10px", paddingLeft: 20 }}>{aiDiagnosis.ai_diagnosis.success_criteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul></> : null}
                          {aiDiagnosis.ai_diagnosis.rollback_condition ? <Text type="secondary" style={{ display: "block", marginBottom: 10, fontSize: 12 }}>回滚条件：{aiDiagnosis.ai_diagnosis.rollback_condition}</Text> : null}
                          <Space align="center" wrap><Text type="secondary" style={{ fontSize: 12 }}>{aiDiagnosis.ai_diagnosis.next_step}</Text><Button size="small" onClick={() => navigate(aiDiagnosis.next_path)}>进入 AI 决策</Button></Space>
                        </>
                      ) : null}
                    </>
                  ),
                },
                {
                  key: "check",
                  label: "待核查原因与数据边界",
                  children: (
                    <>
                      <Space orientation="vertical" size={8} style={{ width: "100%" }}>{selected.possible_causes.map((cause) => <Alert key={cause} type="warning" title={cause} />)}</Space>
                      {selected.unknown_dimensions.length ? <><Text strong style={{ display: "block", marginTop: 12, marginBottom: 6 }}>尚未接入的判断维度</Text><Space wrap>{selected.unknown_dimensions.map((dimension) => <Tag key={dimension}>{dimension}</Tag>)}</Space></> : null}
                    </>
                  ),
                },
                {
                  key: "action",
                  label: "下一步处理",
                  children: (
                    <>
                      <Space orientation="vertical" size={10} style={{ width: "100%" }}>{selected.recommendations.map((item) => <Card key={item.key} size="small"><Space align="start" style={{ width: "100%", justifyContent: "space-between" }}><div><Text strong>{item.label}</Text><Paragraph type="secondary" style={{ margin: "3px 0 0" }}>{item.reason}</Paragraph></div><Button aria-label={`${item.label}：${selected.plan_name}`} type={item.key === "ai_decision" ? "primary" : "default"} icon={<ArrowRightOutlined />} onClick={() => navigate(contextualPath(item.path, selected))} /></Space></Card>)}</Space>
                      <Alert type="success" showIcon icon={<SafetyCertificateOutlined />} title="所有处理动作仍需人工确认" description="执行后请回到观察验证中心记录结果。" style={{ marginTop: 12 }} />
                    </>
                  ),
                },
              ]}
            />
          </>
        ) : null}
      </Drawer>

      <Modal
        open={ruleSettingsOpen}
        title="诊断规则设置"
        width={860}
        okText="保存设置"
        cancelText="取消"
        confirmLoading={ruleSettingsSaving}
        onCancel={() => setRuleSettingsOpen(false)}
        onOk={() => void handleSaveRuleSettings()}
        destroyOnHidden
      >
        <Paragraph type="secondary" style={{ marginTop: -4, marginBottom: 16 }}>
          规则用于生成异常诊断，不会自动修改推广计划。关闭规则后，新的诊断结果中将不再显示对应信号。
        </Paragraph>
        <div style={{ border: "1px solid var(--ops-border)", borderRadius: 8, padding: "12px 14px", marginBottom: 16, background: "var(--ops-panel-2)" }}>
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <div>
              <Text strong>诊断渠道</Text>
              <div><Text type="secondary" style={{ fontSize: 12 }}>只对勾选的渠道运行下方诊断规则；取消勾选后，该渠道不会生成新的诊断信号。</Text></div>
            </div>
            <Checkbox.Group
              aria-label="选择需要诊断的推广渠道"
              options={diagnosticChannelOptions}
              value={diagnosticChannelOptions.filter((item) => ruleSettings.channels?.[item.value] !== false).map((item) => item.value)}
              onChange={(values) => {
                const selectedChannels = new Set(values.map(String));
                setRuleSettings((current) => ({
                  ...current,
                  channels: Object.fromEntries(diagnosticChannelOptions.map((item) => [item.value, selectedChannels.has(item.value)])),
                }));
              }}
            />
          </Space>
        </div>
        <div style={{ border: "1px solid var(--ops-border)", borderRadius: 8, overflowX: "auto", overflowY: "hidden" }}>
          <div style={{ display: "grid", gridTemplateColumns: "minmax(150px, 1fr) 70px 130px 130px minmax(220px, 1.4fr)", gap: 12, padding: "9px 14px", background: "var(--ops-panel-2)", color: "var(--ops-text-secondary)", fontSize: 12 }}>
            <span>诊断规则</span><span>启用</span><span>优先级模式</span><span>固定级别</span><span>判断说明</span>
          </div>
          {Object.entries(ruleSettings.rules).map(([code, setting], index) => (
            <div key={code} style={{ padding: "11px 14px", borderTop: index ? "1px solid var(--ops-border)" : undefined }}>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(150px, 1fr) 70px 130px 130px minmax(220px, 1.4fr)", gap: 12, alignItems: "center" }}>
              <Text strong style={{ fontSize: 13 }}>{diagnosticRuleLabels[code] || code}</Text>
              <Switch
                size="small"
                aria-label={`${diagnosticRuleLabels[code] || code}启用状态`}
                checked={setting.enabled}
                checkedChildren="开"
                unCheckedChildren="关"
                onChange={(enabled) => setRuleSettings((current) => ({
                  ...current,
                  rules: { ...current.rules, [code]: { ...current.rules[code], enabled } },
                }))}
              />
              <Select size="small" aria-label={`${diagnosticRuleLabels[code] || code}优先级模式`} value={setting.priority_mode === "fixed" ? "fixed" : "dynamic"} options={[{ value: "dynamic", label: "动态计算" }, { value: "fixed", label: "固定级别" }]} onChange={(value) => setRuleSettings((current) => ({ ...current, rules: { ...current.rules, [code]: { ...current.rules[code], priority_mode: value as "dynamic" | "fixed" } } }))} />
              <Select size="small" aria-label={`${diagnosticRuleLabels[code] || code}固定优先级`} disabled={setting.priority_mode !== "fixed"} value={setting.priority} options={priorityOptions} onChange={(value) => setRuleSettings((current) => ({ ...current, rules: { ...current.rules, [code]: { ...current.rules[code], priority: value as Priority } } }))} />
              <Text type="secondary" style={{ fontSize: 12 }}>{diagnosticRuleDescriptions[code] || "根据当前数据判断是否需要关注"}</Text>
              </div>
              {setting.priority_mode !== "fixed" ? (
                <div style={{ marginTop: 10, marginLeft: "calc(min(150px, 18vw) + 12px)", display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {(["p0", "p1", "p2", "p3"] as Priority[]).map((priorityKey) => {
                    const clauses = ruleSettings.priority_thresholds?.[code]?.[priorityKey] || {};
                    const entries = Object.entries(clauses);
                    if (!entries.length) return null;
                    return <div key={priorityKey} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 8px", border: "1px solid var(--ops-border)", borderRadius: 6 }}><Tag color={priorityMeta[priorityKey].color}>{priorityKey.toUpperCase()}</Tag>{entries.map(([metric, threshold]) => <InputNumber key={metric} size="small" min={0} precision={1} value={threshold} addonBefore={priorityMetricLabels[metric]?.label || metric} addonAfter={priorityMetricLabels[metric]?.unit || ""} style={{ width: 175 }} aria-label={`${diagnosticRuleLabels[code] || code}${priorityKey}${priorityMetricLabels[metric]?.label || metric}`} onChange={(value) => { if (value === null) return; setRuleSettings((current) => ({ ...current, priority_thresholds: { ...current.priority_thresholds, [code]: { ...current.priority_thresholds?.[code], [priorityKey]: { ...current.priority_thresholds?.[code]?.[priorityKey], [metric]: Number(value) } } } })); }} />)}</div>;
                  })}
                </div>
              ) : null}
            </div>
          ))}
        </div>

        <Divider titlePlacement="start" style={{ margin: "20px 0 12px" }}>关键样本门槛</Divider>
        <Row gutter={[12, 12]}>
          {diagnosticThresholdFields.map((field) => (
            <Col xs={24} sm={12} key={field.key}>
              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                <Text type="secondary" style={{ fontSize: 12 }}>{field.label}</Text>
                <InputNumber
                  aria-label={field.label}
                  min={0}
                  precision={field.unit === "%" ? 1 : 0}
                  addonAfter={field.unit}
                  value={ruleSettings.thresholds[field.key]}
                  style={{ width: "100%" }}
                  onChange={(value) => {
                    if (value === null) return;
                    setRuleSettings((current) => ({
                      ...current,
                      thresholds: { ...current.thresholds, [field.key]: Number(value) },
                    }));
                  }}
                />
              </Space>
            </Col>
          ))}
        </Row>
      </Modal>
    </WorkspacePage>
  );
}
