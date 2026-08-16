import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Empty, Row, Space, Spin, Statistic, Table, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, StoreScopeSelect, daySwitch, fmtMoney, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsCustomers } from "../types";

const { Text } = Typography;

export function AnalyticsCustomersPage() {
  const [data, setData] = useState<AnalyticsCustomers | null>(null);
  const [days, setDays] = useState(14);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (d: number, sid?: number) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ days: String(d) });
      if (sid) params.set("store_id", String(sid));
      const { data: res } = await http.get<AnalyticsCustomers>(`/analytics/customers?${params.toString()}`);
      setData(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(days, storeId);
  }, [days, storeId, load]);

  const { syncing, syncAll } = useSyncStores(() => load(days, storeId));
  const items = data?.items ?? [];
  const labels = items.map((p) => p.date);

  const columns: TableColumnsType<AnalyticsCustomers["items"][number]> = [
    { title: "日期", dataIndex: "date", width: 70 },
    { title: "销售额", dataIndex: "sales", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "复购成交额", dataIndex: "repeat_sales", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "复购占比", dataIndex: "repeat_rate", align: "right", render: (v: number) => (v ? `${v.toFixed(1)}%` : "—") },
    { title: "新客占比", dataIndex: "new_rate", align: "right", render: (v: number) => (v ? `${v.toFixed(1)}%` : "—") },
    { title: "老客买家数", dataIndex: "old_buyer_cnt", align: "right", render: (v: number) => (v ? v : "—") },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="客群分析"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<ReloadOutlined />} onClick={() => load(days, storeId)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>统计范围</Text>
        {daySwitch(days, setDays)}
      </Space>

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description="暂无数据，先同步店铺数据（需包含新老客占比）" />
        </Card>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="销售额" value={data.summary.sales} precision={2} prefix="¥" /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="复购成交额" value={data.summary.repeat_sales} precision={2} prefix="¥" /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="复购占比" value={data.summary.repeat_rate} precision={1} suffix="%" valueStyle={{ color: "#1677ff" }} /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="新客占比" value={data.summary.new_rate} precision={1} suffix="%" /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="老客买家数" value={data.summary.old_buyer_cnt} /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="订单" value={data.summary.orders} /></Card></Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={14}>
              <Card variant="borderless" title="复购成交额 / 销售额" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
                <LineChart
                  labels={labels}
                  series={[
                    { name: "销售额", color: "#1677ff", values: items.map((p) => p.sales), format: fmtMoney },
                    { name: "复购成交额", color: "#ff5000", values: items.map((p) => p.repeat_sales), format: fmtMoney },
                  ]}
                />
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card variant="borderless" title="复购占比 / 新客占比（%）" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <LineChart
                  labels={labels}
                  series={[
                    { name: "复购占比", color: "#52c41a", values: items.map((p) => p.repeat_rate) },
                    { name: "新客占比", color: "#faad14", values: items.map((p) => p.new_rate) },
                  ]}
                  height={170}
                />
              </Card>
            </Col>
          </Row>

          <Card variant="borderless" title="每日明细" style={{ boxShadow: "var(--ops-shadow-sm)", marginTop: 16 }}>
            <Table rowKey="date" size="small" columns={columns} dataSource={items} pagination={{ pageSize: 10, showTotal: (c) => `共 ${c} 天` }} scroll={{ x: 620 }} />
          </Card>
        </>
      )}
    </div>
  );
}
