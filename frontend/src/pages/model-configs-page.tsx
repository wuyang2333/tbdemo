import {
  ApiOutlined,
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  StarFilled,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Select, Slider, Space, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { ModelConfig } from "../types";

const { Text, Paragraph } = Typography;

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "deepseek", label: "DeepSeek（深度求索）" },
  { value: "dashscope", label: "阿里云百炼（通义千问）" },
  { value: "moonshot", label: "Moonshot（月之暗面）" },
  { value: "custom", label: "中转站 / 自定义（OpenAI 兼容）" },
];

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  deepseek: "DeepSeek",
  dashscope: "阿里云百炼",
  moonshot: "Moonshot",
  custom: "自定义",
};

const PROVIDER_DEFAULTS: Record<string, { base_url: string; model: string }> = {
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  deepseek: { base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  dashscope: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  moonshot: { base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  custom: { base_url: "", model: "" },
};

type FormValues = {
  name: string;
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
};

export function ModelConfigsPage() {
  const [items, setItems] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [form] = Form.useForm<FormValues>();
  const providerValue = Form.useWatch("provider", form);
  const [lastProvider, setLastProvider] = useState("openai");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: ModelConfig[] }>("/model-configs");
      setItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    setLastProvider("openai");
    setModalOpen(true);
  };

  const openEdit = (item: ModelConfig) => {
    setEditing(item);
    form.setFieldsValue({
      name: item.name,
      provider: item.provider,
      base_url: item.base_url,
      api_key: "",
      model: item.model,
      temperature: item.temperature,
    });
    setLastProvider(item.provider);
    setModalOpen(true);
  };

  const handleProviderChange = (provider: string) => {
    const defaults = PROVIDER_DEFAULTS[provider];
    if (!defaults) return;
    const current = form.getFieldsValue();
    const prevDefaults = PROVIDER_DEFAULTS[lastProvider] ?? PROVIDER_DEFAULTS.openai;
    const urlIsDefault = !current.base_url || (prevDefaults && current.base_url === prevDefaults.base_url);
    const modelIsDefault = !current.model || (prevDefaults && current.model === prevDefaults.model);
    if (urlIsDefault) form.setFieldValue("base_url", defaults.base_url);
    if (modelIsDefault) form.setFieldValue("model", defaults.model);
    setLastProvider(provider);
  };

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await http.put(`/model-configs/${editing.id}`, values);
        message.success("模型已更新");
      } else {
        await http.post("/model-configs", values);
        message.success("模型已添加");
      }
      setModalOpen(false);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const testModel = async (item: ModelConfig) => {
    setTestingId(item.id);
    try {
      const { data } = await http.post<{ reply: string }>("/model-configs/test", { id: item.id });
      message.success(`「${item.name}」连接成功，模型回复：${data.reply}`);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTestingId(null);
    }
  };

  const setDefault = async (item: ModelConfig) => {
    try {
      await http.post(`/model-configs/${item.id}/default`);
      message.success(`已将「${item.name}」设为默认`);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const remove = async (item: ModelConfig) => {
    try {
      await http.delete(`/model-configs/${item.id}`);
      message.success("模型已删除");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const columns: TableColumnsType<ModelConfig> = [
    {
      title: "名称",
      dataIndex: "name",
      render: (_, record) => (
        <Space size={6}>
          {record.is_default && <StarFilled style={{ color: "#ff5000" }} />}
          <Text strong>{record.name}</Text>
          {record.is_default && <Tag color="orange" style={{ marginInlineEnd: 0 }}>默认</Tag>}
        </Space>
      ),
    },
    {
      title: "服务商",
      dataIndex: "provider",
      render: (value: string) => PROVIDER_LABELS[value] ?? value,
    },
    { title: "模型", dataIndex: "model", render: (value: string) => value || "-" },
    { title: "接口地址", dataIndex: "base_url", ellipsis: true, render: (value: string) => value || "-" },
    {
      title: "状态",
      render: (_, record) =>
        record.configured ? (
          <Tag color="green" style={{ borderRadius: 999 }}>已配置</Tag>
        ) : (
          <Tag color="orange" style={{ borderRadius: 999 }}>缺 API Key</Tag>
        ),
    },
    {
      title: "操作",
      render: (_, record) => (
        <Space size={4} wrap>
          {!record.is_default && (
            <Button size="small" type="link" onClick={() => setDefault(record)}>
              设为默认
            </Button>
          )}
          <Button
            size="small"
            type="link"
            icon={<ThunderboltOutlined />}
            loading={testingId === record.id}
            onClick={() => testModel(record)}
          >
            测试
          </Button>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title={`确定删除「${record.name}」？`} onConfirm={() => remove(record)}>
            <Button size="small" type="link" danger icon={<DeleteOutlined />}>
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
        icon={<ApiOutlined />}
        eyebrow="AI 模型接入"
        title="模型配置"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新增模型
          </Button>
        }
      />

      <Card variant="borderless" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={false}
          locale={{ emptyText: "还没有模型，点击右上角「新增模型」添加第一个" }}
        />
      </Card>

      <Paragraph type="secondary" style={{ marginTop: 16, marginBottom: 0, fontSize: 13 }}>
        💡 带 ⭐ 的是默认模型：AI 助手每次对话默认使用它。你可以在 AI 助手页面右上角随时切换本次对话用的模型。
      </Paragraph>

      <Modal
        title={editing ? `编辑「${editing.name}」` : "新增模型"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={save}
        confirmLoading={saving}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ provider: "openai", base_url: "", api_key: "", model: "", temperature: 0.7 }}
        >
          <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
            <Input placeholder="例如：DeepSeek 主力 / 通义千问" />
          </Form.Item>
          <Form.Item name="provider" label="服务商" rules={[{ required: true, message: "请选择服务商" }]}>
            <Select options={PROVIDERS} onChange={handleProviderChange} placeholder="选择 AI 服务商" />
          </Form.Item>
          {providerValue === "custom" && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message="中转站 / 自定义接口"
              description="接口地址填中转站提供的完整地址（通常以 /v1 结尾），API Key 填中转站的 Key，模型名称填它支持的模型 ID（如 gpt-4o）。"
            />
          )}
          <Form.Item name="base_url" label="接口地址（base_url）" extra={providerValue === "custom" ? "填中转站给的完整地址，通常以 /v1 结尾" : "选择服务商后自动填入，一般不用改"}>
            <Input placeholder="例如 https://api.deepseek.com/v1" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            extra={editing ? "已保存一个 Key，留空表示不修改" : "在服务商官网创建，格式类似 sk-xxxx"}
          >
            <Input.Password placeholder={editing ? "留空不修改" : "粘贴你的 API Key"} />
          </Form.Item>
          <Form.Item name="model" label="模型名称" extra="例如 deepseek-chat / qwen-plus / gpt-4o-mini">
            <Input placeholder="模型名称" />
          </Form.Item>
          <Form.Item name="temperature" label="温度（越高回答越有创造性）">
            <Slider min={0} max={1.5} step={0.1} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
