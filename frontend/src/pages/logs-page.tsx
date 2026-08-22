import { HistoryOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Card, Select, Space, Table, Tag, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { OpLog } from "../types";

const MODULE_OPTIONS = [
  { value: "", label: "全部模块" },
  { value: "stores", label: "店铺管理" },
  { value: "products", label: "商品管理" },
  { value: "promotions", label: "推广管理" },
  { value: "system", label: "系统任务" },
  { value: "gifts", label: "礼品单" },
  { value: "accounts", label: "账号管理" },
];

const ACTION_LABELS: Record<string, string> = {
  bind: "绑定店铺",
  edit: "编辑店铺",
  unbind: "解绑店铺",
  refresh_auth: "刷新授权",
  status: "状态变更",
  current: "切换当前店",
  inspect: "巡检",
  perm: "权限设置",
  create: "新增",
  delete: "删除",
  retry_sync: "重试同步",
  sync: "同步数据",
  maintenance_enable: "进入维护模式",
  maintenance_update: "更新维护设置",
  maintenance_resume: "恢复后台任务",
  maintenance_auto_resume: "维护到期自动恢复",
};

export function LogsPage() {
  const [module, setModule] = useState("");
  const [items, setItems] = useState<OpLog[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: OpLog[] }>("/logs", {
        params: { module, limit: 200 },
      });
      setItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [module]);

  useEffect(() => {
    load();
  }, [load]);

  const columns: TableColumnsType<OpLog> = [
    {
      title: "时间",
      dataIndex: "created_at",
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "模块",
      dataIndex: "module",
      render: (value: string) => (
        <Tag>{MODULE_OPTIONS.find((option) => option.value === value)?.label ?? value}</Tag>
      ),
    },
    { title: "操作人", dataIndex: "username" },
    {
      title: "操作",
      dataIndex: "action",
      render: (value: string) => ACTION_LABELS[value] ?? value,
    },
    { title: "对象", dataIndex: "target_name", render: (value: string) => value || "—" },
    { title: "详情", dataIndex: "detail", render: (value: string) => value || "—" },
  ];

  return (
    <div>
      <PageHeader
        icon={<HistoryOutlined />}
        eyebrow="审计中心"
        title="操作日志"
        extra={
          <Space>
            <Select
              value={module}
              onChange={setModule}
              options={MODULE_OPTIONS}
              style={{ width: 160 }}
            />
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新
            </Button>
          </Space>
        }
      />
      <Card variant="borderless">
        <Table<OpLog>
          rowKey="id"
          size="small"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{ defaultPageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (count) => `共 ${count} 条` }}
          scroll={{ x: 900 }}
        />
      </Card>
    </div>
  );
}
