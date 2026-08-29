import { CheckCircleOutlined, EditOutlined, ExperimentOutlined, FileImageOutlined, FileTextOutlined, PlusOutlined, RobotOutlined, SafetyCertificateOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Input, InputNumber, Modal, Progress, Row, Segmented, Select, Space, Statistic, Table, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/ui/page-header";
import { DecisionBand, MetricRail, WorkspacePage } from "../components/ui/workspace-template";
import { fmtMoney } from "../components/promotions/promotions-ui";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";
import type { PromoPlan } from "../types";

const { Paragraph, Text } = Typography;

type DecisionPlanStatus = "needs_decision" | "observe" | "insufficient";
type DecisionPlanFilter = "all" | DecisionPlanStatus;

const decisionPlanFilterMeta: Record<DecisionPlanStatus, { label: string; color: string }> = {
  needs_decision: { label: "待处理", color: "red" },
  observe: { label: "正常观察", color: "green" },
  insufficient: { label: "证据不足", color: "orange" },
};

function decisionPlanStatus(plan: PromoPlan, diagnosticStatuses: Record<number, DecisionPlanStatus>): DecisionPlanStatus {
  return diagnosticStatuses[plan.id] || "observe";
}

function matchesDecisionPlanFilter(plan: PromoPlan, filter: DecisionPlanFilter, diagnosticStatuses: Record<number, DecisionPlanStatus>): boolean {
  if (filter === "all") return true;
  return decisionPlanStatus(plan, diagnosticStatuses) === filter;
}

function WorkflowList<T>({ dataSource, renderItem }: { dataSource: T[]; renderItem: (item: T, index: number) => ReactNode }) {
  return (
    <Space orientation="vertical" size={0} style={{ width: "100%" }}>
      {dataSource.map((item, index) => (
        <div key={index}>{renderItem(item, index)}</div>
      ))}
    </Space>
  );
}

function WorkflowListItem({ actions, children, actionsPlacement = "bottom", className = "" }: { actions?: ReactNode[]; children: ReactNode; actionsPlacement?: "bottom" | "side"; className?: string }) {
  const visibleActions = (actions || []).filter(Boolean);
  return (
    <div className={`ops-workflow-item ${className}`.trim()} style={{ padding: "14px 0", borderBottom: "1px solid var(--ops-border)" }}>
      <div className={actionsPlacement === "side" ? "ops-workflow-item__layout ops-workflow-item__layout--side" : "ops-workflow-item__layout"}>
        <div>{children}</div>
        {visibleActions.length ? (
          <Space wrap size={6} orientation={actionsPlacement === "side" ? "vertical" : "horizontal"} style={actionsPlacement === "side" ? { width: "100%", alignItems: "stretch" } : { marginTop: 10 }}>
            {visibleActions}
          </Space>
        ) : null}
      </div>
    </div>
  );
}

function WorkflowListMeta({ title, description }: { title: ReactNode; description?: ReactNode }) {
  return (
    <div>
      <div>{title}</div>
      {description ? <div style={{ marginTop: 5 }}>{description}</div> : null}
    </div>
  );
}

type WorkflowSection = "decision" | "validation" | "strategies";
type DecisionView = "workspace" | "attribution" | "archive";
type ActionRecord = {
  id: number;
  plan_id: number;
  plan_name?: string;
  campaign_id?: string;
  scene_name?: string;
  action_type: string;
  description: string;
  before_spend: number;
  before_sales: number;
  before_roi: number;
  after_value?: number | null;
  expected: string;
  observation_hours: number;
  status: "planned" | "observing" | "success" | "partial" | "failed" | "insufficient";
  result: string;
  executed_at?: string | null;
  created_at?: string | null;
  observation_due_at?: string | null;
  after_spend?: number;
  after_sales?: number;
  after_roi?: number;
  data_quality?: string;
  verified_at?: string | null;
  decision_id?: string | null;
  strategy_id?: number | null;
  success_criteria?: Record<string, number>;
  interference_notes?: string;
  manual_conclusion?: string;
  rollback_condition?: string;
  confidence?: "high" | "medium" | "low" | "";
  baseline_days?: number;
  after_days?: number;
  metric_summary?: {
    before_daily_spend?: number;
    before_daily_sales?: number;
    after_daily_spend?: number;
    after_daily_sales?: number;
    roi_change?: number;
    spend_change_pct?: number | null;
    sales_change_pct?: number | null;
  };
  lifecycle_status?: "active" | "voided" | "archived";
  lifecycle_reason?: string;
  lifecycle_updated_at?: string | null;
};

type VerificationStats = {
  actions: number;
  verified: number;
  conclusive: number;
  success: number;
  partial: number;
  failed: number;
  insufficient: number;
  reliable: number;
  success_rate: number;
  reliable_rate: number;
  avg_roi_change: number | null;
  avg_sales_change_pct: number | null;
  avg_spend_change_pct: number | null;
};

type VerificationGroup = VerificationStats & { name: string };

type VerificationSummary = {
  totals: VerificationStats;
  outcomes: { key: ActionRecord["status"]; name: string; count: number }[];
  confidence: { key: "high" | "medium" | "low"; name: string; count: number }[];
  action_types: VerificationGroup[];
  scenes: VerificationGroup[];
  plans: VerificationGroup[];
  focuses: { name: string; count: number }[];
  review_items: Pick<ActionRecord, "id" | "plan_name" | "scene_name" | "action_type" | "status" | "confidence" | "result" | "interference_notes" | "manual_conclusion" | "verified_at">[];
  generated_at: string;
};

type DecisionDraft = {
  plan_id: number;
  store_id?: number;
  campaign_id?: string;
  plan_name: string;
  scene_name: string;
  action_type: string;
  priority: "urgent" | "growth" | "efficiency";
  priority_label: string;
  field: "day_budget" | "bid_value";
  change_pct: number;
  old_value: number;
  new_value: number;
  reason: string;
  expected: string;
  observation_hours: number;
  risk: string;
  rollback_condition: string;
  success_criteria: Record<string, number>;
  tier: "conservative" | "balanced" | "aggressive";
  tier_label: string;
  recommended_tier: "conservative" | "balanced" | "aggressive";
  options: DecisionOption[];
  strategy_id?: number | null;
  strategy_name?: string | null;
  strategy_outcome?: string | null;
  strategy_source_type?: "verified" | "manual" | null;
  strategy_verification_status?: "verified" | "pending" | null;
  strategy_score?: number | null;
  learning_weight?: number;
  learning_sample_count?: number;
  learning_explanation?: string;
  strategy_candidates?: DecisionStrategy[];
  strategy_conflict?: boolean;
  conflict_reason?: string;
  constraint_summary?: string;
  channel?: "whole_site" | "search" | "audience" | "content" | "other";
  channel_name?: string;
  confidence?: "high" | "medium" | "low";
  confidence_reason?: string;
  sample_count?: number;
  evidence_items?: string[];
  risk_boundary?: string;
  not_recommended_reason?: string;
  minimum_sample_count?: number;
  minimum_evidence_score?: number;
  sample_adequate?: boolean;
  historical_validation_weight?: number;
  max_change_pct?: number;
  target_conflicts?: string[];
  actionable?: boolean;
  operating_explanation?: {
    why_recommended: string;
    why_not_operate: string;
    safe_range: string;
    worst_case: string;
    review_timing: string;
    missing_data: string[];
    recovery_action: string;
  };
  decision_mode?: "intervene" | "observe" | "insufficient";
  ai_decision?: "建议干预" | "建议观察" | "证据不足";
  primary_cause?: string;
  affected_stage?: string;
  diagnostic_rule?: string;
  diagnostic_title?: string;
  diagnostic_confidence?: "high" | "medium" | "low";
  decision_confidence?: "high" | "medium" | "low";
  decision_evidence?: string[];
  missing_data?: string[];
  ai_success_criteria_text?: string[];
  next_step?: string;
  guardrail_reasons?: string[];
};
type DecisionPrediction = { basis: string; spend_low: number; spend_high: number; sales_low: number; sales_high: number; roi_low: number; roi_high: number };
type DecisionOption = {
  tier: "conservative" | "balanced" | "aggressive";
  tier_label: string;
  recommended: boolean;
  field: "day_budget" | "bid_value";
  change_pct: number;
  old_value: number;
  new_value: number;
  expected: string;
  observation_hours: number;
  risk: string;
  rollback_condition: string;
  success_criteria: Record<string, number>;
  evidence_summary: string;
  prediction?: DecisionPrediction;
  max_change_pct?: number;
  within_boundary?: boolean;
};
type DecisionStrategy = {
  id: number;
  name: string;
  action_type: string;
  conditions: string;
  evidence: string;
  success_count: number;
  use_count?: number;
  outcome?: string;
  evidence_score?: number;
  evidence_level?: "high" | "medium" | "low";
  sample_count?: number;
  group_success_rate?: number;
  learning_weight?: number;
  learning_sample_count?: number;
  learning_explanation?: string;
  learned_score?: number;
  source_type?: "verified" | "manual";
  verification_status?: "verified" | "pending";
};
type StrategyGroup = {
  group_id: string;
  action_type: string;
  scene: string;
  sample_count: number;
  success_count: number;
  partial_count: number;
  failed_count: number;
  success_rate: number;
  avg_evidence_score: number;
};
type DecisionReply = {
  sections?: Record<string, string | string[]>;
  reply?: string;
  decision_id?: string;
  drafts?: DecisionDraft[];
  strategies?: DecisionStrategy[];
  strategy_groups?: StrategyGroup[];
  source_context?: { store_id?: number | null; channel?: string; plan_id?: number | null; diagnostic_id?: string; diagnostic?: string; rule?: string; evidence?: unknown[] };
  recovery?: { can_retry: boolean; action: string };
  decision_engine?: { version: string; data_scope: string; model_judgment_count: number; guardrail: string };
};
type DiagnosticIndexItem = { plan_id: number; signal_type: "risk" | "opportunity" | "observation"; rule_code: string };
type DiagnosticIndexResponse = { items: DiagnosticIndexItem[] };
type DecisionRecord = {
  id: number;
  decision_id: string;
  plan_id: number;
  plan_name?: string;
  scene_name?: string;
  strategy_id?: number | null;
  recommended_tier: DecisionOption["tier"];
  selected_tier: DecisionOption["tier"];
  feedback_status: "adopted" | "modified" | "rejected" | "insufficient";
  workflow_status: "selected" | "rejected" | "deferred" | "planned" | "executed" | "verified";
  ai_field: string;
  ai_change_pct: number;
  final_field: string;
  final_change_pct: number;
  ai_success_criteria: Record<string, number>;
  final_success_criteria: Record<string, number>;
  ai_observation_hours: number;
  final_observation_hours: number;
  rollback_condition: string;
  feedback_reason: string;
  feedback_note: string;
  action_record_id?: number | null;
  result_status?: ActionRecord["status"] | "";
  result_summary?: string;
  created_at: string;
  updated_at: string;
};
type DecisionArchiveData = {
  items: DecisionRecord[];
  summary: {
    total: number;
    adopted: number;
    modified: number;
    rejected: number;
    insufficient: number;
    executed: number;
    verified: number;
  };
  tiers: {
    tier: DecisionOption["tier"];
    name: string;
    selected: number;
    executed: number;
    verified: number;
    success: number;
    partial: number;
    failed: number;
    insufficient: number;
    success_rate: number;
  }[];
  attribution: {
    summary: {
      manual_intervention: number;
      manual_intervention_rate: number;
      insufficient: number;
      tier_changed: number;
      same_tier_adjustment: number;
      reason_coverage: number;
    };
    reasons: { reason: string; count: number; share: number }[];
    directions: {
      key: "more_conservative" | "same_tier_adjustment" | "more_aggressive";
      name: string;
      count: number;
    }[];
    transitions: {
      recommended_tier: DecisionOption["tier"];
      selected_tier: DecisionOption["tier"];
      count: number;
    }[];
    scenes: {
      scene_name: string;
      total: number;
      adopted: number;
      modified: number;
      rejected: number;
      insufficient: number;
      manual_intervention_rate: number;
      verified: number;
      success_rate: number;
    }[];
  };
};

const statusMeta: Record<ActionRecord["status"], { label: string; color: string }> = {
  planned: { label: "待执行", color: "default" },
  observing: { label: "观察中", color: "blue" },
  success: { label: "改善", color: "green" },
  partial: { label: "部分改善", color: "gold" },
  failed: { label: "恶化", color: "red" },
  insufficient: { label: "数据不足", color: "default" },
};

const lifecycleMeta: Record<NonNullable<ActionRecord["lifecycle_status"]>, { label: string; color: string }> = {
  active: { label: "有效", color: "green" },
  voided: { label: "已作废", color: "default" },
  archived: { label: "已归档", color: "blue" },
};
const confidenceMeta = {
  high: { label: "高可信", color: "green" },
  medium: { label: "中可信", color: "orange" },
  low: { label: "低可信", color: "red" },
};
const decisionTierMeta: Record<DecisionOption["tier"], { label: string; color: string }> = {
  conservative: { label: "稳健", color: "green" },
  balanced: { label: "平衡", color: "blue" },
  aggressive: { label: "激进", color: "red" },
};
const decisionFeedbackMeta: Record<DecisionRecord["feedback_status"], { label: string; color: string }> = {
  adopted: { label: "采纳", color: "green" },
  modified: { label: "修改", color: "blue" },
      rejected: { label: "拒绝", color: "red" },
      insufficient: { label: "暂不调整", color: "default" },
};
const decisionWorkflowMeta: Record<DecisionRecord["workflow_status"], { label: string; color: string }> = {
  selected: { label: "已选择", color: "cyan" },
  rejected: { label: "已拒绝", color: "default" },
  deferred: { label: "暂缓观察", color: "default" },
  planned: { label: "待执行", color: "default" },
  executed: { label: "观察中", color: "blue" },
  verified: { label: "已验证", color: "green" },
};
const decisionViewOptions = [
  { label: "决策工作区", value: "workspace" },
  { label: "决策归因", value: "attribution" },
  { label: "决策档案", value: "archive" },
];

const aiSectionLabels: Record<string, string> = {
  overall: "总体判断",
  highlights: "关键发现",
  conversion: "转化表现",
  promo: "推广表现",
  risks: "风险提示",
  suggestions: "后续建议",
};

function hasAiSectionContent(value: string | string[]): boolean {
  return (Array.isArray(value) ? value : [value]).some((item) => String(item || "").trim());
}

function successCriteriaText(criteria: Record<string, number>): string {
  const labels: Record<string, string> = {
    target_roi_min: "最终 ROI≥",
    roi_change_min: "ROI 提升≥",
    sales_change_pct_min: "日均成交变化≥",
    spend_change_pct_max: "日均花费变化≤",
  };
  return Object.entries(criteria)
    .map(([key, value]) => `${labels[key] || key}${value}${key.includes("pct") ? "%" : ""}`)
    .join("；");
}

function formatDate(value?: string | null): string {
  if (!value) return "—";
  return value.replace("T", " ").slice(0, 16);
}

function isVerificationDue(item: ActionRecord): boolean {
  if (item.status !== "observing") return false;
  if (!item.observation_due_at) return true;
  return new Date(item.observation_due_at).getTime() <= Date.now();
}

function formatDelta(value: number | null | undefined, suffix = ""): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value}${suffix}`;
}

function observationCheckpoint(item: ActionRecord): { label: string; color: string; hint: string } {
  const hours = item.executed_at ? Math.max(0, (Date.now() - new Date(item.executed_at).getTime()) / 3_600_000) : 0;
  if (hours >= 168) return { label: "7 天复盘", color: "purple", hint: "判断是否沉淀为可复用经验" };
  if (hours >= 48 || item.observation_hours <= 48 && isVerificationDue(item)) return { label: "48h 验证", color: "orange", hint: "形成改善、恶化或无法判断结论" };
  if (hours >= 24) return { label: "24h 检查", color: "blue", hint: "先排除数据延迟和短期波动" };
  return { label: "等待 24h", color: "default", hint: "保持单一变量，避免连续调整" };
}

function verificationDirection(item: ActionRecord): { label: string; color: string } | null {
  if (item.status === "success" || item.status === "partial") return { label: item.status === "success" ? "改善" : "部分改善", color: item.status === "success" ? "green" : "orange" };
  if (item.status === "failed") return { label: "恶化", color: "red" };
  if (item.status === "insufficient") return { label: "数据不足", color: "default" };
  return null;
}

export function PromotionsWorkflowPage({ section }: { section: WorkflowSection }) {
  if (section === "decision") return <DecisionPage />;
  if (section === "validation") return <ValidationPage />;
  return <StrategiesPage />;
}

function DecisionPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { currentStore } = useStores();
  const targetPlanId = Number(searchParams.get("plan_id")) || null;
  const sourceStoreId = Number(searchParams.get("store_id")) || currentStore?.id || null;
  const sourceChannel = searchParams.get("channel") || "";
  const sourceDiagnosticId = searchParams.get("diagnostic_id") || "";
  const sourceDiagnostic = searchParams.get("diagnostic") || "";
  const sourceRule = searchParams.get("rule") || sourceDiagnostic;
  const targetDecisionRecordId = Number(searchParams.get("decision_record_id")) || null;
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [diagnosticStatuses, setDiagnosticStatuses] = useState<Record<number, DecisionPlanStatus>>({});
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiReply, setAiReply] = useState<DecisionReply | null>(null);
  const [selectedStrategies, setSelectedStrategies] = useState<Record<number, number | undefined>>({});
  const [selectedOptions, setSelectedOptions] = useState<Record<number, DecisionOption["tier"]>>({});
  const [view, setView] = useState<DecisionView>("workspace");
  const [archive, setArchive] = useState<DecisionArchiveData | null>(null);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [savingDecisionId, setSavingDecisionId] = useState<number | null>(null);
  const [rejectDraft, setRejectDraft] = useState<DecisionDraft | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectNote, setRejectNote] = useState("");
  const [planFilter, setPlanFilter] = useState<DecisionPlanFilter>(targetPlanId ? "all" : "needs_decision");
  const decisionPlanListRef = useRef<HTMLDivElement>(null);
  const autoGenerateRef = useRef(false);

  useEffect(() => {
    setPlanFilter(targetPlanId ? "all" : "needs_decision");
    autoGenerateRef.current = false;
  }, [targetPlanId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const decisionMode = targetPlanId ? "realtime" : "7d";
      const planQuery = `/promotions/plans?mode=${decisionMode}${sourceStoreId ? `&store_id=${sourceStoreId}` : ""}${sourceChannel ? `&channel=${encodeURIComponent(sourceChannel)}` : ""}`;
      const diagnosticQuery = {
        ...(sourceStoreId ? { store_id: sourceStoreId } : {}),
        ...(sourceChannel ? { channel: sourceChannel } : {}),
      };
      const [plansResponse, diagnosticsResponse] = await Promise.all([
        http.get<{ items: PromoPlan[] }>(planQuery),
        http.get<DiagnosticIndexResponse>("/promotions/diagnostics", { params: diagnosticQuery }),
      ]);
      const nextPlans = plansResponse.data.items || [];
      const findingsByPlan = new Map<number, DiagnosticIndexItem[]>();
      for (const finding of diagnosticsResponse.data.items || []) {
        const findings = findingsByPlan.get(finding.plan_id) || [];
        findings.push(finding);
        findingsByPlan.set(finding.plan_id, findings);
      }
      const nextStatuses: Record<number, DecisionPlanStatus> = {};
      for (const plan of nextPlans) {
        if (plan.status !== "在投") continue;
        const findings = findingsByPlan.get(plan.id) || [];
        if (findings.some((finding) => finding.signal_type === "risk")) {
          nextStatuses[plan.id] = "needs_decision";
        } else if (findings.some((finding) => ["data_stale", "no_spend", "low_spend"].includes(finding.rule_code))) {
          nextStatuses[plan.id] = "insufficient";
        } else {
          nextStatuses[plan.id] = "observe";
        }
      }
      setPlans(nextPlans);
      setDiagnosticStatuses(nextStatuses);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [sourceChannel, sourceStoreId, targetPlanId]);

  useEffect(() => {
    void load();
  }, [load]);

  const loadArchive = useCallback(async () => {
    setArchiveLoading(true);
    try {
      const response = await http.get<DecisionArchiveData>(`/promotions/decision-records${currentStore ? `?store_id=${currentStore.id}` : ""}`);
      setArchive(response.data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setArchiveLoading(false);
    }
  }, [currentStore?.id]);

  useEffect(() => {
    if (targetDecisionRecordId) setView("archive");
  }, [targetDecisionRecordId]);

  useEffect(() => {
    if (view !== "workspace") void loadArchive();
  }, [loadArchive, view]);

  const runAi = async () => {
    if (!targetPlanId && decisionCounts.needs_decision === 0) {
      message.info("当前没有需要决策的计划，正常计划保持观察即可");
      return;
    }
    setAiLoading(true);
    try {
      const params = new URLSearchParams({ mode: "realtime" });
      if (sourceStoreId) params.set("store_id", String(sourceStoreId));
      if (sourceChannel) params.set("channel", sourceChannel);
      if (targetPlanId) params.set("plan_id", String(targetPlanId));
      if (sourceDiagnosticId) params.set("diagnostic_id", sourceDiagnosticId);
      if (sourceDiagnostic) params.set("diagnostic", sourceDiagnostic);
      if (sourceRule) params.set("rule", sourceRule);
      const response = await http.post<DecisionReply>(`/promotions/insight?${params.toString()}`);
      setAiReply(response.data);
      setSelectedOptions(Object.fromEntries((response.data.drafts || []).map((draft) => [draft.plan_id, draft.recommended_tier])));
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiLoading(false);
    }
  };

  const saveDecisionFeedback = async (draft: DecisionDraft, selectedOption: DecisionOption, feedbackStatus: DecisionRecord["feedback_status"], feedbackReason = "", feedbackNote = ""): Promise<number> => {
    if (!aiReply?.decision_id) throw new Error("本次 AI 决策缺少批次 ID，请重新生成方案");
    const recommendedOption = draft.options.find((option) => option.tier === draft.recommended_tier);
    if (!recommendedOption) throw new Error("AI 推荐档位数据不完整，请重新生成方案");
    const strategyId = selectedStrategies[draft.plan_id] ?? draft.strategy_id ?? undefined;
    const response = await http.post<{ id: number }>("/promotions/decision-records", {
      decision_id: aiReply.decision_id,
      plan_id: draft.plan_id,
      strategy_id: strategyId,
      recommended_tier: draft.recommended_tier,
      selected_tier: selectedOption.tier,
      feedback_status: feedbackStatus,
      ai_field: recommendedOption.field,
      ai_change_pct: recommendedOption.change_pct,
      final_field: selectedOption.field,
      final_change_pct: selectedOption.change_pct,
      ai_success_criteria: recommendedOption.success_criteria,
      final_success_criteria: selectedOption.success_criteria,
      ai_observation_hours: recommendedOption.observation_hours,
      final_observation_hours: selectedOption.observation_hours,
      rollback_condition: selectedOption.rollback_condition,
      feedback_reason: feedbackReason,
      feedback_note: feedbackNote,
    });
    return response.data.id;
  };

  const openExecutionPreview = async (draft: DecisionDraft, selectedOption: DecisionOption) => {
    if (draft.actionable === false) {
      message.warning(draft.not_recommended_reason || "当前证据不足，不建议调整");
      return;
    }
    if (selectedOption.within_boundary === false) {
      message.warning(`所选方案超过最大调整幅度 ${selectedOption.max_change_pct ?? draft.max_change_pct ?? 0}%，请改选较稳健方案`);
      return;
    }
    setSavingDecisionId(draft.plan_id);
    try {
      const feedbackStatus = selectedOption.tier === draft.recommended_tier ? "adopted" : "modified";
      const decisionRecordId = await saveDecisionFeedback(draft, selectedOption, feedbackStatus);
      const selectedStrategyId = selectedStrategies[draft.plan_id] ?? draft.strategy_id ?? undefined;
      const params = new URLSearchParams({
        plan_id: String(draft.plan_id),
        ...(draft.store_id ? { store_id: String(draft.store_id) } : {}),
        ...(draft.channel ? { channel: draft.channel } : sourceChannel ? { channel: sourceChannel } : {}),
        ...(sourceDiagnosticId ? { diagnostic_id: sourceDiagnosticId } : {}),
        ...(sourceDiagnostic ? { diagnostic: sourceDiagnostic } : {}),
        ...(sourceRule ? { rule: sourceRule } : {}),
        ...(selectedOption.evidence_summary ? { evidence: selectedOption.evidence_summary } : {}),
        draft_field: selectedOption.field,
        draft_pct: String(selectedOption.change_pct),
        decision_id: aiReply?.decision_id || "",
        decision_record_id: String(decisionRecordId),
        ...(selectedStrategyId ? { strategy_id: String(selectedStrategyId) } : {}),
        draft_reason: `${draft.reason}；选择${selectedOption.tier_label}方案`,
        draft_expected: selectedOption.expected,
        draft_observation_hours: String(selectedOption.observation_hours),
        draft_success_criteria: JSON.stringify(selectedOption.success_criteria),
        draft_rollback_condition: selectedOption.rollback_condition,
        draft_tier: selectedOption.tier,
      });
      navigate(`/promotions/plans?${params.toString()}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : getApiErrorMessage(error));
    } finally {
      setSavingDecisionId(null);
    }
  };

  const rejectDecision = async () => {
    if (!rejectDraft || !rejectReason) return;
    const selectedTier = selectedOptions[rejectDraft.plan_id] || rejectDraft.recommended_tier;
    const selectedOption = rejectDraft.options.find((option) => option.tier === selectedTier) || rejectDraft.options[0];
    setSavingDecisionId(rejectDraft.plan_id);
    try {
      await saveDecisionFeedback(rejectDraft, selectedOption, "rejected", rejectReason, rejectNote);
      message.success("已记录拒绝原因，后续会纳入决策复盘");
      setRejectDraft(null);
      setRejectReason("");
      setRejectNote("");
    } catch (error) {
      message.error(error instanceof Error ? error.message : getApiErrorMessage(error));
    } finally {
      setSavingDecisionId(null);
    }
  };

  const deferDecision = async (draft: DecisionDraft) => {
    const selectedTier = selectedOptions[draft.plan_id] || draft.recommended_tier;
    const selectedOption = draft.options.find((option) => option.tier === selectedTier) || draft.options[0];
    if (!selectedOption) {
      message.error("当前方案缺少可记录的档位，请重新生成方案");
      return;
    }
    setSavingDecisionId(draft.plan_id);
    try {
      await saveDecisionFeedback(
        draft,
        selectedOption,
        "insufficient",
        "",
        draft.not_recommended_reason || "证据不足，暂不调整",
      );
      message.success("已记录为暂不调整，补齐数据后可重新评估");
    } catch (error) {
      message.error(error instanceof Error ? error.message : getApiErrorMessage(error));
    } finally {
      setSavingDecisionId(null);
    }
  };

  const activePlans = useMemo(() => plans.filter((plan) => plan.status === "在投"), [plans]);
  const focusedActivePlans = targetPlanId ? activePlans.filter((plan) => plan.id === targetPlanId) : activePlans;
  const visibleActivePlans = useMemo(
    () => focusedActivePlans.filter((plan) => matchesDecisionPlanFilter(plan, planFilter, diagnosticStatuses)),
    [diagnosticStatuses, focusedActivePlans, planFilter],
  );
  const focusedDrafts = targetPlanId ? (aiReply?.drafts || []).filter((draft) => draft.plan_id === targetPlanId) : aiReply?.drafts || [];
  const focusedArchiveItems = targetDecisionRecordId ? (archive?.items || []).filter((item) => item.id === targetDecisionRecordId) : archive?.items || [];
  const decisionCounts = useMemo(
    () => ({
      needs_decision: activePlans.filter((plan) => decisionPlanStatus(plan, diagnosticStatuses) === "needs_decision").length,
      observe: activePlans.filter((plan) => decisionPlanStatus(plan, diagnosticStatuses) === "observe").length,
      insufficient: activePlans.filter((plan) => decisionPlanStatus(plan, diagnosticStatuses) === "insufficient").length,
    }),
    [activePlans, diagnosticStatuses],
  );
  const decisionFocusFilter: DecisionPlanFilter = decisionCounts.needs_decision ? "needs_decision" : decisionCounts.observe ? "observe" : decisionCounts.insufficient ? "insufficient" : "all";
  const focusPlanFilter = (filter: DecisionPlanFilter) => {
    setPlanFilter(filter);
    decisionPlanListRef.current?.scrollIntoView({ block: "start" });
  };
  const focusDecisionPlans = () => {
    focusPlanFilter(decisionFocusFilter);
  };

  useEffect(() => {
    if (searchParams.get("auto_generate") !== "1" || !targetPlanId || loading || aiLoading || aiReply || focusedActivePlans.length === 0 || autoGenerateRef.current) return;
    autoGenerateRef.current = true;
    const next = new URLSearchParams(searchParams);
    next.delete("auto_generate");
    setSearchParams(next, { replace: true });
    void runAi();
  }, [aiLoading, aiReply, focusedActivePlans.length, loading, searchParams, setSearchParams, targetPlanId]);

  const archiveSummary = archive?.summary || {
    total: 0,
    adopted: 0,
    modified: 0,
    rejected: 0,
    insufficient: 0,
    executed: 0,
    verified: 0,
  };
  const attribution = archive?.attribution || {
    summary: {
      manual_intervention: 0,
      manual_intervention_rate: 0,
      insufficient: 0,
      tier_changed: 0,
      same_tier_adjustment: 0,
      reason_coverage: 0,
    },
    reasons: [],
    directions: [],
    transitions: [],
    scenes: [],
  };

  if (view === "attribution") {
    return (
      <WorkspacePage kind="analysis">
        <PageHeader
          icon={<ExperimentOutlined />}
          eyebrow="推广管理"
          title="AI 决策归因"
          description="分析运营人员为什么修改或拒绝 AI 方案，识别档位偏差、业务约束与高干预场景。"
          extra={
            <Space wrap>
              <Segmented value={view} onChange={(value) => setView(value as DecisionView)} options={decisionViewOptions} />
              <Button loading={archiveLoading} onClick={() => void loadArchive()}>
                刷新归因
              </Button>
            </Space>
          }
        />
        <Alert type="info" showIcon title="归因结果用于校正建议，不会直接改变投放计划" description="建议累计足够的人工反馈和验证样本后，再把归因结果用于自动调整策略权重；‘暂不调整’会单独统计，不会被当成拒绝。" style={{ marginBottom: 16 }} />
        <Row gutter={[12, 12]}>
          {[
            {
              label: "人工干预",
              value: attribution.summary.manual_intervention,
              suffix: "次",
            },
            {
              label: "人工干预率",
              value: attribution.summary.manual_intervention_rate,
              suffix: "%",
            },
            {
              label: "暂不调整",
              value: attribution.summary.insufficient,
              suffix: "次",
            },
            {
              label: "跨档修改",
              value: attribution.summary.tier_changed,
              suffix: "次",
            },
            {
              label: "拒绝原因覆盖",
              value: attribution.summary.reason_coverage,
              suffix: "%",
            },
          ].map((item) => (
            <Col xs={12} sm={6} key={item.label}>
              <Card variant="borderless">
                <Statistic title={item.label} value={item.value} suffix={item.suffix} />
              </Card>
            </Col>
          ))}
        </Row>
        <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={12}>
            <Card variant="borderless" title="拒绝原因与业务约束" loading={archiveLoading} style={{ height: "100%" }}>
              {!archiveLoading && attribution.reasons.length === 0 ? (
                <Empty description="暂无拒绝反馈">
                  <Button type="primary" onClick={() => setView("workspace")}>
                    返回决策工作区
                  </Button>
                </Empty>
              ) : (
                <Table
                  rowKey="reason"
                  size="small"
                  pagination={false}
                  dataSource={attribution.reasons}
                  columns={[
                    { title: "原因", dataIndex: "reason", key: "reason" },
                    {
                      title: "次数",
                      dataIndex: "count",
                      key: "count",
                      width: 72,
                    },
                    {
                      title: "占拒绝方案",
                      key: "share",
                      width: 150,
                      render: (_: unknown, item: DecisionArchiveData["attribution"]["reasons"][number]) => <Progress percent={item.share} size="small" />,
                    },
                  ]}
                />
              )}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card variant="borderless" title="人工修改方向" loading={archiveLoading} style={{ height: "100%" }}>
              {!archiveLoading && archiveSummary.modified === 0 ? (
                <Empty description="暂无人工修改记录">
                  <Button type="primary" onClick={() => setView("workspace")}>
                    返回决策工作区
                  </Button>
                </Empty>
              ) : (
                <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                  <Table
                    rowKey="key"
                    size="small"
                    pagination={false}
                    dataSource={attribution.directions}
                    columns={[
                      { title: "调整方向", dataIndex: "name", key: "name" },
                      {
                        title: "次数",
                        dataIndex: "count",
                        key: "count",
                        width: 72,
                      },
                      {
                        title: "占修改方案",
                        key: "share",
                        width: 150,
                        render: (_: unknown, item: DecisionArchiveData["attribution"]["directions"][number]) => <Progress percent={archiveSummary.modified ? Number(((item.count / archiveSummary.modified) * 100).toFixed(1)) : 0} size="small" />,
                      },
                    ]}
                  />
                  {attribution.transitions.length ? (
                    <Space wrap>
                      <Text type="secondary">档位迁移：</Text>
                      {attribution.transitions.map((item) => (
                        <Tag key={`${item.recommended_tier}-${item.selected_tier}`}>
                          {decisionTierMeta[item.recommended_tier].label} → {decisionTierMeta[item.selected_tier].label} · {item.count}
                        </Tag>
                      ))}
                    </Space>
                  ) : null}
                </Space>
              )}
            </Card>
          </Col>
        </Row>
        <Card variant="borderless" title="场景人工干预分析" style={{ marginTop: 16 }} loading={archiveLoading}>
          {!archiveLoading && attribution.scenes.length === 0 ? (
            <Empty description="暂无可分析的决策样本">
              <Button type="primary" onClick={() => setView("workspace")}>
                生成并处理决策方案
              </Button>
            </Empty>
          ) : (
            <Table<DecisionArchiveData["attribution"]["scenes"][number]>
              rowKey="scene_name"
              size="small"
              pagination={false}
              scroll={{ x: 850 }}
              dataSource={attribution.scenes}
              columns={[
                {
                  title: "推广场景",
                  dataIndex: "scene_name",
                  key: "scene_name",
                  width: 180,
                },
                {
                  title: "决策数",
                  dataIndex: "total",
                  key: "total",
                  width: 80,
                },
                {
                  title: "采纳",
                  dataIndex: "adopted",
                  key: "adopted",
                  width: 72,
                },
                {
                  title: "修改",
                  dataIndex: "modified",
                  key: "modified",
                  width: 72,
                },
                {
                  title: "拒绝",
                  dataIndex: "rejected",
                  key: "rejected",
                  width: 72,
                },
                {
                  title: "人工干预率",
                  key: "manual_intervention_rate",
                  width: 160,
                  render: (_: unknown, item) => <Progress percent={item.manual_intervention_rate} size="small" />,
                },
                {
                  title: "已验证",
                  dataIndex: "verified",
                  key: "verified",
                  width: 80,
                },
                {
                  title: "验证成功率",
                  key: "success_rate",
                  width: 160,
                  render: (_: unknown, item) => <Progress percent={item.success_rate} size="small" />,
                },
              ]}
            />
          )}
        </Card>
      </WorkspacePage>
    );
  }

  if (view === "archive") {
    return (
      <WorkspacePage kind="analysis">
        <PageHeader
          icon={<FileTextOutlined />}
          eyebrow="推广管理"
          title="AI 决策档案"
          description="追踪每次 AI 建议、人工选择、执行状态与最终验证结果，让后续建议有真实经验可依。"
          extra={
            <Space wrap>
              <Segmented value={view} onChange={(value) => setView(value as DecisionView)} options={decisionViewOptions} />
              <Button loading={archiveLoading} onClick={() => void loadArchive()}>
                刷新档案
              </Button>
            </Space>
          }
        />
        <Alert type="info" showIcon title="学习闭环从真实动作与验证结果中积累" description="未执行、暂不调整和被拒绝的方案都会保留；暂不调整不会计入拒绝或人工干预，只有完成验证的结果才会用于评估方案档位效果。" style={{ marginBottom: 16 }} />
        {targetDecisionRecordId && !archiveLoading && focusedArchiveItems.length === 0 ? <Alert type="error" showIcon title="目标决策记录不存在或不在当前店铺范围" style={{ marginBottom: 16 }} /> : null}
        <Row gutter={[12, 12]}>
          {[
            { label: "决策总数", value: archiveSummary.total },
            { label: "直接采纳", value: archiveSummary.adopted },
            { label: "人工修改", value: archiveSummary.modified },
            { label: "拒绝方案", value: archiveSummary.rejected },
            { label: "暂不调整", value: archiveSummary.insufficient },
            { label: "已执行", value: archiveSummary.executed },
            { label: "已验证", value: archiveSummary.verified },
          ].map((item) => (
            <Col xs={12} sm={8} lg={4} key={item.label}>
              <Card variant="borderless">
                <Statistic title={item.label} value={item.value} />
              </Card>
            </Col>
          ))}
        </Row>
        <Card variant="borderless" title="稳健 / 平衡 / 激进方案效果" style={{ marginTop: 16 }} loading={archiveLoading}>
          <Table<DecisionArchiveData["tiers"][number]>
            rowKey="tier"
            pagination={false}
            dataSource={archive?.tiers || []}
            columns={[
              {
                title: "方案",
                key: "name",
                render: (_: unknown, item) => <Tag color={decisionTierMeta[item.tier].color}>{item.name}</Tag>,
              },
              { title: "已选择", dataIndex: "selected", key: "selected" },
              { title: "已执行", dataIndex: "executed", key: "executed" },
              { title: "已验证", dataIndex: "verified", key: "verified" },
              {
                title: "成功 / 部分 / 失败",
                key: "result",
                render: (_: unknown, item) => (
                  <Space>
                    <Text type="success">{item.success}</Text>
                    <Text type="warning">{item.partial}</Text>
                    <Text type="danger">{item.failed}</Text>
                  </Space>
                ),
              },
              {
                title: "数据不足",
                dataIndex: "insufficient",
                key: "insufficient",
              },
              {
                title: "成功率",
                key: "success_rate",
                render: (_: unknown, item) => <Progress percent={item.success_rate} size="small" style={{ minWidth: 120 }} />,
              },
            ]}
          />
        </Card>
        <Card variant="borderless" title="决策时间线" style={{ marginTop: 16 }} loading={archiveLoading}>
          {!archiveLoading && !focusedArchiveItems.length ? (
            <Empty description="暂无决策档案，先在决策工作区生成并处理一批方案">
              <Button type="primary" onClick={() => setView("workspace")}>
                返回决策工作区
              </Button>
            </Empty>
          ) : (
            <WorkflowList
              dataSource={focusedArchiveItems}
              renderItem={(item) => {
                const feedback = decisionFeedbackMeta[item.feedback_status];
                const workflow = decisionWorkflowMeta[item.workflow_status];
                const result = item.result_status && item.result_status !== "planned" && item.result_status !== "observing" ? statusMeta[item.result_status] : null;
                return (
                  <WorkflowListItem>
                    <WorkflowListMeta
                      title={
                        <Space wrap>
                          <Text strong>{item.plan_name || `计划 ${item.plan_id}`}</Text>
                          <Tag>{item.scene_name || "未标注场景"}</Tag>
                          <Tag color={decisionTierMeta[item.selected_tier].color}>{decisionTierMeta[item.selected_tier].label}方案</Tag>
                          <Tag color={feedback.color}>{feedback.label}</Tag>
                          <Tag color={workflow.color}>{workflow.label}</Tag>
                          {result ? <Tag color={result.color}>{result.label}</Tag> : null}
                        </Space>
                      }
                      description={
                        <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                          <Text type="secondary">
                            AI 建议 {decisionTierMeta[item.recommended_tier].label}档 {formatDelta(item.ai_change_pct, "%")}；{item.feedback_status === "insufficient" ? "当前暂不执行，等待补齐证据" : `最终 ${decisionTierMeta[item.selected_tier].label}档 ${formatDelta(item.final_change_pct, "%")} · 观察 ${item.final_observation_hours} 小时`}
                          </Text>
                          {item.feedback_reason ? (
                            <Text>
                              拒绝原因：{item.feedback_reason}
                              {item.feedback_note ? ` · ${item.feedback_note}` : ""}
                            </Text>
                          ) : null}
                          {item.feedback_status === "insufficient" && item.feedback_note ? <Text>暂缓说明：{item.feedback_note}</Text> : null}
                          {item.result_summary ? <Text>验证结论：{item.result_summary}</Text> : null}
                          <Text type="secondary">更新于 {formatDate(item.updated_at)}</Text>
                        </Space>
                      }
                    />
                  </WorkflowListItem>
                );
              }}
            />
          )}
        </Card>
      </WorkspacePage>
    );
  }

  return (
    <WorkspacePage kind="management">
      <PageHeader
        icon={<RobotOutlined />}
        eyebrow="推广管理"
        title="AI 决策中心"
        description="用真实计划数据生成可解释的调整方案，确认后进入执行与验证。"
        extra={
          <Space wrap>
            <Segmented value={view} onChange={(value) => setView(value as DecisionView)} options={decisionViewOptions} />
            <Button onClick={() => void load()}>刷新数据</Button>
            <Button type="primary" icon={<RobotOutlined />} loading={aiLoading} disabled={!targetPlanId && decisionCounts.needs_decision === 0} onClick={() => void runAi()}>
              {targetPlanId ? "生成当前计划决策" : decisionCounts.needs_decision ? "生成待决策方案" : "当前无需决策"}
            </Button>
          </Space>
        }
      />
      <DecisionBand
        eyebrow="本轮决策重点"
        title={decisionCounts.needs_decision ? `${decisionCounts.needs_decision} 个计划需要先处理` : "当前没有待决策计划"}
        description={<>待处理来源于诊断中心：在投计划被诊断规则标记为风险异常后进入复核队列。ROI 只是诊断证据，不再单独决定状态；它不代表系统已经决定调整。</>}
        action={<Button onClick={focusDecisionPlans}>{decisionCounts.needs_decision ? "查看待决策计划" : decisionCounts.observe ? "查看正常观察" : "查看证据不足"}</Button>}
        ariaLabel="AI 决策首要结论"
      />
      {sourceDiagnosticId ? <Alert type="success" showIcon title="已带入异常诊断上下文" description={`店铺 ${sourceStoreId ?? "当前"} · 渠道 ${sourceChannel || "未指定"} · 计划 ${targetPlanId ?? "未指定"} · 规则 ${sourceRule || sourceDiagnosticId}。AI 将只聚焦当前计划，执行和验证链接会继续携带这些信息。`} style={{ marginBottom: 16 }} /> : null}
      {targetPlanId && !loading && focusedActivePlans.length === 0 ? <Alert type="error" showIcon title="目标计划不存在、不在投或不在当前店铺范围" style={{ marginBottom: 16 }} /> : null}
      <MetricRail columns={4} items={[
          { key: "active", label: "在投计划", value: activePlans.length, hint: "当前可见的在投计划", onClick: () => focusPlanFilter("all"), active: planFilter === "all", ariaLabel: "查看全部在投计划" },
          { key: "needs_decision", label: "待处理", value: decisionCounts.needs_decision, hint: "诊断标记为风险异常", onClick: () => focusPlanFilter("needs_decision"), active: planFilter === "needs_decision", ariaLabel: "筛选待处理计划" },
          { key: "observe", label: "正常观察", value: decisionCounts.observe, hint: "诊断未发现风险异常", onClick: () => focusPlanFilter("observe"), active: planFilter === "observe", ariaLabel: "筛选正常观察计划" },
          { key: "insufficient", label: "证据不足", value: decisionCounts.insufficient, hint: "诊断标记为数据不足", onClick: () => focusPlanFilter("insufficient"), active: planFilter === "insufficient", ariaLabel: "筛选证据不足计划" },
        ]} />
      {aiReply ? (
        <Card
          variant="borderless"
          title={
            <Space>
              <RobotOutlined />
              本次 AI 决策方案
            </Space>
          }
          style={{ marginTop: 16 }}
        >
          {aiReply.decision_engine ? (
            <Alert
              type="info"
              showIcon
              title="AI 判断原因，系统校验能否执行"
              description={`${aiReply.decision_engine.data_scope}。${aiReply.decision_engine.guardrail}。`}
              style={{ marginBottom: 14 }}
            />
          ) : null}
          {focusedDrafts.length ? (
            <div style={{ marginBottom: 16 }}>
              <Text strong style={{ display: "block", marginBottom: 8 }}>
                {focusedDrafts.some((draft) => draft.actionable !== false) ? "AI 判断与单变量方案（需人工确认）" : "AI 判断结果"}
              </Text>
              <WorkflowList
                dataSource={focusedDrafts}
                renderItem={(draft) => {
                  const selectedTier = selectedOptions[draft.plan_id] || draft.recommended_tier;
                  const selectedOption = draft.options.find((option) => option.tier === selectedTier) || draft.options[0];
                  return (
                    <WorkflowListItem
                      actions={[
                        <Button key="detail" size="small" onClick={() => navigate(`/promotions/plans/${draft.plan_id}`)}>
                          查看计划详情
                        </Button>,
                        <Button
                          key="reject"
                          danger
                          size="small"
                          onClick={() => {
                            setRejectDraft(draft);
                            setRejectReason("");
                            setRejectNote("");
                          }}
                        >
                          拒绝方案
                        </Button>,
                        draft.actionable === false ? (
                          <Button key="defer" type="primary" size="small" loading={savingDecisionId === draft.plan_id} onClick={() => void deferDecision(draft)}>
                            记录暂不调整
                          </Button>
                        ) : (
                          <Button key="execute" type="primary" size="small" disabled={selectedOption.within_boundary === false} loading={savingDecisionId === draft.plan_id} onClick={() => void openExecutionPreview(draft, selectedOption)}>
                            {selectedOption.within_boundary === false ? "超过安全幅度" : `确认${selectedOption.tier_label}方案，进入调整预览`}
                          </Button>
                        ),
                      ]}
                    >
                      <WorkflowListMeta
                        title={
                          <Space wrap>
                            <Text strong>{draft.plan_name}</Text>
                            <Tag color="blue">{draft.channel_name || "其他渠道"}</Tag>
                            <Tag color={draft.actionable === false ? (draft.ai_decision === "建议观察" ? "blue" : "orange") : "red"}>{draft.actionable === false ? (draft.ai_decision || "暂不调整") : "建议干预"}</Tag>
                            {draft.confidence ? (
                              <Tag color={confidenceMeta[draft.confidence].color}>
                                {confidenceMeta[draft.confidence].label}
                              </Tag>
                            ) : null}
                            {selectedOption.tier !== draft.recommended_tier ? <Tag color="blue">人工改选</Tag> : null}
                          </Space>
                        }
                        description={
                          <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                            <Text type="secondary" style={{ fontVariantNumeric: "tabular-nums" }}>
                              平台计划 ID {draft.campaign_id || "未同步"} · 系统记录 #{draft.plan_id} · 店铺 {currentStore?.name || (draft.store_id ? `#${draft.store_id}` : "当前店铺")}
                            </Text>
                            <Text type="secondary">{draft.reason}</Text>
                            <Alert
                              type={draft.actionable === false ? (draft.ai_decision === "建议观察" ? "info" : "warning") : "success"}
                              showIcon
                              title={draft.actionable === false ? (draft.ai_decision || "暂不调整") : `建议干预：只调整${selectedOption.field === "day_budget" ? "日预算" : "出价"}`}
                              description={
                                <Space orientation="vertical" size={3}>
                                  <Text><Text type="secondary">最可能原因：</Text>{draft.primary_cause || "现有数据无法确认根因"}</Text>
                                  <Text><Text type="secondary">影响环节：</Text>{draft.affected_stage || "待确认"}</Text>
                                  <Text><Text type="secondary">下一步：</Text>{draft.next_step || draft.operating_explanation?.recovery_action || "补齐证据后重新判断"}</Text>
                                </Space>
                              }
                            />
                            {draft.decision_evidence?.length ? (
                              <div>
                                <Text strong>判断依据</Text>
                                <Space orientation="vertical" size={2} style={{ width: "100%", marginTop: 4 }}>
                                  {draft.decision_evidence.slice(0, 4).map((item) => <Text key={item} type="secondary">• {item}</Text>)}
                                </Space>
                              </div>
                            ) : null}
                            {draft.missing_data?.length ? <Text type="warning">仍需确认：{draft.missing_data.join("；")}</Text> : null}
                            {draft.actionable !== false ? <Table<DecisionOption>
                              rowKey="tier"
                              size="small"
                              pagination={false}
                              dataSource={draft.options}
                              scroll={{ x: 760 }}
                              columns={[
                                {
                                  title: "方案",
                                  key: "tier",
                                  width: 100,
                                  render: (_: unknown, option: DecisionOption) => (
                                    <Space>
                                      <Tag color={option.tier === "aggressive" ? "red" : option.tier === "balanced" ? "blue" : "green"}>{option.tier_label}</Tag>
                                      {option.recommended ? <Tag color="gold">AI 推荐</Tag> : null}
                                    </Space>
                                  ),
                                },
                                {
                                  title: "变量与目标值",
                                  key: "change",
                                  width: 190,
                                  render: (_: unknown, option: DecisionOption) => (
                                    <Space orientation="vertical" size={0}>
                                      <Text>{option.field === "day_budget" ? "日预算" : "出价"} {fmtMoney(option.old_value)} → <Text strong>{fmtMoney(option.new_value)}</Text></Text>
                                      <Text type="secondary">{option.change_pct > 0 ? "+" : ""}{option.change_pct}%</Text>
                                    </Space>
                                  ),
                                },
                                {
                                  title: "预期",
                                  dataIndex: "expected",
                                  key: "expected",
                                  width: 220,
                                },
                                {
                                  title: "成功标准",
                                  key: "criteria",
                                  width: 230,
                                  render: (_: unknown, option: DecisionOption) => successCriteriaText(option.success_criteria),
                                },
                                {
                                  title: "回退条件",
                                  dataIndex: "rollback_condition",
                                  key: "rollback_condition",
                                  width: 260,
                                },
                                {
                                  title: "方案状态",
                                  key: "select",
                                  fixed: "right",
                                  width: 86,
                                  render: (_: unknown, option: DecisionOption) => (
                                    draft.actionable === false ? (
                                      <Tag>仅供对比</Tag>
                                    ) : (
                                      <Button
                                        size="small"
                                        type={selectedTier === option.tier ? "primary" : "default"}
                                        disabled={option.within_boundary === false}
                                        onClick={() =>
                                          setSelectedOptions((current) => ({
                                            ...current,
                                            [draft.plan_id]: option.tier,
                                          }))
                                        }
                                      >
                                        {selectedTier === option.tier ? "已选择" : "选择"}
                                      </Button>
                                    )
                                  ),
                                },
                              ]}
                            /> : null}
                            <details>
                              <summary style={{ cursor: "pointer", color: "var(--ops-text-secondary)" }}>查看规则、历史经验与安全边界</summary>
                              <Space orientation="vertical" size={8} style={{ width: "100%", marginTop: 10 }}>
                                <Text type="secondary">诊断：{draft.diagnostic_title || "—"} · 规则 {draft.diagnostic_rule || "—"} · 场景 {draft.scene_name}</Text>
                                {draft.evidence_items?.map((item) => <Text key={item} type="secondary">• {item}</Text>)}
                                {draft.target_conflicts?.map((item) => <Text key={item} type="warning">• {item}</Text>)}
                                {draft.strategy_name ? (
                                  <Space wrap>
                                    {draft.strategy_candidates?.map((strategy) => (
                                      <Button
                                        key={strategy.id}
                                        size="small"
                                        type={(selectedStrategies[draft.plan_id] ?? draft.strategy_id) === strategy.id ? "primary" : "default"}
                                        danger={strategy.outcome === "failed"}
                                        onClick={() => setSelectedStrategies((current) => ({ ...current, [draft.plan_id]: strategy.id }))}
                                      >
                                        {strategy.name} · {strategy.verification_status === "pending" ? "待验证" : `${strategy.outcome === "failed" ? "失败" : strategy.outcome === "partial" ? "部分有效" : "成功"} · 证据 ${strategy.evidence_score ?? 0}`}
                                      </Button>
                                    ))}
                                  </Space>
                                ) : <Text type="secondary">暂无匹配的已验证历史经验</Text>}
                                {draft.constraint_summary ? <Text type="warning">业务约束：{draft.constraint_summary}</Text> : null}
                                {draft.not_recommended_reason ? <Text type="warning">执行拦截：{draft.not_recommended_reason}</Text> : null}
                                <Text type="secondary">安全边界：{draft.risk_boundary || `${selectedOption.risk}；${selectedOption.rollback_condition}`} · 观察 {selectedOption.observation_hours} 小时</Text>
                              </Space>
                            </details>
                          </Space>
                        }
                      />
                    </WorkflowListItem>
                  );
                }}
              />
            </div>
          ) : null}
        {!focusedDrafts.length ? <Empty description={targetPlanId ? "当前计划没有达到生成决策方案的数据条件" : "当前没有待决策计划，无需生成调整方案"}><Button onClick={() => void load()}>刷新计划状态</Button></Empty> : null}
        {aiReply.strategy_groups?.length ? (
            <Alert
              type="success"
              showIcon
              title="本次决策已合并同类历史经验"
              description={
                <Space wrap>
                  {aiReply.strategy_groups.slice(0, 6).map((group) => (
                    <Tag color="green" key={group.group_id}>
                      {group.action_type} · {group.scene} · 样本 {group.sample_count} · 成功率 {group.success_rate}% · 证据 {group.avg_evidence_score}
                    </Tag>
                  ))}
                </Space>
              }
              style={{ marginBottom: 14 }}
            />
          ) : null}
          {aiReply.sections ? (
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid var(--ops-border)" }}>
              <Text strong style={{ display: "block", marginBottom: 10 }}>AI 补充分析</Text>
              {Object.entries(aiReply.sections)
                .filter(([, value]) => hasAiSectionContent(value))
                .map(([title, value]) => (
                  <div key={title} style={{ marginBottom: 12 }}>
                    <Text strong>{aiSectionLabels[title] || title}</Text>
                    <Paragraph type="secondary" style={{ whiteSpace: "pre-wrap", margin: "4px 0 0" }}>
                      {Array.isArray(value) ? value.join("\n") : value}
                    </Paragraph>
                  </div>
                ))}
            </div>
          ) : (
            <Paragraph style={{ whiteSpace: "pre-wrap" }}>{aiReply.reply}</Paragraph>
          )}
        </Card>
      ) : null}
      <div ref={decisionPlanListRef} style={{ scrollMarginTop: 96 }}>
      <Card
        variant="borderless"
        title={
          <Space wrap>
            <span>{planFilter === "all" ? "在投计划" : `${decisionPlanFilterMeta[planFilter].label}计划`}</span>
            {planFilter !== "all" ? <Tag color={decisionPlanFilterMeta[planFilter].color}>{decisionPlanFilterMeta[planFilter].label} · {visibleActivePlans.length}</Tag> : null}
          </Space>
        }
        extra={(
          <Space wrap size={4}>
            <Select
              aria-label="计划状态"
              size="small"
              value={planFilter}
              onChange={(value) => setPlanFilter(value as DecisionPlanFilter)}
              options={[
                { value: "needs_decision", label: `待处理（${decisionCounts.needs_decision}）` },
                { value: "observe", label: `正常观察（${decisionCounts.observe}）` },
                { value: "insufficient", label: `证据不足（${decisionCounts.insufficient}）` },
                { value: "all", label: `全部在投（${activePlans.length}）` },
              ]}
            />
          </Space>
        )}
        style={{ marginTop: 16 }}
        loading={loading}
      >
        {!loading && focusedActivePlans.length === 0 ? (
          <Empty description="暂无在投计划数据，请先同步推广计划" />
        ) : !loading && visibleActivePlans.length === 0 ? (
          <Empty description="当前重点下没有符合条件的计划"><Button onClick={() => setPlanFilter("all")}>查看全部在投计划</Button></Empty>
        ) : (
          <WorkflowList
            dataSource={visibleActivePlans}
            renderItem={(plan) => {
              const status = decisionPlanStatus(plan, diagnosticStatuses);
              const recommendation = status === "needs_decision" ? "需要处理" : status === "insufficient" ? "证据不足，暂不调整" : "正常观察，保持现状";
              const color = decisionPlanFilterMeta[status].color;
              return (
                <WorkflowListItem
                  actionsPlacement="side"
                  className="ops-decision-plan-item"
                  actions={[
                    <Button key="detail" type="link" style={{ justifyContent: "flex-start", paddingInline: 0 }} onClick={() => navigate(`/promotions/plans/${plan.id}`)}>
                      查看计划详情
                    </Button>,
                    <Button key="assess" type="link" style={{ justifyContent: "flex-start", paddingInline: 0 }} onClick={() => navigate(`/promotions/decisions?plan_id=${plan.id}&store_id=${plan.store_id}&channel=${encodeURIComponent(plan.channel || "")}&auto_generate=1`)}>
                      {status === "needs_decision" ? "生成 AI 决策" : "主动评估"}
                    </Button>,
                  ]}
                >
                  <WorkflowListMeta
                    title={
                      <div className="ops-plan-identity">
                        <div className="ops-plan-identity__image">
                          {plan.item_image ? <img src={plan.item_image} alt="" /> : <FileImageOutlined aria-hidden="true" />}
                        </div>
                        <div className="ops-plan-identity__body">
                          <Space wrap size={[8, 6]}>
                            <Text strong ellipsis={{ tooltip: plan.plan_name }} style={{ maxWidth: "100%", fontSize: 15 }}>{plan.plan_name}</Text>
                            <Tag>{plan.scene_name}</Tag>
                            <Tag color={color}>{recommendation}</Tag>
                          </Space>
                          <Text className="ops-plan-identity__item-title" type={plan.item_title ? "secondary" : "warning"} ellipsis={{ tooltip: plan.item_title || "宝贝标题未同步" }}>
                            宝贝标题：{plan.item_title || "未同步"}
                          </Text>
                        </div>
                      </div>
                    }
                    description={
                      <Space orientation="vertical" size={7} style={{ width: "100%" }}>
                        <div className="ops-plan-identity__ids">
                          <Text type="secondary" style={{ fontVariantNumeric: "tabular-nums" }}>宝贝 ID <Text code>{plan.item_id || "未同步"}</Text></Text>
                          <Text type="secondary" style={{ fontVariantNumeric: "tabular-nums" }}>平台计划 ID <Text code>{plan.campaign_id || "未同步"}</Text></Text>
                          <Text type="secondary">系统记录 <Text code>#{plan.id}</Text></Text>
                          <Text type="secondary">店铺 {currentStore?.name || `#${plan.store_id}`}</Text>
                        </div>
                        <Space wrap size={[18, 4]}>
                          <Text type="secondary">花费 <Text strong>{fmtMoney(plan.spend)}</Text></Text>
                          <Text type="secondary">成交 <Text strong>{fmtMoney(plan.sales)}</Text></Text>
                          <Text type="secondary">ROI <Text strong style={{ fontVariantNumeric: "tabular-nums" }}>{plan.roi.toFixed(2)}</Text></Text>
                          <Text type="secondary">状态 {plan.status}</Text>
                        </Space>
                        <Text type="secondary">
                          {status === "needs_decision"
                            ? "诊断中心已标记风险异常，建议进入 AI 决策复核"
                            : status === "insufficient"
                              ? "诊断中心标记为数据不足，补齐数据后再判断"
                              : "诊断中心未发现风险异常，保持现状并继续观察"}
                        </Text>
                      </Space>
                    }
                  />
                </WorkflowListItem>
              );
            }}
          />
        )}
      </Card>
      </div>
      <Modal open={!!rejectDraft} title="拒绝本次 AI 方案" onCancel={() => setRejectDraft(null)} onOk={() => void rejectDecision()} okText="确认拒绝并记录" okButtonProps={{ danger: true, disabled: !rejectReason }} confirmLoading={!!rejectDraft && savingDecisionId === rejectDraft.plan_id} destroyOnHidden>
        <Paragraph type="secondary">记录真实拒绝原因，后续复盘时可识别库存、利润、活动与预算等业务约束。</Paragraph>
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Select value={rejectReason || undefined} onChange={setRejectReason} placeholder="请选择拒绝原因" style={{ width: "100%" }} options={["库存不足", "利润空间不足", "活动临近", "预算限制", "当前不适合调整", "AI 判断不合理", "其他"].map((value) => ({ value, label: value }))} />
          <Input.TextArea value={rejectNote} onChange={(event) => setRejectNote(event.target.value)} rows={3} maxLength={300} showCount placeholder="补充说明（可选）" />
        </Space>
      </Modal>
    </WorkspacePage>
  );
}

function ValidationPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { currentStore } = useStores();
  const targetActionId = Number(searchParams.get("action_id")) || null;
  const contextParams = useMemo(() => {
    const params = new URLSearchParams();
    for (const key of ["store_id", "channel", "plan_id", "diagnostic_id", "diagnostic", "rule", "evidence", "decision_id", "decision_record_id", "from", "patrol_id", "patrol_date"] as const) {
      const value = searchParams.get(key);
      if (value) params.set(key, value);
    }
    if (targetActionId) params.set("action_id", String(targetActionId));
    return params;
  }, [searchParams, targetActionId]);
  const contextualRoute = (path: string, extra: Record<string, string | number | null | undefined> = {}) => {
    const params = new URLSearchParams(contextParams);
    Object.entries(extra).forEach(([key, value]) => {
      if (value != null && value !== "") params.set(key, String(value));
    });
    return `${path}?${params.toString()}`;
  };
  const [records, setRecords] = useState<ActionRecord[]>([]);
  const [summary, setSummary] = useState<VerificationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState<number | null>(null);
  const [view, setView] = useState<"queue" | "dashboard">("queue");
  const [filter, setFilter] = useState<"all" | "planned" | "observing" | "ready" | "completed">("all");
  const [lifecycle, setLifecycle] = useState<"active" | "voided" | "archived">("active");
  const [lifecycleRecord, setLifecycleRecord] = useState<ActionRecord | null>(null);
  const [lifecycleAction, setLifecycleAction] = useState<"void" | "archive" | "restore">("void");
  const [lifecycleReason, setLifecycleReason] = useState("");
  const [lifecycleSaving, setLifecycleSaving] = useState(false);
  const [reviewRecord, setReviewRecord] = useState<ActionRecord | null>(null);
  const [targetRoi, setTargetRoi] = useState<number | null>(null);
  const [roiChangeMin, setRoiChangeMin] = useState<number | null>(null);
  const [salesChangeMin, setSalesChangeMin] = useState<number | null>(null);
  const [spendChangeMax, setSpendChangeMax] = useState<number | null>(null);
  const [interferenceNotes, setInterferenceNotes] = useState("");
  const [manualConclusion, setManualConclusion] = useState("");
  const [reproducibility, setReproducibility] = useState<"pending" | "reproducible" | "not_reproducible">("pending");
  const [reviewSaving, setReviewSaving] = useState(false);
  const [loadError, setLoadError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ lifecycle });
      if (currentStore) params.set("store_id", String(currentStore.id));
      const [recordResponse, summaryResponse] = await Promise.all([http.get<{ items: ActionRecord[] }>(`/promotions/action-records?${params.toString()}`), http.get<VerificationSummary>(`/promotions/action-records/summary${currentStore ? `?store_id=${currentStore.id}` : ""}`)]);
      setRecords(recordResponse.data.items || []);
      setSummary(summaryResponse.data);
      setLoadError("");
    } catch (error) {
      setLoadError(getApiErrorMessage(error));
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id, lifecycle]);
  useEffect(() => {
    void load();
  }, [load]);
  const verify = async (id: number) => {
    setVerifying(id);
    try {
      await http.post(`/promotions/action-records/${id}/verify`);
      message.success("验证完成");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setVerifying(null);
    }
  };
  const markExecuted = async (id: number) => {
    setVerifying(id);
    try {
      await http.post(`/promotions/action-records/${id}/mark-executed`);
      message.success("已进入观察窗口");
      if (searchParams.get("from") === "cockpit" && searchParams.get("patrol_id")) {
        const patrolDate = searchParams.get("patrol_date") || dayjs().format("YYYY-MM-DD");
        const storeKey = currentStore?.id || "all";
        const channelKey = searchParams.get("patrol_channel") || "all";
        const storageKey = `promotions-patrol:${patrolDate}:${storeKey}:${channelKey}`;
        try {
          const raw = localStorage.getItem(storageKey);
          const state = raw ? JSON.parse(raw) as { date?: string; current_id?: string; records?: Record<string, { status: string; updated_at?: string }> } : { date: patrolDate, records: {} };
          const records = state.records || {};
          const patrolId = searchParams.get("patrol_id") as string;
          records[patrolId] = { status: "completed", updated_at: new Date().toISOString() };
          localStorage.setItem(storageKey, JSON.stringify({ ...state, date: patrolDate, current_id: undefined, records }));
          navigate("/promotions/cockpit");
          return;
        } catch {
          // 本地进度写入失败时仍保留当前验证页面，避免丢失真实执行结果。
        }
      }
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setVerifying(null);
    }
  };
  const openReview = (record: ActionRecord) => {
    setReviewRecord(record);
    setTargetRoi(record.success_criteria?.target_roi_min ?? null);
    setRoiChangeMin(record.success_criteria?.roi_change_min ?? null);
    setSalesChangeMin(record.success_criteria?.sales_change_pct_min ?? null);
    setSpendChangeMax(record.success_criteria?.spend_change_pct_max ?? null);
    setInterferenceNotes(record.interference_notes || "");
    setManualConclusion(record.manual_conclusion || "");
    setReproducibility(record.manual_conclusion?.includes("可复制性：可复制") ? "reproducible" : record.manual_conclusion?.includes("可复制性：不可复制") ? "not_reproducible" : "pending");
  };
  const saveReview = async () => {
    if (!reviewRecord) return;
    const criteria: Record<string, number> = {};
    if (targetRoi != null) criteria.target_roi_min = targetRoi;
    if (roiChangeMin != null) criteria.roi_change_min = roiChangeMin;
    if (salesChangeMin != null) criteria.sales_change_pct_min = salesChangeMin;
    if (spendChangeMax != null) criteria.spend_change_pct_max = spendChangeMax;
    setReviewSaving(true);
    try {
      const cleanedConclusion = manualConclusion.replace(/^可复制性：(可复制|不可复制)\s*[；;]?\s*/, "");
      const reproducibilityText = reproducibility === "reproducible" ? "可复制性：可复制；" : reproducibility === "not_reproducible" ? "可复制性：不可复制；" : "";
      await http.put(`/promotions/action-records/${reviewRecord.id}/review`, {
        success_criteria: criteria,
        interference_notes: interferenceNotes,
        manual_conclusion: `${reproducibilityText}${cleanedConclusion}`.trim(),
      });
      message.success("验证设置已保存");
      setReviewRecord(null);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setReviewSaving(false);
    }
  };
  const openLifecycle = (record: ActionRecord, action: "void" | "archive" | "restore") => {
    setLifecycleRecord(record);
    setLifecycleAction(action);
    setLifecycleReason("");
  };
  const updateLifecycle = async () => {
    if (!lifecycleRecord || lifecycleSaving) return;
    if (lifecycleAction === "void" && !lifecycleReason.trim()) return;
    setLifecycleSaving(true);
    try {
      await http.put(`/promotions/action-records/${lifecycleRecord.id}/lifecycle`, { action: lifecycleAction, reason: lifecycleReason.trim() });
      message.success(lifecycleAction === "void" ? "记录已作废" : lifecycleAction === "archive" ? "记录已归档" : "记录已恢复");
      setLifecycleRecord(null);
      setLifecycleReason("");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLifecycleSaving(false);
    }
  };
  const observing = records.filter((item) => item.status === "observing").length;
  const ready = records.filter(isVerificationDue).length;
  const checkpoints = useMemo(() => ({
    h24: records.filter((item) => item.status === "observing" && observationCheckpoint(item).label === "24h 检查").length,
    h48: records.filter((item) => item.status === "observing" && observationCheckpoint(item).label === "48h 验证").length,
    d7: records.filter((item) => !["planned", "observing"].includes(item.status) && item.executed_at && Date.now() - new Date(item.executed_at).getTime() >= 7 * 86_400_000).length,
  }), [records]);
  const visibleRecords = records.filter((item) => {
    if (filter === "all") return true;
    if (filter === "ready") return isVerificationDue(item);
    if (filter === "completed") return !["planned", "observing"].includes(item.status);
    return item.status === filter;
  });
  const focusedRecords = targetActionId ? visibleRecords.filter((item) => item.id === targetActionId) : visibleRecords;
  return (
    <WorkspacePage kind="management">
      <PageHeader
        icon={<SafetyCertificateOutlined />}
        eyebrow="推广管理"
        title="观察验证"
        description="追踪每次调整动作的观察窗口，并用前后日报数据判断结果。"
        extra={
          <Space>
            <Segmented
              value={view}
              onChange={(value) => setView(value as typeof view)}
              options={[
                { label: "任务队列", value: "queue" },
                { label: "结果看板", value: "dashboard" },
              ]}
            />
            <Button onClick={() => void load()}>刷新</Button>
          </Space>
        }
      />
      <DecisionBand
        eyebrow="验证节点"
        title={ready ? `${ready} 个动作已到期，可以形成验证结论` : observing ? `${observing} 个动作仍在观察窗口` : "当前没有待验证动作"}
        description="按 24h 检查、48h 验证、7 天复盘推进；数据不足时保留“无法判断”，不强行判定好坏。"
        action={ready ? <Button type="primary" onClick={() => setFilter("ready")}>查看可验证动作</Button> : <Button onClick={() => navigate("/promotions/decisions")}>建立观察任务</Button>}
        ariaLabel="观察验证首要结论"
      />
      {view === "dashboard" ? (
        <ValidationDashboard summary={summary} loading={loading} />
      ) : (
        <>
          <Alert type="info" showIcon title="按 24h 检查、48h 验证、7 天复盘三个节点观察" description="24 小时先排除数据延迟，48 小时形成改善/恶化/无法判断结论，7 天再决定是否沉淀经验；观察期间尽量保持单一变量。" style={{ marginBottom: 16 }} />
          {loadError ? <Alert type="error" showIcon title="验证数据加载失败" description={loadError} action={<Button size="small" onClick={() => void load()}>重试</Button>} style={{ marginBottom: 16 }} /> : null}
          {targetActionId && !loading && focusedRecords.length === 0 ? <Alert type="error" showIcon title="目标观察任务不存在或不在当前店铺范围" style={{ marginBottom: 16 }} /> : null}
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={6}>
              <Card variant="borderless">
                <Statistic title="全部动作" value={records.length} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless">
                <Statistic title="观察中" value={observing} styles={{ content: { color: "var(--ops-accent)" } }} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless">
                <Statistic
                  title="可立即验证"
                  value={ready}
                  styles={{
                    content: { color: ready ? "var(--ops-warn)" : undefined },
                  }}
                />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless">
                <Statistic title="验证成功" value={records.filter((item) => item.status === "success").length} styles={{ content: { color: "var(--ops-success)" } }} />
              </Card>
            </Col>
          </Row>
          <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
            {[
              { label: "24h 检查", value: checkpoints.h24, hint: "排除延迟与短期波动", color: "blue" },
              { label: "48h 验证", value: checkpoints.h48, hint: "形成好坏或无法判断结论", color: "orange" },
              { label: "7 天复盘", value: checkpoints.d7, hint: "决定是否沉淀经验", color: "purple" },
            ].map((item) => <Col xs={24} sm={8} key={item.label}><Card size="small" style={{ height: "100%" }}><Space style={{ width: "100%", justifyContent: "space-between" }}><Text strong>{item.label}</Text><Tag color={item.color}>{item.value}</Tag></Space><Text type="secondary" style={{ fontSize: 12 }}>{item.hint}</Text></Card></Col>)}
          </Row>
          {ready > 0 ? <Alert type="warning" showIcon title={`${ready} 个观察任务已到期，可立即验证`} style={{ marginTop: 16 }} /> : null}
          <Card
            variant="borderless"
            title="调整动作队列"
            style={{ marginTop: 16 }}
            loading={loading}
            extra={
              <Space wrap size={8}>
                <Segmented
                  size="small"
                  aria-label="记录范围"
                  value={lifecycle}
                  onChange={(value) => { setLifecycle(value as typeof lifecycle); setFilter("all"); }}
                  options={[{ label: "有效记录", value: "active" }, { label: "已作废", value: "voided" }, { label: "已归档", value: "archived" }]}
                />
                <Segmented
                  size="small"
                  value={filter}
                  onChange={(value) => setFilter(value as typeof filter)}
                  options={[
                    { label: "全部", value: "all" },
                    { label: "待执行", value: "planned" },
                    { label: "观察中", value: "observing" },
                    { label: `可验证 ${ready}`, value: "ready" },
                    { label: "已完成", value: "completed" },
                  ]}
                />
              </Space>
            }
          >
            {!loading && records.length === 0 ? (
              <Empty description="还没有动作记录"><Button type="primary" onClick={() => navigate(contextualRoute("/promotions/decisions"))}>去生成 AI 决策</Button></Empty>
            ) : focusedRecords.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选没有动作" />
            ) : (
              <WorkflowList
                dataSource={focusedRecords}
                renderItem={(item) => {
                  const confidence = item.confidence ? confidenceMeta[item.confidence] : null;
                  const metrics = item.metric_summary || {};
                  const verificationDue = isVerificationDue(item);
                  const checkpoint = observationCheckpoint(item);
                  const direction = verificationDirection(item);
                  return (
                    <WorkflowListItem
                      actions={lifecycle === "active" ? [
                        <Button key="review" size="small" onClick={() => openReview(item)}>
                          {item.status === "planned" || item.status === "observing" ? "验证设置" : "补充复盘"}
                        </Button>,
                        item.status === "planned" ? (
                          <Button key="executed" type="primary" size="small" loading={verifying === item.id} onClick={() => void markExecuted(item.id)}>
                            标记已执行
                          </Button>
                        ) : null,
                        item.status === "observing" ? (
                          <Button key="verify" type={verificationDue ? "primary" : "default"} size="small" disabled={!verificationDue} loading={verifying === item.id} onClick={() => void verify(item.id)}>
                            {verificationDue ? "立即验证" : "等待窗口"}
                          </Button>
                        ) : null,
                        item.status === "failed" ? <Button key="rollback" danger size="small" onClick={() => navigate(contextualRoute("/promotions/plans", { plan_id: item.plan_id, rollback_from: item.id }))}>评估回退</Button> : null,
                        !["planned", "observing"].includes(item.status) ? <Button key="review-page" type="primary" size="small" onClick={() => navigate(contextualRoute("/promotions/review", { plan_id: item.plan_id, action_id: item.id }))}>进入经营复盘</Button> : null,
                        !["planned", "observing"].includes(item.status) ? <Button key="experience" size="small" onClick={() => navigate(contextualRoute("/promotions/strategies", { plan_id: item.plan_id, action_id: item.id }))}>沉淀经验</Button> : null,
                        item.status === "planned" ? <Button key="void" size="small" danger onClick={() => openLifecycle(item, "void")}>取消任务</Button> : null,
                        item.status === "observing" ? <Button key="void" size="small" danger onClick={() => openLifecycle(item, "void")}>终止观察</Button> : null,
                        !["planned", "observing"].includes(item.status) ? <Button key="archive" size="small" onClick={() => openLifecycle(item, "archive")}>归档</Button> : null,
                      ] : [<Button key="restore" size="small" onClick={() => openLifecycle(item, "restore")}>恢复记录</Button>]}
                    >
                      <WorkflowListMeta
                        title={
                          <Space wrap>
                            {item.plan_name || `计划 ${item.plan_id}`}
                            {lifecycle !== "active" ? <Tag color={lifecycleMeta[item.lifecycle_status || lifecycle].color}>{lifecycleMeta[item.lifecycle_status || lifecycle].label}</Tag> : null}
                            <Tag color={statusMeta[item.status].color}>{statusMeta[item.status].label}</Tag>
                            {verificationDue ? <Tag color="orange">已到期</Tag> : null}
                            {item.status === "observing" ? <Tag color={checkpoint.color}>{checkpoint.label}</Tag> : null}
                            {direction ? <Tag color={direction.color}>{direction.label}</Tag> : null}
                            {confidence ? <Tag color={confidence.color}>{confidence.label}</Tag> : null}
                            <Tag>{item.action_type}</Tag>
                            {item.decision_id ? <Tag color="purple">决策 {item.decision_id.slice(-8)}</Tag> : null}
                          </Space>
                        }
                        description={
                          <Space orientation="vertical" size={3}>
                            <Text type="secondary">
                              {item.executed_at ? `执行时间 ${formatDate(item.executed_at)}` : `尚未执行 · 创建于 ${formatDate(item.created_at)}`} · 观察 {item.observation_hours} 小时
                              {item.observation_due_at ? ` · 截止 ${formatDate(item.observation_due_at)}` : ""}
                            </Text>
                            {item.status === "observing" ? <Text type="secondary">当前节点：{checkpoint.hint}</Text> : null}
                            {lifecycle !== "active" && item.lifecycle_reason ? <Text type="secondary">处理原因：{item.lifecycle_reason}</Text> : null}
                            <Text type="secondary">
                              基线：日均花费 {fmtMoney(metrics.before_daily_spend ?? item.before_spend)} · 日均成交 {fmtMoney(metrics.before_daily_sales ?? item.before_sales)} · ROI {item.before_roi.toFixed(2)}
                            </Text>
                            {item.after_roi != null && ["success", "partial", "failed", "insufficient"].includes(item.status) ? (
                              <Text type="secondary">
                                观察：日均花费 {fmtMoney(metrics.after_daily_spend ?? item.after_spend ?? 0)} · 日均成交 {fmtMoney(metrics.after_daily_sales ?? item.after_sales ?? 0)} · ROI {item.after_roi.toFixed(2)}
                              </Text>
                            ) : null}
                            {metrics.sales_change_pct != null || metrics.spend_change_pct != null ? (
                              <Text type="secondary">
                                变化：日均成交 {metrics.sales_change_pct != null ? `${metrics.sales_change_pct > 0 ? "+" : ""}${metrics.sales_change_pct}%` : "—"} · 日均花费 {metrics.spend_change_pct != null ? `${metrics.spend_change_pct > 0 ? "+" : ""}${metrics.spend_change_pct}%` : "—"} · ROI {metrics.roi_change != null ? `${metrics.roi_change > 0 ? "+" : ""}${metrics.roi_change}` : "—"}
                              </Text>
                            ) : null}
                            {item.result ? <Text>{item.result}</Text> : <Text type="secondary">预期：{item.expected || "待补充"}</Text>}
                            {item.rollback_condition ? <Text type="warning">回退条件：{item.rollback_condition}</Text> : null}
                            {item.interference_notes ? <Text type="warning">干扰因素：{item.interference_notes}</Text> : null}
                            {item.manual_conclusion ? <Text>人工结论：{item.manual_conclusion}</Text> : null}
                            {item.data_quality ? <Text type="secondary">数据质量：{item.data_quality}</Text> : null}
                          </Space>
                        }
                      />
                    </WorkflowListItem>
                  );
                }}
              />
            )}
          </Card>
        </>
      )}
      <Modal open={!!reviewRecord} title={reviewRecord && !["planned", "observing"].includes(reviewRecord.status) ? "补充验证复盘" : "设置验证标准"} onCancel={() => setReviewRecord(null)} onOk={() => void saveReview()} confirmLoading={reviewSaving} okText="保存">
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Alert type="info" showIcon title="填写的成功标准将作为自动验证依据" description="可设置一个或多个标准；全部达标判定成功，部分达标判定部分有效。" />
          <Space wrap>
            <InputNumber value={targetRoi} onChange={setTargetRoi} min={0} precision={2} addonBefore="最终 ROI≥" style={{ width: 190 }} />
            <InputNumber value={roiChangeMin} onChange={setRoiChangeMin} precision={2} addonBefore="ROI 提升≥" style={{ width: 190 }} />
            <InputNumber value={salesChangeMin} onChange={setSalesChangeMin} precision={1} addonBefore="日均成交变化≥" addonAfter="%" style={{ width: 220 }} />
            <InputNumber value={spendChangeMax} onChange={setSpendChangeMax} precision={1} addonBefore="日均花费变化≤" addonAfter="%" style={{ width: 220 }} />
          </Space>
          <Input.TextArea value={interferenceNotes} onChange={(event) => setInterferenceNotes(event.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} placeholder="干扰因素：大促、价格调整、库存变化、素材更换、自然流量异常等" />
          <Select
            value={reproducibility}
            onChange={setReproducibility}
            options={[
              { label: "可复制性待判断", value: "pending" },
              { label: "可复制：条件明确且可再次使用", value: "reproducible" },
              {
                label: "不可复制：受偶发因素或外部干扰影响",
                value: "not_reproducible",
              },
            ]}
            style={{ width: "100%" }}
          />
          <Input.TextArea value={manualConclusion} onChange={(event) => setManualConclusion(event.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} placeholder="人工复盘结论：是否回退、继续观察或进行二次调整" />
        </Space>
      </Modal>
      <Modal
        open={!!lifecycleRecord}
        title={lifecycleAction === "void" ? (lifecycleRecord?.status === "observing" ? "终止观察" : "取消任务") : lifecycleAction === "archive" ? "归档验证记录" : "恢复记录"}
        onCancel={() => { setLifecycleRecord(null); setLifecycleReason(""); }}
        onOk={() => void updateLifecycle()}
        confirmLoading={lifecycleSaving}
        okText={lifecycleAction === "void" ? "确认作废" : lifecycleAction === "archive" ? "确认归档" : "恢复记录"}
        okButtonProps={{ danger: lifecycleAction === "void", disabled: lifecycleAction === "void" && !lifecycleReason.trim() }}
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type={lifecycleAction === "void" ? "warning" : "info"}
            showIcon
            title={lifecycleAction === "void" ? "记录不会被删除" : lifecycleAction === "archive" ? "归档后仍可在历史范围查看" : "恢复后会重新进入有效记录"}
            description={lifecycleAction === "void" ? "作废后不再进入作战台、待办统计或 AI 经验样本，但会保留在已作废记录中。" : lifecycleAction === "archive" ? "归档只改变记录的日常可见性，不会修改验证结果和原始指标。" : "恢复不会修改原有执行和验证数据。"}
          />
          {lifecycleAction !== "restore" ? <Input.TextArea value={lifecycleReason} onChange={(event) => setLifecycleReason(event.target.value)} autoSize={{ minRows: 3, maxRows: 6 }} maxLength={500} showCount placeholder={lifecycleAction === "archive" ? "可选：填写归档备注" : "请填写原因，例如：重复创建、计划已停止、等待条件变化"} /> : null}
        </Space>
      </Modal>
    </WorkspacePage>
  );
}

function ValidationDashboard({ summary, loading }: { summary: VerificationSummary | null; loading: boolean }) {
  if (loading) return <Card variant="borderless" loading />;
  if (!summary || summary.totals.actions === 0)
    return (
      <Card variant="borderless">
        <Empty description="完成动作验证后，这里会生成结果分析"><Button href="/promotions/decisions">去建立第一条观察任务</Button></Empty>
      </Card>
    );

  const groupColumns = [
    { title: "分组", dataIndex: "name", key: "name", ellipsis: true },
    {
      title: "有效结论",
      dataIndex: "conclusive",
      key: "conclusive",
      width: 90,
    },
    {
      title: "成功 / 部分 / 失败",
      key: "outcomes",
      width: 150,
      render: (_: unknown, item: VerificationGroup) => `${item.success} / ${item.partial} / ${item.failed}`,
    },
    {
      title: "成功率",
      dataIndex: "success_rate",
      key: "success_rate",
      width: 90,
      render: (value: number) => `${value}%`,
    },
    {
      title: "平均 ROI 变化",
      dataIndex: "avg_roi_change",
      key: "avg_roi_change",
      width: 120,
      render: (value: number | null) => formatDelta(value),
    },
    {
      title: "日均成交变化",
      dataIndex: "avg_sales_change_pct",
      key: "avg_sales_change_pct",
      width: 120,
      render: (value: number | null) => formatDelta(value, "%"),
    },
  ];
  const confidenceTotal = summary.confidence.reduce((total, item) => total + item.count, 0);
  const outcomeColors: Record<ActionRecord["status"], string> = {
    planned: "var(--ops-warn)",
    observing: "var(--ops-accent)",
    success: "var(--ops-success)",
    partial: "var(--ops-warn)",
    failed: "var(--ops-danger)",
    insufficient: "var(--ops-text-secondary)",
  };

  return (
    <>
      <Alert type="info" showIcon title="成功率只统计已有明确结论的动作" description="数据不足样本不会计入成功率；平均变化同样只使用成功、部分有效和失败样本，避免低可信数据稀释判断。" style={{ marginBottom: 16 }} />
      <Row gutter={[12, 12]}>
        <Col xs={12} lg={6}>
          <Card variant="borderless">
            <Statistic title="有效结论" value={summary.totals.conclusive} suffix={`/ ${summary.totals.verified}`} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card variant="borderless">
            <Statistic title="验证成功率" value={summary.totals.success_rate} suffix="%" styles={{ content: { color: "var(--ops-success)" } }} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card variant="borderless">
            <Statistic title="平均 ROI 变化" value={formatDelta(summary.totals.avg_roi_change)} />
          </Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card variant="borderless">
            <Statistic
              title="中高可信样本"
              value={summary.totals.reliable_rate}
              suffix="%"
              styles={{
                content: {
                  color: summary.totals.reliable_rate >= 70 ? "var(--ops-success)" : "var(--ops-warn)",
                },
              }}
            />
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card variant="borderless" title="动作结论分布">
            <Space orientation="vertical" size={10} style={{ width: "100%" }}>
              {summary.outcomes.map((item) => (
                <div key={item.key}>
                  <Space style={{ width: "100%", justifyContent: "space-between" }}>
                    <Text>{item.name}</Text>
                    <Text type="secondary">{item.count}</Text>
                  </Space>
                  <Progress percent={summary.totals.actions ? Math.round((item.count / summary.totals.actions) * 100) : 0} showInfo={false} strokeColor={outcomeColors[item.key]} />
                </div>
              ))}
            </Space>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card variant="borderless" title="结论可信度">
            <Space orientation="vertical" size={10} style={{ width: "100%" }}>
              {summary.confidence.map((item) => (
                <div key={item.key}>
                  <Space style={{ width: "100%", justifyContent: "space-between" }}>
                    <Text>{item.name}</Text>
                    <Text type="secondary">{item.count}</Text>
                  </Space>
                  <Progress percent={confidenceTotal ? Math.round((item.count / confidenceTotal) * 100) : 0} showInfo={false} strokeColor={item.key === "high" ? "var(--ops-success)" : item.key === "medium" ? "var(--ops-warn)" : "var(--ops-danger)"} />
                </div>
              ))}
            </Space>
            {confidenceTotal === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无已验证可信度数据" /> : null}
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} xl={12}>
          <Card variant="borderless" title="不同调整动作的效果">
            <Table<VerificationGroup> rowKey="name" size="small" pagination={false} dataSource={summary.action_types} columns={groupColumns} scroll={{ x: 700 }} />
          </Card>
        </Col>
        <Col xs={24} xl={12}>
          <Card variant="borderless" title="不同推广场景的效果">
            <Table<VerificationGroup> rowKey="name" size="small" pagination={false} dataSource={summary.scenes} columns={groupColumns} scroll={{ x: 700 }} />
          </Card>
        </Col>
      </Row>
      <Card variant="borderless" title="计划验证对比" style={{ marginTop: 16 }}>
        <Table<VerificationGroup> rowKey="name" size="small" pagination={false} dataSource={summary.plans} columns={groupColumns} scroll={{ x: 700 }} />
      </Card>
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={8}>
          <Card variant="borderless" title="复盘关注点">
            {summary.focuses.length ? (
              <Space wrap>
                {summary.focuses.map((item) => (
                  <Tag key={item.name} color={item.name === "数据不足" ? "default" : "orange"}>
                    {item.name} · {item.count}
                  </Tag>
                ))}
              </Space>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无风险关注点" />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={16}>
          <Card variant="borderless" title="近期需复盘动作">
            {summary.review_items.length ? (
              <WorkflowList
                dataSource={summary.review_items}
                renderItem={(item) => (
                  <WorkflowListItem>
                    <WorkflowListMeta
                      title={
                        <Space wrap>
                          <Text strong>{item.plan_name}</Text>
                          <Tag color={statusMeta[item.status].color}>{statusMeta[item.status].label}</Tag>
                          <Tag>{item.action_type}</Tag>
                          {item.confidence ? <Tag color={confidenceMeta[item.confidence].color}>{confidenceMeta[item.confidence].label}</Tag> : null}
                        </Space>
                      }
                      description={
                        <Space orientation="vertical" size={2}>
                          <Text type="secondary">
                            {item.scene_name} · 验证时间 {formatDate(item.verified_at)}
                          </Text>
                          <Text>{item.result}</Text>
                          {item.interference_notes ? <Text type="warning">干扰因素：{item.interference_notes}</Text> : null}
                          {item.manual_conclusion ? <Text>人工结论：{item.manual_conclusion}</Text> : null}
                        </Space>
                      }
                    />
                  </WorkflowListItem>
                )}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无失败、部分有效或数据不足动作" />
            )}
          </Card>
        </Col>
      </Row>
    </>
  );
}

function StrategiesPage() {
  const { currentStore } = useStores();
  const [records, setRecords] = useState<ActionRecord[]>([]);
  const [strategies, setStrategies] = useState<
    {
      id: number;
      name: string;
      action_type: string;
      conditions: string;
      evidence: string;
      success_count: number;
      use_count: number;
      outcome?: string;
      status?: string;
      scene?: string;
      min_roi?: number | null;
      max_roi?: number | null;
      evidence_score?: number;
      evidence_level?: "high" | "medium" | "low";
      sample_count?: number;
      group_success_rate?: number;
      source_type?: "verified" | "manual";
      verification_status?: "verified" | "pending";
    }[]
  >([]);
  const [strategyGroups, setStrategyGroups] = useState<StrategyGroup[]>([]);
  const [editing, setEditing] = useState<(typeof strategies)[number] | null>(null);
  const [editName, setEditName] = useState("");
  const [editConditions, setEditConditions] = useState("");
  const [editScene, setEditScene] = useState("");
  const [editMinRoi, setEditMinRoi] = useState<number | null>(null);
  const [editMaxRoi, setEditMaxRoi] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [strategyFilter, setStrategyFilter] = useState<"all" | "active" | "inactive" | "success" | "caution" | "pending">("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createActionType, setCreateActionType] = useState("");
  const [createConditions, setCreateConditions] = useState("");
  const [createEvidence, setCreateEvidence] = useState("");
  const [createScene, setCreateScene] = useState("");
  const [createMinRoi, setCreateMinRoi] = useState<number | null>(null);
  const [createMaxRoi, setCreateMaxRoi] = useState<number | null>(null);
  const load = useCallback(async () => {
    try {
      const scope = currentStore ? `?store_id=${currentStore.id}` : "";
      const [recordResponse, strategyResponse] = await Promise.all([http.get<{ items: ActionRecord[] }>(`/promotions/action-records${scope}`), http.get<{ items: typeof strategies; groups: StrategyGroup[] }>(`/promotions/strategies${scope}`)]);
      setRecords(recordResponse.data.items || []);
      setStrategies(strategyResponse.data.items || []);
      setStrategyGroups(strategyResponse.data.groups || []);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  }, [currentStore?.id]);
  useEffect(() => {
    void load();
  }, [load]);
  const openEdit = (strategy: (typeof strategies)[number]) => {
    setEditing(strategy);
    setEditName(strategy.name);
    setEditConditions(strategy.conditions);
    setEditScene(strategy.scene || "");
    setEditMinRoi(strategy.min_roi ?? null);
    setEditMaxRoi(strategy.max_roi ?? null);
  };
  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await http.put(`/promotions/strategies/${editing.id}`, {
        name: editName,
        conditions: editConditions,
        scene: editScene,
        min_roi: editMinRoi,
        max_roi: editMaxRoi,
      });
      message.success("策略卡已更新");
      setEditing(null);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };
  const toggleStatus = async (strategy: (typeof strategies)[number]) => {
    try {
      await http.put(`/promotions/strategies/${strategy.id}`, {
        status: strategy.status === "inactive" ? "active" : "inactive",
      });
      message.success(strategy.status === "inactive" ? "策略已启用" : "策略已停用");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };
  const openCreate = () => {
    setCreateName("");
    setCreateActionType("");
    setCreateConditions("");
    setCreateEvidence("");
    setCreateScene("");
    setCreateMinRoi(null);
    setCreateMaxRoi(null);
    setCreateOpen(true);
  };
  const createManualStrategy = async () => {
    if (!currentStore) {
      message.error("请先选择店铺");
      return;
    }
    if (!createName.trim() || !createActionType.trim() || !createConditions.trim() || !createEvidence.trim()) {
      message.error("请填写经验名称、推荐动作、适用条件和经验依据");
      return;
    }
    if (createMinRoi != null && createMaxRoi != null && createMinRoi > createMaxRoi) {
      message.error("ROI 下限不能高于上限");
      return;
    }
    setCreating(true);
    try {
      await http.post("/promotions/strategies", {
        store_id: currentStore.id,
        name: createName.trim(),
        action_type: createActionType.trim(),
        conditions: createConditions.trim(),
        evidence: createEvidence.trim(),
        scene: createScene.trim(),
        min_roi: createMinRoi,
        max_roi: createMaxRoi,
      });
      message.success("人工经验已添加，等待真实验证");
      setCreateOpen(false);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setCreating(false);
    }
  };
  const verified = records.filter((item) => !["planned", "observing"].includes(item.status));
  const successRate = verified.length ? Math.round((records.filter((item) => item.status === "success").length / verified.length) * 100) : 0;
  const successStrategies = strategies.filter((item) => !item.outcome || item.outcome === "success").length;
  const cautionStrategies = strategies.filter((item) => item.outcome === "failed" || item.outcome === "partial").length;
  const pendingStrategies = strategies.filter((item) => item.verification_status === "pending").length;
  const filteredStrategies = strategies.filter((item) => {
    if (strategyFilter === "active") return item.status !== "inactive";
    if (strategyFilter === "inactive") return item.status === "inactive";
    if (strategyFilter === "success") return !item.outcome || item.outcome === "success";
    if (strategyFilter === "caution") return item.outcome === "failed" || item.outcome === "partial";
    if (strategyFilter === "pending") return item.verification_status === "pending";
    return true;
  });
  return (
    <WorkspacePage kind="analysis">
      <PageHeader icon={<ExperimentOutlined />} eyebrow="推广管理" title="经验策略库" description="把已验证的调整结果沉淀为可复用证据，也可以先录入人工经验等待验证。" extra={<Space wrap><Button icon={<PlusOutlined />} onClick={openCreate}>添加人工经验</Button><Button onClick={() => void load()}>刷新策略</Button></Space>} />
      <DecisionBand
        eyebrow="经验健康度"
        title={cautionStrategies ? `${cautionStrategies} 条经验需要谨慎复用` : `${successStrategies} 条成功经验可供下一次决策参考`}
        description={`当前启用 ${strategies.filter((item) => item.status !== "inactive").length} 条策略 · ${pendingStrategies} 条人工经验待验证 · 动作验证成功率 ${successRate}%。待验证经验不会单独解锁执行。`}
        action={<Button type="primary" onClick={() => setStrategyFilter(cautionStrategies ? "caution" : "active")}>{cautionStrategies ? "检查风险经验" : "查看启用策略"}</Button>}
        ariaLabel="经验策略首要结论"
      />
      <Row gutter={[12, 12]}>
        <Col xs={12} sm={6}>
          <Card variant="borderless">
            <Statistic title="当前启用" value={strategies.filter((item) => item.status !== "inactive").length} styles={{ content: { color: "var(--ops-success)" } }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card variant="borderless">
            <Statistic title="成功经验" value={successStrategies} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card variant="borderless">
            <Statistic
              title="需谨慎复用"
              value={cautionStrategies}
              styles={{
                content: {
                  color: cautionStrategies ? "var(--ops-warn)" : undefined,
                },
              }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card variant="borderless">
            <Statistic title="待验证经验" value={pendingStrategies} />
          </Card>
        </Col>
      </Row>
      <Row gutter={[12, 12]} style={{ marginTop: 12 }}>
        <Col xs={24} md={16}>
          <Card variant="borderless" title="策略管理建议">
            <Space orientation="vertical" size={4}>
              <Text type="secondary">1. 先验证再复用：每条策略都保留来源动作和前后数据。</Text>
              <Text type="secondary">2. 条件要具体：补充 ROI 区间、场景、预算幅度和观察周期。</Text>
              <Text type="secondary">3. 发现异常及时停用：停用只影响推荐，不会删除历史证据。</Text>
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={8}>
          <Card variant="borderless" title="动作验证概览">
            <Statistic title="验证成功率" value={successRate} suffix="%" />
            <Text type="secondary">已验证 {verified.length} 个动作</Text>
          </Card>
        </Col>
      </Row>
      {strategyGroups.length ? (
        <Card variant="borderless" title="同类经验聚合" style={{ marginTop: 16 }}>
          <Table<StrategyGroup>
            rowKey="group_id"
            size="small"
            pagination={false}
            dataSource={strategyGroups}
            columns={[
              {
                title: "调整动作",
                dataIndex: "action_type",
                key: "action_type",
              },
              { title: "适用场景", dataIndex: "scene", key: "scene" },
              {
                title: "样本",
                dataIndex: "sample_count",
                key: "sample_count",
                width: 70,
              },
              {
                title: "成功 / 部分 / 失败",
                key: "outcomes",
                width: 150,
                render: (_: unknown, item: StrategyGroup) => `${item.success_count} / ${item.partial_count} / ${item.failed_count}`,
              },
              {
                title: "成功率",
                dataIndex: "success_rate",
                key: "success_rate",
                width: 90,
                render: (value: number) => `${value}%`,
              },
              {
                title: "平均证据分",
                dataIndex: "avg_evidence_score",
                key: "avg_evidence_score",
                width: 110,
              },
            ]}
          />
        </Card>
      ) : null}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        {[
          {
            title: "低效计划止损",
            icon: <ThunderboltOutlined />,
            text: "ROI 连续低于保本线时，降低预算或暂停，观察花费和利润是否改善。",
          },
          {
            title: "高效计划放量",
            icon: <CheckCircleOutlined />,
            text: "ROI 和成交规模同时健康时，小幅增加预算，验证边际 ROI 是否稳定。",
          },
          {
            title: "调整后复盘",
            icon: <FileTextOutlined />,
            text: "记录动作前后数据、外部干扰和最终结论，形成可复制的策略条件。",
          },
        ].map((item) => (
          <Col xs={24} md={8} key={item.title}>
            <Card
              variant="borderless"
              title={
                <Space>
                  {item.icon}
                  {item.title}
                </Space>
              }
            >
              <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                {item.text}
              </Paragraph>
              <Tag color="blue" style={{ marginTop: 14 }}>
                框架待沉淀
              </Tag>
            </Card>
          </Col>
        ))}
      </Row>
      <Card
        variant="borderless"
        title="已沉淀经验"
        style={{ marginTop: 16 }}
        extra={
          <Segmented
            size="small"
            value={strategyFilter}
            onChange={(value) => setStrategyFilter(value as typeof strategyFilter)}
            options={[
              { label: "全部", value: "all" },
              { label: "启用中", value: "active" },
              { label: "已停用", value: "inactive" },
              { label: "成功", value: "success" },
              { label: "需谨慎", value: "caution" },
              { label: "待验证", value: "pending" },
            ]}
          />
        }
      >
        {strategies.length ? (
          filteredStrategies.length ? (
            <WorkflowList
              dataSource={filteredStrategies}
              renderItem={(item) => (
                <WorkflowListItem
                  actions={[
                    <Button key="edit" type="link" icon={<EditOutlined />} onClick={() => openEdit(item)}>
                      编辑
                    </Button>,
                    <Button key="status" type="link" danger={item.status !== "inactive"} onClick={() => void toggleStatus(item)}>
                      {item.status === "inactive" ? "启用" : "停用"}
                    </Button>,
                  ]}
                >
                  <WorkflowListMeta
                    title={
                      <Space wrap>
                        {item.name}
                        <Tag color={item.verification_status === "pending" ? "default" : item.outcome === "failed" ? "red" : item.outcome === "partial" ? "orange" : "green"}>{item.verification_status === "pending" ? "人工经验 · 待验证" : item.outcome === "failed" ? "失败经验" : item.outcome === "partial" ? "部分有效" : `成功 ${item.success_count} 次`}</Tag>
                        <Tag color={item.verification_status === "pending" ? "default" : item.evidence_level === "high" ? "green" : item.evidence_level === "medium" ? "orange" : "default"}>{item.verification_status === "pending" ? "暂不计入证据" : `证据 ${item.evidence_score ?? 0} 分`}</Tag>
                        {item.sample_count ? (
                          <Tag color="purple">
                            同类 {item.sample_count} 次 · 成功率 {item.group_success_rate ?? 0}%
                          </Tag>
                        ) : null}
                        {item.scene ? <Tag color="blue">场景：{item.scene}</Tag> : null}
                        {item.min_roi != null || item.max_roi != null ? (
                          <Tag>
                            ROI {item.min_roi ?? "-∞"}~{item.max_roi ?? "+∞"}
                          </Tag>
                        ) : null}
                        {item.status === "inactive" ? <Tag>已停用</Tag> : null}
                      </Space>
                    }
                    description={
                      <Space orientation="vertical" size={2}>
                        <Text type="secondary">
                          动作：{item.action_type} · 被引用 {item.use_count} 次
                        </Text>
                        <Text>{item.conditions}</Text>
                        <Text type="secondary">{item.verification_status === "pending" ? "人工依据" : "证据"}：{item.evidence}</Text>
                      </Space>
                    }
                  />
                </WorkflowListItem>
              )}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选没有策略" />
          )
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="完成动作验证后，成功与失败经验都会出现在这里" />
        )}
      </Card>
      <Modal open={!!editing} title="编辑策略卡" onCancel={() => setEditing(null)} onOk={() => void saveEdit()} confirmLoading={saving} okText="保存">
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Input value={editName} onChange={(event) => setEditName(event.target.value)} placeholder="策略名称" />
          <Input value={editScene} onChange={(event) => setEditScene(event.target.value)} placeholder="适用场景（可选，留空表示不限）" />
          <Space>
            <InputNumber value={editMinRoi} onChange={(value) => setEditMinRoi(value)} min={0} precision={2} placeholder="ROI 下限" />
            <Text type="secondary">至</Text>
            <InputNumber value={editMaxRoi} onChange={(value) => setEditMaxRoi(value)} min={0} precision={2} placeholder="ROI 上限" />
          </Space>
          <Input.TextArea value={editConditions} onChange={(event) => setEditConditions(event.target.value)} autoSize={{ minRows: 3, maxRows: 8 }} placeholder="适用条件（例如 ROI 区间、场景、观察周期）" />
          <Text type="secondary">原始验证证据不可编辑，避免复盘数据被覆盖。</Text>
        </Space>
      </Modal>
      <Modal open={createOpen} title="添加人工经验" onCancel={() => setCreateOpen(false)} onOk={() => void createManualStrategy()} confirmLoading={creating} okText="添加并标记待验证" cancelText="取消" destroyOnHidden>
        <Alert type="info" showIcon title="人工经验不会直接变成历史证据" description="它会作为低可信参考展示给 AI；只有后续真实执行并完成验证，才会升级为可复用经验。" style={{ marginBottom: 14 }} />
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Space orientation="vertical" size={4} style={{ width: "100%" }}><Text strong>经验名称</Text><Input value={createName} onChange={(event) => setCreateName(event.target.value)} placeholder="例如：搜索推广低 ROI 先降出价" /></Space>
          <Space orientation="vertical" size={4} style={{ width: "100%" }}><Text strong>推荐动作</Text><Select value={createActionType || undefined} onChange={setCreateActionType} placeholder="选择系统可识别的调整动作" style={{ width: "100%" }} options={["降低预算/止损", "增加预算/放量", "降低出价/控成本", "排查投放/恢复消耗"].map((value) => ({ value, label: value }))} /></Space>
          <Space orientation="vertical" size={4} style={{ width: "100%" }}><Text strong>适用场景（可选）</Text><Select allowClear showSearch value={createScene || undefined} onChange={(value) => setCreateScene(value || "")} placeholder="不限场景" style={{ width: "100%" }} options={["货品全站推广", "关键词推广", "人群推广", "内容营销"].map((value) => ({ value, label: value }))} /></Space>
          <Space orientation="vertical" size={4} style={{ width: "100%" }}><Text strong>适用 ROI（可选）</Text><Space wrap><InputNumber value={createMinRoi} onChange={(value) => setCreateMinRoi(value)} min={0} precision={2} placeholder="下限" /><Text type="secondary">至</Text><InputNumber value={createMaxRoi} onChange={(value) => setCreateMaxRoi(value)} min={0} precision={2} placeholder="上限" /></Space></Space>
          <Space orientation="vertical" size={4} style={{ width: "100%" }}><Text strong>适用条件</Text><Input.TextArea value={createConditions} onChange={(event) => setCreateConditions(event.target.value)} rows={3} maxLength={1000} showCount placeholder="说明什么数据或经营情境下使用这条经验" /></Space>
          <Space orientation="vertical" size={4} style={{ width: "100%" }}><Text strong>经验依据</Text><Input.TextArea value={createEvidence} onChange={(event) => setCreateEvidence(event.target.value)} rows={3} maxLength={1000} showCount placeholder="说明经验来源，以及过去观察到的结果" /></Space>
        </Space>
      </Modal>
    </WorkspacePage>
  );
}
