import { BarChartOutlined, BulbOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Progress, Row, Segmented, Space, Spin, Table, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "../components/ui/page-header";
import { DecisionBand, MetricRail, WorkspacePage } from "../components/ui/workspace-template";
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
  reliable_count?: number;
  reliable_rate?: number;
  reproducible_count?: number;
  reproducible_rate?: number;
};

type Insight = string | { title?: string; summary?: string; action?: string; level?: string };

type ReviewDashboard = {
  summary: ReviewSummary;
  funnels: FunnelItem[];
  channels?: ReviewGroup[];
  scenes: ReviewGroup[];
  actions: ReviewGroup[];
  tiers: ReviewGroup[];
  weekly_insights: Insight[];
  quality_summary?: {
    verified: number;
    reliable: number;
    reliable_rate: number;
    interfered: number;
    sparse: number;
    manually_reviewed: number;
    reproducible: number;
    reproducible_rate: number;
  };
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
  return (
    <Alert
      key={`${item.title || item.summary || "insight"}-${index}`}
      type={level}
      showIcon
      title={item.title || "复盘建议"}
      description={
        <Space orientation="vertical" size={2}>
          {item.summary ? <span>{item.summary}</span> : null}
          {item.action ? <Text strong>建议动作：{item.action}</Text> : null}
        </Space>
      }
    />
  );
}

export function PromotionsReviewPage() {
  const [searchParams] = useSearchParams();
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

  useEffect(() => {
    void load();
  }, [load]);

  const groupColumns: TableColumnsType<ReviewGroup> = [
    { title: "维度", dataIndex: "name", ellipsis: true },
    {
      title: "决策",
      dataIndex: "decision_count",
      width: 72,
      align: "right",
      render: fmtInt,
    },
    {
      title: "已验证",
      dataIndex: "verified_count",
      width: 82,
      align: "right",
      render: fmtInt,
    },
    {
      title: "成功率",
      dataIndex: "success_rate",
      width: 82,
      align: "right",
      render: percent,
    },
    {
      title: "中高可信",
      dataIndex: "reliable_rate",
      width: 92,
      align: "right",
      render: (value) => (value == null ? "—" : percent(value)),
    },
    {
      title: "可复制",
      dataIndex: "reproducible_rate",
      width: 82,
      align: "right",
      render: (value) => (value == null ? "—" : percent(value)),
    },
    {
      title: "ROI 变化",
      dataIndex: "roi_lift",
      width: 96,
      align: "right",
      render: (value) => <Text type={toNumber(value) < 0 ? "danger" : "success"}>{signed(value)}</Text>,
    },
    {
      title: "日均成交增量",
      dataIndex: "sales_lift",
      width: 128,
      align: "right",
      render: (value) => <Text type={toNumber(value) < 0 ? "danger" : "success"}>{signedMoney(value)}</Text>,
    },
    {
      title: "日均节省花费",
      dataIndex: "saved_spend",
      width: 128,
      align: "right",
      render: fmtMoney,
    },
  ];

  return (
    <WorkspacePage kind="analysis">
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="经营复盘看板"
        description="汇总决策采纳、执行验证与经营结果，沉淀下一轮推广优化依据。"
        updatedAt={data?.generated_at || null}
        extra={
          <Space wrap>
            <Segmented
              value={window}
              options={[
                { label: "近 7 天", value: "7d" },
                { label: "近 30 天", value: "30d" },
              ]}
              onChange={(value) => setWindow(value as ReviewWindow)}
            />
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
              刷新
            </Button>
          </Space>
        }
      />
      <DecisionBand
        eyebrow={window === "7d" ? "近 7 天结论" : "近 30 天结论"}
        title={data ? `验证成功率 ${percent(data.summary.success_rate)}，ROI 变化 ${signed(data.summary.roi_lift)}` : "等待复盘数据"}
        description={data ? `执行率 ${percent(data.summary.execution_rate)} · 验证率 ${percent(data.summary.verification_rate)} · 日均成交增量 ${signedMoney(data.summary.sales_lift)}` : "完成决策、执行和验证后，将在这里生成经营结论。"}
        action={<Button type="primary" onClick={() => setWindow(window === "7d" ? "30d" : "7d")}>切换到{window === "7d" ? "近 30 天" : "近 7 天"}</Button>}
        ariaLabel="推广经营复盘结论"
      />
      {searchParams.get("action_id") || searchParams.get("diagnostic_id") ? (
        <Alert
          type="success"
          showIcon
          title="已带入本次推广闭环上下文"
          description={`店铺 ${searchParams.get("store_id") || "当前"} · 渠道 ${searchParams.get("channel") || "未指定"} · 计划 ${searchParams.get("plan_id") || "未指定"}${searchParams.get("rule") ? ` · 来源规则 ${searchParams.get("rule")}` : ""}。下方复盘指标仍按所选周期汇总。`}
          style={{ marginBottom: 16 }}
        />
      ) : null}

      {loading && !data ? (
        <div style={{ padding: 80, textAlign: "center" }}>
          <Spin size="large" />
        </div>
      ) : null}
      {!loading && error ? (
        <Card variant="borderless">
          <Empty description={error}>
            <Button type="primary" onClick={() => void load()}>
              重新加载
            </Button>
          </Empty>
        </Card>
      ) : null}
      {!loading && !error && !data ? (
        <Card variant="borderless">
          <Empty description="暂无复盘数据，完成决策、执行和验证后将在这里汇总" />
        </Card>
      ) : null}

      {data ? (
        <>
          <MetricRail columns={4} items={[
              {
                label: "决策数",
                value: fmtInt(data.summary.decision_count),
                hint: "本周期进入复盘的决策",
              },
              {
                label: "采纳率",
                value: percent(data.summary.adoption_rate),
                hint: "建议被确认采纳的比例",
              },
              {
                label: "执行率",
                value: percent(data.summary.execution_rate),
                hint: "采纳决策进入执行的比例",
              },
              {
                label: "验证率",
                value: percent(data.summary.verification_rate),
                hint: "已执行动作完成验证的比例",
              },
              {
                label: "成功率",
                value: percent(data.summary.success_rate),
                hint: "已验证动作中的成功占比",
              },
              {
                label: "ROI 变化",
                value: signed(data.summary.roi_lift),
                hint: "验证后 ROI 减去动作前 ROI",
              },
              {
                label: "日均成交增量",
                value: signedMoney(data.summary.sales_lift),
                hint: "验证动作带来的日均成交增量",
              },
              {
                label: "日均节省花费",
                value: fmtMoney(data.summary.saved_spend),
                hint: "验证成功动作确认的日均节省金额",
              },
            ].map((item) => ({ key: item.label, label: item.label, value: item.value, hint: item.hint }))} />

          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={10}>
              <Card variant="borderless" title="决策漏斗" extra={<Text type="secondary">{window === "7d" ? "近 7 天" : "近 30 天"}</Text>}>
                {data.funnels?.length ? (
                  <Space orientation="vertical" size={14} style={{ width: "100%" }}>
                    {data.funnels.map((item) => (
                      <div key={item.key}>
                        <Space
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            marginBottom: 5,
                          }}
                        >
                          <Text>{item.name}</Text>
                          <Text strong>
                            {fmtInt(item.count)} <Text type="secondary">· {percent(item.rate)}</Text>
                          </Text>
                        </Space>
                        <Progress percent={Math.min(100, Math.max(0, toNumber(item.rate)))} showInfo={false} />
                      </div>
                    ))}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无决策漏斗数据" />
                )}
              </Card>
            </Col>
            <Col xs={24} lg={14}>
              <Card
                variant="borderless"
                title={
                  <Space>
                    <BulbOutlined />
                    自动复盘建议
                  </Space>
                }
              >
                {data.weekly_insights?.length ? (
                  <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                    {data.weekly_insights.map(insightAlert)}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂未生成复盘建议，继续积累验证结果后将自动输出" />
                )}
              </Card>
            </Col>
          </Row>

          {data.quality_summary ? (
            <Card variant="borderless" title="验证质量与经验可复制性" style={{ marginTop: 16 }}>
              <Row gutter={[12, 12]}>
                {[
                  {
                    label: "已验证",
                    value: fmtInt(data.quality_summary.verified),
                    hint: "进入质量判断的动作",
                  },
                  {
                    label: "中高可信",
                    value: `${fmtInt(data.quality_summary.reliable)} · ${percent(data.quality_summary.reliable_rate)}`,
                    hint: "基线和观察数据足够",
                  },
                  {
                    label: "外部干扰",
                    value: fmtInt(data.quality_summary.interfered),
                    hint: "不宜直接归因给调整动作",
                  },
                  {
                    label: "稀疏样本",
                    value: fmtInt(data.quality_summary.sparse),
                    hint: "需继续积累日报",
                  },
                  {
                    label: "已人工复盘",
                    value: fmtInt(data.quality_summary.manually_reviewed),
                    hint: "已补充运营判断",
                  },
                  {
                    label: "可复制经验",
                    value: `${fmtInt(data.quality_summary.reproducible)} · ${percent(data.quality_summary.reproducible_rate)}`,
                    hint: "可优先进入下一轮建议",
                  },
                ].map((item) => (
                  <Col xs={12} md={8} xl={4} key={item.label}>
                    <Text type="secondary">{item.label}</Text>
                    <div style={{ fontSize: 20, fontWeight: 700, margin: "4px 0" }}>{item.value}</div>
                    <Text type="secondary" style={{ fontSize: 11 }}>
                      {item.hint}
                    </Text>
                  </Col>
                ))}
              </Row>
            </Card>
          ) : null}

          {[
            {
              title: "渠道效果对比",
              dataSource: data.channels,
              emptyText: "暂无渠道复盘数据",
            },
            {
              title: "场景效果对比",
              dataSource: data.scenes,
              emptyText: "暂无场景复盘数据",
            },
            {
              title: "动作效果对比",
              dataSource: data.actions,
              emptyText: "暂无动作复盘数据",
            },
            {
              title: "档位效果对比",
              dataSource: data.tiers,
              emptyText: "暂无档位复盘数据",
            },
          ].map((section) => (
            <Card key={section.title} variant="borderless" title={section.title} style={{ marginTop: 16 }}>
              <Table<ReviewGroup> rowKey={(record) => record.key || record.name} size="small" pagination={false} scroll={{ x: 760 }} columns={groupColumns} dataSource={section.dataSource || []} locale={{ emptyText: section.emptyText }} />
            </Card>
          ))}
        </>
      ) : null}
    </WorkspacePage>
  );
}
