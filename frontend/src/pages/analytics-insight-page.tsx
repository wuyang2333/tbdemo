import { BarChartOutlined, BulbOutlined, CheckCircleOutlined, RobotOutlined, SendOutlined, WarningOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Input, Segmented, Space, Spin, Typography, message } from "antd";
import dayjs from "dayjs";
import { useRef, useState } from "react";

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
  reply: string;
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
  const [chat, setChat] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [genMode, setGenMode] = useState("14");
  const [genStoreId, setGenStoreId] = useState<number | undefined>(undefined);
  const cacheRef = useRef<Record<string, { result: InsightResult; chat: { role: "user" | "assistant"; content: string }[] }>>({});

  const cacheKey = (m: string, sid?: number) => `${m}|${sid ?? ""}`;

  const applyModeStore = (m: string, sid?: number) => {
    const key = cacheKey(m, sid);
    const cached = cacheRef.current[key];
    if (cached) {
      setResult(cached.result);
      setChat(cached.chat);
      setGenMode(m);
      setGenStoreId(sid);
    } else {
      setResult(null);
      setChat([]);
    }
  };

  const generate = async () => {
    setLoading(true);
    setResult(null);
    try {
      const params = new URLSearchParams({ mode });
      if (storeId) params.set("store_id", String(storeId));
      const { data } = await http.post<InsightResult>(`/analytics/insight?${params.toString()}`);
      setResult(data);
      setGenMode(mode);
      setGenStoreId(storeId);
      setChat([]);
      cacheRef.current[cacheKey(mode, storeId)] = { result: data, chat: [] };
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const sendChat = async () => {
    const q = chatInput.trim();
    if (!q || !result) return;
    const next = [...chat, { role: "user" as const, content: q }];
    setChat(next);
    setChatInput("");
    setChatLoading(true);
    try {
      const { data } = await http.post<{ reply: string }>("/analytics/insight/chat", {
        mode: genMode,
        store_id: genStoreId,
        messages: [{ role: "assistant", content: result.reply }, ...next],
      });
      const full = [...next, { role: "assistant" as const, content: data.reply }];
      setChat(full);
      const key = cacheKey(genMode, genStoreId);
      if (cacheRef.current[key]) cacheRef.current[key] = { ...cacheRef.current[key], chat: full };
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setChatLoading(false);
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
            <StoreScopeSelect
              value={storeId}
              onChange={(v) => {
                setStoreId(v);
                applyModeStore(mode, v);
              }}
            />
            <Segmented
              options={MODE_OPTIONS}
              value={mode}
              onChange={(v) => {
                const m = String(v);
                setMode(m);
                applyModeStore(m, storeId);
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

            <div style={{ marginTop: 20, paddingTop: 16, borderTop: "1px solid var(--ops-border)" }}>
              <div style={{ fontWeight: 600, marginBottom: 10, display: "flex", alignItems: "center", gap: 6 }}>
                <RobotOutlined style={{ color: "var(--ops-accent-light)" }} />
                追问 AI（可针对这份数据继续提问）
              </div>
              {chat.length > 0 && (
                <div style={{ display: "grid", gap: 8, marginBottom: 12, maxHeight: 320, overflowY: "auto" }}>
                  {chat.map((m, i) =>
                    m.role === "user" ? (
                      <div key={i} style={{ alignSelf: "flex-end", maxWidth: "80%", background: "var(--ops-accent-soft)", padding: "8px 12px", borderRadius: 10, fontSize: 13, whiteSpace: "pre-wrap" }}>
                        {m.content}
                      </div>
                    ) : (
                      <div key={i} style={{ alignSelf: "flex-start", maxWidth: "92%", background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", padding: "8px 12px", borderRadius: 10, fontSize: 13, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                        {m.content}
                      </div>
                    ),
                  )}
                </div>
              )}
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <Input.TextArea
                  rows={2}
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onPressEnter={(e) => {
                    if (!e.shiftKey) {
                      e.preventDefault();
                      sendChat();
                    }
                  }}
                  placeholder={"比如：为什么销售额降了？哪个商品该加推？推广 ROI 哪家店最高？"}
                  disabled={chatLoading}
                />
                <Button type="primary" icon={<SendOutlined />} loading={chatLoading} onClick={sendChat} style={{ flexShrink: 0 }}>
                  发送
                </Button>
              </div>
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
