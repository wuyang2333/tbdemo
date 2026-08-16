import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, DatePicker, Empty, InputNumber, Progress, Row, Space, Spin, Statistic, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { LineChart, StoreScopeSelect, fmtMoney, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsForecast, AnalyticsGoalProgress } from "../types";

const { Text } = Typography;

export function AnalyticsGoalPage() {
  const [progress, setProgress] = useState<AnalyticsGoalProgress | null>(null);
  const [forecast, setForecast] = useState<AnalyticsForecast | null>(null);
  const [month, setMonth] = useState(dayjs().format("YYYY-MM"));
  const [goalInput, setGoalInput] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [p, f] = await Promise.all([
        http.get<AnalyticsGoalProgress>(`/analytics/goal/progress?month=${month}${storeId ? `&store_id=${storeId}` : ""}`),
        http.get<AnalyticsForecast>("/analytics/forecast?days=7"),
      ]);
      setProgress(p.data);
      setForecast(f.data);
      setGoalInput(p.data.goal || null);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [month, storeId]);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);

  const saveGoal = async () => {
    setSaving(true);
    try {
      await http.put("/analytics/goal", { goal: goalInput || 0, month });
      message.success("目标已保存");
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const fcLabels = [...(forecast?.actual ?? []).map((p) => p.date), ...(forecast?.predicted ?? []).map((p) => p.date)];
  const fcActual = [...(forecast?.actual ?? []).map((p) => p.sales), ...Array((forecast?.predicted ?? []).length).fill(null as unknown as number)];
  const fcPred = [...Array((forecast?.actual ?? []).length).fill(null as unknown as number), ...(forecast?.predicted ?? []).map((p) => p.sales)];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="目标预测"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
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
        <Space wrap align="center">
          <Text>月份</Text>
          <DatePicker picker="month" value={dayjs(month)} onChange={(v) => v && setMonth(v.format("YYYY-MM"))} />
          <Text>月度销售目标（元）</Text>
          <InputNumber min={0} step={10000} value={goalInput} onChange={(v) => setGoalInput(v ?? 0)} style={{ width: 160 }} />
          <Button type="primary" loading={saving} onClick={saveGoal}>
            保存目标
          </Button>
        </Space>
      </Card>

      {loading && !progress ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !progress ? (
        <Card variant="borderless">
          <Empty description="暂无数据" />
        </Card>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="月度目标" value={progress.goal} precision={0} prefix="¥" /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="已达成" value={progress.sales} precision={2} prefix="¥" valueStyle={{ color: "#1677ff" }} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="预测月底" value={progress.forecast} precision={0} prefix="¥" valueStyle={{ color: progress.forecast >= progress.goal ? "#52c41a" : "#fa8c16" }} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="剩余日均需完成" value={progress.remaining_daily} precision={0} prefix="¥" valueStyle={{ color: "#ff4d4f" }} /></Card></Col>
          </Row>

          <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)", marginBottom: 16 }}>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
              {progress.month} 目标进度：已过 {progress.days_elapsed} / {progress.days_total} 天，日均 {fmtMoney(progress.avg_daily)}
            </Text>
            <Progress percent={Math.min(progress.progress_pct, 100)} status={progress.progress_pct >= 100 ? "success" : "active"} format={() => `${progress.progress_pct}%`} />
          </Card>

          <Card variant="borderless" title="近 14 天实际 + 未来 7 天预测（销售额，仅供参考）" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <LineChart
              labels={fcLabels}
              series={[
                { name: "实际", color: "#1677ff", values: fcActual, format: fmtMoney },
                { name: "预测", color: "#fa8c16", values: fcPred, format: fmtMoney },
              ]}
            />
          </Card>
        </>
      )}
    </div>
  );
}
