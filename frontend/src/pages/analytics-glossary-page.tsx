import { Empty, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useEffect, useState } from "react";

import { DecisionBand, MetricRail, WorkspacePage } from "../components/ui/workspace-template";
import http, { getApiErrorMessage } from "../lib/api";

const { Text } = Typography;

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

  const items = groups.flatMap((group) => group.items.map((item) => ({ ...item, group: group.group })));
  const columns: TableColumnsType<GlossaryItem & { group: string }> = [
    { title: "指标", dataIndex: "metric", key: "metric", width: 180, fixed: "left", render: (value: string) => <Text strong>{value}</Text> },
    { title: "业务分组", dataIndex: "group", key: "group", width: 130, render: (value: string) => <Tag>{value}</Tag> },
    { title: "数据来源", dataIndex: "source", key: "source", width: 180 },
    { title: "时间粒度", dataIndex: "granularity", key: "granularity", width: 110, render: (value: string) => <Tag color="blue">{value}</Tag> },
    { title: "存储位置", dataIndex: "table", key: "table", width: 180, render: (value: string) => <Text code>{value}</Text> },
    { title: "刷新频率", dataIndex: "refresh", key: "refresh", width: 120 },
    { title: "口径说明", dataIndex: "note", key: "note", ellipsis: true },
  ];

  return (
    <WorkspacePage kind="analysis">
      <DecisionBand
        eyebrow="数据洞察 · 指标口径"
        title="先对齐指标定义，再判断经营变化"
        description="集中核对数据来源、时间粒度、存储位置与刷新频率，避免同名指标产生不同解释。"
        ariaLabel="数据指标口径说明"
      />

      <MetricRail
        columns={4}
        items={[
          { label: "业务分组", value: groups.length, hint: "按分析场景归类" },
          { label: "指标总数", value: items.length, hint: "当前已登记口径" },
          { label: "数据来源", value: new Set(items.map((item) => item.source)).size, hint: "去重后的来源数" },
          { label: "刷新策略", value: new Set(items.map((item) => item.refresh)).size, hint: "不同更新频率" },
        ]}
      />

      {loading ? (
        <div style={{ padding: 48, textAlign: "center" }}>
          <Spin />
        </div>
      ) : groups.length === 0 ? (
        <Empty description="暂无口径数据，请先检查数据源或稍后刷新" />
      ) : (
        <Table
          rowKey={(record) => `${record.group}-${record.metric}`}
          columns={columns}
          dataSource={items}
          pagination={false}
          size="small"
          scroll={{ x: 1050 }}
        />
      )}
    </WorkspacePage>
  );
}
