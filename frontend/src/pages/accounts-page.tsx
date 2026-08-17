import {
  DeleteOutlined,
  LockOutlined,
  SafetyOutlined,
  ShopOutlined,
  UserAddOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Modal,
  Popconfirm,
  Radio,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { useAuth } from "../lib/auth";
import { MODULES } from "../lib/modules";
import { PageHeader } from "../components/ui/page-header";

const { Text } = Typography;

type Role = "super_admin" | "admin" | "member";

type AccountRow = {
  id: number;
  username: string;
  nickname: string;
  role: Role;
  status: "active" | "disabled";
  allowed_modules: string[] | null;
  allowed_store_ids: number[] | null;
  created_at: string;
};

const MODULE_OPTIONS = MODULES.filter(
  (module) =>
    module.id !== "accounts" &&
    module.id !== "dashboard" &&
    module.id !== "profile" &&
    module.id !== "logs" &&
    module.id !== "settings"
);

function moduleName(id: string): string {
  return MODULES.find((module) => module.id === id)?.name ?? id;
}

function RoleTag({ role }: { role: Role }) {
  if (role === "super_admin") return <Tag color="gold">超级管理员</Tag>;
  if (role === "admin") return <Tag color="orange">管理员</Tag>;
  return <Tag>普通账号</Tag>;
}

function ModulesCell({ row }: { row: AccountRow }) {
  if (row.role !== "member" || row.allowed_modules == null) {
    return <Tag>全部模块</Tag>;
  }
  if (row.allowed_modules.length === 0) {
    return <Tag>仅总览</Tag>;
  }
  return (
    <Space size={4} wrap>
      {row.allowed_modules.map((id) => (
        <Tag key={id}>{moduleName(id)}</Tag>
      ))}
    </Space>
  );
}

export function AccountsPage() {
  const { user: me } = useAuth();
  const [items, setItems] = useState<AccountRow[]>([]);
  const [loading, setLoading] = useState(true);

  const [createForm] = Form.useForm();
  const [createOpen, setCreateOpen] = useState(false);
  const [createSaving, setCreateSaving] = useState(false);

  const [passwordTarget, setPasswordTarget] = useState<AccountRow | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);

  const [modulesTarget, setModulesTarget] = useState<AccountRow | null>(null);
  const [moduleSelection, setModuleSelection] = useState<string[]>([]);
  const [modulesSaving, setModulesSaving] = useState(false);

  const [roleTarget, setRoleTarget] = useState<AccountRow | null>(null);
  const [roleValue, setRoleValue] = useState<Role>("member");
  const [roleSaving, setRoleSaving] = useState(false);

  const [storeAccessTarget, setStoreAccessTarget] = useState<AccountRow | null>(null);
  const [storeOptions, setStoreOptions] = useState<{ value: number; label: string }[]>([]);
  const [storeSelection, setStoreSelection] = useState<number[]>([]);
  const [storeAccessSaving, setStoreAccessSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: AccountRow[] }>("/accounts");
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

  const post = async (path: string, body: unknown, successText: string): Promise<boolean> => {
    try {
      await http.post(path, body);
      message.success(successText);
      load();
      return true;
    } catch (error) {
      message.error(getApiErrorMessage(error));
      return false;
    }
  };

  const isSuperAdmin = me?.role === "super_admin";
  const canManage = (row: AccountRow): boolean => {
    if (!me || row.id === me.id) return false;
    if (isSuperAdmin) return true;
    if (me.role === "admin") return row.role === "member";
    return false;
  };

  type CreateValues = {
    username: string;
    nickname: string;
    password: string;
    confirm: string;
    role: "admin" | "member";
  };

  const createAccount = async (values: CreateValues) => {
    setCreateSaving(true);
    try {
      await http.post("/accounts", {
        username: values.username.trim(),
        nickname: values.nickname.trim(),
        password: values.password,
        role: isSuperAdmin ? values.role : "member",
      });
      message.success("账号创建成功");
      setCreateOpen(false);
      createForm.resetFields();
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setCreateSaving(false);
    }
  };

  const changeStatus = (row: AccountRow, status: "active" | "disabled") =>
    post(`/accounts/${row.id}/status`, { status }, status === "disabled" ? "已禁用该账号" : "已启用该账号");

  const saveRole = async () => {
    if (!roleTarget) return;
    setRoleSaving(true);
    const ok = await post(`/accounts/${roleTarget.id}/role`, { role: roleValue }, "角色已更新");
    setRoleSaving(false);
    if (ok) setRoleTarget(null);
  };

  const resetPassword = async () => {
    if (!passwordTarget) return;
    if (newPassword.length < 6 || newPassword.length > 64) {
      message.error("密码长度需为 6-64 个字符");
      return;
    }
    setPasswordSaving(true);
    const ok = await post(`/accounts/${passwordTarget.id}/password`, { password: newPassword }, "密码已重置");
    setPasswordSaving(false);
    if (ok) {
      setPasswordTarget(null);
      setNewPassword("");
    }
  };

  const openModules = (row: AccountRow) => {
    setModulesTarget(row);
    setModuleSelection(row.allowed_modules ?? MODULE_OPTIONS.map((module) => module.id));
  };

  const saveModules = async () => {
    if (!modulesTarget) return;
    setModulesSaving(true);
    const ok = await post(`/accounts/${modulesTarget.id}/modules`, { modules: moduleSelection }, "模块权限已更新");
    setModulesSaving(false);
    if (ok) setModulesTarget(null);
  };

  const deleteAccount = async (row: AccountRow) => {
    try {
      await http.delete(`/accounts/${row.id}`);
      message.success("账号已删除");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const openStoreAccess = async (row: AccountRow) => {
    setStoreAccessTarget(row);
    try {
      const { data } = await http.get<{ items: { id: number; name: string }[] }>("/stores");
      setStoreOptions(data.items.map((store) => ({ value: store.id, label: store.name })));
      setStoreSelection(row.allowed_store_ids ?? data.items.map((store) => store.id));
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setStoreAccessTarget(null);
    }
  };

  const saveStoreAccess = async () => {
    if (!storeAccessTarget) return;
    setStoreAccessSaving(true);
    try {
      await http.post(`/accounts/${storeAccessTarget.id}/stores`, { store_ids: storeSelection });
      message.success("店铺权限已更新");
      setStoreAccessTarget(null);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setStoreAccessSaving(false);
    }
  };

  const columns: TableColumnsType<AccountRow> = [
    {
      title: "账号",
      dataIndex: "username",
      render: (_, row) => (
        <Space size={6}>
          <Text strong>{row.username}</Text>
          {row.id === me?.id && <Tag color="gold">当前账号</Tag>}
        </Space>
      ),
    },
    {
      title: "花名",
      dataIndex: "nickname",
      render: (value: string) => value || "—",
    },
    {
      title: "角色",
      dataIndex: "role",
      render: (role: Role) => <RoleTag role={role} />,
    },
    {
      title: "状态",
      dataIndex: "status",
      render: (status: AccountRow["status"]) =>
        status === "active" ? <Tag color="green">正常</Tag> : <Tag color="red">已禁用</Tag>,
    },
    {
      title: "可见模块",
      key: "modules",
      render: (_, row) => <ModulesCell row={row} />,
    },
    {
      title: "注册时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    {
      title: "操作",
      key: "actions",
      width: 380,
      render: (_, row) => {
        const isSelf = row.id === me?.id;
        const manageable = canManage(row);
        return (
          <Space size={4} wrap>
            {manageable && row.role === "member" && (
              <Button size="small" icon={<SafetyOutlined />} onClick={() => openModules(row)}>
                模块权限
              </Button>
            )}
            {isSuperAdmin && manageable && row.role === "member" && (
              <Button size="small" icon={<ShopOutlined />} onClick={() => openStoreAccess(row)}>
                店铺权限
              </Button>
            )}
            {manageable && (
              <Button
                size="small"
                icon={<LockOutlined />}
                onClick={() => {
                  setPasswordTarget(row);
                  setNewPassword("");
                }}
              >
                重置密码
              </Button>
            )}
            {isSuperAdmin && !isSelf && (
              <Button
                size="small"
                icon={<UserSwitchOutlined />}
                onClick={() => {
                  setRoleTarget(row);
                  setRoleValue(row.role);
                }}
              >
                角色
              </Button>
            )}
            {manageable &&
              (row.status === "active" ? (
                <Popconfirm
                  title={`禁用账号 ${row.username}？禁用后该账号将无法登录`}
                  onConfirm={() => changeStatus(row, "disabled")}
                >
                  <Button size="small" danger>
                    禁用
                  </Button>
                </Popconfirm>
              ) : (
                <Popconfirm title={`启用账号 ${row.username}？`} onConfirm={() => changeStatus(row, "active")}>
                  <Button size="small">启用</Button>
                </Popconfirm>
              ))}
            {isSuperAdmin && !isSelf && (
              <Popconfirm
                title={`删除账号 ${row.username}？删除后无法恢复！`}
                okText="删除"
                okButtonProps={{ danger: true }}
                onConfirm={() => deleteAccount(row)}
              >
                <Button size="small" danger icon={<DeleteOutlined />}>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <PageHeader
        icon={<SafetyOutlined />}
        eyebrow="账号与权限"
        title="账号管理"
        extra={
          <Button
            type="primary"
            icon={<UserAddOutlined />}
            onClick={() => {
              createForm.resetFields();
              setCreateOpen(true);
            }}
          >
            新增账号
          </Button>
        }
      />

      <Card variant="borderless">
        <Table<AccountRow>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (total) => `共 ${total} 个账号` }}
          scroll={{ x: 1200 }}
        />
      </Card>

      <Modal
        title={`重置密码：${passwordTarget?.username ?? ""}`}
        open={!!passwordTarget}
        onOk={resetPassword}
        onCancel={() => setPasswordTarget(null)}
        confirmLoading={passwordSaving}
        okText="重置"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">设置新密码后，该账号会立即退出登录，需要重新登录。</Text>
          <Input.Password
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            placeholder="新密码（6-64 位）"
          />
        </Space>
      </Modal>

      <Modal
        title={`模块权限：${modulesTarget?.username ?? ""}`}
        open={!!modulesTarget}
        onOk={saveModules}
        onCancel={() => setModulesTarget(null)}
        confirmLoading={modulesSaving}
        okText="保存"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">
            勾选该账号可见的业务模块；总览和个人中心始终可见，账号管理仅管理员可见。不勾选任何模块 = 仅总览。
          </Text>
          <Checkbox.Group
            options={MODULE_OPTIONS.map((module) => ({ label: module.name, value: module.id }))}
            value={moduleSelection}
            onChange={(values) => setModuleSelection(values as string[])}
          />
        </Space>
      </Modal>

      <Modal
        title={`修改角色：${roleTarget?.username ?? ""}`}
        open={!!roleTarget}
        onOk={saveRole}
        onCancel={() => setRoleTarget(null)}
        confirmLoading={roleSaving}
        okText="保存"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">
            超级管理员可以管理任何人；管理员可以管理普通账号；普通账号仅使用被授权的模块。
          </Text>
          <Radio.Group value={roleValue} onChange={(event) => setRoleValue(event.target.value)}>
            <Space orientation="vertical">
              <Radio value="member">普通账号</Radio>
              <Radio value="admin">管理员</Radio>
              <Radio value="super_admin">超级管理员</Radio>
            </Space>
          </Radio.Group>
        </Space>
      </Modal>

      <Modal
        title={`店铺权限：${storeAccessTarget?.username ?? ""}`}
        open={!!storeAccessTarget}
        onOk={saveStoreAccess}
        onCancel={() => setStoreAccessTarget(null)}
        confirmLoading={storeAccessSaving}
        okText="保存"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">
            勾选该账号可见的店铺；不勾选任何店铺 = 不可见任何店铺。管理员和超级管理员始终可见全部店铺。
          </Text>
          <Checkbox.Group
            options={storeOptions}
            value={storeSelection}
            onChange={(values) => setStoreSelection(values as number[])}
          />
        </Space>
      </Modal>

      <Modal
        title="新增账号"
        open={createOpen}
        onOk={() => createForm.submit()}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={createSaving}
        okText="创建"
      >
        <Form
          form={createForm}
          layout="vertical"
          onFinish={createAccount}
          initialValues={{ role: "member" }}
          style={{ marginTop: 8 }}
        >
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
          {isSuperAdmin && (
            <Form.Item name="role" label="角色">
              <Radio.Group>
                <Radio value="member">普通账号</Radio>
                <Radio value="admin">管理员</Radio>
              </Radio.Group>
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
}
