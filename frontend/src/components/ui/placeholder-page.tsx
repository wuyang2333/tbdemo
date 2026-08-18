import { ApiOutlined, ToolOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Row, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { fetchModuleData } from "../../lib/api";
import { getModule } from "../../lib/modules";
import type { ModuleData } from "../../types";
import { PageHeader } from "./page-header";

const { Text, Title } = Typography;

export function PlaceholderPage({ moduleId }: { moduleId: string }) {
  const navigate = useNavigate();
  const module = getModule(moduleId);
  const [data, setData] = useState<ModuleData | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchModuleData(moduleId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch(() => {
        if (!cancelled) setData({ message: "后端未启动或接口尚未实现" });
      });
    return () => {
      cancelled = true;
    };
  }, [moduleId]);

  return (
    <div>
      <PageHeader
        icon={<ToolOutlined />}
        eyebrow={module?.description ?? "模块"}
        title={module?.name ?? moduleId}
        extra={
          <Tag color="orange" style={{ borderRadius: 999, marginInlineEnd: 0, paddingInline: 12 }}>
            功能开发中
          </Tag>
        }
      />

      <Card
        variant="borderless"
        styles={{ body: { padding: 0 } }}
        style={{ boxShadow: "var(--ops-shadow-sm)" }}
      >
        <div className="ops-empty">
          <span className="ops-empty-icon">
            <ToolOutlined />
          </span>
          <Title level={4} style={{ margin: "0 0 6px" }}>
            该模块正在建设中
          </Title>
          <Text type="secondary" style={{ maxWidth: 420, display: "block", lineHeight: "22px" }}>
            「{module?.name ?? moduleId}」的完整功能即将上线，你可以先体验总览、个人中心等已就绪模块。
          </Text>
          <Space size={12} style={{ marginTop: 24 }}>
            <Button type="primary" onClick={() => navigate("/dashboard")}>
              返回总览
            </Button>
            <Button onClick={() => navigate("/profile")}>前往个人中心</Button>
          </Space>
        </div>
      </Card>

      {data && (
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          <Col xs={24} md={12}>
            <Alert
              type="info"
              showIcon
              icon={<ApiOutlined />}
              title="接口链路"
              description={<Text code>GET /api/{moduleId}</Text>}
              style={{ borderRadius: "var(--ops-radius)" }}
            />
          </Col>
          <Col xs={24} md={12}>
            <Alert
              type="success"
              showIcon
              title="后端骨架已就绪"
              description={typeof data.message === "string" ? data.message : "占位接口返回正常"}
              style={{ borderRadius: "var(--ops-radius)" }}
            />
          </Col>
        </Row>
      )}
    </div>
  );
}
