import { BarChartOutlined, DownloadOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Drawer, Empty, Row, Segmented, Space, Spin, Statistic, Table, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { TOKEN_KEY, getApiErrorMessage } from "../lib/api";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, MODE_OPTIONS, SceneTable, fmtMoney } from "../components/promotions/promotions-ui";
import type { PromoData } from "../types";

const { Text } = Typography;

export function PromotionsDataPage() {
  const [data, setData] = useState<PromoData | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [mode, setMode] = useState("realtime");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [kwOpen, setKwOpen] = useState(false);
  const [kwLoading, setKwLoading] = useState(false);
  const [kwItems, setKwItems] = useState<{ word: string; promotion: string; spend: number; sales: number; roi: number; clicks: number; orders: number }[]>([]);

  const load = useCallback(async (m: string) => {
    setLoading(true);
    try {
      const { data: res } = await http.get<PromoData>(`/promotions/data?mode=${encodeURIComponent(m)}`);
      setData(res);
      setLastUpdated(dayjs().format("HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(mode);
  }, [mode, load]);
  useAutoRefresh(() => load(mode));

  const openKeywords = async () => {
    setKwOpen(true);
    setKwLoading(true);
    setKwItems([]);
    try {
      const { data } = await http.get<{ items: { word: string; promotion: string; spend: number; sales: number; roi: number; clicks: number; orders: number }[] }>(`/promotions/keywords?mode=${encodeURIComponent(mode)}`);
      setKwItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setKwLoading(false);
    }
  };

  const exportData = async () => {
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch(`/api/promotions/export?mode=${encodeURIComponent(mode)}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error("导出失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `推广数据_${mode}_${dayjs().format("YYYYMMDD")}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      message.success("已导出 Excel");
    } catch {
      message.error("导出失败，请重试");
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const { data: res } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>(
        `/promotions/sync?mode=${encodeURIComponent(mode)}`
      );
      message.success(`同步完成：成功 ${res.ok} / 共 ${res.total} 家`);
      res.results.filter((r) => !r.ok).slice(0, 3).forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await load(mode);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const labels = (data?.trend ?? []).map((p) => p.label);
  const trend = data?.trend ?? [];
  const isRealtime = data?.mode === "realtime";
  const periodTitle = mode === "realtime" ? "今日实时" : mode === "yesterday" ? "昨天" : "近七天";

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="推广数据"
        extra={
          <Space>
            <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
            <Button icon={<DownloadOutlined />} onClick={exportData}>
              导出
            </Button>
            <Button onClick={openKeywords}>关键词报表</Button>
            <Button icon={<ReloadOutlined />} onClick={() => load(mode)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={sync}>
              同步{periodTitle}数据
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }} wrap>
        <Segmented options={MODE_OPTIONS} value={mode} onChange={(value) => setMode(String(value))} />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {data
            ? `${periodTitle} · 已绑定 ${data.bound_stores} 家店铺 · 最近同步 ${data.last_sync ? dayjs(data.last_sync).format("MM-DD HH:mm") : "—"}`
            : "先同步数据"}
        </Text>
      </Space>

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description={`暂无${periodTitle}数据，点「同步${periodTitle}数据」从万相台自动抓取`} />
        </Card>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title={isRealtime ? "今日实时花费" : "区间花费"} value={data.summary.spend} precision={2} prefix="¥" />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title={isRealtime ? "今日实时成交" : "成交金额"} value={data.summary.sales} precision={2} prefix="¥" />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="ROI" value={data.summary.roi} precision={2} valueStyle={{ color: "#1677ff" }} />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="点击量" value={data.summary.clicks} />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="点击率" value={data.summary.ctr} precision={2} suffix="%" />
              </Card>
            </Col>
            <Col xs={12} sm={4}>
              <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Statistic title="成交订单" value={data.summary.orders} />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={10}>
              <Card variant="borderless" title={`各推广场景 · ${isRealtime ? "今日实时" : periodTitle}`} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <SceneTable scenes={data.scenes} summary={data.summary} />
              </Card>
            </Col>
            <Col xs={24} lg={14}>
              <Card variant="borderless" title={isRealtime ? "今日分时：花费 / 成交金额" : "花费 / 成交金额 趋势"} style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
                <LineChart
                  labels={labels}
                  series={[
                    { name: "花费", color: "#ff5000", values: trend.map((p) => p.spend), format: fmtMoney },
                    { name: "成交金额", color: "#52c41a", values: trend.map((p) => p.sales), format: fmtMoney },
                  ]}
                />
              </Card>
              <Card variant="borderless" title={isRealtime ? "今日分时 ROI" : "ROI 趋势"} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <LineChart labels={labels} series={[{ name: "ROI", color: "#1677ff", values: trend.map((p) => p.roi) }]} height={160} />
              </Card>
              {isRealtime && (
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 12 }}>
                  实时数据按小时更新（00:00 起到当前小时），覆盖货品全站 / 关键词 / 人群各场景。
                </Text>
              )}
            </Col>
          </Row>
        </>
      )}
      <Drawer
        title="关键词报表"
        width={640}
        open={kwOpen}
        onClose={() => setKwOpen(false)}
        destroyOnClose
      >
        {kwLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin tip="正在拉取关键词报表…" />
          </div>
        ) : kwItems.length === 0 ? (
          <Empty description="该范围暂无关键词数据（实时可能没有，试试昨天/近七天）" />
        ) : (
          <Table
            rowKey={(r, i) => `${r.word}-${i}`}
            size="small"
            dataSource={kwItems}
            pagination={{ pageSize: 20, showTotal: (t) => `共 ${t} 个关键词` }}
            columns={[
              { title: "关键词", dataIndex: "word", width: 180, ellipsis: true },
              { title: "计划/商品", dataIndex: "promotion", width: 220, ellipsis: true },
              { title: "花费", dataIndex: "spend", align: "right", width: 90, render: (v: number) => fmtMoney(v) },
              { title: "成交", dataIndex: "sales", align: "right", width: 90, render: (v: number) => fmtMoney(v) },
              {
                title: "ROI",
                dataIndex: "roi",
                align: "right",
                width: 70,
                render: (v: number) => (
                  <span style={{ color: v >= 2 ? "#52c41a" : v >= 1 ? "#fa8c16" : "#ff4d4f", fontWeight: 600 }}>
                    {v.toFixed(2)}
                  </span>
                ),
              },
              { title: "点击", dataIndex: "clicks", align: "right", width: 70 },
              { title: "订单", dataIndex: "orders", align: "right", width: 70 },
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
