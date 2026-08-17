import { DeleteOutlined, KeyOutlined, TeamOutlined, UserAddOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, Modal, Popconfirm, Space, Table, Tag, Typography, message } from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { PageHeader } from "../components/ui/page-header";

const { Text } = Typography;

type SubAccountRow = {
  id: number;
  username: string;
  nickname: string;
  role: string;
  status: string;
  created_at: string;
  last_login_at: string | null;
  last_login_ip: string | null;
};

export function TeamPage() {
  const { user } = useAuth();
  const isOwner = user?.role === "member" && !user?.parent_id;
  const isSub = !!user?.parent_id;

  const [items, setItems] = useState<SubAccountRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [form] = Form.useForm<{ username: string; nickname: string; password: string; confirm: string }>();
  const [createOpen, setCreateOpen] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);
  const [passwordTarget, setPasswordTarget] = useState<SubAccountRow | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);

  const load = useCallback(async () => {
    if (!isOwner) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const { data } = await http.get<{ items: SubAccountRow[] }>("/accounts/my/sub-accounts");
      setItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [isOwner]);

  useEffect(() => {
    load();
  }, [load]);

  const create = async (values: { username: string; nickname: string; password: string }) => {
    setCreateSaving(true);
    try {
      await http.post("/accounts/my/sub-accounts", {
        username: values.username.trim(),
        nickname: values.nickname.trim(),
        password: values.password,
      });
      message.success("子账号创建成功，可登录查看你绑定的店铺数据");
      setCreateOpen(false);
      form.resetFields();
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setCreateSaving(false);
    }
  };

  const resetPassword = async () => {
    if (!passwordTarget) return;
    if (newPassword.length < 6 || newPassword.length > 64) {
      message.error("密码长度需为 6-64 个字符");
      return;
    }
    setPasswordSaving(true);
    try {
      await http.post(`/accounts/my/sub-accounts/${passwordTarget.id}/password`, { password: newPassword });
      message.success("密码已重置");
      setPasswordTarget(null);
      setNewPassword("");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setPasswordSaving(false);
    }
  };

  const remove = async (row: SubAccountRow) => {
    try {
      await http.delete(`/accounts/my/sub-accounts/${row.id}`);
      message.success("子账号已删除");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const columns: TableColumnsType<SubAccountRow> = [
    {
      title: "账号",
      dataIndex: "username",
      render: (value: string) => <Text strong>{value}</Text>,
    },
    { title: "花名", dataIndex: "nickname", render: (value: string) => value || "—" },
    {
      title: "最近登录",
      dataIndex: "last_login_at",
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : <Text type="secondary">从未</Text>,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    {
      title: "操作",
      key: "actions",
      width: 180,
      render: (_, row) => (
        <Space size={4}>
          <Button
            size="small"
            icon={<KeyOutlined />}
            onClick={() => {
              setPasswordTarget(row);
              setNewPassword("");
            }}
          >
            重置密码
          </Button>
          <Popconfirm title={`删除子账号 ${row.username}？`} okText="删除" okButtonProps={{ danger: true }} onConfirm={() => remove(row)}>
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
      <PageHeader icon={<TeamOutlined />} eyebrow="团队管理" title="我的团队" />

      {isSub ? (
        <Card variant="borderless">
          <Text type="secondary">你是子账号，店铺数据由主账号统一分配，无需在此管理团队。</Text>
        </Card>
      ) : (
        <>
          <Card
            variant="borderless"
            style={{ marginBottom: 16 }}
            title="团队说明"
            extra={
              <Space size={8}>
                <Tag color="blue">子账号 {items.length}/{user?.sub_account_quota ?? 2} 个</Tag>
                <Tag color="blue">店铺 {user?.store_quota ?? 3} 家</Tag>
              </Space>
            }
          >
            <Text type="secondary">
              作为主账号，你可以创建子账号给团队成员使用。子账号登录后会自动看到你绑定的店铺数据
              （你在店铺管理里新绑定店铺，子账号也会同步可见）。子账号不能自行绑定/解绑店铺。
            </Text>
          </Card>
          <Card
            variant="borderless"
            title="子账号列表"
            extra={
              <Button
                type="primary"
                icon={<UserAddOutlined />}
                onClick={() => {
                  form.resetFields();
                  setCreateOpen(true);
                }}
              >
                创建子账号
              </Button>
            }
          >
            <Table<SubAccountRow> rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={false} />
          </Card>
        </>
      )}

      <Modal
        title="创建子账号"
        open={createOpen}
        onOk={() => form.submit()}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={createSaving}
        okText="创建"
      >
        <Form form={form} layout="vertical" onFinish={create} style={{ marginTop: 8 }}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: "请输入用户名" },
              { pattern: /^[A-Za-z][A-Za-z0-9]*$/, message: "用户名需以字母开头，仅限英文字母和数字" },
            ]}
          >
            <Input placeholder="3-20 位英文字母/数字" autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="nickname"
            label="花名"
            rules={[
              { required: true, message: "请输入花名" },
              { max: 20, message: "花名不能超过 20 个字符" },
            ]}
          >
            <Input placeholder="花名（必填）" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[
              { required: true, message: "请输入密码" },
              { min: 6, max: 64, message: "密码长度需为 6-64 个字符" },
            ]}
          >
            <Input.Password placeholder="至少 6 位" autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            name="confirm"
            label="确认密码"
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
            <Input.Password placeholder="再次输入密码" autoComplete="new-password" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`重置密码：${passwordTarget?.username ?? ""}`}
        open={!!passwordTarget}
        onOk={resetPassword}
        onCancel={() => setPasswordTarget(null)}
        confirmLoading={passwordSaving}
        okText="重置"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">重置后该子账号需重新登录。</Text>
          <Input.Password value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="新密码（6-64 位）" />
        </Space>
      </Modal>
    </div>
  );
}