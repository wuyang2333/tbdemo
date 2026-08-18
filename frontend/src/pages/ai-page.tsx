import {
  CheckOutlined,
  ClearOutlined,
  CopyOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Card, Input, Modal, Select, Space, Tag, Typography, message } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../lib/api";
import { Markdown } from "../lib/markdown";
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

function bubbleStyle(role: "user" | "assistant") {
  if (role === "user") {
    return {
      maxWidth: "76%",
      padding: "11px 15px",
      borderRadius: "var(--ops-radius-lg)",
      borderTopRightRadius: 4,
      background: "var(--ops-accent)",
      color: "#fff",
      fontSize: 14,
      lineHeight: "22px",
      whiteSpace: "pre-wrap" as const,
      wordBreak: "break-word" as const,
    };
  }
  return {
    maxWidth: "82%",
    padding: "12px 56px 12px 16px",
    borderRadius: "var(--ops-radius-lg)",
    borderTopLeftRadius: 4,
    background: "var(--ops-card-bg-2)",
    border: "1px solid var(--ops-border)",
    color: "var(--ops-text)",
    fontSize: 14,
    lineHeight: "22px",
    wordBreak: "break-word" as const,
  };
}

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
  const [copyOpen, setCopyOpen] = useState(false);
  const [copyName, setCopyName] = useState("");
  const [loading, setLoading] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
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
      const { data } = await http.post<{ reply: string }>(
        "/ai/chat",
        { messages: next.slice(-10), model_id: modelId },
        { timeout: 120000 },
      );
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

  const copyMessage = async (content: string, index: number) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedIndex(index);
      message.success("已复制");
      setTimeout(() => setCopiedIndex(null), 1500);
    } catch {
      message.error("复制失败");
    }
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
                style={{ minWidth: 180 }}
                placeholder="选择模型"
                options={models.map((m) => ({
                  value: m.id,
                  label: m.name + (m.is_default ? "（默认）" : ""),
                }))}
              />
            )}
            <Button icon={<ClearOutlined />} onClick={() => setCopyOpen(true)}>
              文案生成
            </Button>
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
          height: "calc(100vh - 250px)",
          minHeight: 460,
          display: "flex",
          flexDirection: "column",
        }}
        styles={{ body: { display: "flex", flexDirection: "column", flex: 1, minHeight: 0, padding: 0 } }}
      >
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 22px" }}>
          {messages.length === 0 ? (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100%", padding: "24px 0" }}>
              <div
                style={{
                  width: 72,
                  height: 72,
                  borderRadius: "var(--ops-radius-lg)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 34,
                  color: "var(--ops-accent)",
                  background: "var(--ops-accent-soft)",
                  marginBottom: 18,
                }}
              >
                <RobotOutlined />
              </div>
              <Text strong style={{ fontSize: 20, letterSpacing: -0.01 }}>
                我是你的 AI 运营助手
              </Text>
              <Text type="secondary" style={{ marginTop: 6, fontSize: 14 }}>
                可以问数据、写文案、给运营建议
              </Text>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", maxWidth: 560, marginTop: 22 }}>
                {SUGGESTIONS.map((s) => (
                  <Button key={s} onClick={() => send(s)}>
                    {s}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, index) => {
              const isUser = m.role === "user";
              return (
                <div
                  key={index}
                  className="ops-fade-in"
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    justifyContent: isUser ? "flex-end" : "flex-start",
                    gap: 10,
                    marginBottom: 16,
                  }}
                >
                  {!isUser && (
                    <div
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: "var(--ops-radius)",
                        flexShrink: 0,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "var(--ops-accent)",
                        background: "var(--ops-accent-soft)",
                        fontSize: 17,
                      }}
                    >
                      <RobotOutlined />
                    </div>
                  )}
                  <div style={{ position: "relative", maxWidth: "82%" }}>
                    <div style={bubbleStyle(m.role)}>
                      {isUser ? m.content : <Markdown text={m.content} />}
                    </div>
                    {!isUser && (
                      <Button
                        type="text"
                        size="small"
                        icon={copiedIndex === index ? <CheckOutlined /> : <CopyOutlined />}
                        onClick={() => copyMessage(m.content, index)}
                        style={{ position: "absolute", right: 6, top: 6, opacity: 0.55 }}
                      >
                        {copiedIndex === index ? "已复制" : "复制"}
                      </Button>
                    )}
                  </div>
                  {isUser && (
                    <div
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: "50%",
                        flexShrink: 0,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        color: "#fff",
                        background: "var(--ops-accent)",
                        fontSize: 15,
                      }}
                    >
                      <UserOutlined />
                    </div>
                  )}
                </div>
              );
            })
          )}
          {loading && (
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 16 }}>
              <div
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "var(--ops-radius)",
                  flexShrink: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "var(--ops-accent)",
                  background: "var(--ops-accent-soft)",
                  fontSize: 17,
                }}
              >
                <RobotOutlined />
              </div>
              <div
                style={{
                  padding: "13px 16px",
                  borderRadius: "var(--ops-radius-lg)",
                  borderTopLeftRadius: 4,
                  background: "var(--ops-card-bg-2)",
                  border: "1px solid var(--ops-border)",
                }}
              >
                <span className="ops-typing">
                  <span className="ops-typing-dot" />
                  <span className="ops-typing-dot" />
                  <span className="ops-typing-dot" />
                </span>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div style={{ borderTop: "1px solid var(--ops-border)", padding: "14px 20px 16px", flexShrink: 0, background: "var(--ops-card-bg)" }}>
          <div
            style={{
              display: "flex",
              alignItems: "flex-end",
              gap: 10,
              border: "1px solid var(--ops-border)",
              borderRadius: "var(--ops-radius-lg)",
              padding: "10px 10px 10px 16px",
              background: "var(--ops-card-bg)",
              transition: "border-color 0.2s ease",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "var(--ops-accent)")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "var(--ops-border)")}
          >
            <Input.TextArea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder='问问 AI：例如「有哪些礼品单待发货？」（Shift+回车换行）'
              autoSize={{ minRows: 1, maxRows: 5 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              disabled={loading}
              style={{ flex: 1, border: "none", boxShadow: "none", background: "transparent", resize: "none", padding: 0, fontSize: 14 }}
            />
            <Button
              type="primary"
              shape="circle"
              icon={<SendOutlined />}
              loading={loading}
              disabled={!input.trim()}
              onClick={() => send()}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 10 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              AI 回复可能有误，重要经营决策请以生意参谋为准
            </Text>
            <Tag color="orange" style={{ marginRight: 0 }}>
              模型可在右上角随时切换
            </Tag>
          </div>
        </div>
      </Card>

      <Modal title="AI 文案生成" open={copyOpen} onCancel={() => setCopyOpen(false)} footer={null}>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Input
            placeholder="输入商品名 / 卖点，如：尹颜森林成人软毛牙刷 情侣款 家庭装"
            value={copyName}
            onChange={(e) => setCopyName(e.target.value)}
            onPressEnter={() => {
              if (copyName.trim()) {
                send(`请为商品「${copyName.trim()}」生成 5 个淘宝商品标题，每个 30 字以内，突出核心卖点，直接列出编号`);
                setCopyOpen(false);
              }
            }}
          />
          <Space>
            <Button
              type="primary"
              disabled={!copyName.trim()}
              onClick={() => {
                send(`请为商品「${copyName.trim()}」生成 5 个淘宝商品标题，每个 30 字以内，突出核心卖点，直接列出编号`);
                setCopyOpen(false);
              }}
            >
              生成标题
            </Button>
            <Button
              disabled={!copyName.trim()}
              onClick={() => {
                send(`请为商品「${copyName.trim()}」生成一段详情页卖点文案（约 200 字，分点，突出 3 个核心卖点和使用场景）`);
                setCopyOpen(false);
              }}
            >
              生成详情文案
            </Button>
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>生成结果会出现在对话中，可继续追问调整。</Text>
        </Space>
      </Modal>
    </div>
  );
}
