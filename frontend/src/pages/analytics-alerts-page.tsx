import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { ChangeBadge, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsAlert } from "../types";

const { Text } = Typography;

export function AnalyticsAlertsPage() {
  const [alerts, setAlerts] = useState<AnalyticsAlert[]>([]);
  const [baselineDays, setBaselineDays] = useState(7);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: AnalyticsAlert[]; baseline_days: number }>("/analytics/alerts");
      setAlerts(data.items);
      setBaselineDays(data.baseline_days);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);

  const columns: TableColumnsType<AnalyticsAlert> = [
    { title: "日期", dataIndex: "date_label", width: 90 },
    { title: "店铺", dataIndex: "store_name", width: 160 },
    { title: "指标", dataIndex: "metric", width: 90 },
    { title: "波动", dataIndex: "change_pct", width: 100, align: "right", render: (v: number) => <ChangeBadge change={v} /> },
    {
      title: "等级",
      dataIndex: "level",
      width: 80,
      render: (level: AnalyticsAlert["level"]) =>
        level === "error" ? <Tag color="red">严重</Tag> : level === "warn" ? <Tag color="orange">提醒</Tag> : <Tag>信息</Tag>,
    },
    { title: "说明", dataIndex: "message" },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="异常提醒"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
          检测规则：按店铺对比每天指标与前 {baselineDays} 天均值——销售额下跌超 30%（严重）/上涨超 60%、订单或访客下跌超 30%、转化率下滑超 20% 时提醒。
        </Text>
        {loading && alerts.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : alerts.length === 0 ? (
          <Empty description="目前还没有波动提醒。需要至少积累 3 天数据，系统才会开始自动判断波动。" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />
        ) : (
          <Table<AnalyticsAlert>
            rowKey={(row) => `${row.date}_${row.store_id}_${row.metric}`}
            size="small"
            columns={columns}
            dataSource={alerts}
            pagination={{ pageSize: 10, showTotal: (c) => `共 ${c} 条` }}
            scroll={{ x: 760 }}
          />
        )}
      </Card>
    </div>
  );
}
