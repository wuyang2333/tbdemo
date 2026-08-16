import { BarChartOutlined, ReloadOutlined, SyncOutlined } from "@ant-design/icons";
import { Button, Card, Empty, InputNumber, Modal, Space, Spin, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import { ChangeBadge, StoreScopeSelect, useSyncStores } from "../components/analytics/analytics-ui";
import type { AnalyticsAlert, AnalyticsAlertsConfig } from "../types";

const { Text } = Typography;

export function AnalyticsAlertsPage() {
  const [alerts, setAlerts] = useState<AnalyticsAlert[]>([]);
  const [baselineDays, setBaselineDays] = useState(7);
  const [loading, setLoading] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(undefined);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: AnalyticsAlert[]; baseline_days: number }>(`/analytics/alerts${storeId ? `?store_id=${storeId}` : ""}`);
      setAlerts(data.items);
      setBaselineDays(data.baseline_days);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setAlerts([]);
    } finally {
      setLoading(false);
    }
  }, [storeId]);

  useEffect(() => {
    load();
  }, [load]);

  const { syncing, syncAll } = useSyncStores(load);

  const [configOpen, setConfigOpen] = useState(false);
  const [config, setConfig] = useState<AnalyticsAlertsConfig | null>(null);
  const [savingConfig, setSavingConfig] = useState(false);

  const loadConfig = async () => {
    try {
      const { data } = await http.get<AnalyticsAlertsConfig>("/analytics/alerts/config");
      setConfig(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const openConfig = async () => {
    await loadConfig();
    setConfigOpen(true);
  };

  const saveConfig = async () => {
    if (!config) return;
    setSavingConfig(true);
    try {
      await http.put("/analytics/alerts/config", config);
      message.success("阈值已保存");
      setConfigOpen(false);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSavingConfig(false);
    }
  };

  const setCfg = (key: keyof AnalyticsAlertsConfig, value: number) => {
    setConfig((c) => (c ? { ...c, [key]: value } : c));
  };

  const columns: TableColumnsType<AnalyticsAlert> = [
    { title: "日期", dataIndex: "date_label", width: 90 },
    { title: "店铺", dataIndex: "store_name", width: 160 },
    { title: "指标", dataIndex: "metric", width: 90 },
    { title: "波动", dataIndex: "change_pct", width: 100, align: "right", sorter: (a: AnalyticsAlert, b: AnalyticsAlert) => a.change_pct - b.change_pct, render: (v: number) => <ChangeBadge change={v} /> },
    {
      title: "等级",
      dataIndex: "level",
      width: 80,
      render: (level: AnalyticsAlert["level"]) =>
        level === "error" ? <Tag color="red">严重</Tag> : level === "warn" ? <Tag color="orange">提醒</Tag> : <Tag>信息</Tag>,
    },
    { title: "说明", dataIndex: "message" },
  ];

  return (
    <div>
      <PageHeader
        icon={<BarChartOutlined />}
        eyebrow="数据洞察"
        title="异常提醒"
        extra={
          <Space>
            <StoreScopeSelect value={storeId} onChange={setStoreId} />
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
            <Button onClick={openConfig}>阈值设置</Button>
            <Button type="primary" icon={<SyncOutlined />} loading={syncing} onClick={syncAll}>
              同步店铺数据
            </Button>
          </Space>
        }
      />

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 12 }}>
          检测规则：按店铺对比每天指标与前 {baselineDays} 天均值——销售额下跌超 30%（严重）/上涨超 60%、订单或访客下跌超 30%、转化率下滑超 20% 时提醒。
        </Text>
        {loading && alerts.length === 0 ? (
          <div style={{ textAlign: "center", padding: 40 }}>
            <Spin />
          </div>
        ) : alerts.length === 0 ? (
          <Empty description="目前还没有波动提醒。需要至少积累 3 天数据，系统才会开始自动判断波动。" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />
        ) : (
          <Table<AnalyticsAlert>
            rowKey={(row) => `${row.date}_${row.store_id}_${row.metric}`}
            size="small"
            columns={columns}
            dataSource={alerts}
            pagination={{ pageSize: 10, showTotal: (c) => `共 ${c} 条` }}
            scroll={{ x: 760 }}
          />
        )}
      </Card>

      <Modal
        title="预警阈值设置"
        open={configOpen}
        onCancel={() => setConfigOpen(false)}
        onOk={saveConfig}
        okText="保存"
        confirmLoading={savingConfig}
        destroyOnClose
      >
        {config && (
          <Space direction="vertical" style={{ width: "100%" }} size={14}>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>对比基线天数（前 N 天均值，2-30）</Text>
              <InputNumber min={2} max={30} value={config.baseline_days} onChange={(v) => setCfg("baseline_days", v ?? 7)} style={{ width: "100%" }} />
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>销售额下跌超（%，负数，如 -30）</Text>
              <InputNumber value={config.sales_down} onChange={(v) => setCfg("sales_down", v ?? -30)} style={{ width: "100%" }} />
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>销售额上涨超（% 才提示，如 60）</Text>
              <InputNumber value={config.sales_up} onChange={(v) => setCfg("sales_up", v ?? 60)} style={{ width: "100%" }} />
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>订单下跌超（%）</Text>
              <InputNumber value={config.orders_down} onChange={(v) => setCfg("orders_down", v ?? -30)} style={{ width: "100%" }} />
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>访客下跌超（%）</Text>
              <InputNumber value={config.visitors_down} onChange={(v) => setCfg("visitors_down", v ?? -30)} style={{ width: "100%" }} />
            </div>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>转化率下滑超（%，负数，如 -20）</Text>
              <InputNumber value={config.conversion_down} onChange={(v) => setCfg("conversion_down", v ?? -20)} style={{ width: "100%" }} />
            </div>
          </Space>
        )}
      </Modal>
    </div>
  );
}
