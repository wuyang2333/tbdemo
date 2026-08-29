import { BulbOutlined, CheckCircleOutlined, RobotOutlined, SendOutlined, WarningOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Input, Segmented, Space, Spin, Typography, message } from "antd";
import dayjs from "dayjs";
import { useRef, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { StoreScopeSelect } from "../components/analytics/analytics-ui";
import { DecisionBand, MetricRail, WorkspacePage, WorkspaceToolbar } from "../components/ui/workspace-template";

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
  conversion: string[];
  promo: string[];
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
  if (change == null) return <span style={{ color: "var(--ops-text-3)", fontSize: 12 }}>—</span>;
  const up = change >= 0;
  const color = up ? "var(--ops-up)" : "var(--ops-down)";
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
        borderRadius: "var(--ops-radius)",
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
      const { data } = await http.post<InsightResult>(`/analytics/insight?${params.toString()}`, undefined, { timeout: 120000 });
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
      }, { timeout: 120000 });
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
    <WorkspacePage kind="analysis">
      <DecisionBand
        eyebrow="数据洞察 · AI 解读"
        title={result?.sections.overall || "先生成经营结论，再围绕证据继续追问"}
        description={result ? `解读范围：${result.range} · 生成于 ${dayjs().format("MM-DD HH:mm:ss")}` : "AI 会综合销售、推广、商品与时段数据，输出亮点、风险和建议。"}
        action={
          <Button className="ops-insight-generate" type="primary" icon={<RobotOutlined />} loading={loading} onClick={generate}>
            生成 AI 解读
          </Button>
        }
        ariaLabel="AI 数据解读结论"
      />

      <WorkspaceToolbar>
        <Space className="ops-insight-controls" wrap>
            <StoreScopeSelect
              value={storeId}
              onChange={(v) => {
                setStoreId(v);
                applyModeStore(mode, v);
              }}
            />
            <Segmented
              className="ops-insight-range"
              options={MODE_OPTIONS}
              value={mode}
              onChange={(v) => {
                const m = String(v);
                setMode(m);
                applyModeStore(m, storeId);
              }}
            />
        </Space>
        <Text type="secondary" style={{ fontSize: 12 }}>数据基于生意参谋与万相台同步结果</Text>
      </WorkspaceToolbar>

      <Card variant="borderless">
        {loading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="AI 正在分析数据…" />
          </div>
        ) : result ? (
          <div>
            <MetricRail
              columns={result.metrics.length <= 4 ? 4 : 6}
              items={result.metrics.map((m) => ({
                key: m.label,
                label: m.label,
                value: m.value,
                hint: <ChangeBadge change={m.change} unit={m.unit} />,
              }))}
            />

            <div style={{ display: "grid", gap: 10 }}>
              <InsightSection icon={<CheckCircleOutlined />} color="green" title="亮点" items={result.sections.highlights} />
              <InsightSection icon={<RobotOutlined />} color="orange" title="推广表现" items={result.sections.promo} />
              <InsightSection icon={<WarningOutlined />} color="red" title="风险" items={result.sections.risks} />
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
                      <div key={i} style={{ alignSelf: "flex-end", maxWidth: "80%", background: "var(--ops-accent-soft)", padding: "8px 12px", borderRadius: "var(--ops-radius)", fontSize: 13, whiteSpace: "pre-wrap" }}>
                        {m.content}
                      </div>
                    ) : (
                      <div key={i} style={{ alignSelf: "flex-start", maxWidth: "92%", background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", padding: "8px 12px", borderRadius: "var(--ops-radius)", fontSize: 13, lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                        {m.content}
                      </div>
                    ),
                  )}
                </div>
              )}
              <div className="ops-insight-chat-composer" style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
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
                <Button className="ops-insight-send" type="primary" icon={<SendOutlined />} loading={chatLoading} onClick={sendChat} style={{ flexShrink: 0 }}>
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
    </WorkspacePage>
  );
}
