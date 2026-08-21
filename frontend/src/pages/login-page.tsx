import {
  BarChartOutlined,
  LockOutlined,
  RocketOutlined,
  ShopOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Card, Form, Input, Space, Typography, message } from "antd";
import { useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { getApiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { BRAND } from "../lib/brand";

const { Title, Text } = Typography;

type LoginValues = {
  username: string;
  password: string;
};

const FEATURES = [
  { icon: <ShopOutlined />, label: "多店铺统一管理" },
  { icon: <BarChartOutlined />, label: "实时经营数据洞察" },
  { icon: <RocketOutlined />, label: "推广投放一站操作" },
  { icon: <TeamOutlined />, label: "客户与内容运营" },
];

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/dashboard" replace />;

  const from = (location.state as { from?: string } | null)?.from ?? "/dashboard";

  const handleFinish = async (values: LoginValues) => {
    setSubmitting(true);
    try {
      await login(values.username, values.password);
      navigate(from, { replace: true });
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
                borderRadius: "var(--ops-radius)",
                background: BRAND.logoUrl ? "transparent" : BRAND.gradient,
                color: "#fff",
                fontSize: 21,
                fontWeight: 800,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "0 8px 24px rgba(94,106,210,0.45)",
              }}
            >
              {BRAND.logoUrl ? (
                <img src={BRAND.logoUrl} alt="" style={{ width: "100%", height: "100%", borderRadius: "var(--ops-radius)", objectFit: "cover", display: "block" }} />
              ) : (
                (BRAND.name || "淘").slice(0, 1)
              )}
            </span>
            <span>
              <div style={{ fontSize: 17, fontWeight: 700, lineHeight: "22px" }}>{BRAND.name}</div>
              <div style={{ fontSize: 10, letterSpacing: 2, opacity: 0.6 }}>{BRAND.eyebrow}</div>
            </span>
          </Space>
        </div>

        <div>
          <Title level={1} style={{ color: "#fff", margin: "0 0 10px", fontSize: 34 }}>
            把淘宝店铺经营，
            <br />
            变得简单一点。
          </Title>
          <Text style={{ color: "rgba(255,255,255,0.72)", fontSize: 15, lineHeight: "24px", display: "block" }}>
            一个工作台，覆盖店铺、商品、订单、数据与推广，
            <br />
            让运营更专注、更高效。
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
                  borderRadius: "var(--ops-radius)",
                  background: "rgba(255,255,255,0.07)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  fontSize: 13,
                  color: "rgba(255,255,255,0.9)",
                  
                }}
              >
                <span style={{ color: "var(--ops-accent-light)", fontSize: 16 }}>{feature.icon}</span>
                {feature.label}
              </span>
            ))}
          </div>
          <Space size={10} style={{ marginTop: 28 }} wrap>
            {["14 个业务模块", "实时数据接口", "角色权限管理"].map((item) => (
              <span
                key={item}
                style={{
                  fontSize: 12,
                  color: "rgba(255,255,255,0.55)",
                  border: "1px solid rgba(255,255,255,0.16)",
                  borderRadius: 999,
                  padding: "4px 12px",
                }}
              >
                {item}
              </span>
            ))}
          </Space>
        </div>
      </div>

      <div className="ops-auth-form">
        <Card
          variant="borderless"
          style={{ width: 400, maxWidth: "100%", borderRadius: "var(--ops-radius-lg)" }}
          styles={{ body: { padding: "38px 40px 30px" } }}
        >
          <div style={{ marginBottom: 26 }}>
            <Title level={3} style={{ margin: 0 }}>
              欢迎回来
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              登录 {BRAND.name}，继续你的运营工作
            </Text>
          </div>

          <Form<LoginValues> onFinish={handleFinish} size="large" requiredMark={false}>
            <Form.Item name="username" rules={[{ required: true, message: "请输入用户名" }]}>
              <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={submitting} style={{ marginTop: 6, height: 42 }}>
              登 录
            </Button>
          </Form>

          <div style={{ marginTop: 22, textAlign: "center" }}>
            <Text type="secondary" style={{ fontSize: 13 }}>
              还没有账号？
            </Text>{" "}
            <Link to="/register" style={{ fontSize: 13 }}>
              立即注册
            </Link>
          </div>
        </Card>
      </div>
    </div>
  );
}
