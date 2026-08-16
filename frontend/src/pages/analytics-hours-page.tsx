import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, DatePicker, Empty, Row, Space, Spin, Statistic, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, fmtInt, fmtMoney } from "../components/analytics/analytics-ui";
import type { AnalyticsHours } from "../types";

const { Text } = Typography;

export function AnalyticsHoursPage() {
  const [data, setData] = useState<AnalyticsHours | null>(null);
  const [date, setDate] = useState(dayjs());
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async (d: string, sid?: number) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ date: d });
      if (sid) params.set("store_id", String(sid));
      const { data: res } = await http.get<AnalyticsHours>(`/analytics/hours?${params.toString()}`);
      setData(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(date.format("YYYY-MM-DD"), storeId);
  }, [date, storeId, load]);

  const syncHourly = async () => {
    setSyncing(true);
    try {
      const { data: res } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/stores/sync-hourly");
      message.success(`分时同步完成：成功 ${res.ok} / 共 ${res.total} 家`);
      res.results.filter((r) => !r.ok).slice(0, 3).forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await load(date.format("YYYY-MM-DD"), storeId);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const items = data?.items ?? [];
  const maxVisitors = Math.max(1, ...items.map((p) => p.visitors));
  const maxSales = Math.max(1, ...items.map((p) => p.sales));

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="时段分析"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<ReloadOutlined />} onClick={() => load(date.format("YYYY-MM-DD"), storeId)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncHourly}>
              同步分时数据
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }} wrap>
        <Text type="secondary" style={{ fontSize: 12 }}>日期</Text>
        <DatePicker value={date} onChange={(v) => v && setDate(v)} allowClear={false} />
        {data?.peak_hour && (
          <Tag color="orange">销售高峰：{data.peak_hour}（{fmtMoney(data.peak_sales)}）</Tag>
        )}
      </Space>

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description="暂无分时数据，点「同步分时数据」从生意参谋抓取" />
        </Card>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="访客" value={data.summary.visitors} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="浏览量" value={data.summary.pv} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="销售额" value={data.summary.sales} precision={2} prefix="¥" /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="订单" value={data.summary.orders} /></Card></Col>
          </Row>

          <Card variant="borderless" title="24 小时访客 / 销售额分布" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 190 }}>
              {items.map((p) => (
                <div key={p.hour} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }} title={`${p.hour} 访客 ${p.visitors} / 销售 ${fmtMoney(p.sales)}`}>
                  <div style={{ width: "100%", flex: 1, display: "flex", alignItems: "flex-end", gap: 2 }}>
                    <div style={{ width: "45%", height: `${(p.visitors / maxVisitors) * 100}%`, background: "var(--ops-accent)", borderRadius: "3px 3px 0 0", minHeight: p.visitors ? 2 : 0 }} />
                    <div style={{ width: "45%", height: `${(p.sales / maxSales) * 100}%`, background: "#52c41a", borderRadius: "3px 3px 0 0", minHeight: p.sales ? 2 : 0 }} />
                  </div>
                  <div style={{ fontSize: 9, color: "rgba(128,128,128,0.8)", whiteSpace: "nowrap" }}>{p.hour.slice(0, 2)}时</div>
                </div>
              ))}
            </div>
            <Space style={{ marginTop: 8 }}>
              <Tag color="var(--ops-accent)">访客</Tag>
              <Tag color="#52c41a">销售额</Tag>
            </Space>
          </Card>

          <Card variant="borderless" title="分时明细" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: 8 }}>
              {items.map((p) => (
                <div key={p.hour} style={{ border: "1px solid var(--ops-border)", borderRadius: 8, padding: "8px 10px" }}>
                  <Text strong style={{ fontSize: 13 }}>{p.hour}</Text>
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    访客 {fmtInt(p.visitors)}<br />
                    销售 {fmtMoney(p.sales)}<br />
                    订单 {p.orders} · 转化 {p.conversion_rate.toFixed(2)}%
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
