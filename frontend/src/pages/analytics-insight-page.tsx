import { BarChartOutlined, RobotOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Space, Spin, Typography, message } from "antd";
import { useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";

const { Text } = Typography;

export function AnalyticsInsightPage() {
  const [reply, setReply] = useState("");
  const [loading, setLoading] = useState(false);

  const generate = async () => {
    setLoading(true);
    setReply("");
    try {
      const { data } = await http.post<{ reply: string }>("/analytics/insight");
      setReply(data.reply);
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
          <Space>
            <Button type="primary" icon={<RobotOutlined />} loading={loading} onClick={generate}>
              生成 AI 解读
            </Button>
          </Space>
        }
      />

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
          基于近 14 天销售与推广数据，由 AI 自动生成经营解读与建议（需先在「模型配置」里配置好模型）。
        </Text>
        {loading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin />
          </div>
        ) : reply ? (
          <Text style={{ fontSize: 14, whiteSpace: "pre-wrap", lineHeight: 1.9 }}>{reply}</Text>
        ) : (
          <Empty description="点「生成 AI 解读」查看分析" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />
        )}
      </Card>
    </div>
  );
}
