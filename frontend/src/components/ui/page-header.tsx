import { Space, Tag, Typography } from "antd";
import type { ReactNode } from "react";

const { Title, Text } = Typography;

export function PageHeader({
  icon,
  eyebrow,
  title,
  description,
  source,
  updatedAt,
  stale = false,
  extra,
}: {
  icon: ReactNode;
  eyebrow: string;
  title: string;
  description?: ReactNode;
  source?: string;
  updatedAt?: string | null;
  stale?: boolean;
  extra?: ReactNode;
}) {
  return (
    <div className="ops-page-head">
      <span className="ops-module-icon">{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Text
          type="secondary"
          style={{
            fontSize: 12,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            display: "block",
          }}
        >
          {eyebrow}
        </Text>
        <Title level={3} style={{ margin: "2px 0 0" }}>
          {title}
        </Title>
        {(description || source || updatedAt) && (
          <Space size={8} wrap style={{ marginTop: 5 }}>
            {description ? <Text type="secondary">{description}</Text> : null}
            {source ? <Tag bordered={false}>来源：{source}</Tag> : null}
            {updatedAt ? <Tag color={stale ? "orange" : "green"}>{stale ? "数据可能过期" : "已更新"} · {updatedAt}</Tag> : null}
          </Space>
        )}
      </div>
      {extra ? <div className="ops-page-actions">{extra}</div> : null}
    </div>
  );
}
