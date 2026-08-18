import { ReadOutlined } from "@ant-design/icons";
import { Card, Col, Empty, Row, Spin, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";

import { PageHeader } from "../components/ui/page-header";
import http, { getApiErrorMessage } from "../lib/api";

const { Text, Paragraph } = Typography;

type GlossaryItem = {
  metric: string;
  source: string;
  granularity: string;
  table: string;
  refresh: string;
  note: string;
};

type GlossaryGroup = {
  group: string;
  items: GlossaryItem[];
};

export function AnalyticsGlossaryPage() {
  const [groups, setGroups] = useState<GlossaryGroup[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    http
      .get<{ groups: GlossaryGroup[] }>("/analytics/glossary")
      .then((res) => {
        if (alive) setGroups(res.data.groups);
      })
      .catch((error) => {
        if (alive) message.error(getApiErrorMessage(error));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div>
      <PageHeader icon={<ReadOutlined />} eyebrow="数据洞察" title="数据口径说明" />
      <Paragraph type="secondary" style={{ marginTop: 0 }}>
        统一说明每个指标的数据来源、时间口径、存储位置与刷新频率，方便核对数据是否对得上。
      </Paragraph>

      {loading ? (
        <div style={{ padding: 48, textAlign: "center" }}>
          <Spin />
        </div>
      ) : groups.length === 0 ? (
        <Empty description="暂无数据" />
      ) : (
        <Row gutter={[16, 16]}>
          {groups.map((g) => (
            <Col xs={24} lg={12} key={g.group}>
              <Card
                variant="borderless"
                title={g.group}
                style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", borderRadius: "var(--ops-radius-lg)" }}
              >
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {g.items.map((it, idx) => (
                    <div
                      key={idx}
                      style={{
                        border: "1px solid var(--ops-border, #e5e7eb)",
                        borderRadius: "var(--ops-radius)",
                        padding: "12px 14px",
                        background: "var(--ops-card-bg-2, #fafafa)",
                      }}
                    >
                      <Text strong style={{ fontSize: 14, display: "block", marginBottom: 6 }}>
                        {it.metric}
                      </Text>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px", fontSize: 13 }}>
                        <Text type="secondary">来源：{it.source}</Text>
                        <span>
                          <Tag color="blue">{it.granularity}</Tag>
                        </span>
                        <Text type="secondary">存储：{it.table}</Text>
                        <Text type="secondary">刷新：{it.refresh}</Text>
                      </div>
                      <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 6 }}>
                        {it.note}
                      </Text>
                    </div>
                  ))}
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  );
}
