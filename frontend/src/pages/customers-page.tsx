import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloudUploadOutlined,
  CommentOutlined,
  CopyOutlined,
  FileSearchOutlined,
  MoreOutlined,
  ReloadOutlined,
  RobotOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Col, Descriptions, Drawer, Dropdown, Empty, Input, InputNumber, List, Modal, Popconfirm, Progress, Row, Select, Space, Statistic, Table, Tabs, Tag, Typography, Upload, message } from "antd";
import type { TableColumnsType, UploadProps } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";
import { PageHeader } from "../components/ui/page-header";
import { LoadingBlock } from "../components/ui/page-state";
import { MetricRail, WorkspaceToolbar } from "../components/ui/workspace-template";

const { Text, Paragraph } = Typography;

type Review = {
  id: number;
  store_id: number;
  store_name: string;
  review_id: string;
  item_id: string;
  item_title: string;
  sku_id: string;
  content: string;
  append_content: string;
  image_urls: string[];
  review_time: string;
  reply_status: string;
  reply_content: string;
  reply_error: string;
  reply_approved_at?: string;
  reply_published_at?: string;
  process_status: string;
  source: string;
  sentiment: "positive" | "neutral" | "negative";
  confidence: number;
  aspects: { aspect: string; sentiment: string; keywords: string[] }[];
  keywords: string[];
  severity: "normal" | "medium" | "high";
  review_status: "auto" | "needs_review" | "confirmed";
  analysis_reason: string;
  analysis_source: "rules" | "ai" | "manual" | "learned";
  routing_reason: string;
  priority_score: number;
  priority_level: "normal" | "high" | "urgent";
};

type Summary = {
  days: number;
  total: number;
  positive: number;
  neutral: number;
  negative: number;
  positive_rate: number;
  negative_rate: number;
  pending_count: number;
  needs_review_count: number;
  top_aspects: { aspect: string; count: number }[];
  trend: { date: string; total: number; negative: number }[];
};
type ProductSummary = { item_id: string; item_title: string; total: number; positive: number; negative: number; negative_rate: number };
type ReviewAlert = { id: number; title: string; message: string; status: string; content: string; item_title: string; review_time: string };
type ReplyTemplate = { id: number; name: string; category: string; content: string };
type TrendAlert = { id: number; store_name: string; message: string; level: "warning" | "critical"; status: string; current_rate: number; baseline_rate: number; alert_date: string };
type TopicReport = { total: number; items: { topic: string; count: number; negative: number; negative_rate: number; products: { name: string; count: number }[]; examples: { id: number; content: string; item_title: string }[] }[]; emerging_terms: { term: string; count: number }[] };
type AccuracyReport = { total: number; confirmed_sample: number; corrected_count: number; manual_agreement_rate: number | null; correction_rate: number | null; needs_review_count: number; average_confidence: number; sources: { source: string; count: number }[]; corrections: { transition: string; count: number }[] };
type WeeklyReport = { week_start: string; week_end: string; total: number; positive: number; neutral: number; negative: number; negative_rate: number; summary: string; actions: string[]; topics: TopicReport["items"]; products: { item_title: string; total: number; negative: number }[] };
type CustomTerm = { id: number; store_id: number; term: string; sentiment: "positive" | "neutral" | "negative"; weight: number; enabled: boolean; source: string };
type KnowledgeArticle = { id: number; store_id: number; title: string; category: string; problem_terms: string[]; solution: string; reply_template: string; enabled: boolean; confidence?: number; matched_terms?: string[] };

const sentimentLabels: Record<string, string> = { positive: "好评", neutral: "中评", negative: "差评" };
const processLabels: Record<string, string> = { pending: "待处理", contacted: "已联系", resolved: "已解决", ignored: "已忽略" };
const replyStatusLabels: Record<string, string> = { draft: "回复待审核", approved: "回复已审核", published: "回复已发布", failed: "回复发布失败" };

function sentimentTag(value: string) {
  return <Tag color={value === "positive" ? "green" : value === "negative" ? "red" : "gold"}>{sentimentLabels[value] ?? "待分析"}</Tag>;
}

export function CustomersPage() {
  const [searchParams] = useSearchParams();
  const { stores, currentStore } = useStores();
  const todoStoreId = Number(searchParams.get("store_id")) || undefined;
  const [storeId, setStoreId] = useState<number | undefined>(todoStoreId ?? currentStore?.id);
  const [days, setDays] = useState(30);
  const [sentiment, setSentiment] = useState(searchParams.get("sentiment") || "");
  const [processStatus, setProcessStatus] = useState(searchParams.get("process_status") || "");
  const [replyStatus, setReplyStatus] = useState(searchParams.get("reply_status") || "");
  const [keyword, setKeyword] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [total, setTotal] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [detail, setDetail] = useState<Review | null>(null);
  const [replyLoading, setReplyLoading] = useState(false);
  const [replyPublishing, setReplyPublishing] = useState(false);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);
  const [productSummary, setProductSummary] = useState<ProductSummary[]>([]);
  const [alerts, setAlerts] = useState<ReviewAlert[]>([]);
  const [aiSummary, setAiSummary] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiReviewLoading, setAiReviewLoading] = useState(false);
  const [replyTemplates, setReplyTemplates] = useState<ReplyTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number>();
  const [templateOpen, setTemplateOpen] = useState(false);
  const [templateEditing, setTemplateEditing] = useState<ReplyTemplate | null>(null);
  const [templateName, setTemplateName] = useState("");
  const [templateCategory, setTemplateCategory] = useState("通用");
  const [templateContent, setTemplateContent] = useState("");
  const [trendAlerts, setTrendAlerts] = useState<TrendAlert[]>([]);
  const [insightsOpen, setInsightsOpen] = useState(false);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [topics, setTopics] = useState<TopicReport | null>(null);
  const [accuracy, setAccuracy] = useState<AccuracyReport | null>(null);
  const [weeklyReport, setWeeklyReport] = useState<WeeklyReport | null>(null);
  const [termsOpen, setTermsOpen] = useState(false);
  const [customTerms, setCustomTerms] = useState<CustomTerm[]>([]);
  const [termText, setTermText] = useState("");
  const [termSentiment, setTermSentiment] = useState<CustomTerm["sentiment"]>("negative");
  const [termWeight, setTermWeight] = useState(1.5);
  const [askOpen, setAskOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState(false);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [knowledgeArticles, setKnowledgeArticles] = useState<KnowledgeArticle[]>([]);
  const [knowledgeEditing, setKnowledgeEditing] = useState<KnowledgeArticle | null>(null);
  const [knowledgeTitle, setKnowledgeTitle] = useState("");
  const [knowledgeCategory, setKnowledgeCategory] = useState("通用");
  const [knowledgeTerms, setKnowledgeTerms] = useState("");
  const [knowledgeSolution, setKnowledgeSolution] = useState("");
  const [knowledgeReply, setKnowledgeReply] = useState("");
  const [knowledgeMatches, setKnowledgeMatches] = useState<KnowledgeArticle[]>([]);

  useEffect(() => {
    if (!todoStoreId && currentStore?.id) setStoreId(currentStore.id);
  }, [currentStore?.id, todoStoreId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "20", days: String(days) });
      if (storeId) params.set("store_id", String(storeId));
      if (sentiment) params.set("sentiment", sentiment);
      if (processStatus) params.set("process_status", processStatus);
      if (replyStatus) params.set("reply_status", replyStatus);
      if (query) params.set("q", query);
      const summaryParams = new URLSearchParams({ days: String(days) });
      if (storeId) summaryParams.set("store_id", String(storeId));
      const [listResponse, summaryResponse, productResponse, alertResponse, templateResponse, trendResponse] = await Promise.all([
        http.get<{ items: Review[]; total: number }>(`/customers/reviews?${params.toString()}`),
        http.get<Summary>(`/customers/reviews/summary?${summaryParams.toString()}`),
        http.get<{ items: ProductSummary[] }>(`/customers/reviews/product-summary?${summaryParams.toString()}`),
        http.get<{ items: ReviewAlert[] }>(`/customers/reviews/alerts?${storeId ? `store_id=${storeId}` : ""}`),
        http.get<{ items: ReplyTemplate[] }>("/customers/reviews/reply-templates"),
        http.get<{ items: TrendAlert[] }>(`/customers/reviews/trend-alerts?${storeId ? `store_id=${storeId}` : ""}`),
      ]);
      setReviews(listResponse.data.items);
      setTotal(listResponse.data.total);
      setSummary(summaryResponse.data);
      setProductSummary(productResponse.data.items);
      setAlerts(alertResponse.data.items);
      setReplyTemplates(templateResponse.data.items);
      setTrendAlerts(trendResponse.data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [days, page, processStatus, query, replyStatus, sentiment, storeId]);

  useEffect(() => {
    load();
  }, [load]);

  const importCsv = async (file: File) => {
    if (!storeId) {
      message.warning("请先选择店铺");
      return;
    }
    setImporting(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("store_id", String(storeId));
      const { data } = await http.post<{ imported: number; updated: number; error_count: number }>("/customers/reviews/import", form, { timeout: 120000 });
      message.success(`导入完成：新增 ${data.imported} 条，更新 ${data.updated} 条${data.error_count ? `，${data.error_count} 条失败` : ""}`);
      setPage(1);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setImporting(false);
    }
  };

  const uploadProps: UploadProps = {
    accept: ".csv,.txt",
    showUploadList: false,
    beforeUpload: (file) => {
      void importCsv(file);
      return false;
    },
  };

  const syncReviews = async () => {
    if (!storeId) {
      message.warning("请先选择店铺");
      return;
    }
    setSyncing(true);
    try {
      const syncDays = Math.min(days, 7);
      const { data } = await http.post<{ ok: boolean; message?: string; fetched?: number; results?: { imported?: number; updated?: number; error?: string; auto_reply_drafts?: { generated: number } }[] }>("/customers/reviews/sync-auto", { store_id: storeId, days: syncDays }, { timeout: 180000 });
      setSyncNotice(data.message || null);
      if (!data.ok) {
        message.warning(data.message || "当前平台没有可直接读取的评论正文");
        return;
      }
      const result = data.results?.[0];
      message.success(`自动同步完成：新增 ${result?.imported ?? 0} 条，更新 ${result?.updated ?? 0} 条，生成 ${result?.auto_reply_drafts?.generated ?? 0} 条待审核回复`);
      setPage(1);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const updateProcess = async (review: Review, status: string) => {
    try {
      await http.put(`/customers/reviews/${review.id}/process`, { status });
      message.success("处理状态已更新");
      await load();
      if (detail?.id === review.id) setDetail({ ...detail, process_status: status });
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const createReplyDraft = async () => {
    if (!detail) return;
    setReplyLoading(true);
    try {
      const { data } = await http.post<{ reply: string; knowledge: KnowledgeArticle[] }>(`/customers/reviews/${detail.id}/reply-draft`, { template_id: selectedTemplateId });
      setDetail({ ...detail, reply_content: data.reply, reply_status: "draft" });
      setKnowledgeMatches(data.knowledge ?? []);
      message.success("回复草稿已生成");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setReplyLoading(false);
    }
  };

  const openDetail = async (review: Review) => {
    setDetail(review);
    setKnowledgeMatches([]);
    try {
      const { data } = await http.get<{ items: KnowledgeArticle[] }>(`/customers/reviews/${review.id}/knowledge`);
      setKnowledgeMatches(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const approveReply = async () => {
    if (!detail?.reply_content.trim()) return;
    setReplyLoading(true);
    try {
      await http.put(`/customers/reviews/${detail.id}/reply`, { content: detail.reply_content.trim() });
      setDetail({ ...detail, reply_status: "approved", reply_error: "" });
      message.success("回复已审核，可以发布到淘宝");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setReplyLoading(false);
    }
  };

  const publishReply = async () => {
    if (!detail || detail.reply_status !== "approved") return;
    setReplyPublishing(true);
    try {
      const { data } = await http.post<{ status: string; published_at: string }>(`/customers/reviews/${detail.id}/reply/publish`, undefined, { timeout: 120000 });
      setDetail({ ...detail, reply_status: data.status, reply_published_at: data.published_at, reply_error: "" });
      message.success("回复已发布到淘宝");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setDetail({ ...detail, reply_status: "failed", reply_error: getApiErrorMessage(error) });
    } finally {
      setReplyPublishing(false);
    }
  };

  const createAiSummary = async () => {
    setAiLoading(true);
    try {
      const { data } = await http.post<{ summary: string }>("/customers/reviews/ai-summary", { days, store_id: storeId });
      setAiSummary(data.summary);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiLoading(false);
    }
  };

  const reviewAmbiguousWithAi = async () => {
    setAiReviewLoading(true);
    try {
      const { data } = await http.post<{ requested: number; updated: number }>("/customers/reviews/ai-review", { days, store_id: storeId, limit: 30 }, { timeout: 180000 });
      message.success(data.requested ? `AI 已复核 ${data.updated}/${data.requested} 条评论` : "当前没有待确认评论");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiReviewLoading(false);
    }
  };

  const confirmSentiment = async (value: "positive" | "neutral" | "negative") => {
    if (!detail) return;
    try {
      const { data } = await http.put<{ item: Review }>(`/customers/reviews/${detail.id}/sentiment`, { sentiment: value, reason: "人工确认" });
      setDetail(data.item);
      message.success("情绪已人工确认，后续同步不会覆盖");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const updateAlert = async (alert: ReviewAlert, status: string) => {
    try {
      await http.put(`/customers/reviews/alerts/${alert.id}`, { status });
      setAlerts((items) => items.filter((item) => item.id !== alert.id));
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const editTemplate = (template?: ReplyTemplate) => {
    setTemplateEditing(template ?? null);
    setTemplateName(template?.name ?? "");
    setTemplateCategory(template?.category ?? "通用");
    setTemplateContent(template?.content ?? "");
    setTemplateOpen(true);
  };

  const saveTemplate = async () => {
    if (!templateName.trim() || !templateContent.trim()) {
      message.warning("请填写模板名称和内容");
      return;
    }
    try {
      const body = { name: templateName.trim(), category: templateCategory.trim() || "通用", content: templateContent.trim() };
      if (templateEditing) await http.put(`/customers/reviews/reply-templates/${templateEditing.id}`, body);
      else await http.post("/customers/reviews/reply-templates", body);
      setTemplateOpen(false);
      message.success("回复模板已保存");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const deleteTemplate = async (template: ReplyTemplate) => {
    try {
      await http.delete(`/customers/reviews/reply-templates/${template.id}`);
      if (selectedTemplateId === template.id) setSelectedTemplateId(undefined);
      message.success("模板已删除");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const loadInsights = async () => {
    setInsightsLoading(true);
    try {
      const params = new URLSearchParams({ days: String(days) });
      if (storeId) params.set("store_id", String(storeId));
      const [topicResponse, accuracyResponse, weeklyResponse, trendResponse] = await Promise.all([
        http.get<TopicReport>(`/customers/reviews/topics?${params.toString()}`),
        http.get<AccuracyReport>(`/customers/reviews/accuracy?${params.toString()}`),
        http.get<WeeklyReport>(`/customers/reviews/weekly-report?${storeId ? `store_id=${storeId}` : ""}`),
        http.get<{ items: TrendAlert[] }>(`/customers/reviews/trend-alerts?${storeId ? `store_id=${storeId}` : ""}`),
      ]);
      setTopics(topicResponse.data);
      setAccuracy(accuracyResponse.data);
      setWeeklyReport(weeklyResponse.data);
      setTrendAlerts(trendResponse.data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setInsightsLoading(false);
    }
  };

  const openInsights = () => {
    setInsightsOpen(true);
    void loadInsights();
  };

  const openTerms = async () => {
    if (!storeId) {
      message.warning("请先选择店铺，再维护店铺词库");
      return;
    }
    setTermsOpen(true);
    try {
      const { data } = await http.get<{ items: CustomTerm[] }>(`/customers/reviews/custom-terms?store_id=${storeId}`);
      setCustomTerms(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const loadKnowledge = async () => {
    const { data } = await http.get<{ items: KnowledgeArticle[] }>(`/customers/reviews/knowledge${storeId ? `?store_id=${storeId}` : ""}`);
    setKnowledgeArticles(data.items);
  };

  const openKnowledge = async () => {
    setKnowledgeOpen(true);
    try {
      await loadKnowledge();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const editKnowledge = (article?: KnowledgeArticle) => {
    setKnowledgeEditing(article ?? null);
    setKnowledgeTitle(article?.title ?? "");
    setKnowledgeCategory(article?.category ?? "通用");
    setKnowledgeTerms(article?.problem_terms.join("、") ?? "");
    setKnowledgeSolution(article?.solution ?? "");
    setKnowledgeReply(article?.reply_template ?? "");
  };

  const saveKnowledge = async () => {
    if (!knowledgeTitle.trim() || !knowledgeSolution.trim()) {
      message.warning("请填写知识标题和处理方案");
      return;
    }
    const body = {
      store_id: knowledgeEditing?.store_id ?? storeId ?? 0,
      title: knowledgeTitle.trim(),
      category: knowledgeCategory.trim() || "通用",
      problem_terms: knowledgeTerms.split(/[,，、;；\n]/).map((item) => item.trim()).filter(Boolean),
      solution: knowledgeSolution.trim(),
      reply_template: knowledgeReply.trim(),
      enabled: knowledgeEditing?.enabled ?? true,
    };
    try {
      if (knowledgeEditing) await http.put(`/customers/reviews/knowledge/${knowledgeEditing.id}`, body);
      else await http.post("/customers/reviews/knowledge", body);
      editKnowledge();
      await loadKnowledge();
      message.success("问题知识已保存");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const deleteKnowledge = async (article: KnowledgeArticle) => {
    try {
      await http.delete(`/customers/reviews/knowledge/${article.id}`);
      await loadKnowledge();
      message.success("知识条目已删除");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const saveTerm = async () => {
    if (!storeId || !termText.trim()) {
      message.warning("请填写词语并选择店铺");
      return;
    }
    try {
      const { data } = await http.post<{ reanalyzed: number }>("/customers/reviews/custom-terms", { store_id: storeId, term: termText.trim(), sentiment: termSentiment, weight: termWeight, enabled: true });
      message.success(`词条已保存，并重新分析 ${data.reanalyzed} 条评论`);
      setTermText("");
      await openTerms();
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const toggleTerm = async (term: CustomTerm) => {
    try {
      await http.put(`/customers/reviews/custom-terms/${term.id}`, { store_id: term.store_id, term: term.term, sentiment: term.sentiment, weight: term.weight, enabled: !term.enabled });
      await openTerms();
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const deleteTerm = async (term: CustomTerm) => {
    try {
      await http.delete(`/customers/reviews/custom-terms/${term.id}`);
      message.success("词条已删除，相关评论已重新分析");
      await openTerms();
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const updateTrendAlert = async (alert: TrendAlert) => {
    try {
      await http.put(`/customers/reviews/trend-alerts/${alert.id}`, { status: "acknowledged" });
      setTrendAlerts((items) => items.filter((item) => item.id !== alert.id));
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const askReviews = async () => {
    if (!question.trim()) {
      message.warning("请先输入想了解的问题");
      return;
    }
    setAsking(true);
    setAnswer("");
    try {
      const { data } = await http.post<{ answer: string }>("/customers/reviews/ask", { question: question.trim(), store_id: storeId, days }, { timeout: 180000 });
      setAnswer(data.answer);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAsking(false);
    }
  };

  const columns = useMemo<TableColumnsType<Review>>(() => [
    {
      title: "评价",
      key: "content",
      width: 390,
      render: (_, row) => (
        <div style={{ maxWidth: 380 }}>
          <Space size={6} wrap>{sentimentTag(row.sentiment)}{row.review_status === "needs_review" ? <Tag color="purple">待确认</Tag> : row.review_status === "confirmed" ? <Tag color="blue">人工确认</Tag> : null}{row.analysis_source === "ai" ? <Tag color="geekblue">AI 判断</Tag> : row.analysis_source === "rules" ? <Tag>规则判断</Tag> : row.analysis_source === "learned" ? <Tag color="cyan">历史学习</Tag> : null}{row.severity !== "normal" ? <Tag color="orange">{row.severity === "high" ? "重点" : "需关注"}</Tag> : null}{row.reply_status === "draft" ? <Tag color="gold">回复待审核</Tag> : row.reply_status === "approved" ? <Tag color="blue">回复已审核</Tag> : row.reply_status === "published" ? <Tag color="green">回复已发布</Tag> : row.reply_status === "failed" ? <Tag color="red">回复发布失败</Tag> : null}</Space>
          <Paragraph ellipsis={{ rows: 2 }} style={{ margin: "5px 0 0", fontSize: 13 }}>{row.content || row.append_content || "（无文字评价）"}</Paragraph>
          {row.keywords?.length > 0 ? <Text type="secondary" style={{ fontSize: 12 }}>关键词：{row.keywords.slice(0, 4).join("、")}</Text> : null}
        </div>
      ),
    },
    { title: "商品", dataIndex: "item_title", key: "item_title", width: 190, ellipsis: true, render: (value: string, row) => <div><Text ellipsis style={{ maxWidth: 170 }}>{value || "未关联商品"}</Text><Text type="secondary" style={{ display: "block", fontSize: 11 }}>{row.item_id}</Text></div> },
    { title: "店铺", dataIndex: "store_name", key: "store_name", width: 140, ellipsis: true },
    { title: "时间", dataIndex: "review_time", key: "review_time", width: 150, render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm") },
    { title: "优先级", dataIndex: "priority_level", key: "priority_level", width: 100, render: (value: Review["priority_level"], row) => <Tag color={value === "urgent" ? "red" : value === "high" ? "orange" : "default"}>{value === "urgent" ? "紧急" : value === "high" ? "优先" : "普通"} {row.priority_score}</Tag> },
    { title: "处理", dataIndex: "process_status", key: "process_status", width: 110, render: (value: string) => <Tag icon={value === "resolved" ? <CheckCircleOutlined /> : <ClockCircleOutlined />} color={value === "resolved" ? "green" : value === "pending" ? "orange" : "blue"}>{processLabels[value] ?? value}</Tag> },
    { title: "操作", key: "action", width: 150, fixed: "right", render: (_, row) => <Space size={4}><Button size="small" icon={<FileSearchOutlined />} onClick={() => void openDetail(row)}>查看</Button>{row.sentiment === "negative" && row.process_status === "pending" ? <Button size="small" type="link" onClick={() => updateProcess(row, "contacted")}>标记已联系</Button> : null}</Space> },
  ], [detail, load]);

  return (
    <div>
      <PageHeader
        icon={<CommentOutlined />}
        eyebrow="评价管理"
        title="评论分析"
        description="识别评价情绪、归纳商品问题、跟进差评处理"
        extra={<Space wrap><Button onClick={syncReviews} loading={syncing}>同步评论</Button><Button icon={<RobotOutlined />} onClick={reviewAmbiguousWithAi} loading={aiReviewLoading}>AI 复核{summary?.needs_review_count ? ` (${summary.needs_review_count})` : ""}</Button><Upload {...uploadProps}><Button type="primary" icon={<CloudUploadOutlined />} loading={importing}>导入 CSV</Button></Upload><Dropdown trigger={["click"]} menu={{ items: [{ key: "summary", label: "AI 总结", onClick: createAiSummary }, { key: "insights", label: "分析中心", onClick: openInsights }, { key: "ask", label: "评论问答", onClick: () => setAskOpen(true) }, { type: "divider" }, { key: "terms", label: "自定义词库", onClick: () => void openTerms() }, { key: "knowledge", label: "问题知识库", onClick: () => void openKnowledge() }, { key: "template", label: "回复模板", onClick: () => editTemplate() }] }}><Button icon={<MoreOutlined />} aria-label="更多评价工具" loading={aiLoading}>更多</Button></Dropdown></Space>}
      />

      <WorkspaceToolbar>
        <Select value={storeId} onChange={(value) => { setStoreId(value); setPage(1); }} allowClear placeholder="全部店铺" style={{ width: 170 }} options={stores.map((store) => ({ value: store.id, label: store.name }))} />
        <Select value={days} onChange={(value) => { setDays(value); setPage(1); }} options={[{ value: 7, label: "近 7 天" }, { value: 30, label: "近 30 天" }, { value: 90, label: "近 90 天" }]} style={{ width: 120 }} />
        <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
        <Text className="ops-filter-bar__meta">先处理待办评价，再进入趋势和知识分析</Text>
      </WorkspaceToolbar>

      <Alert type={syncNotice ? "warning" : "info"} showIcon title={syncNotice || "每小时自动增量同步"} description="系统从千牛评价管理读取评论正文；新差评会自动生成回复草稿并等待人工审核，不会自动发布。差评预警可通过 PushPlus/Webhook 推送。" style={{ marginBottom: 16 }} />

      {trendAlerts.length ? <Alert type="error" showIcon title={`${trendAlerts.length} 个评论趋势异常`} description={<List size="small" dataSource={trendAlerts.slice(0, 3)} renderItem={(alert) => <List.Item actions={[<Button size="small" onClick={() => updateTrendAlert(alert)}>已知悉</Button>]}><List.Item.Meta title={`${alert.store_name || "店铺"} · ${alert.level === "critical" ? "严重" : "预警"}`} description={alert.message} /></List.Item>} />} style={{ marginBottom: 16 }} /> : null}

      {loading && !summary ? <LoadingBlock /> : summary ? <>
        {summary.needs_review_count > 0 ? <Alert type="warning" showIcon title={`${summary.needs_review_count} 条评论情绪不明确`} description="这些评论存在正负冲突、隐含表达或没有明显情绪词，可点击“AI 复核”批量判断，也可在详情中人工确认。" style={{ marginBottom: 16 }} /> : null}
        {alerts.length ? <Alert type="warning" showIcon title={`有 ${alerts.length} 条评论预警`} description={<List size="small" dataSource={alerts.slice(0, 3)} renderItem={(alert) => <List.Item actions={[<Button size="small" onClick={() => updateAlert(alert, "acknowledged")}>已知悉</Button>]}><List.Item.Meta title={alert.title} description={`${alert.message} · ${alert.item_title || "未关联商品"}`} /></List.Item>} />} style={{ marginBottom: 16 }} /> : null}
        {productSummary.length ? <Card variant="borderless" title="商品维度分析" style={{ marginBottom: 16 }}><Table<ProductSummary> size="small" rowKey="item_id" pagination={{ pageSize: 5 }} dataSource={productSummary.slice(0, 20)} columns={[{ title: "商品", dataIndex: "item_title", ellipsis: true }, { title: "评论数", dataIndex: "total", width: 80 }, { title: "差评数", dataIndex: "negative", width: 80 }, { title: "差评率", dataIndex: "negative_rate", width: 90, render: (value: number) => `${value}%` }]} /></Card> : null}
        <MetricRail columns={4} items={[
          { label: "评论总数", value: summary.total, hint: `近 ${days} 天` },
          { label: "好评率", value: `${summary.positive_rate.toFixed(1)}%`, hint: "正向评价占比", tone: "var(--ops-success)" },
          { label: "差评率", value: `${summary.negative_rate.toFixed(1)}%`, hint: "需要持续观察", tone: summary.negative_rate > 5 ? "var(--ops-danger)" : "var(--ops-warn)" },
          { label: "待处理重点", value: summary.pending_count, hint: "优先跟进", tone: summary.pending_count ? "var(--ops-danger)" : "var(--ops-success)" },
        ]} />
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} lg={15}><Card variant="borderless" title={`问题维度（近 ${days} 天）`}><Space wrap>{summary.top_aspects.length ? summary.top_aspects.map((item) => <Tag key={item.aspect} color={item.count >= 5 ? "red" : "gold"}>{item.aspect} {item.count}</Tag>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无问题标签" />}</Space></Card></Col>
          <Col xs={24} lg={9}><Card variant="borderless" title="评价结构"><Space direction="vertical" style={{ width: "100%" }}><div><Text>好评</Text><Progress percent={summary.total ? summary.positive / summary.total * 100 : 0} strokeColor="var(--ops-success)" format={(value) => `${value?.toFixed(1)}%`} /></div><div><Text>中评</Text><Progress percent={summary.total ? summary.neutral / summary.total * 100 : 0} strokeColor="var(--ops-warn)" format={(value) => `${value?.toFixed(1)}%`} /></div><div><Text>差评</Text><Progress percent={summary.total ? summary.negative / summary.total * 100 : 0} strokeColor="var(--ops-danger)" format={(value) => `${value?.toFixed(1)}%`} /></div></Space></Card></Col>
        </Row>
        <Card variant="borderless" title="评论明细" extra={<Space wrap><Input.Search value={keyword} onChange={(event) => setKeyword(event.target.value)} onSearch={(value) => { setQuery(value.trim()); setPage(1); }} allowClear placeholder="搜索评价、商品" style={{ width: 220 }} /><Select value={sentiment || undefined} onChange={(value) => { setSentiment(value ?? ""); setPage(1); }} allowClear placeholder="情绪" style={{ width: 100 }} options={[{ value: "positive", label: "好评" }, { value: "neutral", label: "中评" }, { value: "negative", label: "差评" }]} /><Select value={processStatus || undefined} onChange={(value) => { setProcessStatus(value ?? ""); setPage(1); }} allowClear placeholder="处理状态" style={{ width: 120 }} options={Object.entries(processLabels).map(([value, label]) => ({ value, label }))} /><Select value={replyStatus || undefined} onChange={(value) => { setReplyStatus(value ?? ""); setPage(1); }} allowClear placeholder="回复标签" style={{ width: 130 }} options={Object.entries(replyStatusLabels).map(([value, label]) => ({ value, label }))} /></Space>}>
          <Table<Review> rowKey="id" loading={loading} columns={columns} dataSource={reviews} scroll={{ x: 1100 }} pagination={{ current: page, pageSize: 20, total, showSizeChanger: false, onChange: (next) => setPage(next), showTotal: (count) => `共 ${count} 条` }} locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无评论，请先导入 CSV" /> }} />
        </Card>
      </> : null}

      <Modal title={`AI 评论总结（近 ${days} 天）`} open={Boolean(aiSummary)} onCancel={() => setAiSummary("")} footer={null} width={680}><Paragraph style={{ whiteSpace: "pre-wrap" }}>{aiSummary}</Paragraph></Modal>

      <Modal title={templateEditing ? "编辑回复模板" : "回复模板管理"} open={templateOpen} onCancel={() => setTemplateOpen(false)} onOk={saveTemplate} okText="保存模板" width={720}>
        {!templateEditing && replyTemplates.length ? <List size="small" dataSource={replyTemplates} style={{ marginBottom: 16, maxHeight: 220, overflow: "auto" }} renderItem={(template) => <List.Item actions={[<Button size="small" onClick={() => editTemplate(template)}>编辑</Button>, <Popconfirm title="确认删除这个模板？" onConfirm={() => deleteTemplate(template)}><Button size="small" danger>删除</Button></Popconfirm>]}><List.Item.Meta title={<Space><Tag>{template.category}</Tag>{template.name}</Space>} description={template.content} /></List.Item>} /> : null}
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input value={templateName} onChange={(event) => setTemplateName(event.target.value)} placeholder="模板名称，例如：包装破损安抚" maxLength={40} />
          <Input value={templateCategory} onChange={(event) => setTemplateCategory(event.target.value)} placeholder="分类，例如：质量、物流、好评" maxLength={20} />
          <Input.TextArea value={templateContent} onChange={(event) => setTemplateContent(event.target.value)} placeholder="回复模板内容" rows={5} maxLength={1000} showCount />
        </Space>
      </Modal>

      <Modal title="评论分析中心" open={insightsOpen} onCancel={() => setInsightsOpen(false)} footer={<Button onClick={() => void loadInsights()} loading={insightsLoading}>刷新分析</Button>} width={920}>
        {insightsLoading && !topics ? <LoadingBlock /> : <Tabs items={[
          { key: "topics", label: "问题主题", children: topics ? <Space direction="vertical" style={{ width: "100%" }} size={16}><div><Text strong>新出现的高频表达：</Text><Space wrap>{topics.emerging_terms.length ? topics.emerging_terms.map((item) => <Tag key={item.term}>{item.term} {item.count}</Tag>) : <Text type="secondary">暂无</Text>}</Space></div><Table size="small" rowKey="topic" pagination={false} dataSource={topics.items} columns={[{ title: "主题", dataIndex: "topic" }, { title: "涉及评论", dataIndex: "count", width: 90 }, { title: "负面数", dataIndex: "negative", width: 80 }, { title: "负面率", dataIndex: "negative_rate", width: 90, render: (value: number) => `${value}%` }, { title: "主要商品", dataIndex: "products", render: (items: { name: string; count: number }[]) => items.map((item) => `${item.name}(${item.count})`).join("、") }]}/></Space> : <Empty description="暂无主题数据" /> },
          { key: "trend", label: `趋势预警${trendAlerts.length ? ` (${trendAlerts.length})` : ""}`, children: trendAlerts.length ? <List dataSource={trendAlerts} renderItem={(alert) => <List.Item actions={[<Button size="small" onClick={() => updateTrendAlert(alert)}>已知悉</Button>]}><List.Item.Meta title={<Space><Tag color={alert.level === "critical" ? "red" : "orange"}>{alert.level === "critical" ? "严重" : "预警"}</Tag>{alert.store_name}</Space>} description={`${alert.message} · ${alert.alert_date}`} /></List.Item>} /> : <Empty description="当前没有评论趋势异常" /> },
          { key: "weekly", label: "每周改进报告", children: weeklyReport ? <Space direction="vertical" size={16} style={{ width: "100%" }}><Alert type={weeklyReport.negative_rate >= 20 ? "warning" : "success"} showIcon message={weeklyReport.summary} description={`${weeklyReport.week_start} 至 ${weeklyReport.week_end}`} /><Row gutter={12}><Col span={6}><Statistic title="评论数" value={weeklyReport.total} /></Col><Col span={6}><Statistic title="好评" value={weeklyReport.positive} /></Col><Col span={6}><Statistic title="差评" value={weeklyReport.negative} /></Col><Col span={6}><Statistic title="差评率" value={weeklyReport.negative_rate} suffix="%" /></Col></Row><Card size="small" title="建议动作"><List size="small" dataSource={weeklyReport.actions} renderItem={(item) => <List.Item>{item}</List.Item>} /></Card><Card size="small" title="重点商品"><Table size="small" rowKey="item_title" pagination={false} dataSource={weeklyReport.products} columns={[{ title: "商品", dataIndex: "item_title" }, { title: "评论数", dataIndex: "total", width: 90 }, { title: "差评数", dataIndex: "negative", width: 90 }]} /></Card></Space> : <Empty description="暂无周报" /> },
          { key: "accuracy", label: "准确率看板", children: accuracy ? <Space direction="vertical" style={{ width: "100%" }} size={16}><Row gutter={12}><Col span={6}><Statistic title="平均置信度" value={accuracy.average_confidence} suffix="%" /></Col><Col span={6}><Statistic title="人工确认样本" value={accuracy.confirmed_sample} /></Col><Col span={6}><Statistic title="人工修正" value={accuracy.corrected_count} /></Col><Col span={6}><Statistic title="待确认" value={accuracy.needs_review_count} /></Col></Row><Alert type="info" showIcon message={accuracy.manual_agreement_rate !== null ? `人工确认一致率 ${accuracy.manual_agreement_rate}%` : accuracy.confirmed_sample ? "已有人工确认，继续积累修正对比样本" : "还没有人工确认样本"} description="人工修正会成为历史记忆，并作为后续 AI 复核的示例。样本越多，这里的评估越可靠。" /><div><Text strong>分析来源：</Text><Space wrap>{accuracy.sources.map((item) => <Tag key={item.source}>{item.source} {item.count}</Tag>)}</Space></div>{accuracy.corrections.length ? <div><Text strong>常见修正：</Text><Space wrap>{accuracy.corrections.map((item) => <Tag color="orange" key={item.transition}>{item.transition} {item.count}</Tag>)}</Space></div> : null}</Space> : <Empty description="暂无准确率数据" /> },
        ]} />}
      </Modal>

      <Modal title="评论问题知识库" open={knowledgeOpen} onCancel={() => setKnowledgeOpen(false)} footer={null} width={860}>
        <Alert type="info" showIcon message="命中问题词后，会在评论详情中推荐处理方案，并用于生成更贴合的回复草稿。" style={{ marginBottom: 16 }} />
        <List size="small" dataSource={knowledgeArticles} style={{ maxHeight: 280, overflow: "auto", marginBottom: 16 }} locale={{ emptyText: "暂无知识条目" }} renderItem={(article) => <List.Item actions={[<Button size="small" onClick={() => editKnowledge(article)}>编辑</Button>, <Popconfirm title="确认删除这条问题知识？" onConfirm={() => deleteKnowledge(article)}><Button size="small" danger>删除</Button></Popconfirm>]}><List.Item.Meta title={<Space><Tag>{article.category}</Tag>{article.title}{article.store_id === 0 ? <Tag color="blue">全局</Tag> : null}</Space>} description={<><div>匹配词：{article.problem_terms.join("、") || "未设置"}</div><Text type="secondary">{article.solution}</Text></>} /></List.Item>} />
        <Card size="small" title={knowledgeEditing ? `编辑：${knowledgeEditing.title}` : "新增知识条目"}>
          <Space direction="vertical" style={{ width: "100%" }}>
            <Space style={{ width: "100%" }}><Input value={knowledgeTitle} onChange={(event) => setKnowledgeTitle(event.target.value)} placeholder="问题标题" style={{ width: 280 }} /><Input value={knowledgeCategory} onChange={(event) => setKnowledgeCategory(event.target.value)} placeholder="分类" style={{ width: 160 }} />{knowledgeEditing ? <Button onClick={() => editKnowledge()}>取消编辑</Button> : null}</Space>
            <Input value={knowledgeTerms} onChange={(event) => setKnowledgeTerms(event.target.value)} placeholder="匹配词，用逗号或顿号分隔，例如：包装破损、盒子压坏" />
            <Input.TextArea value={knowledgeSolution} onChange={(event) => setKnowledgeSolution(event.target.value)} rows={3} placeholder="内部处理步骤" maxLength={2000} showCount />
            <Input.TextArea value={knowledgeReply} onChange={(event) => setKnowledgeReply(event.target.value)} rows={3} placeholder="推荐给买家的回复话术（可选）" maxLength={1000} showCount />
            <Button type="primary" onClick={saveKnowledge}>保存知识条目</Button>
          </Space>
        </Card>
      </Modal>

      <Modal title="自定义情绪词库" open={termsOpen} onCancel={() => setTermsOpen(false)} footer={null} width={760}>
        <Alert type="info" showIcon message="词条保存后会立即重新分析包含该词的评论" description="店铺词库适合添加行业黑话、产品专用表达和容易误判的反讽词。" style={{ marginBottom: 16 }} />
        <Space wrap style={{ marginBottom: 16 }}><Input value={termText} onChange={(event) => setTermText(event.target.value)} placeholder="词语，例如：绝绝子" style={{ width: 220 }} /><Select value={termSentiment} onChange={setTermSentiment} style={{ width: 100 }} options={[{ value: "positive", label: "正向" }, { value: "neutral", label: "中性" }, { value: "negative", label: "负向" }]} /><InputNumber min={0.5} max={4} step={0.5} value={termWeight} onChange={(value) => setTermWeight(value ?? 1.5)} /><Button type="primary" onClick={saveTerm}>添加词条</Button></Space>
        <List dataSource={customTerms} locale={{ emptyText: "暂无自定义词条" }} renderItem={(term) => <List.Item actions={term.store_id === storeId ? [<Button size="small" onClick={() => toggleTerm(term)}>{term.enabled ? "停用" : "启用"}</Button>, <Popconfirm title="删除后会重新分析相关评论，确认删除？" onConfirm={() => deleteTerm(term)}><Button size="small" danger>删除</Button></Popconfirm>] : []}><List.Item.Meta title={<Space>{term.term}{sentimentTag(term.sentiment)}{term.store_id === 0 ? <Tag>全局</Tag> : null}{!term.enabled ? <Tag>已停用</Tag> : null}</Space>} description={`权重 ${term.weight} · 来源 ${term.source === "learned" ? "自动学习" : "人工维护"}`} /></List.Item>} />
      </Modal>

      <Modal title="评论问答" open={askOpen} onCancel={() => setAskOpen(false)} onOk={askReviews} confirmLoading={asking} okText="分析并回答" width={760}>
        <Space direction="vertical" style={{ width: "100%" }} size={16}><Input.TextArea value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} maxLength={300} showCount placeholder="例如：最近客户最不满意什么？哪个商品的包装问题最多？" />{answer ? <Card size="small" title="分析结果"><Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{answer}</Paragraph></Card> : <Alert type="info" showIcon message={`将分析近 ${days} 天评论`} description="回答只依据当前筛选店铺的评论，不会编造没有出现的信息。" />}</Space>
      </Modal>

      <Drawer title="评价详情" open={Boolean(detail)} onClose={() => setDetail(null)} width={560}>
        {detail ? <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="商品">{detail.item_title || detail.item_id || "未关联商品"}</Descriptions.Item>
            <Descriptions.Item label="店铺">{detail.store_name}</Descriptions.Item>
            <Descriptions.Item label="评价时间">{dayjs(detail.review_time).format("YYYY-MM-DD HH:mm")}</Descriptions.Item>
            <Descriptions.Item label="评价结果">{sentimentTag(detail.sentiment)} · 置信度 {(detail.confidence * 100).toFixed(0)}%</Descriptions.Item>
            <Descriptions.Item label="分析依据">{detail.analysis_reason || "暂无"}</Descriptions.Item>
            <Descriptions.Item label="分析路由"><Tag color={detail.analysis_source === "ai" ? "geekblue" : detail.analysis_source === "manual" ? "blue" : "default"}>{detail.analysis_source === "ai" ? "AI" : detail.analysis_source === "manual" ? "人工" : detail.analysis_source === "learned" ? "历史学习" : "本地规则"}</Tag>{detail.routing_reason || "按规则完成"}</Descriptions.Item>
            <Descriptions.Item label="问题标签">{detail.aspects?.length ? detail.aspects.map((item) => <Tag key={item.aspect} color={item.sentiment === "negative" ? "red" : "blue"}>{item.aspect}</Tag>) : "暂无"}</Descriptions.Item>
          </Descriptions>
          <Card size="small" title="评价内容"><Paragraph style={{ whiteSpace: "pre-wrap" }}>{detail.content || "（无文字评价）"}</Paragraph>{detail.append_content ? <Paragraph type="secondary" style={{ whiteSpace: "pre-wrap" }}>追评：{detail.append_content}</Paragraph> : null}</Card>
          <Card size="small" title="人工确认情绪"><Space><Button onClick={() => confirmSentiment("positive")}>好评</Button><Button onClick={() => confirmSentiment("neutral")}>中评</Button><Button danger onClick={() => confirmSentiment("negative")}>差评</Button></Space></Card>
          {knowledgeMatches.length ? <Card size="small" title="知识库推荐"><List size="small" dataSource={knowledgeMatches} renderItem={(article) => <List.Item><List.Item.Meta title={<Space><Tag>{article.category}</Tag>{article.title}<Tag color="green">匹配 {(article.confidence! * 100).toFixed(0)}%</Tag></Space>} description={<><div>命中：{article.matched_terms?.join("、")}</div><div>{article.solution}</div></>} /></List.Item>} /></Card> : null}
          <Space wrap><Select value={detail.process_status} onChange={(value) => updateProcess(detail, value)} options={Object.entries(processLabels).map(([value, label]) => ({ value, label }))} /><Select allowClear value={selectedTemplateId} onChange={setSelectedTemplateId} placeholder="选择回复模板" style={{ width: 170 }} options={replyTemplates.map((template) => ({ value: template.id, label: `${template.category} · ${template.name}` }))} /><Button icon={<RobotOutlined />} loading={replyLoading} onClick={createReplyDraft}>生成回复草稿</Button></Space>
          {detail.reply_content ? <Card size="small" title={<Space>回复内容<Tag color={detail.reply_status === "published" ? "green" : detail.reply_status === "approved" ? "blue" : detail.reply_status === "failed" ? "red" : "gold"}>{detail.reply_status === "published" ? "已发布" : detail.reply_status === "approved" ? "已审核" : detail.reply_status === "failed" ? "发布失败" : "草稿"}</Tag></Space>} extra={<Button type="text" icon={<CopyOutlined />} onClick={() => { void navigator.clipboard?.writeText(detail.reply_content); message.success("已复制"); }}>复制</Button>}><Space direction="vertical" style={{ width: "100%" }}><Input.TextArea value={detail.reply_content} disabled={detail.reply_status === "published"} onChange={(event) => setDetail({ ...detail, reply_content: event.target.value, reply_status: "draft", reply_error: "" })} rows={5} maxLength={500} showCount />{detail.reply_error ? <Alert type="error" showIcon message={detail.reply_error} /> : null}{detail.reply_published_at ? <Text type="secondary">发布时间：{dayjs(detail.reply_published_at).format("YYYY-MM-DD HH:mm")}</Text> : null}<Space><Button onClick={approveReply} loading={replyLoading} disabled={detail.reply_status === "published"}>审核通过</Button><Popconfirm title="确认将这段回复发布到淘宝？发布后不能撤回。" onConfirm={publishReply} disabled={detail.reply_status !== "approved"}><Button type="primary" loading={replyPublishing} disabled={detail.reply_status !== "approved" || detail.source !== "seller-review-management"}>发布到淘宝</Button></Popconfirm>{detail.source !== "seller-review-management" && detail.reply_status !== "published" ? <Text type="secondary">仅千牛评价管理抓取的评论可直接发布</Text> : null}</Space></Space></Card> : null}
          {detail.image_urls?.length ? <Space wrap>{detail.image_urls.map((url) => <a key={url} href={url} target="_blank" rel="noreferrer">查看评价图片</a>)}</Space> : null}
        </Space> : null}
      </Drawer>
    </div>
  );
}
