import { BarChartOutlined, FullscreenOutlined, HistoryOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Dropdown, Empty, Row, Space, Spin, Statistic, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { BucketCard, StoreBars, StoreScopeSelect, TrendChart, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsSummary } from "../types";

const { Text } = Typography;

export function AnalyticsOverviewPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<AnalyticsSummary>(`/analytics/summary?days=14${storeId ? `&store_id=${storeId}` : ""}`);
      setSummary(data);
      setLastUpdated(dayjs().format("HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    load();
  }, [load]);
  useAutoRefresh(load);

  const { syncing, syncAll } = useSyncStores(load);
  const [syncingHistory, setSyncingHistory] = useState(false);
  const syncHistory = async (days: number) => {
    setSyncingHistory(true);
    try {
      const { data } = await http.post<{ ok: number; total: number; days: number; results?: { store_name: string; ok: boolean; error?: string }[] }>(`/stores/sync-history?days=${days}`);
      showSyncFeedback(`历史数据补拉（近 ${data.days} 天）`, [{ ok: data.ok, total: data.total, results: data.results ?? [] }]);
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncingHistory(false);
    }
  };

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="总览"
        extra={
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<FullscreenOutlined />} onClick={() => navigate("/board")}>
              大屏模式
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Dropdown
              menu={{
                items: [
                  { key: "7", label: "近 7 天" },
                  { key: "14", label: "近 14 天" },
                  { key: "30", label: "近 30 天" },
                ],
                onClick: ({ key }) => syncHistory(Number(key)),
              }}
            >
              <Button icon={<HistoryOutlined />} loading={syncingHistory}>
                补历史数据
              </Button>
            </Dropdown>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      {summary?.last_sync && (
        <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
          最近同步：{dayjs(summary.last_sync).format("YYYY-MM-DD HH:mm:ss")} · 已配置 {summary.store_count} 家店铺
        </Text>
      )}

      {loading && !summary ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : summary ? (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日访客" value={summary.today.visitors} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日销售额" value={summary.today.sales} precision={2} prefix="¥" />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日订单" value={summary.today.orders} />
              </Card>
            </Col>
            <Col xs={12} sm={6}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="今日转化率" value={summary.today.conversion_rate} precision={2} suffix="%" styles={{ content: {  color: "#1677ff"  } }} />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} md={8}><BucketCard title="本周（近 7 天）" data={summary.week} /></Col>
            <Col xs={24} md={8}><BucketCard title="本月" data={summary.month} /></Col>
            <Col xs={24} md={8}><BucketCard title="累计" data={summary.total} /></Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={15}>
              <Card variant="borderless" title="销售额 / 订单数趋势" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Space style={{ marginBottom: 8 }}>
                  <Tag color="#0066cc">销售额</Tag>
                  <Tag color="#1677ff">订单数</Tag>
                </Space>
                <TrendChart trend={summary.trend} />
              </Card>
            </Col>
            <Col xs={24} lg={9}>
              <Card variant="borderless" title="按店铺汇总（累计）" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%" }}>
                <StoreBars items={summary.by_store} />
              </Card>
            </Col>
          </Row>
        </>
      ) : (
        <Card variant="borderless">
          <Empty description="还没有数据，点击右上角「同步店铺数据」抓取生意参谋数据" />
        </Card>
      )}
    </div>
  );
}
