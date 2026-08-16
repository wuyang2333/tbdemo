import { BarChartOutlined, BulbOutlined, CheckCircleOutlined, RobotOutlined, WarningOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Segmented, Space, Spin, Typography, message } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect } from "../components/analytics/analytics-ui";

const { Text } = Typography;

const MODE_OPTIONS = [
  { label: "实时", value: "realtime" },
  { label: "昨天", value: "yesterday" },
  { label: "近7天", value: "7" },
  { label: "近14天", value: "14" },
  { label: "近30天", value: "30" },
];

interface InsightSections {
  overall: string;
  highlights: string[];
  risks: string[];
  suggestions: string[];
}
interface InsightMetric {
  label: string;
  value: string;
  change: number | null;
  unit: "%" | "pp" | "val";
}
interface InsightResult {
  sections: InsightSections;
  metrics: InsightMetric[];
  range: string;
  date: string;
}

function ChangeBadge({ change, unit }: { change: number | null; unit: string }) {
  if (change == null) return <span style={{ color: "rgba(128,128,128,0.55)", fontSize: 12 }}>—</span>;
  const up = change >= 0;
  const color = up ? "#ff4d4f" : "#52c41a";
  const suffix = unit === "%" ? "%" : unit === "pp" ? "pp" : "";
  return (
    <span style={{ color, fontSize: 12, fontWeight: 600 }}>
      {up ? "+" : "-"}
      {Math.abs(change).toFixed(unit === "val" ? 2 : 1)}
      {suffix}
    </span>
  );
}

function InsightSection({
  icon,
  color,
  title,
  items,
}: {
  icon: React.ReactNode;
  color: string;
  title: string;
  items: string[];
}) {
  if (!items || items.length === 0) return null;
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        padding: "10px 14px",
        borderRadius: 10,
        background: "var(--ops-card-bg-2)",
        border: "1px solid var(--ops-border)",
      }}
    >
      <span style={{ color, fontSize: 16, marginTop: 2, flexShrink: 0 }}>{icon}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>{title}</div>
        {items.map((it, idx) => (
          <div key={idx} style={{ fontSize: 13, lineHeight: 1.9, color: "var(--ops-text-secondary)" }}>
            {it}
          </div>
        ))}
      </div>
    </div>
  );
}

export function AnalyticsInsightPage() {
  const [mode, setMode] = useState("14");
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [result, setResult] = useState<InsightResult | null>(null);
  const [loading, setLoading] = useState(false);

  const generate = async () => {
    setLoading(true);
    setResult(null);
    try {
      const params = new URLSearchParams({ mode });
      if (storeId) params.set("store_id", String(storeId));
      const { data } = await http.post<InsightResult>(`/analytics/insight?${params.toString()}`);
      setResult(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="AI 解读"
        extra={
          <Space wrap>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Segmented
              options={MODE_OPTIONS}
              value={mode}
              onChange={(v) => {
                setResult(null);
                setMode(String(v));
              }}
            />
            <Button type="primary" icon={<RobotOutlined />} loading={loading} onClick={generate}>
              生成 AI 解读
            </Button>
          </Space>
        }
      />

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        {loading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin tip="AI 正在分析数据…" />
          </div>
        ) : result ? (
          <div>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
              解读范围：{result.range} · 生成于 {dayjs().format("MM-DD HH:mm:ss")} · 数据基于生意参谋与万相台同步结果
            </Text>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginBottom: 16 }}>
              {result.metrics.map((m) => (
                <div
                  key={m.label}
                  style={{
                    flex: "1 1 150px",
                    minWidth: 140,
                    padding: "10px 14px",
                    borderRadius: 10,
                    background: "var(--ops-card-bg-2)",
                    border: "1px solid var(--ops-border)",
                  }}
                >
                  <div style={{ fontSize: 12, color: "var(--ops-text-secondary)", marginBottom: 2 }}>{m.label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{m.value}</div>
                  <ChangeBadge change={m.change} unit={m.unit} />
                </div>
              ))}
            </div>

            {result.sections.overall && (
              <div
                style={{
                  padding: "12px 16px",
                  borderRadius: 10,
                  background: "var(--ops-accent-soft)",
                  borderLeft: "3px solid var(--ops-accent)",
                  marginBottom: 12,
                }}
              >
                <Text style={{ fontSize: 14, lineHeight: 1.9 }}>{result.sections.overall}</Text>
              </div>
            )}

            <div style={{ display: "grid", gap: 10 }}>
              <InsightSection icon={<CheckCircleOutlined />} color="#52c41a" title="亮点" items={result.sections.highlights} />
              <InsightSection icon={<WarningOutlined />} color="#ff4d4f" title="风险" items={result.sections.risks} />
              <InsightSection icon={<BulbOutlined />} color="var(--ops-accent-light)" title="建议" items={result.sections.suggestions} />
            </div>
          </div>
        ) : (
          <Empty
            description="选择范围后点「生成 AI 解读」，AI 会结合销售、推广、商品与时段数据给出结构化经营解读"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            style={{ padding: 40 }}
          />
        )}
      </Card>
    </div>
  );
}
