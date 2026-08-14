import { DeleteOutlined, EditOutlined, GiftOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  DatePicker,
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
import type { Gift, GiftReviewStatus, GiftSettleStatus, Store } from "../types";

const { Text } = Typography;

type GiftFormValues = {
  order_no: string;
  store_id: number;
  keyword: string;
  spec: string;
  price: number;
  commission: number;
  wangwang: string;
  order_time: dayjs.Dayjs;
  review_status: GiftReviewStatus;
  settle_status: GiftSettleStatus;
};

const REVIEW_META: Record<GiftReviewStatus, { label: string; color: string }> = {
  none: { label: "未评论", color: "orange" },
  reviewed: { label: "已评论", color: "green" },
};

const SETTLE_META: Record<GiftSettleStatus, { label: string; color: string }> = {
  unsettled: { label: "未结款", color: "orange" },
  settled: { label: "已结款", color: "green" },
};

const REVIEW_OPTIONS = (Object.entries(REVIEW_META) as [GiftReviewStatus, { label: string }][]).map(([value, meta]) => ({
  value,
  label: meta.label,
}));
const SETTLE_OPTIONS = (Object.entries(SETTLE_META) as [GiftSettleStatus, { label: string }][]).map(([value, meta]) => ({
  value,
  label: meta.label,
}));

export function GiftsPage() {
  const [items, setItems] = useState<Gift[]>([]);
  const [stores, setStores] = useState<Store[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [storeFilter, setStoreFilter] = useState<number | undefined>();
  const [reviewFilter, setReviewFilter] = useState<GiftReviewStatus | undefined>();
  const [settleFilter, setSettleFilter] = useState<GiftSettleStatus | undefined>();
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

  useEffect(() => {
    http
      .get<{ items: Store[] }>("/stores")
      .then(({ data }) => setStores(data.items))
      .catch(() => {});
  }, []);

  const storeOptions = useMemo(() => {
    const list = stores.map((store) => ({ value: store.id, label: store.name }));
    return [{ value: 0, label: "未关联店铺" }, ...list];
  }, [stores]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return items.filter((item) => {
      if (storeFilter !== undefined && item.store_id !== storeFilter) return false;
      if (reviewFilter && item.review_status !== reviewFilter) return false;
      if (settleFilter && item.settle_status !== settleFilter) return false;
      if (!kw) return true;
      return (
        item.order_no.toLowerCase().includes(kw) ||
        item.wangwang.toLowerCase().includes(kw) ||
        item.keyword.toLowerCase().includes(kw) ||
        item.spec.toLowerCase().includes(kw)
      );
    });
  }, [items, keyword, storeFilter, reviewFilter, settleFilter]);

  const resetFilters = () => {
    setKeyword("");
    setStoreFilter(undefined);
    setReviewFilter(undefined);
    setSettleFilter(undefined);
  };

  const toggleReview = async (row: Gift) => {
    const next: GiftReviewStatus = row.review_status === "reviewed" ? "none" : "reviewed";
    try {
      await http.post(`/gifts/${row.id}/review`, { status: next });
      message.success(`「${row.order_no}」已标记为「${REVIEW_META[next].label}」`);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const toggleSettle = async (row: Gift) => {
    const next: GiftSettleStatus = row.settle_status === "settled" ? "unsettled" : "settled";
    try {
      await http.post(`/gifts/${row.id}/settle`, { status: next });
      message.success(`「${row.order_no}」已标记为「${SETTLE_META[next].label}」`);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const submitGift = async (values: GiftFormValues) => {
    setSaving(true);
    try {
      const payload = {
        order_no: values.order_no?.trim() ?? "",
        store_id: values.store_id ?? 0,
        keyword: values.keyword?.trim() ?? "",
        spec: values.spec?.trim() ?? "",
        price: values.price ?? 0,
        commission: values.commission ?? 0,
        wangwang: values.wangwang?.trim() ?? "",
        order_time: values.order_time ? values.order_time.format("YYYY-MM-DD HH:mm:ss") : "",
        review_status: values.review_status ?? "none",
        settle_status: values.settle_status ?? "unsettled",
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
      store_id: row.store_id,
      keyword: row.keyword,
      spec: row.spec,
      price: row.price,
      commission: row.commission,
      wangwang: row.wangwang,
      order_time: row.order_time ? dayjs(row.order_time) : undefined,
      review_status: row.review_status,
      settle_status: row.settle_status,
    });
    setCreateOpen(true);
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
  const unreviewed = filtered.filter((item) => item.review_status === "none").length;
  const unsettled = filtered.filter((item) => item.settle_status === "unsettled").length;

  const columns: TableColumnsType<Gift> = [
    {
      title: "日期",
      key: "date",
      width: 110,
      render: (_, row) => (row.order_time ? dayjs(row.order_time).format("YYYY-MM-DD") : "-"),
    },
    {
      title: "下单时间",
      key: "order_time",
      width: 150,
      render: (_, row) => (row.order_time ? dayjs(row.order_time).format("YYYY-MM-DD HH:mm") : "-"),
    },
    {
      title: "店铺",
      dataIndex: "store_name",
      filters: storeOptions.map((option) => ({ text: option.label, value: option.value })),
      onFilter: (value, row) => row.store_id === value,
      render: (value: string) => (value === "未关联店铺" ? <Text type="secondary">未关联店铺</Text> : value),
    },
    { title: "关键词", dataIndex: "keyword", render: (value: string) => value || "-" },
    { title: "规格", dataIndex: "spec", render: (value: string) => value || "-" },
    { title: "金额", dataIndex: "price", width: 100, render: (value: number) => `¥${Number(value).toFixed(2)}` },
    { title: "佣金", dataIndex: "commission", width: 100, render: (value: number) => `¥${Number(value).toFixed(2)}` },
    { title: "旺旺号", dataIndex: "wangwang", render: (value: string) => value || "-" },
    { title: "订单编号", dataIndex: "order_no", width: 150, render: (value: string) => <Text code>{value}</Text> },
    {
      title: "评论状态",
      dataIndex: "review_status",
      width: 100,
      render: (_, row) => (
        <Tag color={REVIEW_META[row.review_status].color} style={{ cursor: "pointer" }} onClick={() => toggleReview(row)}>
          {REVIEW_META[row.review_status].label}
        </Tag>
      ),
    },
    {
      title: "结款状态",
      dataIndex: "settle_status",
      width: 100,
      render: (_, row) => (
        <Tag color={SETTLE_META[row.settle_status].color} style={{ cursor: "pointer" }} onClick={() => toggleSettle(row)}>
          {SETTLE_META[row.settle_status].label}
        </Tag>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 130,
      render: (_, row) => (
        <Space size={4} wrap>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
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
        eyebrow="礼品单台账"
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
            placeholder="搜索订单编号 / 旺旺号 / 关键词 / 规格"
            allowClear
            style={{ width: 260 }}
          />
          <Select
            value={storeFilter}
            onChange={setStoreFilter}
            placeholder="按店铺筛选"
            allowClear
            options={storeOptions}
            style={{ width: 180 }}
          />
          <Select
            value={reviewFilter}
            onChange={setReviewFilter}
            placeholder="评论状态"
            allowClear
            options={REVIEW_OPTIONS}
            style={{ width: 120 }}
          />
          <Select
            value={settleFilter}
            onChange={setSettleFilter}
            placeholder="结款状态"
            allowClear
            options={SETTLE_OPTIONS}
            style={{ width: 120 }}
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
            <Text type="secondary" style={{ fontSize: 12 }}>未评论</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: "#fa8c16" }}>{unreviewed}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>未结款</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: "#1677ff" }}>{unsettled}</div>
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
          scroll={{ x: 1400 }}
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
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={submitGift} style={{ marginTop: 8 }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="order_time" label="下单时间">
                <DatePicker showTime style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="store_id" label="店铺" initialValue={0}>
                <Select options={storeOptions} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="keyword" label="关键词">
                <Input placeholder="如：礼品 女装" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="spec" label="规格">
                <Input placeholder="如：S 码 / 红色" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="price" label="金额（元）" initialValue={0}>
                <InputNumber min={0} step={1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="commission" label="佣金（元）" initialValue={0}>
                <InputNumber min={0} step={1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="wangwang" label="旺旺号">
            <Input placeholder="买家旺旺号" />
          </Form.Item>
          <Form.Item name="order_no" label="订单编号" extra="留空自动生成">
            <Input placeholder="如：淘宝订单号，留空自动生成" maxLength={40} />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="review_status" label="评论状态" initialValue="none">
                <Select options={REVIEW_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="settle_status" label="结款状态" initialValue="unsettled">
                <Select options={SETTLE_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
