import { BarChartOutlined, DownloadOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, DatePicker, Drawer, Empty, Row, Segmented, Space, Spin, Table, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { TOKEN_KEY, getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, MODE_OPTIONS, SceneTable, fmtMoney } from "../components/promotions/promotions-ui";
import type { PromoData } from "../types";
import { useStores } from "../lib/store";

const { Text } = Typography;

export function PromotionsDataPage() {
  const { currentStore } = useStores();
  const [data, setData] = useState<PromoData | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [mode, setMode] = useState("realtime");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [kwOpen, setKwOpen] = useState(false);
  const [kwLoading, setKwLoading] = useState(false);
  const [kwItems, setKwItems] = useState<{ word: string; promotion: string; spend: number; sales: number; roi: number; clicks: number; orders: number }[]>([]);
  const [range, setRange] = useState<[string, string] | null>(null);

  const load = useCallback(async (m: string, rg?: [string, string] | null) => {
    setLoading(true);
    try {
      const scope = currentStore ? `&store_id=${currentStore.id}` : "";
      let url = `/promotions/data?mode=${encodeURIComponent(m)}${scope}`;
      if (m === "range" && rg) {
        url = `/promotions/data?start=${rg[0]}&end=${rg[1]}${scope}`;
      }
      const { data: res } = await http.get<PromoData>(url);
      setData(res);
      setLastUpdated(dayjs().format("HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id]);

  useEffect(() => {
    load(mode, mode === "range" ? range : null);
  }, [mode, range, load]);
  useAutoRefresh(() => load(mode, mode === "range" ? range : null));

  const openKeywords = async () => {
    setKwOpen(true);
    setKwLoading(true);
    setKwItems([]);
    try {
      const scope = currentStore ? `&store_id=${currentStore.id}` : "";
      const { data } = await http.get<{ items: { word: string; promotion: string; spend: number; sales: number; roi: number; clicks: number; orders: number }[] }>(`/promotions/keywords?mode=${encodeURIComponent(mode)}${scope}`);
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
      const scope = currentStore ? `&store_id=${currentStore.id}` : "";
      const response = await fetch(`/api/promotions/export?mode=${encodeURIComponent(mode)}${scope}`, {
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
        `/promotions/sync?mode=${encodeURIComponent(mode)}${currentStore ? `&store_id=${currentStore.id}` : ""}`
      );
      showSyncFeedback("同步", [{ ok: res.ok, total: res.total, results: res.results }]);
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
        <Segmented
          options={MODE_OPTIONS}
          value={mode}
          onChange={(value) => {
            const v = String(value);
            setMode(v);
            if (v === "range" && !range) {
              setRange([dayjs().subtract(7, "day").format("YYYY-MM-DD"), dayjs().subtract(1, "day").format("YYYY-MM-DD")]);
            }
          }}
        />
        {mode === "range" && (
          <DatePicker.RangePicker
            value={range ? [dayjs(range[0]), dayjs(range[1])] : null}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                setRange([dates[0].format("YYYY-MM-DD"), dates[1].format("YYYY-MM-DD")]);
              }
            }}
          />
        )}
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
            {[
              { label: isRealtime ? "今日实时花费" : "区间花费", value: `¥${data.summary.spend.toLocaleString()}`, cmp: data.compare.spend, color: undefined },
              { label: isRealtime ? "今日实时成交" : "成交金额", value: `¥${data.summary.sales.toLocaleString()}`, cmp: data.compare.sales, color: undefined },
              { label: "推广 ROI", value: data.summary.roi.toFixed(2), cmp: null, color: data.summary.roi >= 2 ? "var(--ops-success)" : "var(--ops-warn)" },
              { label: "真实 ROI", value: data.summary.real_roi?.toFixed(2) ?? "—", cmp: null, color: (data.summary.real_roi ?? 0) >= 2 ? "var(--ops-success)" : "var(--ops-warn)" },
              { label: "广告占比", value: data.summary.ad_share != null ? `${data.summary.ad_share}%` : "—", cmp: null, color: undefined },
              { label: "获客成本", value: data.summary.cost_per_order != null ? `¥${data.summary.cost_per_order.toFixed(2)}` : "—", cmp: null, color: undefined },
              { label: "点击量", value: data.summary.clicks.toLocaleString(), cmp: null, color: undefined },
              { label: "点击率", value: `${data.summary.ctr}%`, cmp: null, color: undefined },
              { label: "成交订单", value: data.summary.orders.toLocaleString(), cmp: null, color: undefined },
            ].map((card) => (
              <Col xs={12} sm={8} key={card.label}>
                <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>{card.label}</Text>
                  <div style={{ fontSize: 20, fontWeight: 700, color: card.color }}>{card.value}</div>
                  {card.cmp !== null && card.cmp !== undefined && (
                    <Text style={{ fontSize: 12, color: (card.cmp ?? 0) >= 0 ? "var(--ops-up)" : "var(--ops-down)" }}>
                      {(card.cmp ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(card.cmp ?? 0)}% {isRealtime ? "较昨日同时段" : "较上周同期"}
                    </Text>
                  )}
                </Card>
              </Col>
            ))}
          </Row>

          {data.alerts.length > 0 && (
            <Card variant="borderless" style={{ marginBottom: 16, borderColor: "var(--ops-warn)" }} size="small">
              <Space direction="vertical" size={4}>
                {data.alerts.map((a, i) => (
                  <Text key={i} style={{ color: "var(--ops-warn)", fontSize: 13 }}>⚠ {a.message}</Text>
                ))}
              </Space>
            </Card>
          )}

          <Row gutter={[16, 16]}>
            <Col xs={24} lg={10}>
              <Card variant="borderless" title={`各推广场景 · ${isRealtime ? "今日实时" : periodTitle}`} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <div style={{ marginBottom: 14 }}>
                  {data.scenes.map((s) => (
                    <div key={s.scene} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                      <Text style={{ width: 66, fontSize: 12 }} ellipsis>{s.scene_name}</Text>
                      <div style={{ flex: 1, height: 16, background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius-xs)", position: "relative", overflow: "hidden" }}>
                        <div
                          style={{
                            width: `${Math.min((s.spend / Math.max(data.summary.spend, 1)) * 100, 100)}%`,
                            height: "100%",
                            background: s.roi >= 2 ? "var(--ops-success)" : "var(--ops-warn)",
                            borderRadius: "var(--ops-radius-xs)",
                          }}
                        />
                      </div>
                      <Text style={{ width: 104, fontSize: 12, textAlign: "right" }}>
                        ¥{s.spend.toLocaleString()} · ROI {s.roi}
                      </Text>
                    </div>
                  ))}
                </div>
                <SceneTable scenes={data.scenes} summary={data.summary} />
              </Card>
            </Col>
            <Col xs={24} lg={14}>
              <Card variant="borderless" title={isRealtime ? "今日分时：花费 / 成交金额" : "花费 / 成交金额 趋势"} style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
                <LineChart
                  labels={labels}
                  series={[
                    { name: "花费", color: "var(--ops-chart-accent)", values: trend.map((p) => p.spend), format: fmtMoney },
                    { name: "成交金额", color: "var(--ops-success)", values: trend.map((p) => p.sales), format: fmtMoney },
                  ]}
                />
              </Card>
              <Card variant="borderless" title={isRealtime ? "今日分时 ROI" : "ROI 趋势"} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <LineChart labels={labels} series={[{ name: "ROI", color: "var(--ops-accent)", values: trend.map((p) => p.roi) }]} height={160} />
              </Card>
              {isRealtime && (
                <Card variant="borderless" title="投放时段分析" style={{ boxShadow: "var(--ops-shadow-sm)", marginTop: 16 }}>
                  {(() => {
                    const hours = trend.filter((p) => p.spend > 0).map((p) => ({ label: p.label, roi: p.roi }));
                    const good = hours.filter((h) => h.roi >= 2).sort((a, b) => b.roi - a.roi).slice(0, 4);
                    const bad = hours.filter((h) => h.roi < 1).sort((a, b) => a.roi - b.roi).slice(0, 4);
                    return (
                      <Space direction="vertical" size={10}>
                        <div>
                          <Text strong style={{ color: "var(--ops-success)" }}>高效时段（ROI ≥ 2，建议加大投放）</Text>
                          <div style={{ marginTop: 6 }}>
                            {good.length ? good.map((h) => (<Tag color="green" key={h.label}>{h.label} · ROI {h.roi}</Tag>)) : <Text type="secondary">暂无</Text>}
                          </div>
                        </div>
                        <div>
                          <Text strong style={{ color: "var(--ops-danger)" }}>低效时段（ROI &lt; 1，建议减少）</Text>
                          <div style={{ marginTop: 6 }}>
                            {bad.length ? bad.map((h) => (<Tag color="red" key={h.label}>{h.label} · ROI {h.roi}</Tag>)) : <Text type="secondary">暂无</Text>}
                          </div>
                        </div>
                      </Space>
                    );
                  })()}
                </Card>
              )}
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
        destroyOnHidden
      >
        {kwLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin description="正在拉取关键词报表…" />
          </div>
        ) : kwItems.length === 0 ? (
          <Empty description="该范围暂无关键词数据（实时可能没有，试试昨天/近七天）" />
        ) : (
          <Table
            rowKey={(r, i) => `${r.word}-${i}`}
            size="small"
            dataSource={kwItems}
            pagination={{ defaultPageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (t) => `共 ${t} 个关键词` }}
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
                  <span style={{ color: v >= 2 ? "var(--ops-success)" : v >= 1 ? "var(--ops-warn)" : "var(--ops-danger)", fontWeight: 600 }}>
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
