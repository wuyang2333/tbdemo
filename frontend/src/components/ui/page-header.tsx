import { Typography } from "antd";
import type { ReactNode } from "react";

const { Title, Text } = Typography;

export function PageHeader({
  icon,
  eyebrow,
  title,
  extra,
}: {
  icon: ReactNode;
  eyebrow: string;
  title: string;
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
      </div>
      {extra}
    </div>
  );
}
