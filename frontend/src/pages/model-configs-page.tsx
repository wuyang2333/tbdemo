import { ApiOutlined, SaveOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Button, Card, Col, Form, Input, Row, Select, Slider, Space, Tag, Typography, message } from "antd";
import { useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { ModelConfig } from "../types";

const { Text, Paragraph } = Typography;

const PROVIDERS = [
  { value: "openai", label: "OpenAI" },
  { value: "deepseek", label: "DeepSeek（深度求索）" },
  { value: "dashscope", label: "阿里云百炼（通义千问）" },
  { value: "moonshot", label: "Moonshot（月之暗面）" },
  { value: "custom", label: "自定义（OpenAI 兼容）" },
];

const PROVIDER_DEFAULTS: Record<string, { base_url: string; model: string }> = {
  openai: { base_url: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  deepseek: { base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  dashscope: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
  moonshot: { base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  custom: { base_url: "", model: "" },
};

type FormValues = {
  provider: string;
  base_url: string;
  api_key: string;
  model: string;
  temperature: number;
};

export function ModelConfigsPage() {
  const [form] = Form.useForm<FormValues>();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [configured, setConfigured] = useState(false);
  const [lastProvider, setLastProvider] = useState("openai");

  const load = async () => {
    try {
      const { data } = await http.get<ModelConfig>("/model-configs");
      form.setFieldsValue({
        provider: data.provider,
        base_url: data.base_url,
        model: data.model,
        temperature: data.temperature,
      });
      setConfigured(data.configured);
      setLastProvider(data.provider);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const { data } = await http.put<ModelConfig>("/model-configs", values);
      setConfigured(data.configured);
      message.success("模型配置已保存");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    const values = await form.validateFields();
    setTesting(true);
    try {
      const { data } = await http.post<{ reply: string }>("/model-configs/test", values);
      message.success(`连接成功，模型回复：${data.reply}`);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTesting(false);
    }
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

  return (
    <div>
      <PageHeader
        icon={<ApiOutlined />}
        eyebrow="AI 模型接入"
        title="模型配置"
        extra={
          configured ? (
            <Tag color="green" style={{ borderRadius: 999, paddingInline: 12 }}>
              已配置
            </Tag>
          ) : (
            <Tag color="orange" style={{ borderRadius: 999, paddingInline: 12 }}>
              未配置
            </Tag>
          )
        }
      />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card
            variant="borderless"
            title="模型连接信息"
            style={{ boxShadow: "var(--ops-shadow-sm)" }}
          >
            <Form
              form={form}
              layout="vertical"
              initialValues={{ provider: "openai", base_url: "", api_key: "", model: "", temperature: 0.7 }}
            >
              <Form.Item name="provider" label="服务商" rules={[{ required: true, message: "请选择服务商" }]}>
                <Select options={PROVIDERS} onChange={handleProviderChange} placeholder="选择 AI 服务商" />
              </Form.Item>
              <Form.Item
                name="base_url"
                label="接口地址（base_url）"
                extra="选择服务商后会自动填入，一般不用改"
              >
                <Input placeholder="例如 https://api.deepseek.com/v1" />
              </Form.Item>
              <Form.Item
                name="api_key"
                label="API Key"
                extra={configured ? "已保存一个 Key，留空表示不修改" : "在服务商官网创建，格式类似 sk-xxxx"}
              >
                <Input.Password placeholder={configured ? "已保存（留空不修改）" : "粘贴你的 API Key"} />
              </Form.Item>
              <Form.Item name="model" label="模型名称" extra="例如 deepseek-chat / qwen-plus / gpt-4o-mini">
                <Input placeholder="模型名称" />
              </Form.Item>
              <Form.Item name="temperature" label="温度（越高回答越有创造性）">
                <Slider min={0} max={1.5} step={0.1} />
              </Form.Item>
              <Space>
                <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={save}>
                  保存配置
                </Button>
                <Button icon={<ThunderboltOutlined />} loading={testing} onClick={test}>
                  测试连接
                </Button>
              </Space>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card variant="borderless" title="使用说明" style={{ boxShadow: "var(--ops-shadow-sm)" }}>
            <Paragraph type="secondary" style={{ lineHeight: "24px" }}>
              1. 选一个服务商（DeepSeek、阿里云百炼、OpenAI、月之暗面等都可以，只要兼容 OpenAI 接口）；
            </Paragraph>
            <Paragraph type="secondary" style={{ lineHeight: "24px" }}>
              2. 到服务商官网注册并创建 API Key，粘贴到上面；
            </Paragraph>
            <Paragraph type="secondary" style={{ lineHeight: "24px" }}>
              3. 点「保存配置」，再点「测试连接」确认能用；
            </Paragraph>
            <Paragraph type="secondary" style={{ lineHeight: "24px" }}>
              4. 回到左侧「AI 助手」，就可以问数据、写文案了。它还能看到工作台里的店铺和礼品单实时数据。
            </Paragraph>
            <Text type="secondary" style={{ fontSize: 13 }}>
              API Key 只保存在本机数据库里，不会上传到别处。
            </Text>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
