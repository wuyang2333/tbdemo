import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, DatePicker, Empty, Row, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { ChangeBadge, LineChart, formatValue, fmtMoney, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsRangeCompare } from "../types";

const { Text } = Typography;
const { RangePicker } = DatePicker;

export function AnalyticsRangePage() {
  const [data, setData] = useState<AnalyticsRangeCompare | null>(null);
  const [range1, setRange1] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([dayjs().subtract(6, "day"), dayjs()]);
  const [range2, setRange2] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([dayjs().subtract(13, "day"), dayjs().subtract(7, "day")]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        start: range1[0].format("YYYY-MM-DD"),
        end: range1[1].format("YYYY-MM-DD"),
        start2: range2[0].format("YYYY-MM-DD"),
        end2: range2[1].format("YYYY-MM-DD"),
      });
      const { data: res } = await http.get<AnalyticsRangeCompare>(`/analytics/range?${params.toString()}`);
      setData(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [range1, range2]);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);

  const columns: TableColumnsType<AnalyticsRangeCompare["compare"][number]> = [
    { title: "指标", dataIndex: "name", width: 110 },
    { title: "区间一", dataIndex: "r1", align: "right", render: (v: number | null, row) => <span style={{ fontWeight: 700 }}>{formatValue(row.fmt, v)}</span> },
    { title: "区间二", dataIndex: "r2", align: "right", render: (v: number | null, row) => formatValue(row.fmt, v) },
    { title: "变化", dataIndex: "change_pct", align: "right", render: (v: number | null) => <ChangeBadge change={v} /> },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="区间对比"
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

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
        <Row gutter={[16, 16]} align="middle">
          <Col flex="auto">
            <Space wrap>
              <Text>区间一</Text>
              <RangePicker value={range1} onChange={(v) => v && setRange1(v as [dayjs.Dayjs, dayjs.Dayjs])} />
              <Text>区间二</Text>
              <RangePicker value={range2} onChange={(v) => v && setRange2(v as [dayjs.Dayjs, dayjs.Dayjs])} />
            </Space>
          </Col>
          <Col>
            <Button type="primary" onClick={load}>
              对比
            </Button>
          </Col>
        </Row>
      </Card>

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description="暂无数据" />
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={10}>
            <Card variant="borderless" title="区间对比" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <Space direction="vertical" size={4} style={{ marginBottom: 12 }}>
                <Tag color="blue">区间一：{data.range1.start} ~ {data.range1.end}</Tag>
                <Tag>区间二：{data.range2.start} ~ {data.range2.end}</Tag>
              </Space>
              <Table
                rowKey="key"
                size="small"
                columns={columns}
                dataSource={data.compare}
                pagination={false}
                scroll={{ x: 480 }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={14}>
            <Card variant="borderless" title="区间一 逐日销售额 / 订单" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
              <LineChart
                labels={data.series.map((p) => p.date)}
                series={[
                  { name: "销售额", color: "#ff5000", values: data.series.map((p) => p.sales), format: fmtMoney },
                  { name: "订单", color: "#1677ff", values: data.series.map((p) => p.orders) },
                ]}
              />
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}
