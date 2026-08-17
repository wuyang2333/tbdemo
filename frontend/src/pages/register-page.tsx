import {
  BarChartOutlined,
  KeyOutlined,
  LockOutlined,
  RocketOutlined,
  ShopOutlined,
  SmileOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Card, Form, Input, Space, Typography, message } from "antd";
import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { getApiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { BRAND } from "../lib/brand";

const { Title, Text } = Typography;

type RegisterValues = {
  username: string;
  nickname: string;
  password: string;
  confirm: string;
  inviteCode: string;
};

const FEATURES = [
  { icon: <ShopOutlined />, label: "多店铺统一管理" },
  { icon: <BarChartOutlined />, label: "实时经营数据洞察" },
  { icon: <RocketOutlined />, label: "推广投放一站操作" },
  { icon: <TeamOutlined />, label: "客户与内容运营" },
];

export function RegisterPage() {
  const { user, register } = useAuth();
  const navigate = useNavigate();
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/dashboard" replace />;

  const handleFinish = async (values: RegisterValues) => {
    setSubmitting(true);
    try {
      const result = await register({
        username: values.username.trim(),
        password: values.password,
        nickname: values.nickname.trim(),
        inviteCode: values.inviteCode?.trim() ?? "",
      });
      if (result.pending) {
        message.success("注册申请已提交，请等待管理员审核通过后登录");
        navigate("/login", { replace: true });
      } else {
        message.success("注册成功，已自动登录");
        navigate("/dashboard", { replace: true });
      }
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="ops-auth-shell">
      <div className="ops-auth-brand">
        <div>
          <Space size={12} align="center">
            <span
              style={{
                width: 42,
                height: 42,
                borderRadius: 12,
                background: BRAND.gradient,
                color: "#fff",
                fontSize: 21,
                fontWeight: 800,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "0 8px 24px rgba(255,80,0,0.45)",
              }}
            >
              {BRAND.logoText}
            </span>
            <span>
              <div style={{ fontSize: 17, fontWeight: 700, lineHeight: "22px" }}>{BRAND.name}</div>
              <div style={{ fontSize: 10, letterSpacing: 2, opacity: 0.6 }}>{BRAND.eyebrow}</div>
            </span>
          </Space>
        </div>

        <div>
          <Title level={1} style={{ color: "#fff", margin: "0 0 10px", fontSize: 34 }}>
            一个账号，
            <br />
            管理全部店铺。
          </Title>
          <Text style={{ color: "rgba(255,255,255,0.72)", fontSize: 15, lineHeight: "24px", display: "block" }}>
            注册即开通工作台，店铺、商品、订单、数据与推广
            <br />
            一个入口全部搞定。
          </Text>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 28 }}>
            {FEATURES.map((feature) => (
              <span
                key={feature.label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "11px 14px",
                  borderRadius: 12,
                  background: "rgba(255,255,255,0.07)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  fontSize: 13,
                  color: "rgba(255,255,255,0.9)",
                  backdropFilter: "blur(4px)",
                }}
              >
                <span style={{ color: "#ff9a5f", fontSize: 16 }}>{feature.icon}</span>
                {feature.label}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="ops-auth-form">
        <Card
          variant="borderless"
          style={{ width: 420, maxWidth: "100%", borderRadius: 18 }}
          styles={{ body: { padding: "36px 40px 28px" } }}
        >
          <div style={{ marginBottom: 24 }}>
            <Title level={3} style={{ margin: 0 }}>
              创建账号
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              填邀请码可直接开通；没邀请码可提交申请，等管理员审核
            </Text>
          </div>

          <Form<RegisterValues> onFinish={handleFinish} size="large" requiredMark={false}>
            <Form.Item
              name="username"
              rules={[
                { required: true, message: "请输入用户名" },
                { pattern: /^[A-Za-z][A-Za-z0-9]*$/, message: "用户名需以字母开头，仅限英文字母和数字" },
              ]}
            >
              <Input prefix={<UserOutlined />} placeholder="用户名（3-20 位英文字母/数字）" autoComplete="username" />
            </Form.Item>
            <Form.Item
              name="nickname"
              rules={[
                { required: true, message: "请输入花名" },
                { max: 20, message: "花名不能超过 20 个字符" },
              ]}
            >
              <Input prefix={<SmileOutlined />} placeholder="花名（必填）" />
            </Form.Item>
            <Form.Item name="inviteCode" tooltip="有邀请码可直接开通；没有邀请码可提交申请，等待管理员审核">
              <Input prefix={<KeyOutlined />} placeholder="邀请码（选填，有则直接开通）" autoComplete="off" />
            </Form.Item>
            <Form.Item
              name="password"
              rules={[
                { required: true, message: "请输入密码" },
                { min: 6, max: 64, message: "密码长度需为 6-64 个字符" },
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="密码（至少 6 位）" autoComplete="new-password" />
            </Form.Item>
            <Form.Item
              name="confirm"
              dependencies={["password"]}
              rules={[
                { required: true, message: "请再次输入密码" },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue("password") === value) return Promise.resolve();
                    return Promise.reject(new Error("两次输入的密码不一致"));
                  },
                }),
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder="确认密码" autoComplete="new-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting} style={{ marginTop: 6, height: 42 }}>
              提交注册
            </Button>
          </Form>

          <div style={{ marginTop: 22, textAlign: "center" }}>
            <Text type="secondary" style={{ fontSize: 13 }}>
              已有账号？
            </Text>{" "}
            <Link to="/login" style={{ fontSize: 13 }}>
              去登录
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
