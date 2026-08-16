import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Empty, Row, Space, Spin, Statistic, Table, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, StoreScopeSelect, daySwitch, fmtMoney, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsLinkage, AnalyticsLinkagePoint } from "../types";

const { Text } = Typography;

export function AnalyticsLinkagePage() {
  const [data, setData] = useState<AnalyticsLinkage | null>(null);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);

  const load = useCallback(async (d: number) => {
    setLoading(true);
    try {
      const { data: res } = await http.get<AnalyticsLinkage>(`/analytics/linkage?days=${d}${storeId ? `&store_id=${storeId}` : ""}`);
      setData(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    load(days);
  }, [days, load]);

  const { syncing, syncAll } = useSyncStores(() => load(days));
  const labels = data?.items.map((p) => p.label) ?? [];
  const items = data?.items ?? [];

  const columns: TableColumnsType<AnalyticsLinkagePoint> = [
    { title: "日期", dataIndex: "label", width: 70 },
    { title: "总销售额", dataIndex: "total_sales", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "推广花费", dataIndex: "promo_spend", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "推广成交", dataIndex: "promo_sales", align: "right", render: (v: number) => fmtMoney(v) },
    { title: "广告成交占比", dataIndex: "ad_share", align: "right", render: (v: number) => `${v.toFixed(1)}%` },
    { title: "推广 ROI", dataIndex: "promo_roi", align: "right", render: (v: number) => v.toFixed(2) },
    { title: "整体 ROI", dataIndex: "overall_roi", align: "right", render: (v: number) => v.toFixed(2) },
    { title: "自然销售额", dataIndex: "natural_sales", align: "right", render: (v: number) => fmtMoney(v) },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="联动分析"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<ReloadOutlined />} onClick={() => load(days)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步数据
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
          <Empty description="暂无数据，先同步店铺与推广数据" />
        </Card>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="总销售额" value={data.summary.total_sales} precision={2} prefix="¥" /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="推广花费" value={data.summary.promo_spend} precision={2} prefix="¥" /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="推广成交" value={data.summary.promo_sales} precision={2} prefix="¥" /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="广告成交占比" value={data.summary.ad_share} precision={1} suffix="%" /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="推广 ROI" value={data.summary.promo_roi} precision={2} valueStyle={{ color: "#1677ff" }} /></Card></Col>
            <Col xs={12} sm={4}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="整体 ROI" value={data.summary.overall_roi} precision={2} valueStyle={{ color: data.summary.overall_roi >= 2 ? "#52c41a" : "#ff4d4f" }} /></Card></Col>
          </Row>

          <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
            说明：总销售额来自生意参谋，推广数据来自万相台；广告成交占比 = 推广成交 / 总销售额。若某天总销售额缺失（如刚开始同步），占比会偏高属正常，数据积累几天后即准确。
          </Text>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={14}>
              <Card variant="borderless" title="总销售额 vs 推广成交" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
                <LineChart
                  labels={labels}
                  series={[
                    { name: "总销售额", color: "#1677ff", values: items.map((p) => p.total_sales), format: fmtMoney },
                    { name: "推广成交", color: "#ff5000", values: items.map((p) => p.promo_sales), format: fmtMoney },
                  ]}
                />
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card variant="borderless" title="广告成交占比（%）" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
                <LineChart labels={labels} series={[{ name: "广告占比", color: "#faad14", values: items.map((p) => p.ad_share) }]} height={170} />
              </Card>
              <Card variant="borderless" title="整体 ROI" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <LineChart labels={labels} series={[{ name: "整体 ROI", color: "#52c41a", values: items.map((p) => p.overall_roi) }]} height={150} />
              </Card>
            </Col>
          </Row>

          <Card variant="borderless" title="每日明细" style={{ boxShadow: "var(--ops-shadow-sm)", marginTop: 16 }}>
            <Table<AnalyticsLinkagePoint>
              rowKey="date"
              size="small"
              columns={columns}
              dataSource={items}
              pagination={{ pageSize: 10, showTotal: (c) => `共 ${c} 天` }}
              scroll={{ x: 800 }}
            />
          </Card>
        </>
      )}
    </div>
  );
}
