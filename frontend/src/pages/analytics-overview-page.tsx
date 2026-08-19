import { BarChartOutlined, FullscreenOutlined, FundOutlined, HistoryOutlined, MoneyCollectOutlined, ReloadOutlined, RiseOutlined, SearchOutlined, ShoppingOutlined, SyncOutlined, TeamOutlined, WarningOutlined } from "@ant-design/icons";
import { Button, Card, Col, Dropdown, Empty, Row, Space, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useAutoRefresh } from "../lib/use-auto-refresh";
import { PageHeader } from "../components/ui/page-header";
import { LoadingBlock } from "../components/ui/page-state";
import { StoreScopeSelect, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsSummary } from "../types";

const { Text } = Typography;

type TodayCompare = { sales: number | null; orders: number | null; visitors: number | null; conversion: number | null };
type TodayOverview = {
  kpi: { sales: number; orders: number; visitors: number; conversion_rate: number; avg_order_value: number; buyers: number; compare: TodayCompare };
  promo: { spend: number; sales: number; roi: number; real_roi: number | null; yesterday_real_roi: number | null; compare: { spend: number | null; sales: number | null }; scenes: { scene: string; scene_name: string; spend: number; sales: number; roi: number }[] };
  funnel: { visitors: number; collect: number; add_cart: number; buyers: number; collect_rate: number; cart_rate: number; pay_rate: number };
  flow: { search_uv: number; search_share: number | null; other_share: number | null; has_data: boolean; data_date: string | null; sources: { source: string; uv: number; rank: number }[] };
  refund: { amount: number; pay_amt: number; rate: number; ord_rate: number; cycle: number | null; yest_amount: number; yest_rate: number; data_date: string | null; updated_at: string };
  movers: { risers: { item_id: string; item_title: string; sales: number; cycle: number }[]; fallers: { item_id: string; item_title: string; sales: number; cycle: number }[] };
};

export function AnalyticsOverviewPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [today, setToday] = useState<TodayOverview | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const scope = storeId ? `&store_id=${storeId}` : "";
      const [s, t] = await Promise.all([
        http.get<AnalyticsSummary>(`/analytics/summary?days=14${scope}`),
        http.get<TodayOverview>(`/analytics/summary/today?${scope}`),
      ]);
      setSummary(s.data);
      setToday(t.data);
      setLastUpdated(dayjs().format("HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setSummary(null);
      setToday(null);
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
        title="今日总览"
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
        <LoadingBlock />
      ) : summary ? (
        <>
          {today ? (
            <>
              <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                {[
                  { label: "今日销售额", value: `¥${today.kpi.sales.toLocaleString()}`, cmp: today.kpi.compare.sales, cmpText: "较昨日同时段", color: "var(--ops-accent)", icon: <BarChartOutlined /> },
                  { label: "今日买家数", value: (today.kpi.buyers ?? today.funnel.buyers).toLocaleString(), cmp: null, cmpText: "支付买家数（实时）", color: "var(--ops-success)", icon: <ShoppingOutlined /> },
                  { label: "今日访客", value: today.kpi.visitors.toLocaleString(), cmp: today.kpi.compare.visitors, cmpText: "较昨日同时段", color: "var(--ops-cat-2)", icon: <TeamOutlined /> },
                  { label: "今日转化率", value: `${today.kpi.conversion_rate}%`, cmp: null, cmpText: `客单价 ¥${today.kpi.avg_order_value}`, color: "var(--ops-warn)", icon: <RiseOutlined /> },
                  { label: "今日真实ROI", value: today.promo.real_roi != null ? today.promo.real_roi.toFixed(2) : "—", cmp: null, cmpText: today.promo.yesterday_real_roi != null ? `昨日同时段 ${today.promo.yesterday_real_roi.toFixed(2)}` : "昨日无推广数据", color: "var(--ops-success)", icon: <FundOutlined /> },
                  { label: "今日退款", value: `¥${today.refund.amount.toLocaleString()}`, cmp: today.refund.cycle, cmpText: `较昨日同时段 · 退款率 ${today.refund.rate}%`, color: "var(--ops-danger)", icon: <WarningOutlined /> },
                  { label: "今日净支付金额", value: `¥${(today.kpi.sales - today.refund.amount).toLocaleString()}`, cmp: null, cmpText: `总成交 ¥${today.kpi.sales.toLocaleString()} − 退款 ¥${today.refund.amount.toLocaleString()}`, color: "var(--ops-cat-4)", icon: <MoneyCollectOutlined /> },
                  { label: "今日客单价", value: `¥${today.kpi.avg_order_value.toLocaleString()}`, cmp: null, cmpText: "销售额 ÷ 买家数", color: "var(--ops-accent)", icon: <MoneyCollectOutlined /> },
                ].map((card) => (
                  <Col xs={12} sm={6} key={card.label}>
                    <Card
                      variant="borderless"
                      style={{
                        boxShadow: "var(--ops-shadow-sm)",
                        borderRadius: "var(--ops-radius-lg)",
                        borderLeft: `3px solid ${card.color}`,
                        background: "var(--ops-card-bg)",
                      }}
                    >
                      <Space size={6} style={{ color: card.color }}>
                        {card.icon}
                        <Text type="secondary" style={{ fontSize: 12 }}>{card.label}</Text>
                      </Space>
                      <div style={{ fontSize: 26, fontWeight: 700, marginTop: 4, letterSpacing: -0.5 }}>{card.value}</div>
                      {card.cmp !== null && card.cmp !== undefined ? (
                        <Tag style={{ marginTop: 6, fontSize: 12 }} color={(card.cmp ?? 0) >= 0 ? "red" : "green"}>
                          {(card.cmp ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(card.cmp ?? 0)}% · {card.cmpText}
                        </Tag>
                      ) : (
                        <Text type="secondary" style={{ fontSize: 12, marginTop: 6, display: "block" }}>{card.cmpText}</Text>
                      )}
                    </Card>
                  </Col>
                ))}
              </Row>

              <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                <Col xs={24} lg={12}>
                  <Card variant="borderless" title="今日推广" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", borderRadius: "var(--ops-radius-lg)" }}>
                    <Row gutter={[12, 12]}>
                      <Col span={8}>
                        <div style={{ background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius)", padding: "10px 12px" }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>花费</Text>
                          <div style={{ fontSize: 20, fontWeight: 700 }}>¥{today.promo.spend.toLocaleString()}</div>
                        </div>
                      </Col>
                      <Col span={8}>
                        <div style={{ background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius)", padding: "10px 12px" }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>成交</Text>
                          <div style={{ fontSize: 20, fontWeight: 700 }}>¥{today.promo.sales.toLocaleString()}</div>
                        </div>
                      </Col>
                      <Col span={8}>
                        <div style={{ background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius)", padding: "10px 12px" }}>
                          <Text type="secondary" style={{ fontSize: 12 }}>ROI</Text>
                          <div style={{ fontSize: 20, fontWeight: 700, color: today.promo.roi >= 2 ? "var(--ops-success)" : "var(--ops-warn)" }}>{today.promo.roi}</div>
                        </div>
                      </Col>
                    </Row>
                    <div style={{ marginTop: 12 }}>
                      <Tag color={(today.promo.compare.spend ?? 0) >= 0 ? "red" : "green"}>
                        花费 {(today.promo.compare.spend ?? 0) >= 0 ? "▲" : "▼"}{Math.abs(today.promo.compare.spend ?? 0)}% 较昨日同时段
                      </Tag>
                      <Tag color={(today.promo.compare.sales ?? 0) >= 0 ? "red" : "green"}>
                        成交 {(today.promo.compare.sales ?? 0) >= 0 ? "▲" : "▼"}{Math.abs(today.promo.compare.sales ?? 0)}% 较昨日同时段
                      </Tag>
                    </div>
                    {today.promo.scenes.length > 0 && (
                      <Space size={4} wrap style={{ marginTop: 12 }}>
                        {today.promo.scenes.map((s) => (
                          <Tag key={s.scene} color={s.roi >= 2 ? "green" : "orange"} style={{ borderRadius: "var(--ops-radius-sm)" }}>{s.scene_name} ¥{s.spend.toFixed(0)} · ROI {s.roi}</Tag>
                        ))}
                      </Space>
                    )}
                  </Card>
                </Col>
                <Col xs={24} lg={12}>
                  <Card variant="borderless" title="今日转化漏斗" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", borderRadius: "var(--ops-radius-lg)" }}>
                    {[
                      { label: "访客", value: today.funnel.visitors, rate: null as number | null, color: "var(--ops-accent)" },
                      { label: "收藏", value: today.funnel.collect, rate: today.funnel.collect_rate, color: "var(--ops-cat-2)" },
                      { label: "加购", value: today.funnel.add_cart, rate: today.funnel.cart_rate, color: "var(--ops-warn)" },
                      { label: "支付买家", value: today.funnel.buyers, rate: today.funnel.pay_rate, color: "var(--ops-success)" },
                    ].map((step, idx) => (
                      <div key={step.label} style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                        <Text style={{ width: 64, fontSize: 13 }}>{step.label}</Text>
                        <div style={{ flex: 1, height: 22, background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius-xs)", position: "relative", overflow: "hidden" }}>
                          <div style={{ width: `${idx === 0 ? 100 : Math.max((step.value / Math.max(today.funnel.visitors, 1)) * 100, 6)}%`, height: "100%", background: `linear-gradient(90deg, ${step.color}, color-mix(in srgb, ${step.color} 55%, transparent))`, borderRadius: "var(--ops-radius-xs)" }} />
                        </div>
                        <Text strong style={{ width: 116, textAlign: "right", fontSize: 13 }}>{step.value.toLocaleString()}{step.rate !== null ? ` (${step.rate}%)` : ""}</Text>
                      </div>
                    ))}
                    <Text type="secondary" style={{ fontSize: 12 }}>基于商品实时榜汇总，每 3 分钟刷新</Text>
                  </Card>
                </Col>
              </Row>

              <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                <Col xs={24} md={12}>
                  <Card variant="borderless" title="今日流量结构" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", borderRadius: "var(--ops-radius-lg)" }}>
                    {today.flow.has_data ? (
                      <>
                        <Space size={8}>
                          <SearchOutlined style={{ color: "var(--ops-accent)", fontSize: 18 }} />
                          <Text strong style={{ fontSize: 26 }}>{today.flow.search_share}%</Text>
                        </Space>
                        <Text type="secondary" style={{ display: "block", marginTop: 4 }}>搜索引导（{today.flow.search_uv.toLocaleString()} 访客）{today.flow.data_date ? ` · ${today.flow.data_date} 数据` : ""}</Text>
                        <div style={{ marginTop: 10, height: 10, background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius-xs)", overflow: "hidden" }}>
                          <div style={{ width: `${today.flow.search_share}%`, height: "100%", background: "linear-gradient(90deg,var(--ops-accent),var(--ops-accent-light))", borderRadius: "var(--ops-radius-xs)" }} />
                        </div>
                                                <Text style={{ fontSize: 13, marginTop: 6, display: "block" }}>其他渠道 {today.flow.other_share}%</Text>
                        {today.flow.sources.length > 0 && (
                          <div style={{ marginTop: 12, borderTop: "1px solid var(--ops-border)", paddingTop: 10 }}>
                            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>流量来源 Top</Text>
                            {today.flow.sources.slice(0, 6).map((s) => (
                              <div key={s.rank} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                                <Text style={{ width: 56, fontSize: 12, flexShrink: 0 }} ellipsis>{s.source}</Text>
                                <div style={{ flex: 1, height: 10, background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius-xs)", overflow: "hidden" }}>
                                  <div style={{ width: `${Math.min((s.uv / Math.max(today.flow.sources[0]?.uv ?? 1, 1)) * 100, 100)}%`, height: "100%", background: "linear-gradient(90deg,var(--ops-accent),var(--ops-accent-light))", borderRadius: "var(--ops-radius-xs)" }} />
                                </div>
                                <Text style={{ width: 60, fontSize: 12, textAlign: "right" }}>{s.uv.toLocaleString()}</Text>
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    ) : (
                      <Empty description="实时档暂无搜索引导数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    )}
                  </Card>
                </Col>
                <Col xs={24} md={12}>
                  <Card variant="borderless" title="今日说明" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", borderRadius: "var(--ops-radius-lg)" }}>
                    <Text type="secondary" style={{ fontSize: 13, lineHeight: 1.9 }}>
                      今日数据截至当前小时，较昨日同时段对比；KPI 来自店铺分时表，漏斗/爆款基于商品实时榜，流量/退款来自生意参谋实时接口（流量看板 / 首页-数据概括-完结时间），每 3 分钟自动刷新。
                    </Text>
                  </Card>
                </Col>
              </Row>

              <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                <Col xs={24} md={12}>
                  <Card variant="borderless" title="今日爆款（较昨日同时段上涨）" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", borderRadius: "var(--ops-radius-lg)" }}>
                    {today.movers.risers.length === 0 ? (
                      <Empty description="暂无" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    ) : (
                      <Space direction="vertical" style={{ width: "100%" }} size={8}>
                        {today.movers.risers.map((m, i) => (
                          <div key={m.item_id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span style={{ width: 22, height: 22, borderRadius: "var(--ops-radius-xs)", background: "var(--ops-success)", color: "#fff", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{i + 1}</span>
                            <Text ellipsis style={{ flex: 1, fontSize: 13 }}>{m.item_title}</Text>
                            <Tag color="red" style={{ marginRight: 0 }}>▲ {m.cycle}%</Tag>
                            <Text strong style={{ fontSize: 13, width: 80, textAlign: "right" }}>¥{m.sales.toLocaleString()}</Text>
                          </div>
                        ))}
                      </Space>
                    )}
                  </Card>
                </Col>
                <Col xs={24} md={12}>
                  <Card variant="borderless" title="今日暴跌（较昨日同时段下跌）" style={{ boxShadow: "var(--ops-shadow-sm)", height: "100%", borderRadius: "var(--ops-radius-lg)" }}>
                    {today.movers.fallers.length === 0 ? (
                      <Empty description="暂无" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    ) : (
                      <Space direction="vertical" style={{ width: "100%" }} size={8}>
                        {today.movers.fallers.map((m, i) => (
                          <div key={m.item_id} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <span style={{ width: 22, height: 22, borderRadius: "var(--ops-radius-xs)", background: "var(--ops-danger)", color: "#fff", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center" }}>{i + 1}</span>
                            <Text ellipsis style={{ flex: 1, fontSize: 13 }}>{m.item_title}</Text>
                            <Tag color="green" style={{ marginRight: 0 }}>▼ {Math.abs(m.cycle)}%</Tag>
                            <Text strong style={{ fontSize: 13, width: 80, textAlign: "right" }}>¥{m.sales.toLocaleString()}</Text>
                          </div>
                        ))}
                      </Space>
                    )}
                  </Card>
                </Col>
              </Row>
            </>
          ) : null}

        </>
      ) : (
        <Card variant="borderless">
          <Empty description="还没有数据，点击右上角「同步店铺数据」抓取生意参谋数据" />
        </Card>
      )}
    </div>
  );
}