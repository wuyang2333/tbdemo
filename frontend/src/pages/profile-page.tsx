import { CameraOutlined, IdcardOutlined, LockOutlined, LogoutOutlined } from "@ant-design/icons";
import { Alert, Avatar, Button, Card, Checkbox, Col, Form, Input, Popconfirm, Row, Space, Table, Tag, Typography, Upload, message } from "antd";
import type { UploadProps } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage, TOKEN_KEY } from "../lib/api";
import { useAuth } from "../lib/auth";
import { PageHeader } from "../components/ui/page-header";

const { Text } = Typography;

type PasswordValues = {
  oldPassword: string;
  newPassword: string;
  confirm: string;
};

type SessionRow = { token: string; created_at: string; expires_at: string | null; ip: string; user_agent: string };

const WIDGET_OPTIONS = [
  { value: "kpis", label: "核心指标" },
  { value: "trend", label: "销售趋势" },
  { value: "stores", label: "店铺汇总" },
  { value: "shortcuts", label: "快捷入口" },
  { value: "system", label: "系统状态" },
];

const DEFAULT_AVATARS = ["var(--ops-accent)", "#2a7d4f", "#8e44ad", "#e67e22", "#c0392b"];

function deviceLabel(ua: string): string {
  if (!ua) return "未知设备";
  const u = ua.toLowerCase();
  if (u.includes("curl")) return "接口调用";
  if (u.includes("chrome")) return "Chrome 浏览器";
  if (u.includes("edg")) return "Edge 浏览器";
  if (u.includes("firefox")) return "Firefox 浏览器";
  if (u.includes("safari")) return "Safari 浏览器";
  if (u.includes("mobile") || u.includes("android") || u.includes("iphone")) return "手机";
  return ua.slice(0, 40);
}

export function ProfilePage() {
  const { user, refresh } = useAuth();
  const [nicknameForm] = Form.useForm();
  const [passwordForm] = Form.useForm();
  const [nicknameSaving, setNicknameSaving] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);

  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [widgets, setWidgets] = useState<string[]>([]);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const { data } = await http.get<{ items: SessionRow[] }>("/profile/sessions");
      setSessions(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  const loadWidgets = useCallback(async () => {
    try {
      const { data } = await http.get<{ widgets: string[] }>("/dashboard/config");
      setWidgets(data.widgets);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    loadSessions();
    loadWidgets();
  }, [loadSessions, loadWidgets]);

  const saveNickname = async (values: { nickname: string }) => {
    const nickname = values.nickname.trim();
    if (!nickname) {
      message.error("花名不能为空");
      return;
    }
    setNicknameSaving(true);
    try {
      await http.post("/profile/nickname", { nickname });
      await refresh();
      message.success("花名已更新");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setNicknameSaving(false);
    }
  };

  const savePassword = async (values: PasswordValues) => {
    setPasswordSaving(true);
    try {
      await http.post("/profile/password", {
        old_password: values.oldPassword,
        new_password: values.newPassword,
      });
      passwordForm.resetFields();
      message.success("密码已修改，下次登录请使用新密码");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setPasswordSaving(false);
    }
  };

  const uploadAvatar = async (dataUrl: string) => {
    setAvatarUploading(true);
    try {
      await http.post("/profile/avatar", { data: dataUrl });
      await refresh();
      message.success("头像已更新");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAvatarUploading(false);
    }
  };

  const processAvatar = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        const size = 200;
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        const side = Math.min(img.width, img.height);
        const sx = (img.width - side) / 2;
        const sy = (img.height - side) / 2;
        ctx.drawImage(img, sx, sy, side, side, 0, 0, size, size);
        uploadAvatar(canvas.toDataURL("image/jpeg", 0.85));
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
    return false;
  };

  const setDefaultAvatar = (bg: string) => {
    const canvas = document.createElement("canvas");
    canvas.width = 200;
    canvas.height = 200;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = bg;
    ctx.beginPath();
    ctx.arc(100, 100, 100, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 96px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(displayName.slice(0, 1), 100, 108);
    uploadAvatar(canvas.toDataURL("image/png"));
  };

  const revokeSession = async (row: SessionRow) => {
    try {
      await http.post(`/profile/sessions/${row.token}/revoke`, {});
      message.success("该会话已下线");
      loadSessions();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const revokeOthers = async () => {
    const cur = localStorage.getItem(TOKEN_KEY) ?? "";
    try {
      await http.post("/profile/sessions/revoke-others", undefined, { params: { current_token: cur } });
      message.success("已下线其他所有设备");
      loadSessions();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const saveWidgets = async (next: string[]) => {
    try {
      await http.put("/dashboard/config", { widgets: next });
      setWidgets(next);
      message.success("首页看板已更新");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const uploadProps: UploadProps = {
    showUploadList: false,
    accept: "image/png,image/jpeg,image/webp,image/gif",
    beforeUpload: (file) => {
      processAvatar(file);
      return false;
    },
  };

  const displayName = user?.nickname || user?.username || "?";
  const expiresAt = user?.expires_at ? dayjs(user.expires_at) : null;
  const expiringSoon = expiresAt ? expiresAt.diff(dayjs(), "day") <= 7 && expiresAt.isAfter(dayjs()) : false;
  const expired = expiresAt ? expiresAt.isBefore(dayjs()) : false;
  const currentToken = localStorage.getItem(TOKEN_KEY) ?? "";
  const currentIp = sessions.find((s) => s.token === currentToken)?.ip ?? "";

  const sessionColumns = [
    {
      title: "设备",
      dataIndex: "user_agent",
      render: (ua: string, row: SessionRow) => {
        const isCurrent = row.token === currentToken;
        return (
          <Space size={6}>
            <Text>{deviceLabel(ua)}</Text>
            {isCurrent && <Tag color="blue">当前设备</Tag>}
          </Space>
        );
      },
    },
    {
      title: "IP",
      dataIndex: "ip",
      render: (ip: string, row: SessionRow) => {
        const isDifferent = row.token !== currentToken && currentIp && ip && ip !== currentIp;
        return ip ? (
          <Space size={4}>
            <Text>{ip}</Text>
            {isDifferent && <Tag color="red">异地</Tag>}
          </Space>
        ) : (
          <Text type="secondary">—</Text>
        );
      },
    },
    { title: "登录时间", dataIndex: "created_at", render: (v: string) => dayjs(v).format("YYYY-MM-DD HH:mm") },
    {
      title: "操作",
      key: "actions",
      width: 90,
      render: (_: unknown, row: SessionRow) => (
        <Popconfirm title="下线该会话？" onConfirm={() => revokeSession(row)}>
          <Button size="small" icon={<LogoutOutlined />} danger>
            下线
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <PageHeader icon={<IdcardOutlined />} eyebrow="个人资料" title="个人中心" />

      {expired ? (
        <Alert type="error" showIcon style={{ marginBottom: 16 }} message="账号已到期，请联系管理员续期" />
      ) : expiringSoon ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 16 }}
          message={`账号将于 ${expiresAt?.format("YYYY-MM-DD")} 到期，请提前联系管理员续期`}
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card variant="borderless" title={<Text strong>我的头像</Text>} styles={{ body: { padding: "24px 20px" } }}>
            <div style={{ textAlign: "center" }}>
              <Avatar
                size={112}
                src={user?.avatar_url || undefined}
                style={{ background: "var(--ops-accent)", fontSize: 44, fontWeight: 600 }}
              >
                {displayName.slice(0, 1)}
              </Avatar>
              <div style={{ marginTop: 18 }}>
                <Upload {...uploadProps}>
                  <Button icon={<CameraOutlined />} loading={avatarUploading}>
                    上传头像（自动裁剪为方形）
                  </Button>
                </Upload>
              </div>
              <div style={{ marginTop: 12 }}>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
                  或选择默认头像
                </Text>
                <Space size={8}>
                  {DEFAULT_AVATARS.map((bg) => (
                    <Avatar key={bg} size={34} style={{ background: bg, cursor: "pointer", fontWeight: 600 }} onClick={() => setDefaultAvatar(bg)}>
                      {displayName.slice(0, 1)}
                    </Avatar>
                  ))}
                </Space>
              </div>
            </div>

            <div style={{ marginTop: 22, borderTop: "1px solid var(--ops-border)", paddingTop: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
                <Text type="secondary">用户名</Text>
                <Text strong>{user?.username ?? "—"}</Text>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
                <Text type="secondary">花名</Text>
                <Text strong>{user?.nickname ?? "—"}</Text>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
                <Text type="secondary">角色</Text>
                {user?.role === "super_admin" ? (
                  <Tag color="gold">超级管理员</Tag>
                ) : user?.role === "admin" ? (
                  <Tag color="orange">管理员</Tag>
                ) : (
                  <Tag>普通账号</Tag>
                )}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0" }}>
                <Text type="secondary">账号有效期</Text>
                {expiresAt ? (
                  <Tag color={expired ? "red" : expiringSoon ? "orange" : "blue"}>{expiresAt.format("YYYY-MM-DD")}</Tag>
                ) : (
                  <Tag>永久</Tag>
                )}
              </div>
            </div>
          </Card>
        </Col>

        <Col xs={24} md={16}>
          <Card variant="borderless" title={<Text strong>修改花名</Text>} styles={{ body: { padding: "18px 20px" } }}>
            <Form form={nicknameForm} layout="inline" onFinish={saveNickname} initialValues={{ nickname: user?.nickname }}>
              <Form.Item
                name="nickname"
                rules={[
                  { required: true, message: "请输入花名" },
                  { max: 20, message: "花名不能超过 20 个字符" },
                ]}
              >
                <Input placeholder="花名" style={{ width: 260 }} />
              </Form.Item>
              <Form.Item>
                <Button type="primary" htmlType="submit" loading={nicknameSaving}>
                  保存
                </Button>
              </Form.Item>
            </Form>
          </Card>

          <Card
            variant="borderless"
            title={<Text strong>修改密码</Text>}
            style={{ marginTop: 16 }}
            styles={{ body: { padding: "18px 20px" } }}
          >
            <Form form={passwordForm} layout="vertical" onFinish={savePassword} style={{ maxWidth: 420 }}>
              <Form.Item name="oldPassword" label="原密码" rules={[{ required: true, message: "请输入原密码" }]}>
                <Input.Password prefix={<LockOutlined />} autoComplete="current-password" />
              </Form.Item>
              <Form.Item
                name="newPassword"
                label="新密码"
                rules={[
                  { required: true, message: "请输入新密码" },
                  { min: 6, max: 64, message: "密码长度需为 6-64 个字符" },
                ]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
              </Form.Item>
              <Form.Item
                name="confirm"
                label="确认新密码"
                dependencies={["newPassword"]}
                rules={[
                  { required: true, message: "请再次输入新密码" },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue("newPassword") === value) return Promise.resolve();
                      return Promise.reject(new Error("两次输入的密码不一致"));
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} autoComplete="new-password" />
              </Form.Item>
              <Space>
                <Button type="primary" htmlType="submit" loading={passwordSaving}>
                  确认修改
                </Button>
              </Space>
            </Form>
          </Card>

          <Card
            variant="borderless"
            title={<Text strong>我的登录会话</Text>}
            style={{ marginTop: 16 }}
            styles={{ body: { padding: "18px 20px" } }}
          >
            <Space style={{ marginBottom: 12 }} wrap>
              <Button type="primary" danger ghost onClick={revokeOthers}>
                下线其他所有设备
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>共 {sessions.length} 个会话 · 当前设备已标记</Text>
            </Space>
            <Table<SessionRow>
              rowKey="token"
              size="small"
              loading={sessionsLoading}
              dataSource={sessions}
              pagination={{ pageSize: 8, showSizeChanger: true, pageSizeOptions: [8, 20, 50] }}
              columns={sessionColumns}
            />
          </Card>

          <Card
            variant="borderless"
            title={<Text strong>自定义首页看板</Text>}
            style={{ marginTop: 16 }}
            styles={{ body: { padding: "18px 20px" } }}
          >
            <Checkbox.Group options={WIDGET_OPTIONS} value={widgets} onChange={(values) => saveWidgets(values as string[])} />
            <Text type="secondary" style={{ display: "block", marginTop: 10, fontSize: 12 }}>
              勾选登录后首页展示的卡片（实时保存）
            </Text>
          </Card>
        </Col>
      </Row>
    </div>
  );
}