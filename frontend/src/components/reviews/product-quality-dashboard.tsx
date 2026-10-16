import { ArrowDownOutlined, ArrowUpOutlined, ReloadOutlined, RightOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, List, Progress, Skeleton, Space, Table, Tag, Tooltip, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import http, { getApiErrorMessage } from "../../lib/api";
import { ErrorState } from "../ui/page-state";
import { MetricRail, WorkspacePage } from "../ui/workspace-template";
import ImprovementActionPanel from "./improvement-action-panel";

const { Text, Title } = Typography;

export type QualityRiskLevel = "high" | "medium" | "low" | "normal";

export type QualityAspect = {
  aspect: string;
  count: number;
};

export type QualityProduct = {
  store_id: number | null;
  item_id: string;
  item_title: string;
  total: number;
  negative: number;
  negative_rate: number;
  previous_total: number;
  previous_negative: number;
  previous_negative_rate: number;
  total_change: number;
  negative_change: number;
  negative_rate_change: number;
  top_aspects: QualityAspect[];
  risk_level: QualityRiskLevel;
  sample_warning: string;
};

export type QualityEvidence = {
  id: number;
  store_id: number | null;
  item_id: string;
  content: string;
  item_title: string;
};

export type QualityTopicProduct = {
  store_id: number | null;
  item_id: string;
  name: string;
  count: number;
};

export type QualityTopic = {
  topic: string;
  count: number;
  negative: number;
  negative_rate: number;
  products: QualityTopicProduct[];
  examples: QualityEvidence[];
};

export type QualityOverviewSummary = {
  total: number;
  negative: number;
  negative_rate: number;
  previous_total: number;
  previous_negative: number;
  previous_negative_rate: number;
  total_change: number;
  negative_change: number;
  negative_rate_change: number;
  product_count: number;
  high_risk_product_count: number;
};

export type QualityOverviewResponse = {
  days: number;
  current_window: { start: string; end: string };
  previous_window: { start: string; end: string };
  summary: QualityOverviewSummary;
  products: QualityProduct[];
  topics: QualityTopic[];
  emerging_terms: { term: string; count: number }[];
};

export type ProductQualityDashboardProps = {
  /** 当前店铺；不传表示按当前用户可见店铺汇总。 */
  storeId?: number | null;
  /** 当前分析窗口，单位为天。 */
  days: number;
  /** 点击商品后由 CustomersPage 打开商品详情或筛选评论。 */
  onSelectProduct?: (product: QualityProduct) => void;
  /** 点击问题主题后由 CustomersPage 筛选对应评论。 */
  onSelectTopic?: (topic: QualityTopic) => void;
  className?: string;
};

const riskMeta: Record<QualityRiskLevel, { label: string; color: string }> = {
  high: { label: "高风险", color: "red" },
  medium: { label: "观察", color: "orange" },
  low: { label: "低风险", color: "blue" },
  normal: { label: "正常", color: "green" },
};

function formatDelta(value: number, suffix = "个百分点"): string {
  if (!value) return "持平";
  return `${value > 0 ? "+" : ""}${value}${suffix}`;
}

function trendColor(value: number): string | undefined {
  if (value > 0) return "var(--ops-danger)";
  if (value < 0) return "var(--ops-success)";
  return undefined;
}

function TrendDelta({ value }: { value: number }) {
  if (!value) return <Text type="secondary">持平</Text>;
  const Icon = value > 0 ? ArrowUpOutlined : ArrowDownOutlined;
  return (
    <Space size={4} style={{ color: trendColor(value) }}>
      <Icon aria-hidden="true" />
      <span>{formatDelta(value)}</span>
    </Space>
  );
}

function ProductRiskTable({ products, onSelectProduct }: { products: QualityProduct[]; onSelectProduct?: (product: QualityProduct) => void }) {
  const columns = useMemo<TableColumnsType<QualityProduct>>(() => [
    {
      title: "商品",
      dataIndex: "item_title",
      key: "item_title",
      render: (value: string, record: QualityProduct) => (
        <Space direction="vertical" size={2} style={{ maxWidth: 300 }}>
          <Text strong ellipsis={{ tooltip: value }}>{value || record.item_id || "未命名商品"}</Text>
          {record.item_id ? <Text type="secondary" copyable={{ text: record.item_id }} style={{ fontSize: 12 }}>ID：{record.item_id}</Text> : null}
        </Space>
      ),
    },
    { title: "评论量", dataIndex: "total", key: "total", width: 84, align: "right" },
    { title: "差评", dataIndex: "negative", key: "negative", width: 72, align: "right" },
    {
      title: "差评率",
      dataIndex: "negative_rate",
      key: "negative_rate",
      width: 108,
      render: (value: number, record: QualityProduct) => (
        <Space direction="vertical" size={2}>
          <Text strong>{value}%</Text>
          {record.sample_warning ? <Text type="warning" style={{ fontSize: 12 }}>样本较少</Text> : null}
        </Space>
      ),
    },
    {
      title: "主要问题",
      dataIndex: "top_aspects",
      key: "top_aspects",
      width: 210,
      render: (items: QualityAspect[]) => items?.length ? (
        <Space wrap size={[4, 4]}>
          {items.slice(0, 3).map((item) => <Tag key={item.aspect}>{item.aspect} {item.count}</Tag>)}
        </Space>
      ) : <Text type="secondary">暂无明确主题</Text>,
    },
    {
      title: "较上周期",
      dataIndex: "negative_rate_change",
      key: "negative_rate_change",
      width: 124,
      render: (value: number) => <TrendDelta value={value} />,
    },
    {
      title: "风险",
      dataIndex: "risk_level",
      key: "risk_level",
      width: 90,
      render: (value: QualityRiskLevel) => <Tag color={riskMeta[value]?.color ?? "default"}>{riskMeta[value]?.label ?? "待判断"}</Tag>,
    },
    onSelectProduct ? {
      title: "操作",
      key: "action",
      width: 100,
      fixed: "right",
      render: (_value: unknown, record: QualityProduct) => <Button type="link" size="small" onClick={() => onSelectProduct(record)}>查看商品 <RightOutlined aria-hidden="true" /></Button>,
    } : null,
  ].filter(Boolean) as TableColumnsType<QualityProduct>, [onSelectProduct]);

  return (
    <Table<QualityProduct>
      rowKey={(record) => `${record.store_id ?? "all"}-${record.item_id}-${record.item_title}`}
      size="small"
      sticky
      pagination={{ pageSize: 8, showSizeChanger: false, showTotal: (total) => `共 ${total} 个商品` }}
      dataSource={products}
      columns={columns}
      scroll={{ x: 980 }}
    />
  );
}

function TopicCard({ topic, onSelectTopic }: { topic: QualityTopic; onSelectTopic?: (topic: QualityTopic) => void }) {
  return (
    <Card
      size="small"
      title={<Space size={8}><span>{topic.topic}</span><Tag color={topic.negative_rate >= 30 ? "red" : "orange"}>{topic.negative} 条负面</Tag></Space>}
      extra={onSelectTopic ? <Button type="link" size="small" onClick={() => onSelectTopic(topic)}>查看评价</Button> : null}
      style={{ height: "100%", borderColor: "var(--ops-border)", background: "var(--ops-panel)" }}
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Space split={<Text type="secondary">·</Text>} wrap>
          <Text type="secondary">涉及 {topic.count} 条评价</Text>
          <Text type="secondary">负面率 {topic.negative_rate}%</Text>
        </Space>
        <Progress percent={Math.min(Math.max(topic.negative_rate, 0), 100)} showInfo={false} size="small" />
        <div>
          <Text type="secondary">主要负面商品</Text>
          <div style={{ marginTop: 6 }}>
            {topic.products.length ? topic.products.map((product) => <Tag key={`${product.store_id ?? "all"}-${product.item_id || product.name}`}>{product.name} · {product.count}</Tag>) : <Text type="secondary">暂无负面商品</Text>}
          </div>
        </div>
        <div>
          <Space size={6} style={{ marginBottom: 6 }}>
            <Text type="secondary">代表评价证据</Text>
            <Tooltip title="仅展示当前窗口内该主题的负面评价原文，不等同于已确认的质量缺陷"><Text type="secondary" aria-label="证据说明">ⓘ</Text></Tooltip>
          </Space>
          {topic.examples.length ? (
            <List
              size="small"
              dataSource={topic.examples}
              renderItem={(example) => <List.Item style={{ padding: "6px 0", alignItems: "flex-start" }}><Text ellipsis={{ tooltip: example.content }} style={{ maxWidth: "100%" }}>“{example.content || "（无文字评价）"}”</Text></List.Item>}
            />
          ) : <Text type="secondary">暂无负面评价证据</Text>}
        </div>
      </Space>
    </Card>
  );
}

export function ProductQualityDashboard({ storeId, days, onSelectProduct, onSelectTopic, className }: ProductQualityDashboardProps) {
  const [data, setData] = useState<QualityOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await http.get<QualityOverviewResponse>("/customers/reviews/quality-overview", {
        params: { ...(storeId == null ? {} : { store_id: storeId }), days },
      });
      setData(response.data);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [days, storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading && !data) {
    return <WorkspacePage kind="analysis" className={className}><Skeleton active paragraph={{ rows: 8 }} /></WorkspacePage>;
  }

  if (error && !data) {
    return <WorkspacePage kind="analysis" className={className}><ErrorState title="商品质量数据加载失败" description={error} onRetry={() => void load()} /></WorkspacePage>;
  }

  if (!data) return null;

  const { summary, products, topics } = data;
  const hasReviews = summary.total > 0 || products.length > 0 || topics.length > 0;

  return (
    <WorkspacePage kind="analysis" className={className}>
      {error ? <Alert type="error" showIcon message="商品质量数据刷新失败" description={error} action={<Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>重试</Button>} style={{ marginBottom: 16 }} /> : null}
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 16, marginBottom: 12, flexWrap: "wrap" }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>商品质量总览</Title>
          <Text type="secondary">近 {days} 天评价信号 · 与前一等长周期比较</Text>
        </div>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新数据</Button>
      </div>

      <MetricRail columns={4} items={[
        { label: "风险商品", value: summary.high_risk_product_count, hint: `共 ${summary.product_count} 个有评价商品`, tone: summary.high_risk_product_count ? "var(--ops-danger)" : "var(--ops-success)" },
        { label: "问题主题", value: topics.length, hint: `涉及 ${summary.negative} 条差评`, tone: topics.length ? "var(--ops-warn)" : "var(--ops-success)" },
        { label: "差评率", value: `${summary.negative_rate}%`, hint: <TrendDelta value={summary.negative_rate_change} />, tone: trendColor(summary.negative_rate_change) },
        { label: "评价总量", value: summary.total, hint: formatDelta(summary.total_change, " 条"), tone: "var(--ops-accent)" },
      ]} />

      {!hasReviews ? (
        <div className="ops-data-empty" style={{ marginTop: 16 }}>
          <Empty description="当前时间范围内暂无评价数据"><Text type="secondary">请先同步评价，或扩大时间范围后重试。</Text></Empty>
        </div>
      ) : (
        <Space direction="vertical" size={16} style={{ width: "100%", marginTop: 16 }}>
          <Card title={<Space><span>商品风险排行</span><Text type="secondary" style={{ fontSize: 13 }}>按风险等级、差评数和变化幅度排序</Text></Space>} style={{ borderColor: "var(--ops-border)", background: "var(--ops-panel)" }} bodyStyle={{ padding: 0 }}>
            <ProductRiskTable products={products} onSelectProduct={onSelectProduct} />
          </Card>

          <section aria-labelledby="quality-topics-title">
            <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, marginBottom: 10, flexWrap: "wrap" }}>
              <div>
                <Title id="quality-topics-title" level={5} style={{ margin: 0 }}>问题主题与证据</Title>
                <Text type="secondary">先看集中出现的问题，再进入评论处理或商品详情。</Text>
              </div>
              {data.emerging_terms.length ? <Space wrap size={[4, 4]}><Text type="secondary">近期词：</Text>{data.emerging_terms.slice(0, 5).map((item) => <Tag key={item.term}>{item.term} {item.count}</Tag>)}</Space> : null}
            </div>
            {topics.length ? <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 12 }}>{topics.slice(0, 8).map((topic) => <TopicCard key={topic.topic} topic={topic} onSelectTopic={onSelectTopic} />)}</div> : <Card size="small"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有可归纳的问题主题" /></Card>}
          </section>
          <ImprovementActionPanel storeId={storeId} onChanged={() => void load()} />
        </Space>
      )}
    </WorkspacePage>
  );
}

export default ProductQualityDashboard;
