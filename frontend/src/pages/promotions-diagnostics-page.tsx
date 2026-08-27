import {
  AlertOutlined,
  ArrowRightOutlined,
  FileSearchOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Drawer,
  Empty,
  Progress,
  Row,
  Select,
  Space,
  Spin,
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
import { PageHeader } from "../components/ui/page-header";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";

const { Paragraph, Text, Title } = Typography;

type Severity = "critical" | "high" | "medium";
type Confidence = "high" | "medium" | "low";

type Evidence = {
  label: string;
  current: number | string;
  baseline: number | string | null;
  unit: string;
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
  category: string;
  severity: Severity;
  title: string;
  summary: string;
  confidence: Confidence;
  confidence_reason: string;
  plan_id: number;
  plan_name: string;
  store_id: number;
  store_name: string;
  scene_name: string;
  plan_status: string;
  spend_at_risk: number;
  sales_gap: number;
  evidence: Evidence[];
  possible_causes: string[];
  recommendations: Recommendation[];
  unknown_dimensions: string[];
  detected_at: string;
};

type DiagnosticsData = {
  summary: {
    total: number;
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
  };
  thresholds: Record<string, number>;
  generated_at: string;
};

const severityMeta: Record<Severity, { label: string; color: string }> = {
  critical: { label: "紧急", color: "red" },
  high: { label: "高风险", color: "orange" },
  medium: { label: "中风险", color: "gold" },
};

const confidenceMeta: Record<Confidence, { label: string; color: string }> = {
  high: { label: "高可信", color: "green" },
  medium: { label: "中可信", color: "blue" },
  low: { label: "低可信", color: "default" },
};

const categoryLabels: Record<string, string> = {
  budget: "预算异常",
  conversion: "转化异常",
  efficiency: "效率异常",
  delivery: "投放异常",
  data: "数据异常",
};

function formatEvidenceValue(value: Evidence["current"], unit: string): string {
  if (typeof value === "number") return `${value.toLocaleString("zh-CN")}${unit}`;
  return `${value}${unit}`;
}

export function PromotionsDiagnosticsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { stores, currentStore } = useStores();
  const [data, setData] = useState<DiagnosticsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [storeId, setStoreId] = useState<number | "all">(currentStore?.id ?? "all");
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [category, setCategory] = useState("all");
  const [confidence, setConfidence] = useState<Confidence | "all">("all");
  const [selected, setSelected] = useState<Diagnostic | null>(null);

  useEffect(() => {
    setStoreId(currentStore?.id ?? "all");
  }, [currentStore?.id]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await http.get<DiagnosticsData>("/promotions/diagnostics", {
        params: storeId === "all" ? undefined : { store_id: storeId },
      });
      setData(response.data);
      const targetId = searchParams.get("diagnostic_id");
      if (targetId) setSelected(response.data.items.find((item) => item.id === targetId) || null);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [searchParams, storeId]);

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

  const filteredItems = useMemo(() => (data?.items || []).filter((item) => (
    (severity === "all" || item.severity === severity)
    && (category === "all" || item.category === category)
    && (confidence === "all" || item.confidence === confidence)
  )), [category, confidence, data?.items, severity]);

  const categoryOptions = useMemo(() => [
    { value: "all", label: "全部异常类型" },
    ...(data?.categories || []).map((item) => ({
      value: item.category,
      label: `${categoryLabels[item.category] || item.category} (${item.count})`,
    })),
  ], [data?.categories]);

  const columns: TableColumnsType<Diagnostic> = [
    {
      title: "等级",
      dataIndex: "severity",
      width: 88,
      render: (value: Severity) => <Tag color={severityMeta[value].color}>{severityMeta[value].label}</Tag>,
    },
    {
      title: "异常诊断",
      key: "diagnostic",
      render: (_value, item) => (
        <Space orientation="vertical" size={2}>
          <Space size={6} wrap><Text strong>{item.title}</Text><Tag variant="filled">{categoryLabels[item.category] || item.category}</Tag></Space>
          <Text type="secondary" style={{ fontSize: 12 }}>{item.summary}</Text>
        </Space>
      ),
    },
    {
      title: "计划 / 店铺",
      key: "plan",
      width: 190,
      render: (_value, item) => (
        <Space orientation="vertical" size={1}>
          <Text>{item.plan_name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{item.store_name || "未标注店铺"} · {item.scene_name}</Text>
        </Space>
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
          <Button size="small" icon={<FileSearchOutlined />} onClick={() => openDetail(item)}>查看诊断</Button>
          <Button size="small" type="primary" onClick={() => navigate(item.recommendations[0].path)}>处理</Button>
        </Space>
      ),
    },
  ];

  const coverageStatus = (data?.data_health.realtime_coverage_rate || 0) >= 90 ? "success" : "normal";

  return (
    <div>
      <PageHeader
        icon={<AlertOutlined />}
        eyebrow="推广管理"
        title="推广异常诊断中心"
        description="基于真实计划指标发现异常，先看证据和影响，再由运营人员决定如何处理。"
        updatedAt={data?.generated_at || null}
        extra={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>重新诊断</Button>}
      />

      <Alert
        type="info"
        showIcon
        title="诊断只提供可验证证据和处理建议，不会自动修改万相台"
        description="可能原因统一标记为待核查假设；商品、活动、素材、人群和竞争数据未接入前，不会被伪装成确定结论。"
        style={{ marginBottom: 16 }}
      />

      {loading && !data ? <div style={{ minHeight: 320, display: "flex", alignItems: "center", justifyContent: "center" }} aria-busy="true"><Spin size="large" /></div> : null}
      {!loading && !data ? <Card variant="borderless"><Empty description="暂时无法加载异常诊断"><Button type="primary" onClick={() => void load()}>重新加载</Button></Empty></Card> : null}

      {data ? (
        <>
          <Row gutter={[12, 12]}>
            {[
              { label: "全部异常", value: data.summary.total, color: "var(--ops-text)", hint: "当前规则命中的信号" },
              { label: "紧急", value: data.summary.critical, color: "var(--ops-danger)", hint: "需要立即核查" },
              { label: "高风险", value: data.summary.high, color: "var(--ops-warn)", hint: "建议今天处理" },
              { label: "中风险", value: data.summary.medium, color: "var(--ops-info)", hint: "进入观察队列" },
              { label: "影响计划", value: data.summary.affected_plan_count, color: "var(--ops-text)", hint: `在投计划 ${data.data_health.active_plan_count} 个` },
              { label: "预计风险花费", value: fmtMoney(data.summary.estimated_spend_at_risk), color: "var(--ops-danger)", hint: "按计划去重估算" },
            ].map((item) => (
              <Col xs={12} sm={8} xl={4} key={item.label}>
                <Card variant="borderless" style={{ height: "100%" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
                  <div style={{ color: item.color, fontSize: 24, fontWeight: 700, margin: "5px 0" }}>{item.value}</div>
                  <Text type="secondary" style={{ fontSize: 11 }}>{item.hint}</Text>
                </Card>
              </Col>
            ))}
          </Row>

          <Card
            variant="borderless"
            title="异常清单"
            extra={(
              <Space wrap>
                <Select
                  aria-label="诊断店铺范围"
                  value={storeId}
                  style={{ minWidth: 150 }}
                  options={[{ value: "all", label: "全部可见店铺" }, ...stores.map((store) => ({ value: store.id, label: store.name }))]}
                  onChange={(value) => setStoreId(value)}
                />
                <Select
                  aria-label="异常严重程度"
                  value={severity}
                  style={{ minWidth: 112 }}
                  options={[{ value: "all", label: "全部等级" }, ...Object.entries(severityMeta).map(([value, meta]) => ({ value, label: meta.label }))]}
                  onChange={(value) => setSeverity(value)}
                />
                <Select aria-label="异常类型" value={category} style={{ minWidth: 150 }} options={categoryOptions} onChange={setCategory} />
                <Select
                  aria-label="诊断可信度"
                  value={confidence}
                  style={{ minWidth: 112 }}
                  options={[{ value: "all", label: "全部可信度" }, ...Object.entries(confidenceMeta).map(([value, meta]) => ({ value, label: meta.label }))]}
                  onChange={(value) => setConfidence(value)}
                />
              </Space>
            )}
            style={{ marginTop: 16 }}
          >
            <Table<Diagnostic>
              rowKey="id"
              size="small"
              columns={columns}
              dataSource={filteredItems}
              pagination={{ pageSize: 15, hideOnSinglePage: true }}
              scroll={{ x: 980 }}
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
                <Text type="secondary">可见 {data.data_health.visible_plan_count} 个计划，其中 {data.data_health.realtime_coverage_count} 个在投计划已有实时指标。</Text>
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card variant="borderless" title="当前诊断边界" style={{ height: "100%" }}>
                <Text type="secondary">已接入预算、花费、成交、ROI、点击、计划状态和更新时间。商品库存与价格、活动、素材、人群和竞争环境仍需人工核查。</Text>
              </Card>
            </Col>
          </Row>
        </>
      ) : null}

      <Drawer
        open={Boolean(selected)}
        title={selected ? `异常诊断 · ${selected.plan_name}` : "异常诊断"}
        size="large"
        onClose={closeDetail}
        destroyOnHidden
      >
        {selected ? (
          <>
            <Space wrap style={{ marginBottom: 12 }}>
              <Tag color={severityMeta[selected.severity].color}>{severityMeta[selected.severity].label}</Tag>
              <Tag>{categoryLabels[selected.category] || selected.category}</Tag>
              <Tag color={confidenceMeta[selected.confidence].color}>{confidenceMeta[selected.confidence].label}</Tag>
              <Text type="secondary">{dayjs(selected.detected_at).format("YYYY-MM-DD HH:mm")}</Text>
            </Space>
            <Title level={4} style={{ marginTop: 0 }}>{selected.title}</Title>
            <Paragraph type="secondary">{selected.summary}</Paragraph>

            <Descriptions bordered size="small" column={{ xs: 1, sm: 2 }} items={[
              { key: "store", label: "店铺", children: selected.store_name || "—" },
              { key: "scene", label: "推广场景", children: selected.scene_name },
              { key: "status", label: "计划状态", children: selected.plan_status || "—" },
              { key: "risk", label: "预计风险花费", children: selected.spend_at_risk ? <Text type="danger">{fmtMoney(selected.spend_at_risk)}</Text> : "—" },
              { key: "gap", label: "成交缺口", children: selected.sales_gap ? fmtMoney(selected.sales_gap) : "—" },
              { key: "rule", label: "诊断规则", children: selected.rule_code },
            ]} />

            <Divider titlePlacement="start">真实证据</Divider>
            <Row gutter={[10, 10]}>
              {selected.evidence.map((item) => (
                <Col xs={12} sm={8} key={item.label}>
                  <Card size="small" style={{ height: "100%" }}>
                    <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
                    <div style={{ fontSize: 18, fontWeight: 650, marginTop: 4 }}>{formatEvidenceValue(item.current, item.unit)}</div>
                    {item.baseline !== null ? <Text type="secondary" style={{ fontSize: 11 }}>对比值 {formatEvidenceValue(item.baseline, item.unit)}</Text> : null}
                  </Card>
                </Col>
              ))}
            </Row>

            <Alert type="info" showIcon title={`可信度说明：${selected.confidence_reason}`} style={{ marginTop: 16 }} />

            <Divider titlePlacement="start">待核查原因</Divider>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              {selected.possible_causes.map((cause) => <Alert key={cause} type="warning" title={cause} />)}
            </Space>

            <Divider titlePlacement="start">尚未接入的判断维度</Divider>
            <Space wrap>{selected.unknown_dimensions.map((dimension) => <Tag key={dimension}>{dimension}</Tag>)}</Space>

            <Divider titlePlacement="start">下一步处理</Divider>
            <Space orientation="vertical" size={10} style={{ width: "100%" }}>
              {selected.recommendations.map((item) => (
                <Card key={item.key} size="small">
                  <Space align="start" style={{ width: "100%", justifyContent: "space-between" }}>
                    <div>
                      <Text strong>{item.label}</Text>
                      <Paragraph type="secondary" style={{ margin: "3px 0 0" }}>{item.reason}</Paragraph>
                    </div>
                    <Button aria-label={`${item.label}：${selected.plan_name}`} type={item.key === "ai_decision" ? "primary" : "default"} icon={<ArrowRightOutlined />} onClick={() => navigate(item.path)} />
                  </Space>
                </Card>
              ))}
            </Space>

            <Alert
              type="success"
              showIcon
              icon={<SafetyCertificateOutlined />}
              title="所有处理动作仍需人工确认"
              description="异常诊断不会自动启停计划、修改预算或调整出价；执行后请回到观察验证中心记录结果。"
              style={{ marginTop: 16 }}
            />
          </>
        ) : null}
      </Drawer>
    </div>
  );
}
