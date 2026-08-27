import {
  CheckCircleOutlined,
  EditOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Input, InputNumber, Modal, Progress, Row, Segmented, Select, Space, Statistic, Table, Tag, Typography, message } from "antd";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/ui/page-header";
import { fmtMoney } from "../components/promotions/promotions-ui";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";
import type { PromoPlan } from "../types";

const { Paragraph, Text } = Typography;

function WorkflowList<T>({ dataSource, renderItem }: { dataSource: T[]; renderItem: (item: T, index: number) => ReactNode }) {
  return <Space orientation="vertical" size={0} style={{ width: "100%" }}>{dataSource.map((item, index) => <div key={index}>{renderItem(item, index)}</div>)}</Space>;
}

function WorkflowListItem({ actions, children }: { actions?: ReactNode[]; children: ReactNode }) {
  const visibleActions = (actions || []).filter(Boolean);
  return <div style={{ padding: "14px 0", borderBottom: "1px solid var(--ops-border)" }}><div>{children}</div>{visibleActions.length ? <Space wrap size={6} style={{ marginTop: 10 }}>{visibleActions}</Space> : null}</div>;
}

function WorkflowListMeta({ title, description }: { title: ReactNode; description?: ReactNode }) {
  return <div><div>{title}</div>{description ? <div style={{ marginTop: 5 }}>{description}</div> : null}</div>;
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
  strategy_score?: number | null;
  learning_weight?: number;
  learning_sample_count?: number;
  learning_explanation?: string;
  strategy_candidates?: DecisionStrategy[];
  strategy_conflict?: boolean;
  conflict_reason?: string;
  constraint_summary?: string;
};
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
};
type DecisionRecord = {
  id: number;
  decision_id: string;
  plan_id: number;
  plan_name?: string;
  scene_name?: string;
  strategy_id?: number | null;
  recommended_tier: DecisionOption["tier"];
  selected_tier: DecisionOption["tier"];
  feedback_status: "adopted" | "modified" | "rejected";
  workflow_status: "selected" | "rejected" | "planned" | "executed" | "verified";
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
  summary: { total: number; adopted: number; modified: number; rejected: number; executed: number; verified: number };
  tiers: { tier: DecisionOption["tier"]; name: string; selected: number; executed: number; verified: number; success: number; partial: number; failed: number; insufficient: number; success_rate: number }[];
  attribution: {
    summary: { manual_intervention: number; manual_intervention_rate: number; tier_changed: number; same_tier_adjustment: number; reason_coverage: number };
    reasons: { reason: string; count: number; share: number }[];
    directions: { key: "more_conservative" | "same_tier_adjustment" | "more_aggressive"; name: string; count: number }[];
    transitions: { recommended_tier: DecisionOption["tier"]; selected_tier: DecisionOption["tier"]; count: number }[];
    scenes: { scene_name: string; total: number; adopted: number; modified: number; rejected: number; manual_intervention_rate: number; verified: number; success_rate: number }[];
  };
};

const statusMeta: Record<ActionRecord["status"], { label: string; color: string }> = {
  planned: { label: "待执行", color: "gold" },
  observing: { label: "观察中", color: "blue" },
  success: { label: "验证成功", color: "green" },
  partial: { label: "部分有效", color: "orange" },
  failed: { label: "验证失败", color: "red" },
  insufficient: { label: "数据不足", color: "default" },
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
};
const decisionWorkflowMeta: Record<DecisionRecord["workflow_status"], { label: string; color: string }> = {
  selected: { label: "已选择", color: "cyan" },
  rejected: { label: "已拒绝", color: "default" },
  planned: { label: "待执行", color: "gold" },
  executed: { label: "观察中", color: "blue" },
  verified: { label: "已验证", color: "green" },
};
const decisionViewOptions = [
  { label: "决策工作区", value: "workspace" },
  { label: "决策归因", value: "attribution" },
  { label: "决策档案", value: "archive" },
];

function successCriteriaText(criteria: Record<string, number>): string {
  const labels: Record<string, string> = {
    target_roi_min: "最终 ROI≥",
    roi_change_min: "ROI 提升≥",
    sales_change_pct_min: "日均成交变化≥",
    spend_change_pct_max: "日均花费变化≤",
  };
  return Object.entries(criteria).map(([key, value]) => `${labels[key] || key}${value}${key.includes("pct") ? "%" : ""}`).join("；");
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

export function PromotionsWorkflowPage({ section }: { section: WorkflowSection }) {
  if (section === "decision") return <DecisionPage />;
  if (section === "validation") return <ValidationPage />;
  return <StrategiesPage />;
}

function DecisionPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { currentStore } = useStores();
  const targetPlanId = Number(searchParams.get("plan_id")) || null;
  const targetDecisionRecordId = Number(searchParams.get("decision_record_id")) || null;
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiReply, setAiReply] = useState<DecisionReply | null>(null);
  const [recordPlan, setRecordPlan] = useState<PromoPlan | null>(null);
  const [recording, setRecording] = useState(false);
  const [selectedStrategies, setSelectedStrategies] = useState<Record<number, number | undefined>>({});
  const [selectedOptions, setSelectedOptions] = useState<Record<number, DecisionOption["tier"]>>({});
  const [view, setView] = useState<DecisionView>("workspace");
  const [archive, setArchive] = useState<DecisionArchiveData | null>(null);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [savingDecisionId, setSavingDecisionId] = useState<number | null>(null);
  const [rejectDraft, setRejectDraft] = useState<DecisionDraft | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectNote, setRejectNote] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await http.get<{ items: PromoPlan[] }>(`/promotions/plans?mode=7d${currentStore ? `&store_id=${currentStore.id}` : ""}`);
      setPlans(response.data.items || []);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id]);

  useEffect(() => { void load(); }, [load]);

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
    setAiLoading(true);
    try {
      const response = await http.post<DecisionReply>(`/promotions/insight?mode=7d${currentStore ? `&store_id=${currentStore.id}` : ""}`);
      setAiReply(response.data);
      setSelectedOptions(Object.fromEntries((response.data.drafts || []).map((draft) => [draft.plan_id, draft.recommended_tier])));
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiLoading(false);
    }
  };

  const saveDecisionFeedback = async (
    draft: DecisionDraft,
    selectedOption: DecisionOption,
    feedbackStatus: DecisionRecord["feedback_status"],
    feedbackReason = "",
    feedbackNote = "",
  ): Promise<number> => {
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
    setSavingDecisionId(draft.plan_id);
    try {
      const feedbackStatus = selectedOption.tier === draft.recommended_tier ? "adopted" : "modified";
      const decisionRecordId = await saveDecisionFeedback(draft, selectedOption, feedbackStatus);
      const selectedStrategyId = selectedStrategies[draft.plan_id] ?? draft.strategy_id ?? undefined;
      const params = new URLSearchParams({
        plan_id: String(draft.plan_id),
        ...(draft.store_id ? { store_id: String(draft.store_id) } : {}),
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

  const recordAction = async () => {
    if (!recordPlan) return;
    setRecording(true);
    try {
      await http.post("/promotions/action-records", {
        plan_id: recordPlan.id,
        action_type: recordPlan.roi < 1 ? "降低预算/止损" : "增加预算/放量",
        description: recordPlan.roi < 1 ? "基于计划 ROI 偏低的决策建议，先记录动作并观察结果" : "基于计划 ROI 表现较好的决策建议，先记录动作并观察结果",
        expected: recordPlan.roi < 1 ? "ROI 回升且减少无效花费" : "成交规模增长且 ROI 不明显下降",
        observation_hours: 48,
        success_criteria: recordPlan.roi < 1
          ? { roi_change_min: 0.1, spend_change_pct_max: -5 }
          : { target_roi_min: Math.max(1, Number((recordPlan.roi * 0.85).toFixed(2))), sales_change_pct_min: 5 },
      });
      message.success("已建立观察验证任务");
      setRecordPlan(null);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setRecording(false);
    }
  };

  const activePlans = useMemo(() => plans.filter((plan) => plan.status === "在投"), [plans]);
  const focusedActivePlans = targetPlanId ? activePlans.filter((plan) => plan.id === targetPlanId) : activePlans;
  const focusedDrafts = targetPlanId ? (aiReply?.drafts || []).filter((draft) => draft.plan_id === targetPlanId) : (aiReply?.drafts || []);
  const focusedArchiveItems = targetDecisionRecordId ? (archive?.items || []).filter((item) => item.id === targetDecisionRecordId) : (archive?.items || []);
  const counts = useMemo(() => ({
    healthy: activePlans.filter((plan) => plan.spend > 0 && plan.roi >= 2).length,
    watch: activePlans.filter((plan) => plan.spend > 0 && plan.roi >= 1 && plan.roi < 2).length,
    stop: activePlans.filter((plan) => plan.spend > 0 && plan.roi < 1).length,
  }), [activePlans]);

  const archiveSummary = archive?.summary || { total: 0, adopted: 0, modified: 0, rejected: 0, executed: 0, verified: 0 };
  const attribution = archive?.attribution || {
    summary: { manual_intervention: 0, manual_intervention_rate: 0, tier_changed: 0, same_tier_adjustment: 0, reason_coverage: 0 },
    reasons: [],
    directions: [],
    transitions: [],
    scenes: [],
  };

  if (view === "attribution") {
    return (
      <div>
        <PageHeader
          icon={<ExperimentOutlined />}
          eyebrow="推广管理"
          title="AI 决策归因"
          description="分析运营人员为什么修改或拒绝 AI 方案，识别档位偏差、业务约束与高干预场景。"
          extra={<Space wrap><Segmented value={view} onChange={(value) => setView(value as DecisionView)} options={decisionViewOptions} /><Button loading={archiveLoading} onClick={() => void loadArchive()}>刷新归因</Button></Space>}
        />
        <Alert type="info" showIcon title="归因结果用于校正建议，不会直接改变投放计划" description="建议累计足够的人工反馈和验证样本后，再把归因结果用于自动调整策略权重。" style={{ marginBottom: 16 }} />
        <Row gutter={[12, 12]}>
          {[
            { label: "人工干预", value: attribution.summary.manual_intervention, suffix: "次" },
            { label: "人工干预率", value: attribution.summary.manual_intervention_rate, suffix: "%" },
            { label: "跨档修改", value: attribution.summary.tier_changed, suffix: "次" },
            { label: "拒绝原因覆盖", value: attribution.summary.reason_coverage, suffix: "%" },
          ].map((item) => <Col xs={12} sm={6} key={item.label}><Card variant="borderless"><Statistic title={item.label} value={item.value} suffix={item.suffix} /></Card></Col>)}
        </Row>
        <Row gutter={[12, 12]} style={{ marginTop: 16 }}>
          <Col xs={24} lg={12}>
            <Card variant="borderless" title="拒绝原因与业务约束" loading={archiveLoading} style={{ height: "100%" }}>
              {!archiveLoading && attribution.reasons.length === 0 ? <Empty description="暂无拒绝反馈"><Button type="primary" onClick={() => setView("workspace")}>返回决策工作区</Button></Empty> : <Table
                rowKey="reason"
                size="small"
                pagination={false}
                dataSource={attribution.reasons}
                columns={[
                  { title: "原因", dataIndex: "reason", key: "reason" },
                  { title: "次数", dataIndex: "count", key: "count", width: 72 },
                  { title: "占拒绝方案", key: "share", width: 150, render: (_: unknown, item: DecisionArchiveData["attribution"]["reasons"][number]) => <Progress percent={item.share} size="small" /> },
                ]}
              />}
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card variant="borderless" title="人工修改方向" loading={archiveLoading} style={{ height: "100%" }}>
              {!archiveLoading && archiveSummary.modified === 0 ? <Empty description="暂无人工修改记录"><Button type="primary" onClick={() => setView("workspace")}>返回决策工作区</Button></Empty> : <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                <Table
                  rowKey="key"
                  size="small"
                  pagination={false}
                  dataSource={attribution.directions}
                  columns={[
                    { title: "调整方向", dataIndex: "name", key: "name" },
                    { title: "次数", dataIndex: "count", key: "count", width: 72 },
                    { title: "占修改方案", key: "share", width: 150, render: (_: unknown, item: DecisionArchiveData["attribution"]["directions"][number]) => <Progress percent={archiveSummary.modified ? Number((item.count / archiveSummary.modified * 100).toFixed(1)) : 0} size="small" /> },
                  ]}
                />
                {attribution.transitions.length ? <Space wrap><Text type="secondary">档位迁移：</Text>{attribution.transitions.map((item) => <Tag key={`${item.recommended_tier}-${item.selected_tier}`}>{decisionTierMeta[item.recommended_tier].label} → {decisionTierMeta[item.selected_tier].label} · {item.count}</Tag>)}</Space> : null}
              </Space>}
            </Card>
          </Col>
        </Row>
        <Card variant="borderless" title="场景人工干预分析" style={{ marginTop: 16 }} loading={archiveLoading}>
          {!archiveLoading && attribution.scenes.length === 0 ? <Empty description="暂无可分析的决策样本"><Button type="primary" onClick={() => setView("workspace")}>生成并处理决策方案</Button></Empty> : <Table<DecisionArchiveData["attribution"]["scenes"][number]>
            rowKey="scene_name"
            size="small"
            pagination={false}
            scroll={{ x: 850 }}
            dataSource={attribution.scenes}
            columns={[
              { title: "推广场景", dataIndex: "scene_name", key: "scene_name", width: 180 },
              { title: "决策数", dataIndex: "total", key: "total", width: 80 },
              { title: "采纳", dataIndex: "adopted", key: "adopted", width: 72 },
              { title: "修改", dataIndex: "modified", key: "modified", width: 72 },
              { title: "拒绝", dataIndex: "rejected", key: "rejected", width: 72 },
              { title: "人工干预率", key: "manual_intervention_rate", width: 160, render: (_: unknown, item) => <Progress percent={item.manual_intervention_rate} size="small" /> },
              { title: "已验证", dataIndex: "verified", key: "verified", width: 80 },
              { title: "验证成功率", key: "success_rate", width: 160, render: (_: unknown, item) => <Progress percent={item.success_rate} size="small" /> },
            ]}
          />}
        </Card>
      </div>
    );
  }

  if (view === "archive") {
    return (
      <div>
        <PageHeader
          icon={<FileTextOutlined />}
          eyebrow="推广管理"
          title="AI 决策档案"
          description="追踪每次 AI 建议、人工选择、执行状态与最终验证结果，让后续建议有真实经验可依。"
          extra={<Space wrap><Segmented value={view} onChange={(value) => setView(value as DecisionView)} options={decisionViewOptions} /><Button loading={archiveLoading} onClick={() => void loadArchive()}>刷新档案</Button></Space>}
        />
        <Alert type="info" showIcon title="学习闭环从真实动作与验证结果中积累" description="未执行、数据不足和被拒绝的方案都会保留，但只有完成验证的结果才会用于评估方案档位效果。" style={{ marginBottom: 16 }} />
        {targetDecisionRecordId && !archiveLoading && focusedArchiveItems.length === 0 ? <Alert type="error" showIcon title="目标决策记录不存在或不在当前店铺范围" style={{ marginBottom: 16 }} /> : null}
        <Row gutter={[12, 12]}>
          {[
            { label: "决策总数", value: archiveSummary.total },
            { label: "直接采纳", value: archiveSummary.adopted },
            { label: "人工修改", value: archiveSummary.modified },
            { label: "拒绝方案", value: archiveSummary.rejected },
            { label: "已执行", value: archiveSummary.executed },
            { label: "已验证", value: archiveSummary.verified },
          ].map((item) => <Col xs={12} sm={8} lg={4} key={item.label}><Card variant="borderless"><Statistic title={item.label} value={item.value} /></Card></Col>)}
        </Row>
        <Card variant="borderless" title="稳健 / 平衡 / 激进方案效果" style={{ marginTop: 16 }} loading={archiveLoading}>
          <Table<DecisionArchiveData["tiers"][number]>
            rowKey="tier"
            pagination={false}
            dataSource={archive?.tiers || []}
            columns={[
              { title: "方案", key: "name", render: (_: unknown, item) => <Tag color={decisionTierMeta[item.tier].color}>{item.name}</Tag> },
              { title: "已选择", dataIndex: "selected", key: "selected" },
              { title: "已执行", dataIndex: "executed", key: "executed" },
              { title: "已验证", dataIndex: "verified", key: "verified" },
              { title: "成功 / 部分 / 失败", key: "result", render: (_: unknown, item) => <Space><Text type="success">{item.success}</Text><Text type="warning">{item.partial}</Text><Text type="danger">{item.failed}</Text></Space> },
              { title: "数据不足", dataIndex: "insufficient", key: "insufficient" },
              { title: "成功率", key: "success_rate", render: (_: unknown, item) => <Progress percent={item.success_rate} size="small" style={{ minWidth: 120 }} /> },
            ]}
          />
        </Card>
        <Card variant="borderless" title="决策时间线" style={{ marginTop: 16 }} loading={archiveLoading}>
          {!archiveLoading && !focusedArchiveItems.length ? <Empty description="暂无决策档案，先在决策工作区生成并处理一批方案"><Button type="primary" onClick={() => setView("workspace")}>返回决策工作区</Button></Empty> : <WorkflowList
            dataSource={focusedArchiveItems}
            renderItem={(item) => {
              const feedback = decisionFeedbackMeta[item.feedback_status];
              const workflow = decisionWorkflowMeta[item.workflow_status];
              const result = item.result_status && item.result_status !== "planned" && item.result_status !== "observing" ? statusMeta[item.result_status] : null;
              return <WorkflowListItem><WorkflowListMeta
                title={<Space wrap><Text strong>{item.plan_name || `计划 ${item.plan_id}`}</Text><Tag>{item.scene_name || "未标注场景"}</Tag><Tag color={decisionTierMeta[item.selected_tier].color}>{decisionTierMeta[item.selected_tier].label}方案</Tag><Tag color={feedback.color}>{feedback.label}</Tag><Tag color={workflow.color}>{workflow.label}</Tag>{result ? <Tag color={result.color}>{result.label}</Tag> : null}</Space>}
                description={<Space orientation="vertical" size={4} style={{ width: "100%" }}><Text type="secondary">AI 建议 {decisionTierMeta[item.recommended_tier].label}档 {formatDelta(item.ai_change_pct, "%")}；最终 {decisionTierMeta[item.selected_tier].label}档 {formatDelta(item.final_change_pct, "%")} · 观察 {item.final_observation_hours} 小时</Text>{item.feedback_reason ? <Text>拒绝原因：{item.feedback_reason}{item.feedback_note ? ` · ${item.feedback_note}` : ""}</Text> : null}{item.result_summary ? <Text>验证结论：{item.result_summary}</Text> : null}<Text type="secondary">更新于 {formatDate(item.updated_at)}</Text></Space>}
              /></WorkflowListItem>;
            }}
          />}
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader icon={<RobotOutlined />} eyebrow="推广管理" title="AI 决策中心" description="用真实计划数据生成可解释的调整方案，确认后进入执行与验证。" extra={<Space wrap><Segmented value={view} onChange={(value) => setView(value as DecisionView)} options={decisionViewOptions} /><Button onClick={() => void load()}>刷新数据</Button><Button type="primary" icon={<RobotOutlined />} loading={aiLoading} onClick={() => void runAi()}>生成 AI 决策方案</Button></Space>} />
      <Alert type="info" showIcon title="AI 只提供决策草案，不会自动修改万相台" description="确认方案后，请在计划执行中心完成调整；每个动作都应建立观察验证任务。" style={{ marginBottom: 16 }} />
      {targetPlanId && !loading && focusedActivePlans.length === 0 ? <Alert type="error" showIcon title="目标计划不存在、不在投或不在当前店铺范围" style={{ marginBottom: 16 }} /> : null}
      <Row gutter={[12, 12]}>
        {[{ label: "在投计划", value: activePlans.length }, { label: "健康计划", value: counts.healthy }, { label: "需要观察", value: counts.watch }, { label: "建议止损", value: counts.stop }].map((item) => <Col xs={12} sm={6} key={item.label}><Card variant="borderless"><Statistic title={item.label} value={item.value} /></Card></Col>)}
      </Row>
      {aiReply ? <Card variant="borderless" title={<Space><RobotOutlined />本次 AI 决策方案</Space>} style={{ marginTop: 16 }}>
        {focusedDrafts.length ? <div style={{ marginBottom: 16 }}>
          <Text strong style={{ display: "block", marginBottom: 8 }}>稳健 / 平衡 / 激进方案对比（需人工确认）</Text>
          <WorkflowList dataSource={focusedDrafts} renderItem={(draft) => {
            const selectedTier = selectedOptions[draft.plan_id] || draft.recommended_tier;
            const selectedOption = draft.options.find((option) => option.tier === selectedTier) || draft.options[0];
            return <WorkflowListItem actions={[
              <Button key="reject" danger size="small" onClick={() => { setRejectDraft(draft); setRejectReason(""); setRejectNote(""); }}>拒绝方案</Button>,
              <Button key="execute" type="primary" size="small" loading={savingDecisionId === draft.plan_id} onClick={() => void openExecutionPreview(draft, selectedOption)}>按{selectedOption.tier_label}方案执行预览</Button>,
            ]}><WorkflowListMeta title={<Space wrap><Text strong>{draft.plan_name}</Text><Tag>{draft.scene_name}</Tag><Tag color={draft.priority === "urgent" ? "red" : draft.priority === "growth" ? "green" : "orange"}>{draft.priority_label}</Tag><Tag>{draft.action_type}</Tag><Tag color={draft.recommended_tier === "aggressive" ? "red" : draft.recommended_tier === "balanced" ? "blue" : "green"}>推荐：{draft.options.find((option) => option.tier === draft.recommended_tier)?.tier_label}</Tag>{selectedOption.tier !== draft.recommended_tier ? <Tag color="blue">人工改选</Tag> : null}{draft.learning_sample_count ? <Tag color={Number(draft.learning_weight || 1) >= 1 ? "green" : "orange"}>学习权重 {Number(draft.learning_weight || 1).toFixed(2)} · {draft.learning_sample_count} 条</Tag> : null}{draft.constraint_summary ? <Tag color="orange">业务约束</Tag> : null}{draft.strategy_conflict ? <Tag color="red">证据冲突</Tag> : draft.strategy_name ? <Tag color="purple">证据 {draft.strategy_score ?? 0} 分</Tag> : <Tag>暂无匹配经验</Tag>}</Space>} description={<Space orientation="vertical" size={8} style={{ width: "100%" }}><Text type="secondary">{draft.reason}</Text><Table<DecisionOption> rowKey="tier" size="small" pagination={false} dataSource={draft.options} scroll={{ x: 900 }} columns={[
              { title: "方案", key: "tier", width: 100, render: (_: unknown, option: DecisionOption) => <Space><Tag color={option.tier === "aggressive" ? "red" : option.tier === "balanced" ? "blue" : "green"}>{option.tier_label}</Tag>{option.recommended ? <Tag color="gold">AI 推荐</Tag> : null}</Space> },
              { title: "调整幅度", key: "change", width: 110, render: (_: unknown, option: DecisionOption) => `${option.change_pct > 0 ? "+" : ""}${option.change_pct}%` },
              { title: "预期", dataIndex: "expected", key: "expected", width: 220 },
              { title: "成功标准", key: "criteria", width: 230, render: (_: unknown, option: DecisionOption) => successCriteriaText(option.success_criteria) },
              { title: "回退条件", dataIndex: "rollback_condition", key: "rollback_condition", width: 260 },
              { title: "选择", key: "select", fixed: "right", width: 86, render: (_: unknown, option: DecisionOption) => <Button size="small" type={selectedTier === option.tier ? "primary" : "default"} onClick={() => setSelectedOptions((current) => ({ ...current, [draft.plan_id]: option.tier }))}>{selectedTier === option.tier ? "已选择" : "选择"}</Button> },
            ]} /><Alert type={draft.strategy_conflict || draft.constraint_summary ? "warning" : "info"} showIcon title={draft.strategy_conflict ? draft.conflict_reason : selectedOption.evidence_summary} description={<Space orientation="vertical" size={6} style={{ width: "100%" }}>{draft.strategy_name ? <Space wrap>{draft.strategy_candidates?.map((strategy) => <Button key={strategy.id} size="small" type={(selectedStrategies[draft.plan_id] ?? draft.strategy_id) === strategy.id ? "primary" : "default"} danger={strategy.outcome === "failed"} onClick={() => setSelectedStrategies((current) => ({ ...current, [draft.plan_id]: strategy.id }))}>{strategy.name} · {strategy.outcome === "failed" ? "失败" : strategy.outcome === "partial" ? "部分有效" : "成功"} · 证据 {strategy.evidence_score ?? 0} 分 · 学习 {Number(strategy.learning_weight || 1).toFixed(2)} · 同类 {strategy.sample_count ?? 1} 次</Button>)}</Space> : null}{draft.learning_sample_count ? <Text type="secondary">学习说明：{draft.learning_explanation}</Text> : null}{draft.constraint_summary ? <Text type="warning">业务约束：{draft.constraint_summary}</Text> : null}</Space>} /><Text type="secondary">共同风险：{selectedOption.risk} · 观察 {selectedOption.observation_hours} 小时</Text></Space>} /></WorkflowListItem>;
          }} />
        </div> : null}
        {aiReply.strategy_groups?.length ? <Alert type="success" showIcon title="本次决策已合并同类历史经验" description={<Space wrap>{aiReply.strategy_groups.slice(0, 6).map((group) => <Tag color="green" key={group.group_id}>{group.action_type} · {group.scene} · 样本 {group.sample_count} · 成功率 {group.success_rate}% · 证据 {group.avg_evidence_score}</Tag>)}</Space>} style={{ marginBottom: 14 }} /> : null}
        {aiReply.sections ? Object.entries(aiReply.sections).map(([title, value]) => <div key={title} style={{ marginBottom: 12 }}><Text strong>{title}</Text><Paragraph type="secondary" style={{ whiteSpace: "pre-wrap", margin: "4px 0 0" }}>{Array.isArray(value) ? value.join("\n") : value}</Paragraph></div>) : <Paragraph style={{ whiteSpace: "pre-wrap" }}>{aiReply.reply}</Paragraph>}
      </Card> : null}
      <Card variant="borderless" title="需要决策的在投计划" style={{ marginTop: 16 }} loading={loading}>
        {!loading && focusedActivePlans.length === 0 ? <Empty description="暂无在投计划数据，请先同步推广计划" /> : <WorkflowList dataSource={focusedActivePlans} renderItem={(plan) => {
          const recommendation = plan.roi >= 2 ? "建议评估放量" : plan.roi > 0 && plan.roi < 1 ? "建议止损观察" : "建议继续观察";
          const color = plan.roi >= 2 ? "green" : plan.roi > 0 && plan.roi < 1 ? "red" : "orange";
          return <WorkflowListItem actions={[<Button key="record" type="link" onClick={() => setRecordPlan(plan)}>记录调整动作</Button>]}><WorkflowListMeta title={<Space>{plan.plan_name}<Tag>{plan.scene_name}</Tag><Tag color={color}>{recommendation}</Tag></Space>} description={<Space wrap><Text type="secondary">花费 {fmtMoney(plan.spend)}</Text><Text type="secondary">成交 {fmtMoney(plan.sales)}</Text><Text type="secondary">ROI {plan.roi.toFixed(2)}</Text><Text type="secondary">状态 {plan.status}</Text></Space>} /></WorkflowListItem>;
        }} />}
      </Card>
      <Modal
        open={!!rejectDraft}
        title="拒绝本次 AI 方案"
        onCancel={() => setRejectDraft(null)}
        onOk={() => void rejectDecision()}
        okText="确认拒绝并记录"
        okButtonProps={{ danger: true, disabled: !rejectReason }}
        confirmLoading={!!rejectDraft && savingDecisionId === rejectDraft.plan_id}
        destroyOnHidden
      >
        <Paragraph type="secondary">记录真实拒绝原因，后续复盘时可识别库存、利润、活动与预算等业务约束。</Paragraph>
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Select
            value={rejectReason || undefined}
            onChange={setRejectReason}
            placeholder="请选择拒绝原因"
            style={{ width: "100%" }}
            options={["库存不足", "利润空间不足", "活动临近", "预算限制", "当前不适合调整", "AI 判断不合理", "其他"].map((value) => ({ value, label: value }))}
          />
          <Input.TextArea value={rejectNote} onChange={(event) => setRejectNote(event.target.value)} rows={3} maxLength={300} showCount placeholder="补充说明（可选）" />
        </Space>
      </Modal>
      <Modal open={!!recordPlan} title="建立观察验证任务" onCancel={() => setRecordPlan(null)} onOk={() => void recordAction()} confirmLoading={recording} okText="建立任务">
        {recordPlan ? <Paragraph>将为「{recordPlan.plan_name}」记录一次基于当前 ROI {recordPlan.roi.toFixed(2)} 的调整动作。执行调整后，系统会在观察窗口内比较前后数据。</Paragraph> : null}
      </Modal>
    </div>
  );
}

function ValidationPage() {
  const [searchParams] = useSearchParams();
  const { currentStore } = useStores();
  const targetActionId = Number(searchParams.get("action_id")) || null;
  const [records, setRecords] = useState<ActionRecord[]>([]);
  const [summary, setSummary] = useState<VerificationSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState<number | null>(null);
  const [view, setView] = useState<"queue" | "dashboard">("queue");
  const [filter, setFilter] = useState<"all" | "planned" | "observing" | "ready" | "completed">("all");
  const [reviewRecord, setReviewRecord] = useState<ActionRecord | null>(null);
  const [targetRoi, setTargetRoi] = useState<number | null>(null);
  const [roiChangeMin, setRoiChangeMin] = useState<number | null>(null);
  const [salesChangeMin, setSalesChangeMin] = useState<number | null>(null);
  const [spendChangeMax, setSpendChangeMax] = useState<number | null>(null);
  const [interferenceNotes, setInterferenceNotes] = useState("");
  const [manualConclusion, setManualConclusion] = useState("");
  const [reviewSaving, setReviewSaving] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [recordResponse, summaryResponse] = await Promise.all([
        http.get<{ items: ActionRecord[] }>(`/promotions/action-records${currentStore ? `?store_id=${currentStore.id}` : ""}`),
        http.get<VerificationSummary>(`/promotions/action-records/summary${currentStore ? `?store_id=${currentStore.id}` : ""}`),
      ]);
      setRecords(recordResponse.data.items || []);
      setSummary(summaryResponse.data);
    } catch (error) { message.error(getApiErrorMessage(error)); } finally { setLoading(false); }
  }, [currentStore?.id]);
  useEffect(() => { void load(); }, [load]);
  const verify = async (id: number) => {
    setVerifying(id);
    try { await http.post(`/promotions/action-records/${id}/verify`); message.success("验证完成"); await load(); } catch (error) { message.error(getApiErrorMessage(error)); } finally { setVerifying(null); }
  };
  const markExecuted = async (id: number) => {
    setVerifying(id);
    try { await http.post(`/promotions/action-records/${id}/mark-executed`); message.success("已进入观察窗口"); await load(); } catch (error) { message.error(getApiErrorMessage(error)); } finally { setVerifying(null); }
  };
  const openReview = (record: ActionRecord) => {
    setReviewRecord(record);
    setTargetRoi(record.success_criteria?.target_roi_min ?? null);
    setRoiChangeMin(record.success_criteria?.roi_change_min ?? null);
    setSalesChangeMin(record.success_criteria?.sales_change_pct_min ?? null);
    setSpendChangeMax(record.success_criteria?.spend_change_pct_max ?? null);
    setInterferenceNotes(record.interference_notes || "");
    setManualConclusion(record.manual_conclusion || "");
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
      await http.put(`/promotions/action-records/${reviewRecord.id}/review`, { success_criteria: criteria, interference_notes: interferenceNotes, manual_conclusion: manualConclusion });
      message.success("验证设置已保存");
      setReviewRecord(null);
      await load();
    } catch (error) { message.error(getApiErrorMessage(error)); } finally { setReviewSaving(false); }
  };
  const observing = records.filter((item) => item.status === "observing").length;
  const ready = records.filter(isVerificationDue).length;
  const visibleRecords = records.filter((item) => {
    if (filter === "all") return true;
    if (filter === "ready") return isVerificationDue(item);
    if (filter === "completed") return !["planned", "observing"].includes(item.status);
    return item.status === filter;
  });
  const focusedRecords = targetActionId ? visibleRecords.filter((item) => item.id === targetActionId) : visibleRecords;
  return <div>
    <PageHeader icon={<SafetyCertificateOutlined />} eyebrow="推广管理" title="观察验证" description="追踪每次调整动作的观察窗口，并用前后日报数据判断结果。" extra={<Space><Segmented value={view} onChange={(value) => setView(value as typeof view)} options={[{ label: "任务队列", value: "queue" }, { label: "结果看板", value: "dashboard" }]} /><Button onClick={() => void load()}>刷新</Button></Space>} />
    {view === "dashboard" ? <ValidationDashboard summary={summary} loading={loading} /> : <>
      <Alert type="info" showIcon title="验证以动作前 3 天基线和观察窗口内的计划日报为依据" description="数据不足或观察窗口未结束时，系统不会强行判定好坏；请先完成同步或等待截止时间。" style={{ marginBottom: 16 }} />
      {targetActionId && !loading && focusedRecords.length === 0 ? <Alert type="error" showIcon title="目标观察任务不存在或不在当前店铺范围" style={{ marginBottom: 16 }} /> : null}
      <Row gutter={[12, 12]}><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="全部动作" value={records.length} /></Card></Col><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="观察中" value={observing} styles={{ content: { color: "var(--ops-accent)" } }} /></Card></Col><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="可立即验证" value={ready} styles={{ content: { color: ready ? "var(--ops-warn)" : undefined } }} /></Card></Col><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="验证成功" value={records.filter((item) => item.status === "success").length} styles={{ content: { color: "var(--ops-success)" } }} /></Card></Col></Row>
      {ready > 0 ? <Alert type="warning" showIcon title={`${ready} 个观察任务已到期，可立即验证`} style={{ marginTop: 16 }} /> : null}
      <Card variant="borderless" title="调整动作队列" style={{ marginTop: 16 }} loading={loading} extra={<Segmented size="small" value={filter} onChange={(value) => setFilter(value as typeof filter)} options={[{ label: "全部", value: "all" }, { label: "待执行", value: "planned" }, { label: "观察中", value: "observing" }, { label: `可验证 ${ready}`, value: "ready" }, { label: "已完成", value: "completed" }]} />}>
        {!loading && records.length === 0 ? <Empty description="还没有动作记录；可从 AI 决策中心建立观察任务" /> : focusedRecords.length === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选没有动作" /> : <WorkflowList dataSource={focusedRecords} renderItem={(item) => {
          const confidence = item.confidence ? confidenceMeta[item.confidence] : null;
          const metrics = item.metric_summary || {};
          const verificationDue = isVerificationDue(item);
          return <WorkflowListItem actions={[<Button key="review" size="small" onClick={() => openReview(item)}>{item.status === "planned" || item.status === "observing" ? "验证设置" : "补充复盘"}</Button>, item.status === "planned" ? <Button key="executed" type="primary" size="small" loading={verifying === item.id} onClick={() => void markExecuted(item.id)}>标记已执行</Button> : null, item.status === "observing" ? <Button key="verify" type={verificationDue ? "primary" : "default"} size="small" disabled={!verificationDue} loading={verifying === item.id} onClick={() => void verify(item.id)}>{verificationDue ? "立即验证" : "等待窗口"}</Button> : null]}><WorkflowListMeta title={<Space wrap>{item.plan_name || `计划 ${item.plan_id}`}<Tag color={statusMeta[item.status].color}>{statusMeta[item.status].label}</Tag>{verificationDue ? <Tag color="orange">已到期</Tag> : null}{confidence ? <Tag color={confidence.color}>{confidence.label}</Tag> : null}<Tag>{item.action_type}</Tag>{item.decision_id ? <Tag color="purple">决策 {item.decision_id.slice(-8)}</Tag> : null}</Space>} description={<Space orientation="vertical" size={3}><Text type="secondary">{item.executed_at ? `执行时间 ${formatDate(item.executed_at)}` : `尚未执行 · 创建于 ${formatDate(item.created_at)}`} · 观察 {item.observation_hours} 小时{item.observation_due_at ? ` · 截止 ${formatDate(item.observation_due_at)}` : ""}</Text><Text type="secondary">基线：日均花费 {fmtMoney(metrics.before_daily_spend ?? item.before_spend)} · 日均成交 {fmtMoney(metrics.before_daily_sales ?? item.before_sales)} · ROI {item.before_roi.toFixed(2)}</Text>{item.after_roi != null && ["success", "partial", "failed", "insufficient"].includes(item.status) ? <Text type="secondary">观察：日均花费 {fmtMoney(metrics.after_daily_spend ?? item.after_spend ?? 0)} · 日均成交 {fmtMoney(metrics.after_daily_sales ?? item.after_sales ?? 0)} · ROI {item.after_roi.toFixed(2)}</Text> : null}{metrics.sales_change_pct != null || metrics.spend_change_pct != null ? <Text type="secondary">变化：日均成交 {metrics.sales_change_pct != null ? `${metrics.sales_change_pct > 0 ? "+" : ""}${metrics.sales_change_pct}%` : "—"} · 日均花费 {metrics.spend_change_pct != null ? `${metrics.spend_change_pct > 0 ? "+" : ""}${metrics.spend_change_pct}%` : "—"} · ROI {metrics.roi_change != null ? `${metrics.roi_change > 0 ? "+" : ""}${metrics.roi_change}` : "—"}</Text> : null}{item.result ? <Text>{item.result}</Text> : <Text type="secondary">预期：{item.expected || "待补充"}</Text>}{item.rollback_condition ? <Text type="warning">回退条件：{item.rollback_condition}</Text> : null}{item.interference_notes ? <Text type="warning">干扰因素：{item.interference_notes}</Text> : null}{item.manual_conclusion ? <Text>人工结论：{item.manual_conclusion}</Text> : null}{item.data_quality ? <Text type="secondary">数据质量：{item.data_quality}</Text> : null}</Space>} /></WorkflowListItem>;
        }} />}
      </Card>
    </>}
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
        <Input.TextArea value={manualConclusion} onChange={(event) => setManualConclusion(event.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} placeholder="人工复盘结论：是否回退、继续观察或进行二次调整" />
      </Space>
    </Modal>
  </div>;
}

function ValidationDashboard({ summary, loading }: { summary: VerificationSummary | null; loading: boolean }) {
  if (loading) return <Card variant="borderless" loading />;
  if (!summary || summary.totals.actions === 0) return <Card variant="borderless"><Empty description="完成动作验证后，这里会生成结果分析" /></Card>;

  const groupColumns = [
    { title: "分组", dataIndex: "name", key: "name", ellipsis: true },
    { title: "有效结论", dataIndex: "conclusive", key: "conclusive", width: 90 },
    { title: "成功 / 部分 / 失败", key: "outcomes", width: 150, render: (_: unknown, item: VerificationGroup) => `${item.success} / ${item.partial} / ${item.failed}` },
    { title: "成功率", dataIndex: "success_rate", key: "success_rate", width: 90, render: (value: number) => `${value}%` },
    { title: "平均 ROI 变化", dataIndex: "avg_roi_change", key: "avg_roi_change", width: 120, render: (value: number | null) => formatDelta(value) },
    { title: "日均成交变化", dataIndex: "avg_sales_change_pct", key: "avg_sales_change_pct", width: 120, render: (value: number | null) => formatDelta(value, "%") },
  ];
  const confidenceTotal = summary.confidence.reduce((total, item) => total + item.count, 0);
  const outcomeColors: Record<ActionRecord["status"], string> = { planned: "var(--ops-warn)", observing: "var(--ops-accent)", success: "var(--ops-success)", partial: "var(--ops-warn)", failed: "var(--ops-danger)", insufficient: "var(--ops-text-secondary)" };

  return <>
    <Alert type="info" showIcon title="成功率只统计已有明确结论的动作" description="数据不足样本不会计入成功率；平均变化同样只使用成功、部分有效和失败样本，避免低可信数据稀释判断。" style={{ marginBottom: 16 }} />
    <Row gutter={[12, 12]}>
      <Col xs={12} lg={6}><Card variant="borderless"><Statistic title="有效结论" value={summary.totals.conclusive} suffix={`/ ${summary.totals.verified}`} /></Card></Col>
      <Col xs={12} lg={6}><Card variant="borderless"><Statistic title="验证成功率" value={summary.totals.success_rate} suffix="%" styles={{ content: { color: "var(--ops-success)" } }} /></Card></Col>
      <Col xs={12} lg={6}><Card variant="borderless"><Statistic title="平均 ROI 变化" value={formatDelta(summary.totals.avg_roi_change)} /></Card></Col>
      <Col xs={12} lg={6}><Card variant="borderless"><Statistic title="中高可信样本" value={summary.totals.reliable_rate} suffix="%" styles={{ content: { color: summary.totals.reliable_rate >= 70 ? "var(--ops-success)" : "var(--ops-warn)" } }} /></Card></Col>
    </Row>
    <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
      <Col xs={24} lg={12}><Card variant="borderless" title="动作结论分布"><Space orientation="vertical" size={10} style={{ width: "100%" }}>{summary.outcomes.map((item) => <div key={item.key}><Space style={{ width: "100%", justifyContent: "space-between" }}><Text>{item.name}</Text><Text type="secondary">{item.count}</Text></Space><Progress percent={summary.totals.actions ? Math.round(item.count / summary.totals.actions * 100) : 0} showInfo={false} strokeColor={outcomeColors[item.key]} /></div>)}</Space></Card></Col>
      <Col xs={24} lg={12}><Card variant="borderless" title="结论可信度"><Space orientation="vertical" size={10} style={{ width: "100%" }}>{summary.confidence.map((item) => <div key={item.key}><Space style={{ width: "100%", justifyContent: "space-between" }}><Text>{item.name}</Text><Text type="secondary">{item.count}</Text></Space><Progress percent={confidenceTotal ? Math.round(item.count / confidenceTotal * 100) : 0} showInfo={false} strokeColor={item.key === "high" ? "var(--ops-success)" : item.key === "medium" ? "var(--ops-warn)" : "var(--ops-danger)"} /></div>)}</Space>{confidenceTotal === 0 ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无已验证可信度数据" /> : null}</Card></Col>
    </Row>
    <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
      <Col xs={24} xl={12}><Card variant="borderless" title="不同调整动作的效果"><Table<VerificationGroup> rowKey="name" size="small" pagination={false} dataSource={summary.action_types} columns={groupColumns} scroll={{ x: 700 }} /></Card></Col>
      <Col xs={24} xl={12}><Card variant="borderless" title="不同推广场景的效果"><Table<VerificationGroup> rowKey="name" size="small" pagination={false} dataSource={summary.scenes} columns={groupColumns} scroll={{ x: 700 }} /></Card></Col>
    </Row>
    <Card variant="borderless" title="计划验证对比" style={{ marginTop: 16 }}><Table<VerificationGroup> rowKey="name" size="small" pagination={false} dataSource={summary.plans} columns={groupColumns} scroll={{ x: 700 }} /></Card>
    <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
      <Col xs={24} lg={8}><Card variant="borderless" title="复盘关注点">{summary.focuses.length ? <Space wrap>{summary.focuses.map((item) => <Tag key={item.name} color={item.name === "数据不足" ? "default" : "orange"}>{item.name} · {item.count}</Tag>)}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无风险关注点" />}</Card></Col>
      <Col xs={24} lg={16}><Card variant="borderless" title="近期需复盘动作">{summary.review_items.length ? <WorkflowList dataSource={summary.review_items} renderItem={(item) => <WorkflowListItem><WorkflowListMeta title={<Space wrap><Text strong>{item.plan_name}</Text><Tag color={statusMeta[item.status].color}>{statusMeta[item.status].label}</Tag><Tag>{item.action_type}</Tag>{item.confidence ? <Tag color={confidenceMeta[item.confidence].color}>{confidenceMeta[item.confidence].label}</Tag> : null}</Space>} description={<Space orientation="vertical" size={2}><Text type="secondary">{item.scene_name} · 验证时间 {formatDate(item.verified_at)}</Text><Text>{item.result}</Text>{item.interference_notes ? <Text type="warning">干扰因素：{item.interference_notes}</Text> : null}{item.manual_conclusion ? <Text>人工结论：{item.manual_conclusion}</Text> : null}</Space>} /></WorkflowListItem>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无失败、部分有效或数据不足动作" />}</Card></Col>
    </Row>
  </>;
}

function StrategiesPage() {
  const { currentStore } = useStores();
  const [records, setRecords] = useState<ActionRecord[]>([]);
  const [strategies, setStrategies] = useState<{ id: number; name: string; action_type: string; conditions: string; evidence: string; success_count: number; use_count: number; outcome?: string; status?: string; scene?: string; min_roi?: number | null; max_roi?: number | null; evidence_score?: number; evidence_level?: "high" | "medium" | "low"; sample_count?: number; group_success_rate?: number }[]>([]);
  const [strategyGroups, setStrategyGroups] = useState<StrategyGroup[]>([]);
  const [editing, setEditing] = useState<typeof strategies[number] | null>(null);
  const [editName, setEditName] = useState("");
  const [editConditions, setEditConditions] = useState("");
  const [editScene, setEditScene] = useState("");
  const [editMinRoi, setEditMinRoi] = useState<number | null>(null);
  const [editMaxRoi, setEditMaxRoi] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [strategyFilter, setStrategyFilter] = useState<"all" | "active" | "inactive" | "success" | "caution">("all");
  const load = useCallback(async () => {
    try {
      const scope = currentStore ? `?store_id=${currentStore.id}` : "";
      const [recordResponse, strategyResponse] = await Promise.all([http.get<{ items: ActionRecord[] }>(`/promotions/action-records${scope}`), http.get<{ items: typeof strategies; groups: StrategyGroup[] }>(`/promotions/strategies${scope}`)]);
      setRecords(recordResponse.data.items || []);
      setStrategies(strategyResponse.data.items || []);
      setStrategyGroups(strategyResponse.data.groups || []);
    } catch (error) { message.error(getApiErrorMessage(error)); }
  }, [currentStore?.id]);
  useEffect(() => { void load(); }, [load]);
  const openEdit = (strategy: typeof strategies[number]) => { setEditing(strategy); setEditName(strategy.name); setEditConditions(strategy.conditions); setEditScene(strategy.scene || ""); setEditMinRoi(strategy.min_roi ?? null); setEditMaxRoi(strategy.max_roi ?? null); };
  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    try { await http.put(`/promotions/strategies/${editing.id}`, { name: editName, conditions: editConditions, scene: editScene, min_roi: editMinRoi, max_roi: editMaxRoi }); message.success("策略卡已更新"); setEditing(null); await load(); } catch (error) { message.error(getApiErrorMessage(error)); } finally { setSaving(false); }
  };
  const toggleStatus = async (strategy: typeof strategies[number]) => {
    try { await http.put(`/promotions/strategies/${strategy.id}`, { status: strategy.status === "inactive" ? "active" : "inactive" }); message.success(strategy.status === "inactive" ? "策略已启用" : "策略已停用"); await load(); } catch (error) { message.error(getApiErrorMessage(error)); }
  };
  const verified = records.filter((item) => !["planned", "observing"].includes(item.status));
  const successRate = verified.length ? Math.round(records.filter((item) => item.status === "success").length / verified.length * 100) : 0;
  const successStrategies = strategies.filter((item) => !item.outcome || item.outcome === "success").length;
  const cautionStrategies = strategies.filter((item) => item.outcome === "failed" || item.outcome === "partial").length;
  const filteredStrategies = strategies.filter((item) => {
    if (strategyFilter === "active") return item.status !== "inactive";
    if (strategyFilter === "inactive") return item.status === "inactive";
    if (strategyFilter === "success") return !item.outcome || item.outcome === "success";
    if (strategyFilter === "caution") return item.outcome === "failed" || item.outcome === "partial";
    return true;
  });
  return <div>
    <PageHeader icon={<ExperimentOutlined />} eyebrow="推广管理" title="经验策略库" description="把已验证的调整结果沉淀为下一次决策可以复用的证据。" extra={<Button onClick={() => void load()}>刷新策略</Button>} />
    <Alert type="info" showIcon title="策略库是推广闭环的记忆层" description="成功经验用于复用，失败和部分有效经验用于提醒风险；停用策略不会进入 AI 决策参考。" style={{ marginBottom: 16 }} />
    <Row gutter={[12, 12]}><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="策略总数" value={strategies.length} /></Card></Col><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="当前启用" value={strategies.filter((item) => item.status !== "inactive").length} styles={{ content: { color: "var(--ops-success)" } }} /></Card></Col><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="成功经验" value={successStrategies} /></Card></Col><Col xs={12} sm={6}><Card variant="borderless"><Statistic title="需谨慎复用" value={cautionStrategies} styles={{ content: { color: cautionStrategies ? "var(--ops-warn)" : undefined } }} /></Card></Col></Row>
    <Row gutter={[12, 12]} style={{ marginTop: 12 }}><Col xs={24} md={16}><Card variant="borderless" title="策略管理建议"><Space orientation="vertical" size={4}><Text type="secondary">1. 先验证再复用：每条策略都保留来源动作和前后数据。</Text><Text type="secondary">2. 条件要具体：补充 ROI 区间、场景、预算幅度和观察周期。</Text><Text type="secondary">3. 发现异常及时停用：停用只影响推荐，不会删除历史证据。</Text></Space></Card></Col><Col xs={24} md={8}><Card variant="borderless" title="动作验证概览"><Statistic title="验证成功率" value={successRate} suffix="%" /><Text type="secondary">已验证 {verified.length} 个动作</Text></Card></Col></Row>
    {strategyGroups.length ? <Card variant="borderless" title="同类经验聚合" style={{ marginTop: 16 }}><Table<StrategyGroup> rowKey="group_id" size="small" pagination={false} dataSource={strategyGroups} columns={[
      { title: "调整动作", dataIndex: "action_type", key: "action_type" },
      { title: "适用场景", dataIndex: "scene", key: "scene" },
      { title: "样本", dataIndex: "sample_count", key: "sample_count", width: 70 },
      { title: "成功 / 部分 / 失败", key: "outcomes", width: 150, render: (_: unknown, item: StrategyGroup) => `${item.success_count} / ${item.partial_count} / ${item.failed_count}` },
      { title: "成功率", dataIndex: "success_rate", key: "success_rate", width: 90, render: (value: number) => `${value}%` },
      { title: "平均证据分", dataIndex: "avg_evidence_score", key: "avg_evidence_score", width: 110 },
    ]} /></Card> : null}
    <Row gutter={[16, 16]} style={{ marginTop: 16 }}>{[
      { title: "低效计划止损", icon: <ThunderboltOutlined />, text: "ROI 连续低于保本线时，降低预算或暂停，观察花费和利润是否改善。" },
      { title: "高效计划放量", icon: <CheckCircleOutlined />, text: "ROI 和成交规模同时健康时，小幅增加预算，验证边际 ROI 是否稳定。" },
      { title: "调整后复盘", icon: <FileTextOutlined />, text: "记录动作前后数据、外部干扰和最终结论，形成可复制的策略条件。" },
    ].map((item) => <Col xs={24} md={8} key={item.title}><Card variant="borderless" title={<Space>{item.icon}{item.title}</Space>}><Paragraph type="secondary" style={{ marginBottom: 0 }}>{item.text}</Paragraph><Tag color="blue" style={{ marginTop: 14 }}>框架待沉淀</Tag></Card></Col>)}</Row>
    <Card variant="borderless" title="已沉淀经验" style={{ marginTop: 16 }} extra={<Segmented size="small" value={strategyFilter} onChange={(value) => setStrategyFilter(value as typeof strategyFilter)} options={[{ label: "全部", value: "all" }, { label: "启用中", value: "active" }, { label: "已停用", value: "inactive" }, { label: "成功", value: "success" }, { label: "需谨慎", value: "caution" }]} />}>{strategies.length ? filteredStrategies.length ? <WorkflowList dataSource={filteredStrategies} renderItem={(item) => <WorkflowListItem actions={[<Button key="edit" type="link" icon={<EditOutlined />} onClick={() => openEdit(item)}>编辑</Button>, <Button key="status" type="link" danger={item.status !== "inactive"} onClick={() => void toggleStatus(item)}>{item.status === "inactive" ? "启用" : "停用"}</Button>]}><WorkflowListMeta title={<Space wrap>{item.name}<Tag color={item.outcome === "failed" ? "red" : item.outcome === "partial" ? "orange" : "green"}>{item.outcome === "failed" ? "失败经验" : item.outcome === "partial" ? "部分有效" : `成功 ${item.success_count} 次`}</Tag><Tag color={item.evidence_level === "high" ? "green" : item.evidence_level === "medium" ? "orange" : "default"}>证据 {item.evidence_score ?? 0} 分</Tag>{item.sample_count ? <Tag color="purple">同类 {item.sample_count} 次 · 成功率 {item.group_success_rate ?? 0}%</Tag> : null}{item.scene ? <Tag color="blue">场景：{item.scene}</Tag> : null}{item.min_roi != null || item.max_roi != null ? <Tag>ROI {item.min_roi ?? "-∞"}~{item.max_roi ?? "+∞"}</Tag> : null}{item.status === "inactive" ? <Tag>已停用</Tag> : null}</Space>} description={<Space orientation="vertical" size={2}><Text type="secondary">动作：{item.action_type} · 被引用 {item.use_count} 次</Text><Text>{item.conditions}</Text><Text type="secondary">证据：{item.evidence}</Text></Space>} /></WorkflowListItem>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前筛选没有策略" /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="完成动作验证后，成功与失败经验都会出现在这里" />}</Card>
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
  </div>;
}
