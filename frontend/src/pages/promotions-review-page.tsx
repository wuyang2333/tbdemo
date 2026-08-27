import { BarChartOutlined, BulbOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Progress, Row, Segmented, Space, Spin, Table, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import { PageHeader } from "../components/ui/page-header";
import { fmtInt, fmtMoney } from "../components/promotions/promotions-ui";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";

const { Text } = Typography;

type ReviewWindow = "7d" | "30d";

type ReviewSummary = {
  decision_count: number;
  adoption_rate: number;
  execution_rate: number;
  verification_rate: number;
  success_rate: number;
  roi_lift: number;
  sales_lift: number;
  saved_spend: number;
};

type FunnelItem = { key: string; name: string; count: number; rate: number };

type ReviewGroup = {
  key: string;
  name: string;
  decision_count: number;
  verified_count: number;
  success_rate: number;
  roi_lift: number;
  sales_lift: number;
  saved_spend: number;
};

type Insight = string | { title?: string; summary?: string; action?: string; level?: string };

type ReviewDashboard = {
  summary: ReviewSummary;
  funnels: FunnelItem[];
  scenes: ReviewGroup[];
  actions: ReviewGroup[];
  tiers: ReviewGroup[];
  weekly_insights: Insight[];
  generated_at?: string;
};

const toNumber = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : 0);
const percent = (value: unknown) => `${toNumber(value).toFixed(1)}%`;
const signed = (value: unknown) => `${toNumber(value) >= 0 ? "+" : ""}${toNumber(value).toFixed(2)}`;
const signedMoney = (value: unknown) => {
  const number = toNumber(value);
  return `${number >= 0 ? "+" : "-"}${fmtMoney(Math.abs(number))}`;
};

function insightAlert(item: Insight, index: number) {
  if (typeof item === "string") {
    return <Alert key={`${item}-${index}`} type="info" showIcon title={item} />;
  }
  const level = item.level === "error" ? "error" : item.level === "warning" || item.level === "warn" ? "warning" : item.level === "success" ? "success" : "info";
  return <Alert key={`${item.title || item.summary || "insight"}-${index}`} type={level} showIcon title={item.title || "复盘建议"} description={<Space orientation="vertical" size={2}>{item.summary ? <span>{item.summary}</span> : null}{item.action ? <Text strong>建议动作：{item.action}</Text> : null}</Space>} />;
}

export function PromotionsReviewPage() {
  const { currentStore } = useStores();
  const [window, setWindow] = useState<ReviewWindow>("7d");
  const [data, setData] = useState<ReviewDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await http.get<ReviewDashboard>(`/promotions/review-dashboard?window=${window}${currentStore ? `&store_id=${currentStore.id}` : ""}`);
      setData(response.data);
    } catch (requestError) {
      const detail = getApiErrorMessage(requestError);
      setData(null);
      setError(detail);
      message.error(detail);
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id, window]);

  useEffect(() => { void load(); }, [load]);

  const groupColumns: TableColumnsType<ReviewGroup> = [
    { title: "维度", dataIndex: "name", ellipsis: true },
    { title: "决策", dataIndex: "decision_count", width: 72, align: "right", render: fmtInt },
    { title: "已验证", dataIndex: "verified_count", width: 82, align: "right", render: fmtInt },
    { title: "成功率", dataIndex: "success_rate", width: 82, align: "right", render: percent },
    { title: "ROI 变化", dataIndex: "roi_lift", width: 96, align: "right", render: (value) => <Text type={toNumber(value) < 0 ? "danger" : "success"}>{signed(value)}</Text> },
    { title: "日均成交增量", dataIndex: "sales_lift", width: 128, align: "right", render: (value) => <Text type={toNumber(value) < 0 ? "danger" : "success"}>{signedMoney(value)}</Text> },
    { title: "日均节省花费", dataIndex: "saved_spend", width: 128, align: "right", render: fmtMoney },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="经营复盘看板"
        description="汇总决策采纳、执行验证与经营结果，沉淀下一轮推广优化依据。"
        updatedAt={data?.generated_at || null}
        extra={<Space wrap><Segmented value={window} options={[{ label: "近 7 天", value: "7d" }, { label: "近 30 天", value: "30d" }]} onChange={(value) => setWindow(value as ReviewWindow)} /><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button></Space>}
      />

      {loading && !data ? <div style={{ padding: 80, textAlign: "center" }}><Spin size="large" /></div> : null}
      {!loading && error ? <Card variant="borderless"><Empty description={error}><Button type="primary" onClick={() => void load()}>重新加载</Button></Empty></Card> : null}
      {!loading && !error && !data ? <Card variant="borderless"><Empty description="暂无复盘数据，完成决策、执行和验证后将在这里汇总" /></Card> : null}

      {data ? (
        <>
          <Row gutter={[12, 12]}>
            {[
              { label: "决策数", value: fmtInt(data.summary.decision_count), hint: "本周期进入复盘的决策" },
              { label: "采纳率", value: percent(data.summary.adoption_rate), hint: "建议被确认采纳的比例" },
              { label: "执行率", value: percent(data.summary.execution_rate), hint: "采纳决策进入执行的比例" },
              { label: "验证率", value: percent(data.summary.verification_rate), hint: "已执行动作完成验证的比例" },
              { label: "成功率", value: percent(data.summary.success_rate), hint: "已验证动作中的成功占比" },
              { label: "ROI 变化", value: signed(data.summary.roi_lift), hint: "验证后 ROI 减去动作前 ROI" },
              { label: "日均成交增量", value: signedMoney(data.summary.sales_lift), hint: "验证动作带来的日均成交增量" },
              { label: "日均节省花费", value: fmtMoney(data.summary.saved_spend), hint: "验证成功动作确认的日均节省金额" },
            ].map((item) => <Col xs={12} sm={8} xl={6} key={item.label}><Card variant="borderless" style={{ height: "100%" }}><Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text><div style={{ fontSize: 22, fontWeight: 700, margin: "5px 0" }}>{item.value}</div><Text type="secondary" style={{ fontSize: 11 }}>{item.hint}</Text></Card></Col>)}
          </Row>

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={10}>
              <Card variant="borderless" title="决策漏斗" extra={<Text type="secondary">{window === "7d" ? "近 7 天" : "近 30 天"}</Text>}>
                {data.funnels?.length ? <Space orientation="vertical" size={14} style={{ width: "100%" }}>{data.funnels.map((item) => <div key={item.key}><Space style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}><Text>{item.name}</Text><Text strong>{fmtInt(item.count)} <Text type="secondary">· {percent(item.rate)}</Text></Text></Space><Progress percent={Math.min(100, Math.max(0, toNumber(item.rate)))} showInfo={false} /></div>)}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无决策漏斗数据" />}
              </Card>
            </Col>
            <Col xs={24} lg={14}>
              <Card variant="borderless" title={<Space><BulbOutlined />自动复盘建议</Space>}>
                {data.weekly_insights?.length ? <Space orientation="vertical" size={10} style={{ width: "100%" }}>{data.weekly_insights.map(insightAlert)}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未生成复盘建议，继续积累验证结果后将自动输出" />}
              </Card>
            </Col>
          </Row>

          {[
            { title: "场景效果对比", dataSource: data.scenes, emptyText: "暂无场景复盘数据" },
            { title: "动作效果对比", dataSource: data.actions, emptyText: "暂无动作复盘数据" },
            { title: "档位效果对比", dataSource: data.tiers, emptyText: "暂无档位复盘数据" },
          ].map((section) => <Card key={section.title} variant="borderless" title={section.title} style={{ marginTop: 16 }}><Table<ReviewGroup> rowKey={(record) => record.key || record.name} size="small" pagination={false} scroll={{ x: 760 }} columns={groupColumns} dataSource={section.dataSource || []} locale={{ emptyText: section.emptyText }} /></Card>)}
        </>
      ) : null}
    </div>
  );
}
