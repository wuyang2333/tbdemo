import { Modal, Table, Tag } from "antd";
import type { TableColumnsType } from "antd";
import { useEffect, useState } from "react";

import http from "../../lib/api";
import type { StoreCompareItem } from "../../types";

export function StoreCompareModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<StoreCompareItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    http
      .get<{ items: StoreCompareItem[] }>("/stores/compare")
      .then((response) => {
        if (!cancelled) setItems(response.data.items);
      })
      .catch(() => {
        if (!cancelled) setItems([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const maxSales = Math.max(...items.map((item) => item.sales), 1);

  const columns: TableColumnsType<StoreCompareItem> = [
    {
      title: "店铺",
      dataIndex: "name",
      render: (_, row) => (
        <span>
          {row.name}{" "}
          {row.display_status !== "active" && (
            <Tag color={row.display_status === "stopped" ? "default" : "orange"}>
              {row.display_status === "stopped" ? "停用" : "异常"}
            </Tag>
          )}
        </span>
      ),
    },
    {
      title: "今日销售额",
      dataIndex: "sales",
      render: (value: number) => (
        <div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>
            ¥{value.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}
          </div>
          <div
            style={{
              height: 6,
              width: 160,
              maxWidth: "100%",
              background: "rgba(128,128,128,0.15)",
              borderRadius: 3,
              marginTop: 4,
            }}
          >
            <div
              style={{
                height: 6,
                width: `${Math.min((value / maxSales) * 100, 100)}%`,
                background: "linear-gradient(90deg, #ff5000, #ff7a3d)",
                borderRadius: 3,
              }}
            />
          </div>
        </div>
      ),
    },
    { title: "订单", dataIndex: "orders" },
    { title: "访客", dataIndex: "visitors" },
    {
      title: "退款率",
      dataIndex: "refund_rate",
      render: (value: number) => (
        <span style={{ color: value > 8 ? "#ff4d4f" : undefined }}>{value}%</span>
      ),
    },
  ];

  return (
    <Modal title="多店对比（今日）" open={open} onCancel={onClose} footer={null} width={760}>
      <Table<StoreCompareItem>
        rowKey="store_id"
        size="small"
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={false}
        scroll={{ x: 640 }}
      />
    </Modal>
  );
}
