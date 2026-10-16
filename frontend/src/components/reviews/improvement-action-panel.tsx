import { EditOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, DatePicker, Empty, Form, Input, InputNumber, Modal, Row, Select, Skeleton, Space, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

import http, { getApiErrorMessage } from "../../lib/api";

const { Text } = Typography;

export type ImprovementActionStatus = "pending" | "diagnosed" | "implemented" | "observing" | "improved" | "ignored";

export type ImprovementAction = {
  id: number;
  store_id: number;
  item_id: string;
  item_title: string;
  topic: string;
  title: string;
  description: string;
  owner: string;
  plan: string;
  status: ImprovementActionStatus;
  started_at: string | null;
  due_at: string | null;
  before_negative_rate: number | null;
  after_negative_rate: number | null;
  note: string;
  created_at: string;
  updated_at: string;
};

export type ImprovementActionListResponse = {
  items: ImprovementAction[];
  total: number;
};

export type ImprovementActionPanelProps = {
  storeId?: number | null;
  itemId?: string;
  itemTitle?: string;
  topic?: string;
  onChanged?: () => void;
};

type ActionFormValues = {
  item_id?: string;
  item_title?: string;
  topic?: string;
  title: string;
  description?: string;
  owner?: string;
  plan?: string;
  status: ImprovementActionStatus;
  started_at?: Dayjs | null;
  due_at?: Dayjs | null;
  before_negative_rate?: number | null;
  after_negative_rate?: number | null;
  note?: string;
};

type ImprovementActionPayload = {
  store_id: number;
  item_id: string;
  item_title: string;
  topic: string;
  title: string;
  description: string;
  owner: string;
  plan: string;
  status: ImprovementActionStatus;
  started_at: string | null;
  due_at: string | null;
  before_negative_rate: number | null;
  after_negative_rate: number | null;
  note: string;
};

const statusMeta: Record<ImprovementActionStatus, { label: string; color: string }> = {
  pending: { label: "待确认", color: "orange" },
  diagnosed: { label: "已定位原因", color: "blue" },
  implemented: { label: "已采取措施", color: "cyan" },
  observing: { label: "观察中", color: "gold" },
  improved: { label: "已改善", color: "green" },
  ignored: { label: "无需处理", color: "default" },
};

const statusOptions = Object.entries(statusMeta).map(([value, meta]) => ({ value, label: meta.label }));

function rateText(value: number | null): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

function dateText(value: string | null): string {
  return value ? dayjs(value).format("YYYY-MM-DD") : "—";
}

function toPayload(values: ActionFormValues, storeId: number): ImprovementActionPayload {
  return {
    store_id: storeId,
    item_id: values.item_id?.trim() ?? "",
    item_title: values.item_title?.trim() ?? "",
    topic: values.topic?.trim() ?? "",
    title: values.title.trim(),
    description: values.description?.trim() ?? "",
    owner: values.owner?.trim() ?? "",
    plan: values.plan?.trim() ?? "",
    status: values.status,
    started_at: values.started_at ? values.started_at.format("YYYY-MM-DD") : null,
    due_at: values.due_at ? values.due_at.format("YYYY-MM-DD") : null,
    before_negative_rate: values.before_negative_rate ?? null,
    after_negative_rate: values.after_negative_rate ?? null,
    note: values.note?.trim() ?? "",
  };
}

export function ImprovementActionPanel({ storeId, itemId, itemTitle, topic, onChanged }: ImprovementActionPanelProps) {
  const [form] = Form.useForm<ActionFormValues>();
  const [items, setItems] = useState<ImprovementAction[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ImprovementAction | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await http.get<ImprovementActionListResponse>("/customers/reviews/improvement-actions", {
        params: {
          ...(storeId == null ? {} : { store_id: storeId }),
          ...(itemId?.trim() ? { item_id: itemId.trim() } : {}),
        },
      });
      setItems(response.data.items ?? []);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }, [itemId, storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    if (storeId == null) return;
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      item_id: itemId ?? "",
      item_title: itemTitle ?? "",
      topic: topic ?? "",
      status: "pending",
    });
    setModalOpen(true);
  };

  const openEdit = (item: ImprovementAction) => {
    setEditing(item);
    form.setFieldsValue({
      item_id: item.item_id,
      item_title: item.item_title,
      topic: item.topic,
      title: item.title,
      description: item.description,
      owner: item.owner,
      plan: item.plan,
      status: item.status,
      started_at: item.started_at ? dayjs(item.started_at) : null,
      due_at: item.due_at ? dayjs(item.due_at) : null,
      before_negative_rate: item.before_negative_rate,
      after_negative_rate: item.after_negative_rate,
      note: item.note,
    });
    setModalOpen(true);
  };

  const closeModal = () => {
    if (!saving) {
      setModalOpen(false);
      setEditing(null);
      form.resetFields();
    }
  };

  const submit = async (values: ActionFormValues) => {
    const targetStoreId = editing?.store_id ?? storeId;
    if (targetStoreId == null) {
      message.error("请先选择店铺后再创建改进事项");
      return;
    }
    setSaving(true);
    try {
      const payload = toPayload(values, targetStoreId);
      if (editing) {
        await http.put<{ item: ImprovementAction }>(`/customers/reviews/improvement-actions/${editing.id}`, payload);
        message.success("改进事项已更新");
      } else {
        await http.post<{ item: ImprovementAction }>("/customers/reviews/improvement-actions", payload);
        message.success("改进事项已创建");
      }
      closeModal();
      await load();
      onChanged?.();
    } catch (requestError) {
      message.error(getApiErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const columns = useMemo<TableColumnsType<ImprovementAction>>(() => [
    {
      title: "改进事项",
      key: "title",
      width: 250,
      render: (_value, item) => (
        <Space direction="vertical" size={2} style={{ maxWidth: 240 }}>
          <Text strong ellipsis={{ tooltip: item.title }}>{item.title}</Text>
          <Text type="secondary" ellipsis={{ tooltip: item.description }}>{item.description || "暂无描述"}</Text>
        </Space>
      ),
    },
    {
      title: "商品 / 主题",
      key: "product",
      width: 220,
      render: (_value, item) => (
        <Space direction="vertical" size={2} style={{ maxWidth: 210 }}>
          <Text ellipsis={{ tooltip: item.item_title || item.item_id }}>{item.item_title || item.item_id || "未指定商品"}</Text>
          {item.topic ? <Tag>{item.topic}</Tag> : <Text type="secondary">未指定主题</Text>}
        </Space>
      ),
    },
    { title: "状态", dataIndex: "status", key: "status", width: 108, render: (value: ImprovementActionStatus) => <Tag color={statusMeta[value]?.color ?? "default"}>{statusMeta[value]?.label ?? value}</Tag> },
    { title: "负责人", dataIndex: "owner", key: "owner", width: 100, render: (value: string) => value || <Text type="secondary">未指定</Text> },
    { title: "时间", key: "dates", width: 170, render: (_value, item) => <Text type="secondary">{dateText(item.started_at)} 至 {dateText(item.due_at)}</Text> },
    { title: "差评率", key: "rates", width: 120, render: (_value, item) => <Text>{rateText(item.before_negative_rate)} → {rateText(item.after_negative_rate)}</Text> },
    { title: "操作", key: "action", fixed: "right", width: 84, render: (_value, item) => <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(item)} aria-label={`编辑改进事项：${item.title}`}>编辑</Button> },
  ], []);

  const formContent = (
    <Form form={form} layout="vertical" onFinish={submit} preserve={false} aria-label="改进事项表单">
      <Row gutter={12}>
        <Col xs={24} md={12}>
          <Form.Item name="item_title" label="商品名称">
            <Input aria-label="商品名称" placeholder="例如：商品 A" maxLength={300} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="item_id" label="商品 ID">
            <Input aria-label="商品 ID" placeholder="可填写商品 ID" maxLength={120} />
          </Form.Item>
        </Col>
      </Row>
      <Row gutter={12}>
        <Col xs={24} md={12}>
          <Form.Item name="topic" label="问题主题">
            <Input aria-label="问题主题" placeholder="例如：包装破损、物流" maxLength={80} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="status" label="状态" rules={[{ required: true, message: "请选择状态" }]}>
            <Select aria-label="改进事项状态" options={statusOptions} />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="title" label="事项标题" rules={[{ required: true, message: "请输入事项标题" }]}>
        <Input aria-label="事项标题" placeholder="例如：优化外箱防护" maxLength={200} />
      </Form.Item>
      <Form.Item name="description" label="问题描述">
        <Input.TextArea aria-label="问题描述" rows={3} maxLength={2000} showCount placeholder="描述反馈现象、影响范围或待确认原因" />
      </Form.Item>
      <Row gutter={12}>
        <Col xs={24} md={12}>
          <Form.Item name="owner" label="负责人">
            <Input aria-label="改进事项负责人" placeholder="例如：运营、仓库负责人" maxLength={80} />
          </Form.Item>
        </Col>
        <Col xs={24} md={12}>
          <Form.Item name="started_at" label="开始日期">
            <DatePicker aria-label="改进事项开始日期" style={{ width: "100%" }} placeholder="选择开始日期" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="plan" label="改进方案">
        <Input.TextArea aria-label="改进方案" rows={3} maxLength={2000} showCount placeholder="填写要采取的措施和观察方式" />
      </Form.Item>
      <Row gutter={12}>
        <Col xs={24} md={8}>
          <Form.Item name="due_at" label="截止日期">
            <DatePicker aria-label="改进事项截止日期" style={{ width: "100%" }} placeholder="选择截止日期" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="before_negative_rate" label="改进前差评率">
            <InputNumber aria-label="改进前差评率" min={0} max={100} precision={1} suffix="%" style={{ width: "100%" }} placeholder="可选" />
          </Form.Item>
        </Col>
        <Col xs={24} md={8}>
          <Form.Item name="after_negative_rate" label="改进后差评率">
            <InputNumber aria-label="改进后差评率" min={0} max={100} precision={1} suffix="%" style={{ width: "100%" }} placeholder="观察后填写" />
          </Form.Item>
        </Col>
      </Row>
      <Form.Item name="note" label="备注">
        <Input.TextArea aria-label="改进事项备注" rows={3} maxLength={2000} showCount placeholder="补充复盘结论或关联信息" />
      </Form.Item>
    </Form>
  );

  return (
    <Card
      title={<Space><span>改进事项</span><Text type="secondary" style={{ fontSize: 13 }}>跟踪问题处理和改进效果</Text></Space>}
      extra={<Space><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()} aria-label="刷新改进事项">刷新</Button><Button type="primary" icon={<PlusOutlined />} disabled={storeId == null} onClick={openCreate} aria-label="新建改进事项">新建事项</Button></Space>}
      style={{ borderColor: "var(--ops-border)", background: "var(--ops-panel)" }}
    >
      {storeId == null ? <Alert type="info" showIcon message="当前为跨店铺查看" description="改进事项需要绑定具体店铺；选择店铺后即可新建，现有事项仍可编辑。" style={{ marginBottom: 16 }} /> : null}
      {error ? <Alert type="error" showIcon message="改进事项加载失败" description={error} action={<Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>重试</Button>} style={{ marginBottom: 16 }} /> : null}
      {loading && !items.length ? <Skeleton active paragraph={{ rows: 5 }} /> : items.length ? <Table<ImprovementAction> rowKey="id" size="small" dataSource={items} columns={columns} pagination={{ pageSize: 8, showSizeChanger: false, showTotal: (total) => `共 ${total} 条` }} scroll={{ x: 980 }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无改进事项"><Text type="secondary">从商品问题卡片创建一条改进事项，开始跟踪处理结果。</Text></Empty>}

      <Modal title={editing ? `编辑改进事项 · ${editing.title}` : "新建改进事项"} open={modalOpen} onCancel={closeModal} footer={<Space><Button onClick={closeModal} disabled={saving}>取消</Button><Button type="primary" onClick={() => form.submit()} loading={saving}>{editing ? "保存修改" : "创建事项"}</Button></Space>} width={780} destroyOnHidden>
        {formContent}
      </Modal>
    </Card>
  );
}

export default ImprovementActionPanel;
