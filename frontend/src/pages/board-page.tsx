import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Card, Col, Progress, Row, Spin, Statistic, Typography, message } from "antd";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../lib/api";
import type { AnalyticsGoalProgress, AnalyticsReport, AnalyticsSummary } from "../types";

const { Text } = Typography;

function fmt(v: number): string {
  return `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function BoardPage() {
  const navigate = useNavigate();
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [goal, setGoal] = useState<AnalyticsGoalProgress | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      const [s, r, g] = await Promise.all([
        http.get<AnalyticsSummary>("/analytics/summary?days=14"),
        http.get<AnalyticsReport>("/analytics/report"),
        http.get<AnalyticsGoalProgress>("/analytics/goal/progress"),
      ]);
      setSummary(s.data);
      setReport(r.data);
      setGoal(g.data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div style={{ minHeight: "100vh", background: "linear-gradient(135deg,#0f172a 0%,#1e293b 100%)", color: "#fff", padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <Text style={{ fontSize: 22, fontWeight: 800, color: "#fff" }}>经营数据大屏</Text>
          <Text style={{ marginLeft: 12, fontSize: 13, color: "rgba(255,255,255,0.6)" }}>
            每 60 秒自动刷新 · {new Date().toLocaleString("zh-CN")}
          </Text>
        </div>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate("/analytics/overview")}>
          返回工作台
        </Button>
      </div>

      {loading ? (
        <div style={{ textAlign: "center", padding: 120 }}>
          <Spin size="large" />
        </div>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} md={4}><Card style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}><Statistic title="今日销售额" value={report?.today.sales ?? 0} precision={0} prefix="¥" valueStyle={{ color: "#60a5fa" }} /></Card></Col>
            <Col xs={12} md={4}><Card style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}><Statistic title="今日访客" value={report?.today.visitors ?? 0} valueStyle={{ color: "#34d399" }} /></Card></Col>
            <Col xs={12} md={4}><Card style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}><Statistic title="今日订单" value={report?.today.orders ?? 0} valueStyle={{ color: "#fbbf24" }} /></Card></Col>
            <Col xs={12} md={4}><Card style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}><Statistic title="今日转化率" value={report?.today.conversion_rate ?? 0} precision={2} suffix="%" valueStyle={{ color: "#f472b6" }} /></Card></Col>
            <Col xs={12} md={4}><Card style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}><Statistic title="今日推广花费" value={report?.promo_today.spend ?? 0} precision={0} prefix="¥" valueStyle={{ color: "#f87171" }} /></Card></Col>
            <Col xs={12} md={4}><Card style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}><Statistic title="今日推广 ROI" value={report?.promo_today.roi ?? 0} precision={2} valueStyle={{ color: "#a78bfa" }} /></Card></Col>
          </Row>

          <Row gutter={[16, 16]}>
            <Col xs={24} md={8}>
              <Card title="月度目标" style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}>
                <Statistic title="已达成" value={goal?.sales ?? 0} precision={0} prefix="¥" valueStyle={{ color: "#34d399", fontSize: 28 }} />
                <div style={{ margin: "10px 0" }}>
                  <Progress percent={Math.min(goal?.progress_pct ?? 0, 100)} showInfo={false} strokeColor="#34d399" trailColor="rgba(255,255,255,0.15)" />
                </div>
                <Text style={{ color: "rgba(255,255,255,0.7)", fontSize: 13 }}>
                  目标 {goal ? fmt(goal.goal) : "未设置"} · 进度 {(goal?.progress_pct ?? 0).toFixed(1)}% · 预测 {goal ? fmt(goal.forecast) : "—"}
                </Text>
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card title="今日 vs 昨日" style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}>
                <div style={{ fontSize: 14, lineHeight: 2 }}>
                  <Text style={{ color: "#fff" }}>销售额：{fmt(report?.today.sales ?? 0)}</Text>
                  <Text style={{ marginLeft: 8, color: "rgba(255,255,255,0.6)" }}>昨日 {fmt(report?.yesterday.sales ?? 0)}</Text>
                </div>
                <div style={{ fontSize: 14, lineHeight: 2 }}>
                  <Text style={{ color: "#fff" }}>访客：{report?.today.visitors ?? 0}</Text>
                  <Text style={{ marginLeft: 8, color: "rgba(255,255,255,0.6)" }}>昨日 {report?.yesterday.visitors ?? 0}</Text>
                </div>
                <div style={{ fontSize: 14, lineHeight: 2 }}>
                  <Text style={{ color: "#fff" }}>订单：{report?.today.orders ?? 0}</Text>
                  <Text style={{ marginLeft: 8, color: "rgba(255,255,255,0.6)" }}>昨日 {report?.yesterday.orders ?? 0}</Text>
                </div>
              </Card>
            </Col>
            <Col xs={24} md={8}>
              <Card title="本周累计" style={{ background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 14 }}>
                <div style={{ fontSize: 16, lineHeight: 2 }}>
                  <Text style={{ color: "#60a5fa" }}>销售额：{fmt(summary?.week.sales ?? 0)}</Text>
                </div>
                <div style={{ fontSize: 16, lineHeight: 2 }}>
                  <Text style={{ color: "#34d399" }}>访客：{summary?.week.visitors ?? 0}</Text>
                </div>
                <div style={{ fontSize: 16, lineHeight: 2 }}>
                  <Text style={{ color: "#fbbf24" }}>订单：{summary?.week.orders ?? 0}</Text>
                </div>
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}
