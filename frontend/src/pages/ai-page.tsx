import { ClearOutlined, RobotOutlined, SendOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Input, Select, Space, Tag, Typography, message } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { ChatMessage, ModelConfig } from "../types";

const { Text } = Typography;
const HISTORY_KEY = "tb-ai-history-v1";

const SUGGESTIONS = [
  "今天礼品单情况怎么样？",
  "总结一下我的店铺",
  "有哪些礼品单待发货？",
  "帮我写一条 618 大促的推广文案",
];

export function AiPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const raw = localStorage.getItem(HISTORY_KEY);
      return raw ? (JSON.parse(raw) as ChatMessage[]) : [];
    } catch {
      return [];
    }
  });
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [modelId, setModelId] = useState<number | undefined>();
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(messages.slice(-40)));
  }, [messages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    http
      .get<{ items: ModelConfig[] }>("/model-configs")
      .then(({ data }) => {
        setModels(data.items);
        const def = data.items.find((m) => m.is_default) ?? data.items[0];
        if (def) setModelId((prev) => prev ?? def.id);
      })
      .catch(() => {});
  }, []);

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (!content || loading) return;
    const next: ChatMessage[] = [...messages, { role: "user", content }];
    setMessages(next);
    setInput("");
    setLoading(true);
    try {
      const { data } = await http.post<{ reply: string }>("/ai/chat", {
        messages: next.slice(-10),
        model_id: modelId,
      }, { timeout: 120000 });
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
    } catch (error) {
      const msg = getApiErrorMessage(error);
      if (msg.includes("模型配置")) {
        message.warning("请先到「模型配置」页面填写 API Key，再回来提问");
        navigate("/model-configs");
      } else {
        message.error(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  const clear = () => {
    setMessages([]);
    localStorage.removeItem(HISTORY_KEY);
  };

  return (
    <div>
      <PageHeader
        icon={<RobotOutlined />}
        eyebrow="AI 运营助手"
        title="AI 助手"
        extra={
          <Space>
            {models.length > 0 && (
              <Select
                value={modelId}
                onChange={setModelId}
                style={{ minWidth: 170 }}
                placeholder="选择模型"
                options={models.map((m) => ({
                  value: m.id,
                  label: m.name + (m.is_default ? "（默认）" : ""),
                }))}
              />
            )}
            {messages.length > 0 && (
              <Button icon={<ClearOutlined />} onClick={clear}>
                清空对话
              </Button>
            )}
          </Space>
        }
      />

      <Card
        variant="borderless"
        style={{
          boxShadow: "var(--ops-shadow-sm)",
          height: "calc(100vh - 250px)",
          minHeight: 440,
          display: "flex",
          flexDirection: "column",
        }}
        styles={{ body: { display: "flex", flexDirection: "column", flex: 1, minHeight: 0 } }}
      >
        <div style={{ flex: 1, overflowY: "auto", padding: "4px 6px" }}>
          {messages.length === 0 ? (
            <Empty
              style={{ marginTop: 48 }}
              image={<RobotOutlined style={{ fontSize: 56, color: "var(--ops-primary, #ff5000)" }} />}
              description={
                <span>
                  <Text strong>我是你的 AI 运营助手</Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    可以问数据、写文案、给运营建议
                  </Text>
                </span>
              }
            >
              <Space wrap style={{ justifyContent: "center" }}>
                {SUGGESTIONS.map((s) => (
                  <Button key={s} size="small" onClick={() => send(s)}>
                    {s}
                  </Button>
                ))}
              </Space>
            </Empty>
          ) : (
            messages.map((m, index) => (
              <div
                key={index}
                style={{
                  display: "flex",
                  justifyContent: m.role === "user" ? "flex-end" : "flex-start",
                  marginBottom: 12,
                }}
              >
                <div
                  style={{
                    maxWidth: "78%",
                    padding: "10px 14px",
                    borderRadius: 12,
                    fontSize: 14,
                    lineHeight: "22px",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    background: m.role === "user" ? "#ff5000" : "#f5f5f5",
                    color: m.role === "user" ? "#fff" : "rgba(0,0,0,0.88)",
                    borderTopRightRadius: m.role === "user" ? 2 : 12,
                    borderTopLeftRadius: m.role === "assistant" ? 2 : 12,
                  }}
                >
                  {m.content}
                </div>
              </div>
            ))
          )}
          {loading && (
            <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 12 }}>
              <div
                style={{
                  padding: "10px 14px",
                  borderRadius: 12,
                  borderTopLeftRadius: 2,
                  background: "#f5f5f5",
                  color: "rgba(0,0,0,0.45)",
                  fontSize: 14,
                }}
              >
                AI 正在思考…
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div style={{ borderTop: "1px solid rgba(5,5,5,0.06)", paddingTop: 12, flexShrink: 0 }}>
          <Space.Compact style={{ width: "100%" }}>
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder='问问 AI：例如「有哪些礼品单待发货？」（Shift+回车换行）'
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              disabled={loading}
            />
            <Button type="primary" icon={<SendOutlined />} loading={loading} onClick={() => send()}>
              发送
            </Button>
          </Space.Compact>
          <Tag style={{ marginTop: 8 }} color="orange">
            小提示：右上角可随时切换本次对话的模型；默认模型在「模型配置」里设置
          </Tag>
        </div>
      </Card>
    </div>
  );
}
