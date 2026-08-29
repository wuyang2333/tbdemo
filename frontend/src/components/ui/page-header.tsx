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
  stackActions = false,
}: {
  icon: ReactNode;
  eyebrow: string;
  title: string;
  description?: ReactNode;
  source?: string;
  updatedAt?: string | null;
  stale?: boolean;
  extra?: ReactNode;
  stackActions?: boolean;
}) {
  return (
    <div className={`ops-page-head${stackActions ? " ops-page-head--stacked" : ""}`}>
      <span className="ops-page-head__icon" aria-hidden="true">{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Text className="ops-page-head__eyebrow" type="secondary">
          {eyebrow}
        </Text>
        <Title className="ops-page-head__title" level={2}>
          {title}
        </Title>
        {(description || source || updatedAt) && (
          <Space className="ops-page-head__meta" size={8} wrap>
            {description ? <Text type="secondary" className="ops-page-head__description">{description}</Text> : null}
            {source ? <Tag variant="filled">来源：{source}</Tag> : null}
            {updatedAt ? <Tag color={stale ? "orange" : "green"}>{stale ? "数据可能过期" : "已更新"} · {updatedAt}</Tag> : null}
          </Space>
        )}
      </div>
      {extra ? <div className="ops-page-actions">{extra}</div> : null}
    </div>
  );
}
