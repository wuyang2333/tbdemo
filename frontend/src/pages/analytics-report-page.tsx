import { BarChartOutlined, CopyOutlined, DownloadOutlined, RobotOutlined, ReloadOutlined, SendOutlined, SettingOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, DatePicker, Descriptions, Drawer, Empty, Input, Modal, Row, Space, Spin, Statistic, Switch, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { useDailyRefreshAt } from "../lib/use-daily-refresh";
import { PageHeader } from "../components/ui/page-header";
import { StoreScopeSelect } from "../components/analytics/analytics-ui";
import type { AnalyticsReport } from "../types";
import { buildReportHtml } from "../lib/report-html";
import { HourlyPushButton } from "../components/ui/hourly-push";

const ANALYSIS_KEY = "report_analysis_cache_v1";

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
  const [syncing, setSyncing] = useState(false);
  const [date, setDate] = useState<string | null>(dayjs().subtract(1, "day").format("YYYY-MM-DD"));
  const [aiOpen, setAiOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiReply, setAiReply] = useState("");
  const [pushOpen, setPushOpen] = useState(false);
  const [pushCfg, setPushCfg] = useState({ enabled: false, webhook: "", hour: 9, minute: 0 });
  const [pushSaving, setPushSaving] = useState(false);
  const [pushTesting, setPushTesting] = useState(false);
  const [analysisByDate, setAnalysisByDate] = useState<Record<string, { sections: { 经营分析: string; 推广分析: string; 异常分析: string; 总结: string; 今日行动建议: string }; date: string }>>(() => {
    try {
      const raw = localStorage.getItem(ANALYSIS_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  });
  const [analysisLoading, setAnalysisLoading] = useState(false);

  const analysisKey = `${date || ""}|${storeId || ""}`;
  const currentAnalysis = analysisByDate[analysisKey] || null;
  useEffect(() => {
    try {
      localStorage.setItem(ANALYSIS_KEY, JSON.stringify(analysisByDate));
    } catch {}
  }, [analysisByDate]);

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

  const syncDaily = async () => {
    setSyncing(true);
    try {
      // 同步近 7 天推广按天 + 商品按天数据（日报推广/TOP 商品来源），无需等每天 9 点定时
      const [promoRes, itemRes] = await Promise.all([
        http.post<{ ok: number; total: number }>("/promotions/sync?days=7"),
        http.post<{ ok: number; total: number }>("/stores/sync-items?days=7"),
      ]);
      message.success(
        `同步完成：推广 ${promoRes.data.ok}/${promoRes.data.total} 家，商品 ${itemRes.data.ok}/${itemRes.data.total} 家`
      );
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  useEffect(() => {
    load();
  }, [load]);
  useDailyRefreshAt(() => {
    load();
    // 每天早上 9 点：用完整数据重新生成昨日经营分析和 AI 分析
    runAnalysis(true, dayjs().subtract(1, "day").format("YYYY-MM-DD"));
  }, 9);


  const dayLabel = data?.date === dayjs().format("YYYY-MM-DD") ? "今日" : data?.date === dayjs().subtract(1, "day").format("YYYY-MM-DD") ? "昨日" : (data?.date || "").slice(5) || "";
  const realRoi = data && data.promo_today.spend > 0 ? data.today.sales / data.promo_today.spend : 0;
  const prevRealRoi = data && data.promo_yesterday.spend > 0 ? data.yesterday.sales / data.promo_yesterday.spend : 0;

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
      const { data: res } = await http.post<{ reply: string }>(`/analytics/report/ai?${params.toString()}`, undefined, { timeout: 240000 });
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

  const runAnalysis = async (force = false, targetDate?: string) => {
    const d = targetDate ?? date;
    const key = `${d || ""}|${storeId || ""}`;
    const existing = analysisByDate[key];
    // 旧缓存可能因解析失败全是空板块：只有存在非空内容时才跳过重新生成
    const hasContent =
      !!existing &&
      !!existing.sections &&
      Object.values(existing.sections).some((value) => typeof value === "string" && value.trim().length > 0);
    if (!force && hasContent) return;
    setAnalysisLoading(true);
    try {
      const params = new URLSearchParams();
      if (d) params.set("date", d);
      if (storeId) params.set("store_id", String(storeId));
      const { data: res } = await http.post<{ sections: { 经营分析: string; 推广分析: string; 异常分析: string; 总结: string; 今日行动建议: string }; date: string }>(
        `/analytics/report/analysis?${params.toString()}`,
        undefined,
        { timeout: 180000 }
      );
      setAnalysisByDate((prev) => ({ ...prev, [key]: res }));
      message.success("分析已生成");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAnalysisLoading(false);
    }
  };


  const exportPdf = () => {
    if (!data) return;
    const win = window.open("", "_blank", "width=920,height=1100");
    if (!win) {
      message.error("浏览器拦截了弹窗，请允许本站弹窗后重试");
      return;
    }
    win.document.open();
    win.document.write(buildReportHtml(data));
    win.document.close();
    setTimeout(() => {
      try {
        win.focus();
        win.print();
      } catch {
        // 用户可能已手动关闭窗口
      }
    }, 400);
    message.info("已打开报告，请在打印窗口选择「另存为 PDF」");
  };

  const topCard = (title: string, items: { item_id: string; item_title: string; image?: string; sales: number; orders: number }[]) => (
    <Card variant="borderless" title={title} style={{ boxShadow: "var(--ops-shadow-sm)" }}>
      {items.length === 0 ? (
        <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 16 }} />
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {items.map((it, idx) => (
            <div key={it.item_id} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 20, fontWeight: 700, color: idx < 3 ? "var(--ops-warn)" : "var(--ops-text-3)" }}>{idx + 1}</span>
              {it.image ? <img src={it.image} alt="" style={{ width: 34, height: 34, borderRadius: "var(--ops-radius-xs)", objectFit: "cover", flexShrink: 0 }} /> : <div style={{ width: 34, height: 34, borderRadius: "var(--ops-radius-xs)", background: "var(--ops-card-bg-2)", flexShrink: 0 }} />}
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13 }}>{it.item_title}</div>
                <div style={{ fontSize: 11, color: "var(--ops-text-3)" }}>{fmtInt(it.orders)}单</div>
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
          <div key={x.scene} style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius-sm)", padding: "8px 10px" }}>
            <Text strong style={{ fontSize: 12 }}>{x.scene_name}</Text>
            <div style={{ fontSize: 12, marginTop: 4, color: "var(--ops-text-secondary)" }}>
              花费 {fmt(x.spend)} · 成交 {fmt(x.sales)}
              <br />ROI <Tag color={x.roi >= 2 ? "green" : x.roi >= 1 ? "orange" : "red"}>{x.roi.toFixed(2)}</Tag>
            </div>
          </div>
        ))}
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
              disabledDate={(d) => !d || d.isAfter(dayjs().subtract(1, "day"), "day")}
              onChange={(d) => {
                const next = d ? d.format("YYYY-MM-DD") : null;
                if (analysisLoading) {
                  Modal.confirm({
                    title: "切换日期",
                    content: "当前正在生成该日期的 AI 分析，确定要切换日期吗？（正在生成的结果仍会保存）",
                    okText: "确定切换",
                    cancelText: "取消",
                    onOk: () => setDate(next),
                  });
                } else {
                  setDate(next);
                }
              }}
            />
            
            <Text type="secondary" style={{ fontSize: 12 }}>最近更新 {lastUpdated || "—"}</Text>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<RobotOutlined />} onClick={runAI} disabled={!data}>AI 总结</Button>
            <Button icon={<SettingOutlined />} onClick={openPush}>推送设置</Button>
            <HourlyPushButton />
            <Button icon={<CopyOutlined />} onClick={copyReport} disabled={!data}>复制日报</Button>
            <Button icon={<DownloadOutlined />} onClick={exportPdf}>导出 PDF</Button>
            <Button icon={<SyncOutlined />} loading={syncing} onClick={syncDaily}>同步数据</Button>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          </Space>
        }
      />

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}><Spin /></div>
      ) : !data ? (
        <Card variant="borderless"><Empty description="暂无数据，先同步店铺与推广数据" /></Card>
      ) : (
        <>


          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}销售额`} value={data.today.sales} precision={2} prefix="¥" suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.sales, data.yesterday.sales)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}买家数`} value={data.today.buyers} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.buyers, data.yesterday.buyers)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}访客`} value={data.today.visitors} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.visitors, data.yesterday.visitors)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}转化率`} value={data.today.conversion_rate} precision={2} suffix="%" styles={{ content: {  color: "var(--ops-accent)"  } }} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}真实ROI`} value={realRoi} precision={2} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(realRoi, prevRealRoi)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}退款`} value={data.refund_amount} precision={2} prefix="¥" styles={{ content: {  color: "var(--ops-danger)"  } }} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}净支付金额`} value={data.today.sales - data.refund_amount} precision={2} prefix="¥" /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title={`${dayLabel}客单价`} value={data.today.avg_order_value} precision={2} prefix="¥" suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.avg_order_value, data.yesterday.avg_order_value)}</Text>} /></Card></Col>
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


          <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <Text style={{ whiteSpace: "pre-line" }}>{buildText()}</Text>
          </Card>

          <Card
            variant="borderless"
            title="AI 经营分析"
            style={{ boxShadow: "var(--ops-shadow-sm)", marginTop: 16 }}
            extra={
              !analysisLoading ? (
                <Button type="primary" icon={<RobotOutlined />} onClick={() => runAnalysis(true)}>{currentAnalysis ? "重新生成" : "生成分析"}</Button>
              ) : undefined
            }
          >
            {analysisLoading ? (
              <div style={{ textAlign: "center", padding: 40 }}><Spin description="AI 正在结合数据生成经营分析，约需 30-60 秒，请稍候…" /></div>
            ) : currentAnalysis ? (
              <div style={{ display: "grid", gap: 10 }}>
                {[
                  { key: "经营分析" as const, color: "var(--ops-accent-light)", bg: "var(--ops-accent-soft)" },
                  { key: "推广分析" as const, color: "var(--ops-accent)", bg: "var(--ops-accent-soft)" },
                  { key: "异常分析" as const, color: "var(--ops-danger)", bg: "rgba(255,77,79,0.08)" },
                  { key: "总结" as const, color: "var(--ops-success)", bg: "rgba(82,196,26,0.08)" },
                  { key: "今日行动建议" as const, color: "var(--ops-warn)", bg: "rgba(250,140,22,0.08)" },
                ].map((sec) =>
                  currentAnalysis.sections[sec.key] ? (
                    <div key={sec.key} style={{ border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius)", padding: "12px 14px", background: sec.bg }}>
                      <Text strong style={{ color: sec.color }}>{sec.key}</Text>
                      <div style={{ fontSize: 13, lineHeight: 1.9, marginTop: 6, color: "var(--ops-text)", whiteSpace: "pre-wrap" }}>
                        {currentAnalysis.sections[sec.key]}
                      </div>
                    </div>
                  ) : null
                )}
                <div style={{ marginTop: 4 }}>
                  <Button icon={<CopyOutlined />} onClick={() => {
                    const txt = `【经营日报 ${data?.date} AI分析】\n` + Object.entries(currentAnalysis.sections).map(([k, v]) => (v ? `【${k}】\n${v}` : "")).filter(Boolean).join("\n\n");
                    navigator.clipboard.writeText(txt);
                    message.success("分析已复制");
                  }}>复制分析</Button>
                </div>
              </div>
            ) : (
              <Text type="secondary" style={{ fontSize: 13 }}>
                基于所选日期的真实数据（生意参谋 + 万相台），AI 生成经营分析、推广分析、异常分析、总结和今日行动建议。每个日期生成一次后自动保存，切回已生成的日期直接显示；新日期点「生成分析」生成，点「重新生成」可覆盖。
              </Text>
            )}
          </Card>
        </>
      )}

      <Drawer title="AI 日报总结" size="large" open={aiOpen} onClose={() => setAiOpen(false)} destroyOnHidden>
        {aiLoading ? (
          <div style={{ textAlign: "center", padding: 60 }}><Spin description="AI 正在生成总结…" /></div>
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
        destroyOnHidden
      >
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>启用定时推送</span></div>
            <Switch checked={pushCfg.enabled} onChange={(v) => setPushCfg((p) => ({ ...p, enabled: v }))} checkedChildren="开" unCheckedChildren="关" />
          </div>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>群机器人 Webhook</span> <span style={{ marginLeft: 8, fontSize: 12, color: "var(--ops-text-3)" }}>钉钉/企业微信 自定义机器人地址</span></div>
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
