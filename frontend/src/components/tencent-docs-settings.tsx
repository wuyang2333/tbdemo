import { CloudSyncOutlined, LinkOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Form, Input, Space, Switch, Tag, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";

const { Text } = Typography;

type TencentDocsConfig = {
  enabled: boolean;
  browser_fallback_enabled: boolean;
  browser_cdp_url: string;
  document_url: string;
  file_id: string;
  sheet_id: string;
  sheet_title: string;
  client_id: string;
  client_secret_configured: boolean;
  access_token_configured: boolean;
  redirect_uri: string;
  authorized: boolean;
  token_expires_at: string;
  token_source: "" | "manual" | "oauth";
  auto_refresh_enabled: boolean;
  auth_required: boolean;
  auth_failure_at: string;
  last_sync_at: string;
  last_error: string;
  last_result: { pushed?: number; pulled?: number; updated?: number; errors?: string[]; transport?: string; fallback_used?: boolean };
  poll_minutes: number;
};

const DEFAULT_CONFIG: TencentDocsConfig = {
  enabled: false,
  browser_fallback_enabled: false,
  browser_cdp_url: "http://127.0.0.1:9222",
  document_url: "https://docs.qq.com/sheet/DTG1YaFV2eUhMRGdF",
  file_id: "",
  sheet_id: "",
  sheet_title: "",
  client_id: "",
  client_secret_configured: false,
  access_token_configured: false,
  redirect_uri: "",
  authorized: false,
  token_expires_at: "",
  token_source: "",
  auto_refresh_enabled: false,
  auth_required: false,
  auth_failure_at: "",
  last_sync_at: "",
  last_error: "",
  last_result: {},
  poll_minutes: 15,
};

export function TencentDocsSettings() {
  const [config, setConfig] = useState<TencentDocsConfig>(DEFAULT_CONFIG);
  const [clientSecret, setClientSecret] = useState("");
  const [accessToken, setAccessToken] = useState("");
  const [openId, setOpenId] = useState("");
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState<"test" | "sync" | "authorize" | "disconnect" | null>(null);
  const transportReady = config.authorized || config.browser_fallback_enabled;
  const credentialLabel = config.auto_refresh_enabled
    ? "OAuth 自动续期"
    : config.token_source === "manual"
      ? "手工 Token"
      : config.access_token_configured
        ? "已保存 Token"
        : "未配置";
  const expiryLabel = config.token_expires_at
    ? `${dayjs(config.token_expires_at).format("YYYY-MM-DD HH:mm")}${config.token_source === "manual" ? "（按保存时间估算）" : ""}`
    : config.access_token_configured
      ? "未知（重新保存 Token 后开始记录）"
      : "未配置";
  const authorizationTag = config.auth_required
    ? { color: "red", label: "需重新授权" }
    : config.authorized
      ? { color: "green", label: "已授权" }
      : config.browser_fallback_enabled
        ? { color: "blue", label: "浏览器备用" }
        : { color: "orange", label: "未授权" };

  const load = useCallback(async () => {
    try {
      const { data } = await http.get<TencentDocsConfig>("/settings/tencent-docs");
      setConfig(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (showMessage = true, overrides: Partial<TencentDocsConfig> = {}) => {
    setLoading(true);
    try {
      const { data } = await http.put<TencentDocsConfig>("/settings/tencent-docs", {
        enabled: overrides.enabled ?? config.enabled,
        browser_fallback_enabled: overrides.browser_fallback_enabled ?? config.browser_fallback_enabled,
        browser_cdp_url: config.browser_cdp_url,
        document_url: config.document_url,
        sheet_id: config.sheet_id,
        client_id: config.client_id,
        client_secret: clientSecret,
        access_token: accessToken,
        open_id: openId,
        redirect_uri: config.redirect_uri,
      });
      setConfig(data);
      setClientSecret("");
      setAccessToken("");
      setOpenId("");
      if (showMessage) message.success("腾讯文档同步配置已保存");
      return true;
    } catch (error) {
      message.error(getApiErrorMessage(error));
      return false;
    } finally {
      setLoading(false);
    }
  };

  const toggleEnabled = async (enabled: boolean) => {
    const previous = config.enabled;
    setConfig({ ...config, enabled });
    if (!(await save(false, { enabled }))) {
      setConfig((current) => ({ ...current, enabled: previous }));
    } else {
      message.success(enabled ? `腾讯文档每 ${config.poll_minutes} 分钟自动同步已开启` : "腾讯文档自动同步已关闭");
    }
  };

  const toggleBrowserFallback = async (browser_fallback_enabled: boolean) => {
    const previous = config.browser_fallback_enabled;
    setConfig({ ...config, browser_fallback_enabled });
    if (!(await save(false, { browser_fallback_enabled }))) {
      setConfig((current) => ({ ...current, browser_fallback_enabled: previous }));
    } else {
      message.success(browser_fallback_enabled ? "已开启浏览器备用通道" : "已关闭浏览器备用通道");
    }
  };

  const authorize = async () => {
    setAction("authorize");
    try {
      if (!(await save(false))) return;
      const { data } = await http.get<{ url: string }>("/settings/tencent-docs/oauth-url");
      window.open(data.url, "_blank", "noopener,noreferrer");
      message.info("请在新页面完成腾讯文档授权，成功后返回这里刷新状态");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAction(null);
    }
  };

  const runAction = async (kind: "test" | "sync" | "disconnect") => {
    setAction(kind);
    try {
      if (kind === "test") {
        const { data } = await http.post<{ sheet_title: string }>("/settings/tencent-docs/test");
        message.success(`连接成功：${data.sheet_title || "默认工作表"}`);
      } else if (kind === "sync") {
        const { data } = await http.post<{ pushed: number; pulled: number; errors: string[] }>("/gifts/tencent-docs/sync");
        if (data.errors?.length) message.warning(`同步完成，但有 ${data.errors.length} 条数据未回填`);
        else message.success(`同步完成：新增 ${data.pushed || 0} 条，回填 ${data.pulled || 0} 条`);
      } else {
        await http.post("/settings/tencent-docs/disconnect");
        message.success("腾讯文档授权已断开");
      }
      await load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAction(null);
    }
  };

  return (
    <Card
      variant="borderless"
      title={<Space><CloudSyncOutlined style={{ color: "var(--ops-accent)" }} /><Text strong>礼品单 · 腾讯文档同步</Text></Space>}
      style={{ marginTop: 16 }}
      extra={<Space><Tag color={authorizationTag.color}>{authorizationTag.label}</Tag><Switch checked={config.enabled} loading={loading} onChange={(enabled) => void toggleEnabled(enabled)} /></Space>}
    >
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type={config.auth_required ? "error" : config.last_error ? "warning" : "info"}
          showIcon
          message={config.auth_required ? "腾讯文档授权已失效" : config.last_error || "系统写入业务字段，云表格回传旺旺号和订单号"}
          description={config.auth_required
            ? "后台已暂停官方接口请求。请重新填写 Access Token，或配置 Client Secret 和 HTTPS 回调地址后完成 OAuth 自动授权。"
            : `启用后每 ${config.poll_minutes} 分钟检查腾讯文档；系统内新增、编辑、状态、图片和删除变化会立即排队同步。浏览器备用通道只在官方 API 失败时尝试。`}
        />
        <Alert
          type="warning"
          showIcon
          message="浏览器备用通道需要已登录的 Chrome 调试页"
          description="请用 remote-debugging-port=9222 启动 Chrome，并保持目标腾讯文档标签页打开；系统不会读取或保存浏览器 Cookie。当前备用实现支持单元格读写和清除，图片上传仍需官方 API。"
          action={<Switch checked={config.browser_fallback_enabled} loading={loading} onChange={(enabled) => void toggleBrowserFallback(enabled)} />}
        />
        <Form layout="vertical">
          <Form.Item label="Chrome 调试地址">
            <Input value={config.browser_cdp_url} onChange={(event) => setConfig({ ...config, browser_cdp_url: event.target.value })} placeholder="http://127.0.0.1:9222" />
          </Form.Item>
          <Form.Item label="腾讯在线表格链接">
            <Input value={config.document_url} onChange={(event) => setConfig({ ...config, document_url: event.target.value })} prefix={<LinkOutlined />} />
          </Form.Item>
          <Form.Item label="Client ID">
            <Input value={config.client_id} onChange={(event) => setConfig({ ...config, client_id: event.target.value })} placeholder="腾讯文档开放平台应用 Client ID" />
          </Form.Item>
          <Form.Item label="Access Token" extra="只保存在本机数据库；手工 Token 按保存时间记录 30 天预计有效期，OAuth 模式会自动续期">
            <Input.Password value={accessToken} onChange={(event) => setAccessToken(event.target.value)} placeholder={config.access_token_configured ? "已保存；留空表示不修改" : "腾讯文档 access_token"} />
          </Form.Item>
          <Form.Item label="Open ID">
            <Input.Password value={openId} onChange={(event) => setOpenId(event.target.value)} placeholder={config.authorized ? "已保存；留空表示不修改" : "腾讯文档 open_id"} />
          </Form.Item>
          <Alert type="success" showIcon message="只有 Client ID、Access Token、Open ID 也可以使用" description="按你当前腾讯开发者页面提供的三项填写即可。下面的 Client Secret 和 OAuth 回调属于自动续期方式，没有可以留空。" style={{ marginBottom: 20 }} />
          <Form.Item label="Client Secret">
            <Input.Password value={clientSecret} onChange={(event) => setClientSecret(event.target.value)} placeholder={config.client_secret_configured ? "已保存；留空表示不修改" : "腾讯文档开放平台应用 Client Secret"} />
          </Form.Item>
          <Form.Item label="OAuth HTTPS 回调地址" extra="需在腾讯文档开放平台加入白名单，并指向 /api/settings/tencent-docs/oauth/callback">
            <Input value={config.redirect_uri} onChange={(event) => setConfig({ ...config, redirect_uri: event.target.value })} placeholder="https://你的域名/api/settings/tencent-docs/oauth/callback" />
          </Form.Item>
          <Form.Item label="工作表 ID（可留空，连接测试时自动选择第一个子表）">
            <Input value={config.sheet_id} onChange={(event) => setConfig({ ...config, sheet_id: event.target.value })} placeholder={config.sheet_title || "自动识别"} />
          </Form.Item>
        </Form>
        <Space wrap>
          <Button type="primary" loading={loading} onClick={() => void save()}>保存配置</Button>
          <Button icon={<SafetyCertificateOutlined />} loading={action === "authorize"} disabled={!config.client_secret_configured || !config.redirect_uri} onClick={() => void authorize()}>{config.auth_required ? "重新 OAuth 授权" : "OAuth 自动授权（可选）"}</Button>
          <Button loading={action === "test"} disabled={!transportReady} onClick={() => void runAction("test")}>测试连接</Button>
          <Button icon={<CloudSyncOutlined />} loading={action === "sync"} disabled={!transportReady || !config.enabled} onClick={() => void runAction("sync")}>立即同步</Button>
          {config.access_token_configured ? <Button danger loading={action === "disconnect"} onClick={() => void runAction("disconnect")}>断开授权</Button> : null}
          <Button onClick={() => void load()}>刷新状态</Button>
        </Space>
        <Space wrap>
          <Text type="secondary">凭证模式：{credentialLabel}</Text>
          <Text type={config.auth_required ? "danger" : "secondary"}>Token 到期：{expiryLabel}</Text>
          <Text type="secondary">子表：{config.sheet_title || config.sheet_id || "尚未识别"}</Text>
          <Text type="secondary">最近同步：{config.last_sync_at ? dayjs(config.last_sync_at).format("YYYY-MM-DD HH:mm:ss") : "尚未同步"}</Text>
          {config.last_result?.transport ? <Text type="secondary">最近通道：{config.last_result.transport === "browser" ? "浏览器备用" : "官方 API"}</Text> : null}
        </Space>
      </Space>
    </Card>
  );
}
