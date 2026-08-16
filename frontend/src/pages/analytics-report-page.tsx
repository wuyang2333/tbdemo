import { BarChartOutlined, CopyOutlined, DownloadOutlined, RobotOutlined, ReloadOutlined, SendOutlined, SettingOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, DatePicker, Descriptions, Drawer, Empty, Input, Modal, Row, Space, Spin, Statistic, Switch, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage, TOKEN_KEY } from "../lib/api";
import { useDailyRefreshAt } from "../lib/use-daily-refresh";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsReport } from "../types";

const { Text } = Typography;

function fmt(v: number): string {
  return `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtInt(v: number): string {
  return v.toLocaleString("zh-CN");
}

export function AnalyticsReportPage() {
  const [data, setData] = useState<AnalyticsReport | null>(null);
  const [lastUpdated, setLastUpdated] = useState("");
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);
  const [date, setDate] = useState<string | null>(dayjs().subtract(1, "day").format("YYYY-MM-DD"));
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiReply, setAiReply] = useState("");
  const [pushOpen, setPushOpen] = useState(false);
  const [pushCfg, setPushCfg] = useState({ enabled: false, webhook: "", hour: 9, minute: 0 });
  const [pushSaving, setPushSaving] = useState(false);
  const [pushTesting, setPushTesting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (date) params.set("date", date);
      if (storeId) params.set("store_id", String(storeId));
      const { data: res } = await http.get<AnalyticsReport>(`/analytics/report?${params.toString()}`);
      setData(res);
      setLastUpdated(dayjs().format("HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [date, storeId]);

  useEffect(() => {
    load();
  }, [load]);
  useDailyRefreshAt(load, 9);

  const { syncing, syncAll } = useSyncStores(load);

  const dayLabel = data?.date === dayjs().format("YYYY-MM-DD") ? "今日" : data?.date === dayjs().subtract(1, "day").format("YYYY-MM-DD") ? "昨日" : (data?.date || "").slice(5) || "";

  const pct = (cur: number, prev: number): string => {
    if (!prev) return "—";
    const c = ((cur - prev) / prev) * 100;
    return `${c >= 0 ? "+" : ""}${c.toFixed(1)}%`;
  };

  const buildText = (): string => {
    if (!data) return "";
    const t = data.today;
    const y = data.yesterday;
    const lines: string[] = [
      `【经营日报 ${data.date}】`,
      `访客 ${fmtInt(t.visitors)}（较昨日 ${pct(t.visitors, y.visitors)}）｜销售额 ${fmt(t.sales)}（${pct(t.sales, y.sales)}）｜订单 ${fmtInt(t.orders)}（${pct(t.orders, y.orders)}）｜转化率 ${t.conversion_rate.toFixed(2)}%｜客单价 ${fmt(t.avg_order_value)}`,
    ];
    if (data.add_cart) lines.push(`加购 ${fmtInt(data.add_cart)}`);
    lines.push(`推广：花费 ${fmt(data.promo_today.spend)}，成交 ${fmt(data.promo_today.sales)}，ROI ${data.promo_today.roi.toFixed(2)}`);
    if (data.promo_today_scenes.length) {
      lines.push("分场景：" + data.promo_today_scenes.map((x) => `${x.scene_name}花${fmt(x.spend)}/ROI${x.roi.toFixed(2)}`).join("；"));
    }
    if (data.top_today.length) {
      lines.push("TOP商品：" + data.top_today.slice(0, 3).map((x) => `${x.item_title.slice(0, 12)}${fmt(x.sales)}`).join("、"));
    }
    if (data.report_alerts.length) {
      lines.push("预警：" + data.report_alerts.slice(0, 3).map((a) => a.message).join("；"));
    }
    if (data.goal) lines.push(`${data.month} 目标 ${fmt(data.goal)}，本月已达成 ${fmt(data.month_sales)}`);
    return lines.filter(Boolean).join("\n");
  };

  const copyReport = async () => {
    const text = buildText();
    try {
      await navigator.clipboard.writeText(text);
      message.success("日报已复制，可粘贴到群/文档");
    } catch {
      message.error("复制失败，请手动选择复制");
    }
  };

  const runAI = async () => {
    setAiOpen(true);
    setAiLoading(true);
    setAiReply("");
    try {
      const params = new URLSearchParams();
      if (date) params.set("date", date);
      if (storeId) params.set("store_id", String(storeId));
      const { data: res } = await http.post<{ reply: string }>(`/analytics/report/ai?${params.toString()}`, undefined, { timeout: 120000 });
      setAiReply(res.reply);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAiLoading(false);
    }
  };

  const openPush = async () => {
    setPushOpen(true);
    try {
      const { data: cfg } = await http.get<{ enabled: boolean; webhook: string; hour: number; minute: number }>("/analytics/report/push-config");
      setPushCfg(cfg);
    } catch {}
  };
  const savePush = async () => {
    setPushSaving(true);
    try {
      await http.put("/analytics/report/push-config", pushCfg, { timeout: 20000 });
      message.success("推送设置已保存");
      setPushOpen(false);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setPushSaving(false);
    }
  };
  const testPush = async () => {
    setPushTesting(true);
    try {
      await http.post(`/analytics/report/push${date ? `?date=${date}` : ""}`, undefined, { timeout: 30000 });
      message.success("推送成功，请到群里查看");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setPushTesting(false);
    }
  };

  const exportExcel = async () => {
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const response = await fetch(`/api/analytics/export?days=14`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error("导出失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `经营数据_${dayjs().format("YYYYMMDD")}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      message.success("已导出 Excel");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const topCard = (title: string, items: { item_id: string; item_title: string; image?: string; sales: number; orders: number }[]) => (
    <Card variant="borderless" title={title} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
      {items.length === 0 ? (
        <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 16 }} />
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {items.map((it, idx) => (
            <div key={it.item_id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 20, fontWeight: 700, color: idx < 3 ? "#fa8c16" : "rgba(128,128,128,0.7)" }}>{idx + 1}</span>
              {it.image ? <img src={it.image} alt="" style={{ width: 34, height: 34, borderRadius: 6, objectFit: "cover", flexShrink: 0 }} /> : <div style={{ width: 34, height: 34, borderRadius: 6, background: "var(--ops-card-bg-2)", flexShrink: 0 }} />}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13 }}>{it.item_title}</div>
                <div style={{ fontSize: 11, color: "rgba(128,128,128,0.7)" }}>{fmtInt(it.orders)}单</div>
              </div>
              <Text strong style={{ fontSize: 13 }}>{fmt(it.sales)}</Text>
            </div>
          ))}
        </div>
      )}
    </Card>
  );

  const sceneTable = (items: { scene: string; scene_name: string; spend: number; sales: number; roi: number }[]) =>
    items.length === 0 ? (<Text type="secondary" style={{ fontSize: 12 }}>暂无分场景数据</Text>) : (
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 8 }}>
        {items.map((x) => (
          <div key={x.scene} style={{ border: "1px solid var(--ops-border)", borderRadius: 8, padding: "8px 10px" }}>
            <Text strong style={{ fontSize: 12 }}>{x.scene_name}</Text>
            <div style={{ fontSize: 12, marginTop: 4, color: "var(--ops-text-secondary)" }}>
              花费 {fmt(x.spend)} · 成交 {fmt(x.sales)}
              <br />ROI <Tag color={x.roi >= 2 ? "green" : x.roi >= 1 ? "orange" : "red"}>{x.roi.toFixed(2)}</Tag>
            </div>
          </div>
        ))}
      </div>
    );

  const weekCompare = (label: string, cur: number, week: number) => (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 13 }}>
      <span style={{ color: "var(--ops-text-secondary)" }}>{label}</span>
      <span>{fmtInt(cur)} <Text type="secondary" style={{ fontSize: 12 }}>上周 {fmtInt(week)}（{pct(cur, week)}）</Text></span>
    </div>
  );

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="经营日报"
        extra={
          <Space wrap>
            <DatePicker
              allowClear
              placeholder="选择日期回看"
              value={date ? dayjs(date) : null}
              onChange={(d) => setDate(d ? d.format("YYYY-MM-DD") : null)}
            />
            
            <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<RobotOutlined />} onClick={runAI} disabled={!data}>AI 总结</Button>
            <Button icon={<SettingOutlined />} onClick={openPush}>推送设置</Button>
            <Button icon={<CopyOutlined />} onClick={copyReport} disabled={!data}>复制日报</Button>
            <Button icon={<DownloadOutlined />} onClick={exportExcel}>导出 Excel</Button>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>同步数据</Button>
          </Space>
        }
      />

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}><Spin /></div>
      ) : !data ? (
        <Card variant="borderless"><Empty description="暂无数据，先同步店铺与推广数据" /></Card>
      ) : (
        <>
          {data.report_alerts.length > 0 && (
            <Card variant="borderless" title="今日预警" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
              <div style={{ display: "grid", gap: 4 }}>
                {data.report_alerts.map((a, i) => (
                  <div key={i} style={{ fontSize: 13, color: a.level === "error" ? "#ff4d4f" : "#fa8c16" }}>
                    {a.level === "error" ? "⚠️ " : "❗ "}[{a.type}] {a.message}
                  </div>
                ))}
              </div>
            </Card>
          )}

          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}访客`} value={data.today.visitors} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.visitors, data.yesterday.visitors)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}销售额`} value={data.today.sales} precision={2} prefix="¥" suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.sales, data.yesterday.sales)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}订单`} value={data.today.orders} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.orders, data.yesterday.orders)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}转化率`} value={data.today.conversion_rate} precision={2} suffix="%" valueStyle={{ color: "#1677ff" }} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}客单价`} value={data.today.avg_order_value} precision={2} prefix="¥" suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.avg_order_value, data.yesterday.avg_order_value)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="复购率" value={data.today.repeat_rate ?? 0} precision={1} suffix="%" valueStyle={{ color: "#52c41a" }} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="加购" value={data.add_cart} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{data.add_cart ? "次" : "—"}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="退款额" value={data.refund_amount} precision={2} prefix="¥" valueStyle={{ color: "#ff4d4f" }} /></Card></Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} md={12}>
              <Card variant="borderless" title={`推广（${dayLabel}）`} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Descriptions size="small" column={3}
                  items={[
                    { key: "s", label: "花费", children: fmt(data.promo_today.spend) },
                    { key: "sa", label: "成交", children: fmt(data.promo_today.sales) },
                    { key: "r", label: "ROI", children: <Tag color={data.promo_today.roi >= 2 ? "green" : "orange"}>{data.promo_today.roi.toFixed(2)}</Tag> },
                  ]}
                />
                <div style={{ marginTop: 10 }}>{sceneTable(data.promo_today_scenes)}</div>
              </Card>
            </Col>
            <Col xs={24} md={12}>
              <Card variant="borderless" title="前一日推广" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Descriptions size="small" column={3}
                  items={[
                    { key: "s", label: "花费", children: fmt(data.promo_yesterday.spend) },
                    { key: "sa", label: "成交", children: fmt(data.promo_yesterday.sales) },
                    { key: "r", label: "ROI", children: data.promo_yesterday.roi.toFixed(2) },
                  ]}
                />
                <div style={{ marginTop: 10 }}>{sceneTable(data.promo_yesterday_scenes)}</div>
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} md={12}>{topCard(`${dayLabel} TOP 商品`, data.top_today)}</Col>
            <Col xs={24} md={12}>{topCard("前一日 TOP 商品", data.top_yesterday)}</Col>
          </Row>

          <Card variant="borderless" title="较上周同期" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
            {weekCompare("访客", data.today.visitors, data.last_week.visitors)}
            {weekCompare("销售额", data.today.sales, data.last_week.sales)}
            {weekCompare("订单", data.today.orders, data.last_week.orders)}
            {weekCompare("转化率", data.today.conversion_rate, data.last_week.conversion_rate)}
          </Card>

          <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>月度目标：{data.goal ? `${data.month} 目标 ${fmt(data.goal)}，本月已达成 ${fmt(data.month_sales)}` : "未设置，可到「目标预测」页设置"}</Text>
            <Text style={{ whiteSpace: "pre-line" }}>{buildText()}</Text>
          </Card>
        </>
      )}

      <Drawer title="AI 日报总结" width={520} open={aiOpen} onClose={() => setAiOpen(false)} destroyOnClose>
        {aiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}><Spin tip="AI 正在生成总结…" /></div>
        ) : aiReply ? (
          <div>
            <Text style={{ fontSize: 14, lineHeight: 1.9, whiteSpace: "pre-wrap" }}>{aiReply}</Text>
            <div style={{ marginTop: 16 }}>
              <Button icon={<CopyOutlined />} onClick={() => { navigator.clipboard.writeText(aiReply); message.success("总结已复制"); }}>复制总结</Button>
            </div>
          </div>
        ) : (
          <Empty description="生成失败或暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 40 }} />
        )}
      </Drawer>

      <Modal
        title="日报定时推送设置"
        open={pushOpen}
        onCancel={() => setPushOpen(false)}
        onOk={savePush}
        okText="保存"
        cancelText="取消"
        confirmLoading={pushSaving}
        destroyOnClose
      >
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>启用定时推送</span></div>
            <Switch checked={pushCfg.enabled} onChange={(v) => setPushCfg((p) => ({ ...p, enabled: v }))} checkedChildren="开" unCheckedChildren="关" />
          </div>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>群机器人 Webhook</span> <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>钉钉/企业微信 自定义机器人地址</span></div>
            <Input placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." value={pushCfg.webhook} onChange={(e) => setPushCfg((p) => ({ ...p, webhook: e.target.value }))} />
          </div>
          <div style={{ display: "flex", gap: 16 }}>
            <div>
              <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>推送时间</span></div>
              <Input type="time" defaultValue={`${String(pushCfg.hour).padStart(2, "0")}:${String(pushCfg.minute).padStart(2, "0")}`} key={`${pushCfg.hour}:${pushCfg.minute}`} onChange={(e) => { const [h, m] = (e.target.value || "21:00").split(":"); setPushCfg((p) => ({ ...p, hour: Number(h || 21), minute: Number(m || 0) })); }} />
            </div>
            <div style={{ alignSelf: "flex-end" }}>
              <Button icon={<SendOutlined />} loading={pushTesting} onClick={testPush}>立即测试推送</Button>
            </div>
          </div>
          <Text type="secondary" style={{ fontSize: 12 }}>每天到点自动生成日报并推送到群里；需后端服务保持运行。</Text>
        </div>
      </Modal>
    </div>
  );
}
