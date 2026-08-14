import { DeleteOutlined, EditOutlined, GiftOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { Gift, GiftStatus } from "../types";

const { Text } = Typography;

type GiftFormValues = {
  order_no: string;
  recipient: string;
  gift_name: string;
  quantity: number;
  price: number;
};

const STATUS_META: Record<GiftStatus, { label: string; color: string }> = {
  pending: { label: "待发货", color: "orange" },
  shipped: { label: "已发货", color: "blue" },
  delivered: { label: "已完成", color: "green" },
  refunded: { label: "已退款", color: "default" },
};

export function GiftsPage() {
  const [items, setItems] = useState<Gift[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<GiftStatus | undefined>();
  const [storeFilter, setStoreFilter] = useState<string | undefined>();
  const [form] = Form.useForm<GiftFormValues>();
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Gift | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: Gift[] }>("/gifts");
      setItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const storeOptions = useMemo(() => {
    const names = Array.from(new Set(items.map((item) => item.store_name))).sort();
    return names.map((name) => ({ value: name, text: name, label: name }));
  }, [items]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return items.filter((item) => {
      if (statusFilter && item.status !== statusFilter) return false;
      if (storeFilter && item.store_name !== storeFilter) return false;
      if (!kw) return true;
      return (
        item.order_no.toLowerCase().includes(kw) ||
        item.recipient.toLowerCase().includes(kw) ||
        item.gift_name.toLowerCase().includes(kw)
      );
    });
  }, [items, keyword, statusFilter, storeFilter]);

  const resetFilters = () => {
    setKeyword("");
    setStatusFilter(undefined);
    setStoreFilter(undefined);
  };

  const submitGift = async (values: GiftFormValues) => {
    setSaving(true);
    try {
      const payload = {
        order_no: values.order_no?.trim() ?? "",
        recipient: values.recipient.trim(),
        gift_name: values.gift_name.trim(),
        quantity: values.quantity,
        price: values.price,
      };
      if (editing) {
        await http.put(`/gifts/${editing.id}`, payload);
        message.success(`「${editing.order_no}」已更新`);
      } else {
        await http.post("/gifts", payload);
        message.success("礼品单已创建");
      }
      setCreateOpen(false);
      setEditing(null);
      form.resetFields();
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const openEdit = (row: Gift) => {
    setEditing(row);
    form.setFieldsValue({
      order_no: row.order_no,
      recipient: row.recipient,
      gift_name: row.gift_name,
      quantity: row.quantity,
      price: row.price,
    });
    setCreateOpen(true);
  };

  const changeStatus = async (row: Gift, status: GiftStatus, label: string) => {
    try {
      await http.post(`/gifts/${row.id}/status`, { status });
      message.success(`「${row.order_no}」已${label}`);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const removeGift = async (row: Gift) => {
    try {
      await http.delete(`/gifts/${row.id}`);
      message.success("礼品单已删除");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const total = filtered.length;
  const pending = filtered.filter((item) => item.status === "pending").length;
  const shipped = filtered.filter((item) => item.status === "shipped").length;

  const statusFilters = Object.entries(STATUS_META).map(([value, meta]) => ({
    value,
    text: meta.label,
  }));

  const columns: TableColumnsType<Gift> = [
    { title: "单号", dataIndex: "order_no", render: (value: string) => <Text code>{value}</Text> },
    { title: "收礼人", dataIndex: "recipient" },
    { title: "礼品", dataIndex: "gift_name" },
    { title: "数量", dataIndex: "quantity" },
    {
      title: "单价",
      dataIndex: "price",
      render: (value: number) => `¥${value.toFixed(2)}`,
    },
    {
      title: "金额",
      key: "amount",
      render: (_, row) => <Text strong>¥{(row.quantity * row.price).toFixed(2)}</Text>,
    },
    {
      title: "店铺",
      dataIndex: "store_name",
      filters: storeOptions,
      onFilter: (value, row) => row.store_name === value,
      render: (value: string) => (value === "未关联店铺" ? <Text type="secondary">未关联店铺</Text> : value),
    },
    {
      title: "状态",
      dataIndex: "status",
      filters: statusFilters,
      onFilter: (value, row) => row.status === value,
      render: (status: GiftStatus) => (
        <Tag color={STATUS_META[status].color}>{STATUS_META[status].label}</Tag>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm"),
    },
    {
      title: "操作",
      key: "actions",
      width: 220,
      render: (_, row) => (
        <Space size={4} wrap>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
          {row.status === "pending" && (
            <Button size="small" type="primary" ghost onClick={() => changeStatus(row, "shipped", "发货")}>
              发货
            </Button>
          )}
          {row.status === "shipped" && (
            <Button size="small" type="primary" ghost onClick={() => changeStatus(row, "delivered", "完成")}>
              完成
            </Button>
          )}
          {(row.status === "pending" || row.status === "shipped") && (
            <Button size="small" onClick={() => changeStatus(row, "refunded", "退款")}>
              退款
            </Button>
          )}
          <Popconfirm
            title={`删除礼品单 ${row.order_no}？删除后不可恢复`}
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={() => removeGift(row)}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        icon={<GiftOutlined />}
        eyebrow="礼品单"
        title="礼品单"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              setEditing(null);
              setCreateOpen(true);
            }}
          >
            新增礼品单
          </Button>
        }
      />

      <Card variant="borderless" style={{ marginBottom: 16 }} styles={{ body: { padding: "12px 20px" } }}>
        <Space size={12} wrap>
          <Input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            prefix={<SearchOutlined style={{ color: "var(--ops-text-secondary)" }} />}
            placeholder="搜索单号 / 收礼人 / 礼品"
            allowClear
            style={{ width: 240 }}
          />
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            placeholder="按状态筛选"
            allowClear
            options={statusFilters}
            style={{ width: 150 }}
          />
          <Select
            value={storeFilter}
            onChange={setStoreFilter}
            placeholder="按店铺筛选"
            allowClear
            options={storeOptions}
            style={{ width: 180 }}
          />
          <Button icon={<ReloadOutlined />} onClick={resetFilters}>
            重置
          </Button>
        </Space>
      </Card>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>礼品单总数</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2 }}>{total}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>待发货</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: "#fa8c16" }}>{pending}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>已发货</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: "#1677ff" }}>{shipped}</div>
          </Card>
        </Col>
      </Row>

      <Card variant="borderless">
        <Table<Gift>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={filtered}
          pagination={{ pageSize: 10, showTotal: (count) => `共 ${count} 单` }}
          scroll={{ x: 1100 }}
        />
      </Card>

      <Modal
        title={editing ? `编辑礼品单 ${editing.order_no}` : "新增礼品单"}
        open={createOpen}
        onOk={() => form.submit()}
        onCancel={() => {
          setCreateOpen(false);
          setEditing(null);
        }}
        confirmLoading={saving}
        okText={editing ? "保存" : "创建"}
      >
        <Form form={form} layout="vertical" onFinish={submitGift} style={{ marginTop: 8 }}>
          <Form.Item
            name="order_no"
            label="订单号"
            extra="留空自动生成"
          >
            <Input placeholder="如：淘宝订单号，留空自动生成" maxLength={40} />
          </Form.Item>
          <Form.Item
            name="recipient"
            label="收礼人"
            rules={[{ required: true, message: "请输入收礼人" }]}
          >
            <Input placeholder="收礼人姓名" />
          </Form.Item>
          <Form.Item
            name="gift_name"
            label="礼品名称"
            rules={[{ required: true, message: "请输入礼品名称" }]}
          >
            <Input placeholder="如：中秋伴手礼盒" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="quantity"
                label="数量"
                initialValue={1}
                rules={[{ required: true, message: "请输入数量" }]}
              >
                <InputNumber min={1} max={999} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="price"
                label="单价（元）"
                initialValue={0}
                rules={[{ required: true, message: "请输入单价" }]}
              >
                <InputNumber min={0} step={1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
