import { CameraOutlined, IdcardOutlined, LockOutlined } from "@ant-design/icons";
import { Avatar, Button, Card, Col, Form, Input, Row, Space, Tag, Typography, Upload, message } from "antd";
import type { UploadProps } from "antd";
import { useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { PageHeader } from "../components/ui/page-header";

const { Text } = Typography;

type PasswordValues = {
  oldPassword: string;
  newPassword: string;
  confirm: string;
};

export function ProfilePage() {
  const { user, refresh } = useAuth();
  const [nicknameForm] = Form.useForm();
  const [passwordForm] = Form.useForm();
  const [nicknameSaving, setNicknameSaving] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);

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

  const uploadProps: UploadProps = {
    showUploadList: false,
    accept: "image/png,image/jpeg,image/webp,image/gif",
    beforeUpload: (file) => {
      const reader = new FileReader();
      reader.onload = async () => {
        const result = reader.result as string;
        if (!result) return;
        setAvatarUploading(true);
        try {
          await http.post("/profile/avatar", { data: result });
          await refresh();
          message.success("头像已更新");
        } catch (error) {
          message.error(getApiErrorMessage(error));
        } finally {
          setAvatarUploading(false);
        }
      };
      reader.readAsDataURL(file);
      return false;
    },
  };

  const displayName = user?.nickname || user?.username || "?";

  return (
    <div>
      <PageHeader icon={<IdcardOutlined />} eyebrow="个人资料" title="个人中心" />

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card variant="borderless" title={<Text strong>我的头像</Text>} styles={{ body: { padding: "24px 20px" } }}>
            <div style={{ textAlign: "center" }}>
              <Avatar
                size={112}
                src={user?.avatar_url || undefined}
                style={{ background: "#0066cc", fontSize: 44, fontWeight: 600 }}
              >
                {displayName.slice(0, 1)}
              </Avatar>
              <div style={{ marginTop: 18 }}>
                <Upload {...uploadProps}>
                  <Button icon={<CameraOutlined />} loading={avatarUploading}>
                    更换头像
                  </Button>
                </Upload>
                <Text type="secondary" style={{ display: "block", marginTop: 8, fontSize: 12 }}>
                  支持 PNG / JPG / WebP / GIF，不超过 2MB
                </Text>
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
                {user?.role === "admin" ? <Tag color="orange">管理员</Tag> : <Tag>普通账号</Tag>}
              </div>
            </div>
          </Card>
        </Col>

        <Col xs={24} md={16}>
          <Card variant="borderless" title={<Text strong>修改花名</Text>} styles={{ body: { padding: "18px 20px" } }}>
            <Form
              form={nicknameForm}
              layout="inline"
              onFinish={saveNickname}
              initialValues={{ nickname: user?.nickname }}
            >
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
        </Col>
      </Row>
    </div>
  );
}
