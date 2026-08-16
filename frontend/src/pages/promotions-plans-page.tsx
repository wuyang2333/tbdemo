import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Select, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { PlanNoteCell, PlanTagCell, SCENE_OPTIONS, fmtInt, fmtMoney } from "../components/promotions/promotions-ui";
import type { PromoPlan } from "../types";

const { Text } = Typography;

export function PromotionsPlansPage() {
  const [plans, setPlans] = useState<PromoPlan[]>([]);
  const [scene, setScene] = useState("");
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async (sc: string) => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: PromoPlan[] }>(`/promotions/plans?scene=${encodeURIComponent(sc)}`);
      setPlans(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setPlans([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(scene);
  }, [scene, load]);

  const sync = async () => {
    setSyncing(true);
    try {
      const { data } = await http.post<{ ok: number; total: number; results: { store_name: string; ok: boolean; error?: string }[] }>("/promotions/sync-plans");
      message.success(`计划同步完成：成功 ${data.ok} / 共 ${data.total} 家`);
      data.results.filter((r) => !r.ok).slice(0, 3).forEach((r) => message.warning(`${r.store_name}：${r.error || "同步失败"}`));
      await load(scene);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncing(false);
    }
  };

  const columns: TableColumnsType<PromoPlan> = [
    { title: "场景", dataIndex: "scene_name", width: 120 },
    { title: "计划名", dataIndex: "plan_name", width: 200, ellipsis: true },
    { title: "状态", dataIndex: "status", width: 80, render: (status: string) => (status === "在投" ? <Tag color="green">在投</Tag> : <Tag>暂停</Tag>) },
    { title: "日预算", dataIndex: "day_budget", align: "right", width: 90, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "出价", key: "bid", width: 110, render: (_, row) => (row.bid_value ? `${row.bid_value}${row.bid_type === "roi" ? " ROI" : ""}` : row.bid_type || "—") },
    { title: "花费", dataIndex: "spend", align: "right", width: 110, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "成交", dataIndex: "sales", align: "right", width: 120, render: (v: number) => (v ? fmtMoney(v) : "—") },
    { title: "ROI", dataIndex: "roi", align: "right", width: 80, render: (v: number) => (v ? v.toFixed(2) : "—") },
    { title: "点击", dataIndex: "clicks", align: "right", width: 90, render: (v: number) => (v ? fmtInt(v) : "—") },
    { title: "标记", key: "tag", width: 130, render: (_, row) => <PlanTagCell plan={row} onSaved={() => load(scene)} /> },
    { title: "备注", key: "note", width: 200, render: (_, row) => <PlanNoteCell plan={row} onSaved={() => load(scene)} /> },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="推广管理"
        title="推广计划"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => load(scene)}>
              刷新
            </Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={sync}>
              同步推广计划
            </Button>
          </Space>
        }
      />

      <Space style={{ marginBottom: 12 }}>
        <Select style={{ width: 150 }} value={scene} onChange={setScene} options={SCENE_OPTIONS} />
        <Text type="secondary" style={{ fontSize: 12 }}>共 {plans.length} 个计划（数据来自万相台）</Text>
      </Space>

      {loading && plans.length === 0 ? (
        <div style={{ textAlign: "center", padding: 60 }}>
          <Spin />
        </div>
      ) : plans.length === 0 ? (
        <Card variant="borderless">
          <Empty description="暂无推广计划，点「同步推广计划」从万相台抓取" />
        </Card>
      ) : (
        <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
          <Table<PromoPlan>
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={plans}
            pagination={{ pageSize: 20, showTotal: (c) => `共 ${c} 个计划` }}
            scroll={{ x: 1250 }}
          />
        </Card>
      )}
    </div>
  );
}
