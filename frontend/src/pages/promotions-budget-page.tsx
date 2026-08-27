import { AlertOutlined, BarChartOutlined, ReloadOutlined, SettingOutlined, WarningOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Progress, Row, Space, Spin, Table, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { AlertSettingsModal } from "../components/ui/alert-settings-modal";
import { PageHeader } from "../components/ui/page-header";
import http, { getApiErrorMessage } from "../lib/api";
import { useAlertConfig } from "../lib/use-alert-config";
import { useStores } from "../lib/store";
import type { PromoPlan } from "../types";
import { fmtMoney } from "../components/promotions/promotions-ui";

const { Text } = Typography;

type BudgetAlert = { level?: string; type: string; message: string; plan_id?: number; store_id?: number };

export function PromotionsBudgetPage() {
  const navigate = useNavigate();
  const { currentStore } = useStores();
  const { config, saveConfig } = useAlertConfig();
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [alerts, setAlerts] = useState<BudgetAlert[]>([]);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const scope = currentStore ? `?store_id=${currentStore.id}` : "";
      const [plansRes, alertsRes] = await Promise.all([
        http.get<{ items: PromoPlan[] }>(`/promotions/plans?mode=realtime${currentStore ? `&store_id=${currentStore.id}` : ""}`),
        http.get<{ items: BudgetAlert[] }>(`/promotions/alerts${scope}`),
      ]);
      setPlans(plansRes.data.items || []);
      setAlerts(alertsRes.data.items || []);
      setUpdatedAt(dayjs().format("MM-DD HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [currentStore?.id]);

  useEffect(() => { void load(); }, [load]);

  const summary = useMemo(() => {
    const budget = plans.reduce((sum, plan) => sum + (plan.day_budget || 0), 0);
    const spend = plans.reduce((sum, plan) => sum + (plan.spend || 0), 0);
    const minutes = Math.max(30, new Date().getHours() * 60 + new Date().getMinutes());
    const forecast = spend / minutes * 1440;
    return { budget, spend, forecast, percent: budget ? Math.round(spend / budget * 100) : 0, forecastPercent: budget ? Math.round(forecast / budget * 100) : 0 };
  }, [plans]);

  const rows = useMemo(() => [...plans].sort((a, b) => (b.day_budget ? b.spend / b.day_budget : 0) - (a.day_budget ? a.spend / a.day_budget : 0)), [plans]);

  const saveSettings = async (patch: Parameters<typeof saveConfig>[0]) => {
    setSaving(true);
    try {
      await saveConfig(patch);
      setSettingsOpen(false);
      message.success("预警规则已保存");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="预算与预警中心"
        description="集中查看预算消耗、全天预测和需要处理的推广异常。"
        extra={<Space><Text type="secondary" style={{ fontSize: 12 }}>更新于 {updatedAt || "—"}</Text><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>预警设置</Button></Space>}
      />
      {loading && plans.length === 0 ? <div style={{ textAlign: "center", padding: 80 }}><Spin size="large" /></div> : null}
      {!loading && plans.length === 0 ? <Card variant="borderless"><Empty description="暂无推广计划，请先同步推广计划数据" /></Card> : null}
      {plans.length > 0 ? (
        <>
          <Row gutter={[12, 12]}>
            {[
              { label: "计划预算", value: fmtMoney(summary.budget), hint: "当前店铺计划日预算" },
              { label: "已消耗", value: fmtMoney(summary.spend), hint: `预算使用 ${summary.percent}%` },
              { label: "全天预测", value: fmtMoney(summary.forecast), hint: `预计使用 ${summary.forecastPercent}%` },
              { label: "待处理预警", value: alerts.length, hint: alerts.length ? "建议优先处理红色异常" : "暂无异常" },
            ].map((item) => <Col xs={12} sm={6} key={item.label}><Card variant="borderless"><Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text><div style={{ fontSize: 23, fontWeight: 700, margin: "5px 0" }}>{item.value}</div><Text type="secondary" style={{ fontSize: 11 }}>{item.hint}</Text></Card></Col>)}
          </Row>
          <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
            <Col xs={24} lg={9}><Card variant="borderless" title="整体预算进度" extra={<Tag color={summary.forecastPercent >= 100 ? "red" : summary.percent >= 90 ? "orange" : "blue"}>{summary.percent}%</Tag>}><Progress percent={Math.min(100, summary.percent)} status={summary.percent >= 100 ? "exception" : "active"} /><Text type="secondary">按当前消耗速度预计全天 {fmtMoney(summary.forecast)}，预测值仅供预算控制参考。</Text></Card></Col>
            <Col xs={24} lg={15}><Card variant="borderless" title={<Space><AlertOutlined />重点预警</Space>} extra={<Button type="link" size="small" onClick={() => navigate("/promotions/plans?todo=alerts")}>查看计划</Button>}>{alerts.length ? <Space orientation="vertical" size={8} style={{ width: "100%" }}>{alerts.slice(0, 5).map((item, index) => <Alert key={`${item.type}-${index}`} type={item.level === "error" ? "error" : "warning"} showIcon title={item.type} description={item.message} />)}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无预算预警" />}</Card></Col>
          </Row>
          <Card variant="borderless" title={<Space><WarningOutlined />计划预算排行</Space>} style={{ marginTop: 16 }}>
            <Table<PromoPlan> rowKey="id" size="small" pagination={false} dataSource={rows} columns={[{ title: "计划", dataIndex: "plan_name", ellipsis: true }, { title: "场景", dataIndex: "scene_name", width: 100, render: (value: string) => <Tag>{value}</Tag> }, { title: "日预算", dataIndex: "day_budget", align: "right", width: 110, render: (value: number) => fmtMoney(value) }, { title: "已消耗", dataIndex: "spend", align: "right", width: 110, render: (value: number) => fmtMoney(value) }, { title: "使用率", key: "usage", width: 180, render: (_, row) => { const percent = row.day_budget ? Math.round(row.spend / row.day_budget * 100) : 0; return <Progress percent={Math.min(100, percent)} status={percent >= 100 ? "exception" : percent >= 80 ? "active" : "normal"} />; } }, { title: "操作", key: "action", width: 90, render: (_, row) => <Button type="link" size="small" onClick={() => navigate(`/promotions/plans?plan_id=${row.id}${row.store_id ? `&store_id=${row.store_id}` : ""}`)}>查看计划</Button> }]} />
          </Card>
        </>
      ) : null}
      <AlertSettingsModal open={settingsOpen} title="预算与预警规则" module="plan" config={config} rules={config.rules} onCancel={() => setSettingsOpen(false)} onSave={saveSettings} saving={saving} fields={[{ group: "plan", key: "budget_over", label: "预算超限比例", hint: "花费/日预算达到该比例时红色提醒", min: 0.5, max: 3, step: 0.05 }, { group: "plan", key: "budget_warn", label: "接近预算比例", hint: "花费/日预算达到该比例时橙色提醒", min: 0.1, max: 1, step: 0.05 }, { group: "plan", key: "roi_drop_ratio", label: "ROI 下滑提醒比例", hint: "今日 ROI 低于昨日 ROI × 该比例时提醒", min: 0.1, max: 1, step: 0.05 }, { group: "plan", key: "roi_low", label: "ROI 偏低阈值", hint: "实时 ROI 低于该值时提醒", min: 0.1, max: 10, step: 0.1 }]} />
    </div>
  );
}
