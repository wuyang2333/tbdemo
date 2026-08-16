import { BarChartOutlined, CopyOutlined, DownloadOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Col, Descriptions, Empty, Row, Space, Spin, Statistic, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsReport } from "../types";
import { TOKEN_KEY } from "../lib/api";

const { Text } = Typography;

function fmt(v: number): string {
  return `¥${v.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function AnalyticsReportPage() {
  const [data, setData] = useState<AnalyticsReport | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data: res } = await http.get<AnalyticsReport>("/analytics/report");
      setData(res);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);

  const pct = (cur: number, prev: number): string => {
    if (!prev) return "—";
    const c = ((cur - prev) / prev) * 100;
    return `${c >= 0 ? "+" : ""}${c.toFixed(1)}%`;
  };

  const buildText = (): string => {
    if (!data) return "";
    const t = data.today;
    const y = data.yesterday;
    return [
      `【经营日报 ${data.date}】`,
      `访客 ${t.visitors}（较昨日 ${pct(t.visitors, y.visitors)}）｜销售额 ${fmt(t.sales)}（${pct(t.sales, y.sales)}）｜订单 ${t.orders}（${pct(t.orders, y.orders)}）｜转化率 ${t.conversion_rate.toFixed(2)}%`,
      `推广：今日花费 ${fmt(data.promo_today.spend)}，成交 ${fmt(data.promo_today.sales)}，ROI ${data.promo_today.roi.toFixed(2)}`,
      data.goal ? `${data.month} 目标 ${fmt(data.goal)}，本月已达成 ${fmt(data.month_sales)}` : "",
    ]
      .filter(Boolean)
      .join("\n");
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

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="经营日报"
        extra={
          <Space>
            <Button icon={<CopyOutlined />} onClick={copyReport} disabled={!data}>
              复制日报
            </Button>
            <Button icon={<DownloadOutlined />} onClick={exportExcel}>
              导出 Excel
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步数据
            </Button>
          </Space>
        }
      />

      {loading && !data ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : !data ? (
        <Card variant="borderless">
          <Empty description="暂无数据，先同步店铺与推广数据" />
        </Card>
      ) : (
        <>
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="今日访客" value={data.today.visitors} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.visitors, data.yesterday.visitors)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="今日销售额" value={data.today.sales} precision={2} prefix="¥" suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.sales, data.yesterday.sales)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="今日订单" value={data.today.orders} suffix={<Text type="secondary" style={{ fontSize: 12 }}>{pct(data.today.orders, data.yesterday.orders)}</Text>} /></Card></Col>
            <Col xs={12} sm={6}><Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}><Statistic title="今日转化率" value={data.today.conversion_rate} precision={2} suffix="%" valueStyle={{ color: "#1677ff" }} /></Card></Col>
          </Row>

          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
            <Col xs={24} md={12}>
              <Card variant="borderless" title="今日推广（实时）" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Descriptions size="small" column={3}
                  items={[
                    { key: "s", label: "花费", children: fmt(data.promo_today.spend) },
                    { key: "sa", label: "成交", children: fmt(data.promo_today.sales) },
                    { key: "r", label: "ROI", children: <Tag color={data.promo_today.roi >= 2 ? "green" : "orange"}>{data.promo_today.roi.toFixed(2)}</Tag> },
                  ]}
                />
              </Card>
            </Col>
            <Col xs={24} md={12}>
              <Card variant="borderless" title="昨日推广" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
                <Descriptions size="small" column={3}
                  items={[
                    { key: "s", label: "花费", children: fmt(data.promo_yesterday.spend) },
                    { key: "sa", label: "成交", children: fmt(data.promo_yesterday.sales) },
                    { key: "r", label: "ROI", children: data.promo_yesterday.roi.toFixed(2) },
                  ]}
                />
              </Card>
            </Col>
          </Row>

          <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>月度目标：{data.goal ? `${data.month} 目标 ${fmt(data.goal)}，本月已达成 ${fmt(data.month_sales)}` : "未设置，可到「目标预测」页设置"}</Text>
            <Text style={{ whiteSpace: "pre-line" }}>{buildText()}</Text>
          </Card>
        </>
      )}
    </div>
  );
}
