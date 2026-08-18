import {
  ClockCircleOutlined,
  CopyOutlined,
  DeleteOutlined,
  HistoryOutlined,
  LockOutlined,
  SafetyOutlined,
  SearchOutlined,
  ShopOutlined,
  UserAddOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Checkbox,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Row,
  Col,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import { ColumnSettings } from "../components/ui/column-settings";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";

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
  status: "active" | "disabled" | "pending";
  allowed_modules: string[] | null;
  allowed_store_ids: number[] | null;
  created_at: string;
  last_login_at: string | null;
  last_login_ip: string | null;
  expires_at: string | null;
  failed_count: number;
  locked_until: string | null;
  sub_account_quota: number;
  store_quota: number;
  parent_id: number | null;
};

type SessionRow = {
  token: string;
  created_at: string;
  expires_at: string | null;
};

type LoginLogRow = {
  id: number;
  user_id: number;
  username: string;
  action: "login" | "fail" | "logout";
  ip: string;
  user_agent: string;
  detail: string;
  created_at: string;
};

type OpLogRow = {
  module: string;
  action: string;
  target_name: string;
  detail: string;
  created_at: string;
};

type TenantAccountRow = {
  id: number;
  username: string;
  nickname: string;
  role: Role;
  status: string;
  store_count: number;
  store_names: string[];
  last_login_at: string | null;
  last_login_ip: string | null;
  expires_at: string | null;
  created_at: string;
};

type TenantOverview = {
  summary: {
    total_accounts: number;
    super_admin: number;
    admin: number;
    member: number;
    disabled: number;
    total_stores: number;
    bound_accounts: number;
    unbound_accounts: number;
    total_bindings: number;
  };
  accounts: TenantAccountRow[];
  recent_logins: { id: number; user_id: number; username: string; action: string; ip: string; created_at: string }[];
};

type AnnouncementRow = {
  id: number;
  title: string;
  content: string;
  created_by: number | null;
  created_at: string;
  active: boolean;
};

type InviteRow = {
  id: number;
  code: string;
  note: string;
  created_by: number | null;
  created_at: string;
  expires_at: string | null;
  max_uses: number;
  used_count: number;
  status: "active" | "disabled";
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

  const [tab, setTab] = useState("accounts");
  const [pendingItems, setPendingItems] = useState<AccountRow[]>([]);
  const [invites, setInvites] = useState<InviteRow[]>([]);
  const [inviteForm] = Form.useForm();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteSaving, setInviteSaving] = useState(false);

  // 搜索 + 筛选
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");


  // 会话管理
  const [sessionsTarget, setSessionsTarget] = useState<AccountRow | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);

  // 单账号操作日志
  const [logsTarget, setLogsTarget] = useState<AccountRow | null>(null);
  const [userLogs, setUserLogs] = useState<OpLogRow[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  // 账号有效期
  const [expiryTarget, setExpiryTarget] = useState<AccountRow | null>(null);
  const [expiryValue, setExpiryValue] = useState<dayjs.Dayjs | null>(null);
  const [expirySaving, setExpirySaving] = useState(false);

  // 权限复制
  const [copyTarget, setCopyTarget] = useState<AccountRow | null>(null);
  const [copySource, setCopySource] = useState<number | null>(null);
  const [copyOptions, setCopyOptions] = useState<{ value: number; label: string }[]>([]);
  const [copySaving, setCopySaving] = useState(false);

  // 登录日志
  const [loginLogs, setLoginLogs] = useState<LoginLogRow[]>([]);
  const [loginLogsLoading, setLoginLogsLoading] = useState(false);

  // 租户概览
  const [tenant, setTenant] = useState<TenantOverview | null>(null);
  const [tenantLoading, setTenantLoading] = useState(false);

  // 系统公告
  const [announcements, setAnnouncements] = useState<AnnouncementRow[]>([]);
  const [annLoading, setAnnLoading] = useState(false);
  const [annOpen, setAnnOpen] = useState(false);
  const [annEditing, setAnnEditing] = useState<AnnouncementRow | null>(null);
  const [annSaving, setAnnSaving] = useState(false);
  const [annForm] = Form.useForm<{ title: string; content: string }>();

  // 配额设置
  const [quotaTarget, setQuotaTarget] = useState<AccountRow | null>(null);
  const [quotaSub, setQuotaSub] = useState<number>(2);
  const [quotaStore, setQuotaStore] = useState<number>(3);
  const [quotaSaving, setQuotaSaving] = useState(false);

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

  const loadPending = useCallback(async () => {
    try {
      const { data } = await http.get<{ items: AccountRow[] }>("/accounts/pending");
      setPendingItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  }, []);

  const loadInvites = useCallback(async () => {
    try {
      const { data } = await http.get<{ items: InviteRow[] }>("/accounts/invite-codes");
      setInvites(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  }, []);

  const loadLoginLogs = useCallback(async () => {
    setLoginLogsLoading(true);
    try {
      const { data } = await http.get<{ items: LoginLogRow[] }>("/accounts/login-logs", { params: { limit: 200 } });
      setLoginLogs(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoginLogsLoading(false);
    }
  }, []);

  const loadTenant = useCallback(async () => {
    setTenantLoading(true);
    try {
      const { data } = await http.get<TenantOverview>("/system/tenant-overview");
      setTenant(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTenantLoading(false);
    }
  }, []);

  const loadAnnouncements = useCallback(async () => {
    setAnnLoading(true);
    try {
      const { data } = await http.get<{ items: AnnouncementRow[] }>("/announcements");
      setAnnouncements(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAnnLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    loadPending();
    loadInvites();
    loadLoginLogs();
    loadTenant();
    loadAnnouncements();
  }, [load, loadPending, loadInvites, loadLoginLogs, loadTenant, loadAnnouncements]);

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

  const createInvite = async (values: { note?: string; max_uses?: number; expires_at?: unknown }) => {
    setInviteSaving(true);
    try {
      await http.post("/accounts/invite-codes", {
        note: values.note ?? "",
        max_uses: values.max_uses ?? 1,
        expires_at: values.expires_at ? (values.expires_at as dayjs.Dayjs).toISOString() : "",
      });
      message.success("邀请码已生成");
      setInviteOpen(false);
      inviteForm.resetFields();
      loadInvites();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setInviteSaving(false);
    }
  };

  const disableInvite = async (row: InviteRow) => {
    try {
      await http.post(`/accounts/invite-codes/${row.id}/disable`, {});
      message.success("邀请码已作废");
      loadInvites();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const deleteInvite = async (row: InviteRow) => {
    try {
      await http.delete(`/accounts/invite-codes/${row.id}`);
      message.success("邀请码已删除");
      loadInvites();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const approveUser = async (row: AccountRow) => {
    try {
      await http.post(`/accounts/${row.id}/approve`, {});
      message.success(`已通过 ${row.username} 的注册申请`);
      loadPending();
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const rejectUser = async (row: AccountRow) => {
    try {
      await http.post(`/accounts/${row.id}/reject`, {});
      message.success(`已拒绝 ${row.username} 的注册申请`);
      loadPending();
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };


  // ---- 会话管理 ----
  const openSessions = async (row: AccountRow) => {
    setSessionsTarget(row);
    setSessions([]);
    setSessionsLoading(true);
    try {
      const { data } = await http.get<{ items: SessionRow[] }>(`/accounts/${row.id}/sessions`);
      setSessions(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSessionsLoading(false);
    }
  };

  const revokeSession = async (session: SessionRow) => {
    if (!sessionsTarget) return;
    try {
      await http.post(`/accounts/${sessionsTarget.id}/sessions/${session.token}/revoke`, {});
      message.success("该会话已强制下线");
      openSessions(sessionsTarget);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  // ---- 单账号操作日志 ----
  const openUserLogs = async (row: AccountRow) => {
    setLogsTarget(row);
    setUserLogs([]);
    setLogsLoading(true);
    try {
      const { data } = await http.get<{ items: OpLogRow[]; username: string }>(`/accounts/${row.id}/logs`);
      setUserLogs(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLogsLoading(false);
    }
  };

  // ---- 账号有效期 ----
  const openExpiry = (row: AccountRow) => {
    setExpiryTarget(row);
    setExpiryValue(row.expires_at ? dayjs(row.expires_at) : null);
  };

  const saveExpiry = async () => {
    if (!expiryTarget) return;
    setExpirySaving(true);
    try {
      await http.post(`/accounts/${expiryTarget.id}/expiry`, {
        expires_at: expiryValue ? expiryValue.toISOString() : "",
      });
      message.success("有效期已更新");
      setExpiryTarget(null);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setExpirySaving(false);
    }
  };

  // ---- 权限复制 ----
  const openCopy = async (row: AccountRow) => {
    setCopyTarget(row);
    setCopySource(null);
    try {
      const { data } = await http.get<{ items: AccountRow[] }>("/accounts");
      setCopyOptions(
        data.items
          .filter((account) => account.id !== row.id && account.status === "active")
          .map((account) => ({ value: account.id, label: `${account.username}（${account.nickname}）` }))
      );
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setCopyTarget(null);
    }
  };

  const saveCopy = async () => {
    if (!copyTarget || !copySource) {
      message.error("请选择要复制权限的源账号");
      return;
    }
    setCopySaving(true);
    try {
      await http.post(`/accounts/${copyTarget.id}/copy-permissions`, { source_user_id: copySource });
      message.success("权限已复制");
      setCopyTarget(null);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setCopySaving(false);
    }
  };
  const saveAnnouncement = async (values: { title: string; content: string }) => {
    setAnnSaving(true);
    try {
      if (annEditing) {
        await http.put(`/announcements/${annEditing.id}`, values);
        message.success("公告已更新");
      } else {
        await http.post("/announcements", values);
        message.success("公告已发布");
      }
      setAnnOpen(false);
      setAnnEditing(null);
      loadAnnouncements();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setAnnSaving(false);
    }
  };

  const toggleAnnouncement = async (row: AnnouncementRow) => {
    try {
      await http.post(`/announcements/${row.id}/toggle`, {});
      message.success(row.active ? "公告已停用" : "公告已启用");
      loadAnnouncements();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const deleteAnnouncement = async (row: AnnouncementRow) => {
    try {
      await http.delete(`/announcements/${row.id}`);
      message.success("公告已删除");
      loadAnnouncements();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };
  const openQuota = (row: AccountRow) => {
    setQuotaTarget(row);
    setQuotaSub(row.sub_account_quota ?? 2);
    setQuotaStore(row.store_quota ?? 3);
  };

  const saveQuota = async () => {
    if (!quotaTarget) return;
    setQuotaSaving(true);
    try {
      await http.post(`/accounts/${quotaTarget.id}/quota`, {
        sub_account_quota: quotaSub,
        store_quota: quotaStore,
      });
      message.success("配额已更新");
      setQuotaTarget(null);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setQuotaSaving(false);
    }
  };
  const inviteColumns: TableColumnsType<InviteRow> = [
    {
      title: "邀请码",
      dataIndex: "code",
      render: (code: string, row) => (
        <Space size={6}>
          <Text strong style={{ fontFamily: "monospace", letterSpacing: 1 }}>{code}</Text>
          {row.status === "disabled" && <Tag color="default">已作废</Tag>}
        </Space>
      ),
    },
    {
      title: "备注",
      dataIndex: "note",
      render: (value: string) => value || "—",
    },
    {
      title: "已用/上限",
      key: "uses",
      render: (_, row) => (
        <Text>{row.used_count} / {row.max_uses}</Text>
      ),
    },
    {
      title: "过期时间",
      dataIndex: "expires_at",
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "永久有效",
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      render: (_, row) => (
        <Space size={4}>
          {row.status === "active" && (
            <Popconfirm title={`作废邀请码 ${row.code}？`} onConfirm={() => disableInvite(row)}>
              <Button size="small">作废</Button>
            </Popconfirm>
          )}
          <Popconfirm
            title={`删除邀请码 ${row.code}？`}
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={() => deleteInvite(row)}
          >
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const pendingColumns: TableColumnsType<AccountRow> = [
    {
      title: "账号",
      dataIndex: "username",
      render: (_, row) => <Text strong>{row.username}</Text>,
    },
    {
      title: "花名",
      dataIndex: "nickname",
      render: (value: string) => value || "—",
    },
    {
      title: "申请时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    {
      title: "操作",
      key: "actions",
      width: 180,
      render: (_, row) => (
        <Space size={4}>
          <Button size="small" type="primary" onClick={() => approveUser(row)}>通过</Button>
          <Popconfirm
            title={`拒绝并删除 ${row.username} 的注册申请？`}
            okText="拒绝"
            okButtonProps={{ danger: true }}
            onConfirm={() => rejectUser(row)}
          >
            <Button size="small" danger>拒绝</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];
  const filteredItems = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    return items.filter((row) => {
      if (roleFilter !== "all" && row.role !== roleFilter) return false;
      if (statusFilter !== "all" && row.status !== statusFilter) return false;
      if (
        keyword &&
        !row.username.toLowerCase().includes(keyword) &&
        !(row.nickname || "").toLowerCase().includes(keyword)
      ) {
        return false;
      }
      return true;
    });
  }, [items, search, roleFilter, statusFilter]);

  const loginLogColumns: TableColumnsType<LoginLogRow> = [
    {
      title: "时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    {
      title: "账号",
      dataIndex: "username",
      render: (_, row) =>
        row.username ? <Text strong>{row.username}</Text> : <Text type="secondary">未知</Text>,
    },
    {
      title: "类型",
      dataIndex: "action",
      render: (action: LoginLogRow["action"]) =>
        action === "login" ? (
          <Tag color="green">登录成功</Tag>
        ) : action === "logout" ? (
          <Tag>登出</Tag>
        ) : (
          <Tag color="red">登录失败</Tag>
        ),
    },
    {
      title: "IP",
      dataIndex: "ip",
      render: (value: string) => value || "—",
    },
    {
      title: "说明",
      dataIndex: "detail",
      render: (value: string) => value || "—",
    },
    {
      title: "设备",
      dataIndex: "user_agent",
      render: (value: string) =>
        value ? (
          <Tooltip title={value}>
            <Text style={{ fontSize: 12 }}>{value.slice(0, 40)}</Text>
          </Tooltip>
        ) : (
          "—"
        ),
    },
  ];

  const sessionColumns: TableColumnsType<SessionRow> = [
    {
      title: "登录时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    {
      title: "过期时间",
      dataIndex: "expires_at",
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—",
    },
    {
      title: "操作",
      key: "actions",
      render: (_, row) => (
        <Popconfirm
          title="强制下线该会话？该设备将立即退出登录"
          onConfirm={() => revokeSession(row)}
        >
          <Button size="small" danger>
            强制下线
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const userLogColumns: TableColumnsType<OpLogRow> = [
    {
      title: "时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    { title: "模块", dataIndex: "module" },
    { title: "操作", dataIndex: "action" },
    { title: "对象", dataIndex: "target_name", render: (value: string) => value || "—" },
    { title: "详情", dataIndex: "detail", render: (value: string) => value || "—" },
  ];
  const columns: TableColumnsType<AccountRow> = [
    {
      title: "账号",
      dataIndex: "username",
      render: (_, row) => (
        <Space size={6}>
          <Text strong>{row.username}</Text>
          {row.id === me?.id && <Tag color="gold">当前账号</Tag>}
          {row.locked_until && <Tag color="red">已锁定</Tag>}
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
      title: "最后登录",
      dataIndex: "last_login_at",
      render: (value: string | null, row) =>
        value ? (
          <Space size={2} orientation="vertical" style={{ gap: 0 }}>
            <Text style={{ fontSize: 12 }}>{new Date(value).toLocaleString("zh-CN", { hour12: false })}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>{row.last_login_ip || ""}</Text>
          </Space>
        ) : (
          <Text type="secondary">从未登录</Text>
        ),
    },
    {
      title: "有效期",
      dataIndex: "expires_at",
      render: (value: string | null) =>
        value ? <Tag color="orange">至 {new Date(value).toLocaleDateString("zh-CN")}</Tag> : <Tag>永久</Tag>,
    },
    {
      title: "注册时间",
      dataIndex: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
    },
    {
      title: "操作",
      key: "actions",
      width: 560,
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
            {manageable && row.role === "member" && (
              <Button size="small" icon={<CopyOutlined />} onClick={() => openCopy(row)}>
                复制权限
              </Button>
            )}
            {manageable && (
              <Button size="small" icon={<HistoryOutlined />} onClick={() => openSessions(row)}>
                会话
              </Button>
            )}
            {manageable && (
              <Button size="small" icon={<HistoryOutlined />} onClick={() => openUserLogs(row)}>
                日志
              </Button>
            )}
            {manageable && (
              <Button size="small" icon={<ClockCircleOutlined />} onClick={() => openExpiry(row)}>
                有效期
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
            {isSuperAdmin && manageable && row.role === "member" && !row.parent_id && (
              <Button size="small" icon={<SafetyOutlined />} onClick={() => openQuota(row)}>
                配额
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

  // —— 字段设置：列显隐 + 列顺序（本地持久化） ——
  const [hiddenCols, setHiddenCols] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("tb-accounts-cols") || "{}").hidden ?? [];
    } catch {
      return [];
    }
  });
  const [colOrder, setColOrder] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("tb-accounts-cols") || "{}").order ?? [];
    } catch {
      return [];
    }
  });
  useEffect(() => {
    localStorage.setItem("tb-accounts-cols", JSON.stringify({ hidden: hiddenCols, order: colOrder }));
  }, [hiddenCols, colOrder]);
  const colKey = (col: (typeof columns)[number]) => String((col as { key?: string }).key ?? (col as { dataIndex?: string }).dataIndex ?? "");
  const visibleColumns = columns
    .filter((col) => {
      const k = colKey(col);
      return !k || !hiddenCols.includes(k);
    })
    .sort((a, b) => {
      const ia = colOrder.indexOf(colKey(a));
      const ib = colOrder.indexOf(colKey(b));
      return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
    });
  const colDefs = columns
    .map((col) => ({ key: colKey(col), title: col.title as string }))
    .filter((c) => c.key);
  const tableX = visibleColumns.reduce((sum, col) => sum + ((col.width as number) || 100), 0);

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

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "accounts",
            label: "账号列表",
            children: (
              <Card variant="borderless">
                <Space style={{ marginBottom: 12 }} wrap>
                  <ColumnSettings
                    columns={colDefs}
                    hidden={hiddenCols}
                    order={colOrder}
                    onChange={({ hidden, order }) => {
                      setHiddenCols(hidden);
                      setColOrder(order);
                    }}
                  />
                  <Input
                    allowClear
                    placeholder="搜索用户名 / 花名"
                    prefix={<SearchOutlined />}
                    style={{ width: 220 }}
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                  <Select
                    style={{ width: 140 }}
                    value={roleFilter}
                    onChange={setRoleFilter}
                    options={[
                      { value: "all", label: "全部角色" },
                      { value: "super_admin", label: "超级管理员" },
                      { value: "admin", label: "管理员" },
                      { value: "member", label: "普通账号" },
                    ]}
                  />
                  <Select
                    style={{ width: 140 }}
                    value={statusFilter}
                    onChange={setStatusFilter}
                    options={[
                      { value: "all", label: "全部状态" },
                      { value: "active", label: "正常" },
                      { value: "disabled", label: "已禁用" },
                      { value: "pending", label: "待审核" },
                    ]}
                  />
                </Space>
                <Table<AccountRow>
                  rowKey="id"
                  loading={loading}
                  columns={visibleColumns}
                  dataSource={filteredItems}
                  pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (total) => `共 ${total} 个账号` }}
                  scroll={{ x: tableX }}
                />
              </Card>
            ),
          },
          {
            key: "pending",
            label: pendingItems.length ? `待审核 (${pendingItems.length})` : "待审核",
            children: (
              <Card variant="borderless">
                {pendingItems.length === 0 ? (
                  <Text type="secondary">暂无待审核的注册申请</Text>
                ) : (
                  <Table<AccountRow> rowKey="id" columns={pendingColumns} dataSource={pendingItems} pagination={false} />
                )}
              </Card>
            ),
          },
          {
            key: "invites",
            label: "邀请码",
            children: (
              <Card
                variant="borderless"
                title="员工注册邀请码"
                extra={
                  <Button
                    type="primary"
                    icon={<UserAddOutlined />}
                    onClick={() => {
                      inviteForm.resetFields();
                      setInviteOpen(true);
                    }}
                  >
                    生成邀请码
                  </Button>
                }
              >
                <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
                  凭邀请码注册可直接开通；没有邀请码提交的注册申请会进入「待审核」，管理员通过后才能登录。
                </Text>
                <Table<InviteRow> rowKey="id" columns={inviteColumns} dataSource={invites} pagination={false} scroll={{ x: 900 }} />
              </Card>
            ),
          },
          {
            key: "loginlogs",
            label: "登录日志",
            children: (
              <Card variant="borderless">
                <Table<LoginLogRow>
                  rowKey="id"
                  loading={loginLogsLoading}
                  columns={loginLogColumns}
                  dataSource={loginLogs}
                  pagination={{ defaultPageSize: 20, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100] }}
                  scroll={{ x: 1000 }}
                />
              </Card>
            ),
          },
          {
            key: "tenant",
            label: "租户概览",
            children: (
              <Card variant="borderless" loading={tenantLoading}>
                {tenant && (
                  <>
                    <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                      {[
                        { label: "账号总数", value: tenant.summary.total_accounts, color: "var(--ops-accent)" },
                        { label: "超级管理员", value: tenant.summary.super_admin, color: "#faad14" },
                        { label: "管理员", value: tenant.summary.admin, color: "var(--ops-warn)" },
                        { label: "普通账号", value: tenant.summary.member, color: "var(--ops-success)" },
                        { label: "已禁用", value: tenant.summary.disabled, color: "var(--ops-danger)" },
                        { label: "店铺总数", value: tenant.summary.total_stores, color: "var(--ops-accent)" },
                        { label: "已绑定账号", value: tenant.summary.bound_accounts, color: "var(--ops-success)" },
                        { label: "未绑定账号", value: tenant.summary.unbound_accounts, color: "var(--ops-danger)" },
                        { label: "绑定关系数", value: tenant.summary.total_bindings, color: "var(--ops-cat-2)" },
                      ].map((item) => (
                        <Col xs={12} sm={8} md={6} key={item.label}>
                          <div style={{ background: "var(--ops-card-bg-2)", borderRadius: "var(--ops-radius)", padding: "12px 16px", border: "1px solid var(--ops-border)" }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
                            <div style={{ fontSize: 22, fontWeight: 700, color: item.color }}>{item.value}</div>
                          </div>
                        </Col>
                      ))}
                    </Row>
                    <Text strong style={{ display: "block", margin: "8px 0" }}>账号 · 店铺绑定</Text>
                    <Table<TenantAccountRow>
                      rowKey="id"
                      dataSource={tenant.accounts}
                      pagination={false}
                      size="small"
                      scroll={{ x: 900 }}
                      columns={[
                        {
                          title: "账号",
                          dataIndex: "username",
                          render: (v: string, row) => (
                            <Space size={6}>
                              <Text strong>{v}</Text>
                              {row.role === "super_admin" ? <Tag color="gold">超管</Tag> : row.role === "admin" ? <Tag color="orange">管理员</Tag> : <Tag>普通</Tag>}
                            </Space>
                          ),
                        },
                        { title: "绑定店铺数", dataIndex: "store_count" },
                        {
                          title: "绑定店铺",
                          dataIndex: "store_names",
                          render: (names: string[]) =>
                            names.length === 0 ? (
                              <Text type="secondary">未绑定</Text>
                            ) : names.length <= 3 ? (
                              <Space size={4} wrap>{names.map((n) => <Tag key={n}>{n}</Tag>)}</Space>
                            ) : (
                              <Tooltip title={names.join("、")}>
                                <Text>{names.slice(0, 3).join("、")} 等 {names.length} 家</Text>
                              </Tooltip>
                            ),
                        },
                        {
                          title: "最近登录",
                          dataIndex: "last_login_at",
                          render: (v: string | null) => (v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : <Text type="secondary">从未</Text>),
                        },
                        {
                          title: "有效期",
                          dataIndex: "expires_at",
                          render: (v: string | null) => (v ? <Tag color="orange">至 {new Date(v).toLocaleDateString()}</Tag> : <Tag>永久</Tag>),
                        },
                      ]}
                    />
                    <Text strong style={{ display: "block", margin: "16px 0 8px" }}>最近登录记录</Text>
                    <Table
                      rowKey="id"
                      dataSource={tenant.recent_logins}
                      pagination={false}
                      size="small"
                      columns={[
                        { title: "时间", dataIndex: "created_at", render: (v: string) => new Date(v).toLocaleString("zh-CN", { hour12: false }) },
                        { title: "账号", dataIndex: "username" },
                        { title: "类型", dataIndex: "action", render: (v: string) => (v === "login" ? <Tag color="green">登录成功</Tag> : v === "logout" ? <Tag>登出</Tag> : <Tag color="red">失败</Tag>) },
                        { title: "IP", dataIndex: "ip", render: (v: string) => v || "—" },
                      ]}
                    />
                  </>
                )}
              </Card>
            ),
          },
          {
            key: "announcements",
            label: "公告",
            children: (
              <Card
                variant="borderless"
                title="系统公告"
                extra={
                  <Button
                    type="primary"
                    onClick={() => {
                      annForm.resetFields();
                      setAnnEditing(null);
                      setAnnOpen(true);
                    }}
                  >
                    发布公告
                  </Button>
                }
              >
                <Table<AnnouncementRow>
                  rowKey="id"
                  loading={annLoading}
                  dataSource={announcements}
                  pagination={false}
                  columns={[
                    { title: "标题", dataIndex: "title", render: (v: string) => <Text strong>{v}</Text> },
                    { title: "内容", dataIndex: "content", render: (v: string) => v || "—" },
                    { title: "状态", dataIndex: "active", render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>) },
                    { title: "发布时间", dataIndex: "created_at", render: (v: string) => new Date(v).toLocaleString("zh-CN", { hour12: false }) },
                    {
                      title: "操作",
                      key: "actions",
                      width: 180,
                      render: (_, row) => (
                        <Space size={4}>
                          <Button size="small" onClick={() => { annForm.setFieldsValue({ title: row.title, content: row.content }); setAnnEditing(row); setAnnOpen(true); }}>编辑</Button>
                          <Button size="small" onClick={() => toggleAnnouncement(row)}>{row.active ? "停用" : "启用"}</Button>
                          <Popconfirm title={`删除公告「${row.title}」？`} okText="删除" okButtonProps={{ danger: true }} onConfirm={() => deleteAnnouncement(row)}>
                            <Button size="small" danger>删除</Button>
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
            ),
          },
        ]}
      />

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
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          新账号默认无任何店铺权限，创建后可在「店铺权限」中分配可见店铺。
        </Text>
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

      <Modal
        title="生成邀请码"
        open={inviteOpen}
        onOk={() => inviteForm.submit()}
        onCancel={() => setInviteOpen(false)}
        confirmLoading={inviteSaving}
        okText="生成"
      >
        <Form form={inviteForm} layout="vertical" onFinish={createInvite} initialValues={{ max_uses: 1 }} style={{ marginTop: 8 }}>
          <Form.Item name="note" label="备注（发给谁 / 用途）">
            <Input placeholder="例如：发给张三" maxLength={50} />
          </Form.Item>
          <Form.Item name="max_uses" label="可使用次数" rules={[{ required: true, message: "请输入使用次数" }]}>
            <InputNumber min={1} max={100} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="expires_at" label="过期时间（可选，留空为永久有效）">
            <DatePicker showTime style={{ width: "100%" }} placeholder="选择过期时间" />
          </Form.Item>
        </Form>
      </Modal>


      <Modal
        title={`登录会话：${sessionsTarget?.username ?? ""}`}
        open={!!sessionsTarget}
        onCancel={() => setSessionsTarget(null)}
        footer={null}
        width={640}
      >
        <Table<SessionRow> rowKey="token" loading={sessionsLoading} columns={sessionColumns} dataSource={sessions} pagination={false} />
      </Modal>

      <Modal
        title={`操作日志：${logsTarget?.username ?? ""}`}
        open={!!logsTarget}
        onCancel={() => setLogsTarget(null)}
        footer={null}
        width={760}
      >
        {logsLoading ? (
          <div style={{ textAlign: "center", padding: 24 }}>
            <Spin />
          </div>
        ) : userLogs.length === 0 ? (
          <Empty description="该账号暂无操作记录" />
        ) : (
          <Table<OpLogRow>
            rowKey={(row) => `${row.created_at}-${row.module}-${row.action}`}
            columns={userLogColumns}
            dataSource={userLogs}
            pagination={{ pageSize: 10, showSizeChanger: false }}
            size="small"
            scroll={{ x: 600 }}
          />
        )}
      </Modal>

      <Modal
        title={`设置有效期：${expiryTarget?.username ?? ""}`}
        open={!!expiryTarget}
        onOk={saveExpiry}
        onCancel={() => setExpiryTarget(null)}
        confirmLoading={expirySaving}
        okText="保存"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">设置到期日后，该账号到期将无法登录；留空 = 永久有效。</Text>
          <DatePicker
            showTime
            style={{ width: "100%" }}
            value={expiryValue}
            onChange={(value) => setExpiryValue(value)}
            placeholder="选择到期时间（可清空）"
          />
        </Space>
      </Modal>

      <Modal
        title={`复制权限到：${copyTarget?.username ?? ""}`}
        open={!!copyTarget}
        onOk={saveCopy}
        onCancel={() => setCopyTarget(null)}
        confirmLoading={copySaving}
        okText="复制"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">把源账号的「可见模块 + 可见店铺」权限复制给 {copyTarget?.username ?? ""}。</Text>
          <Select
            style={{ width: "100%" }}
            placeholder="选择源账号"
            value={copySource}
            onChange={setCopySource}
            options={copyOptions}
          />
        </Space>
      </Modal>

      <Modal
        title={annEditing ? "编辑公告" : "发布公告"}
        open={annOpen}
        onOk={() => annForm.submit()}
        onCancel={() => {
          setAnnOpen(false);
          setAnnEditing(null);
        }}
        confirmLoading={annSaving}
        okText="保存"
      >
        <Form form={annForm} layout="vertical" onFinish={saveAnnouncement} style={{ marginTop: 8 }}>
          <Form.Item
            name="title"
            label="标题"
            rules={[
              { required: true, message: "请输入公告标题" },
              { max: 100, message: "标题不能超过 100 字" },
            ]}
          >
            <Input placeholder="公告标题" />
          </Form.Item>
          <Form.Item name="content" label="内容">
            <Input.TextArea rows={4} placeholder="公告内容（可选）" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`设置配额：${quotaTarget?.username ?? ""}`}
        open={!!quotaTarget}
        onOk={saveQuota}
        onCancel={() => setQuotaTarget(null)}
        confirmLoading={quotaSaving}
        okText="保存"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Text type="secondary">子账号配额 = 该账号最多可创建几个子账号；店铺配额 = 最多可绑定几家店铺。</Text>
          <Space>
            <Text>子账号配额：</Text>
            <InputNumber min={0} max={100} value={quotaSub} onChange={(value) => setQuotaSub(value ?? 0)} />
          </Space>
          <Space>
            <Text>店铺配额：</Text>
            <InputNumber min={0} max={100} value={quotaStore} onChange={(value) => setQuotaStore(value ?? 0)} />
          </Space>
        </Space>
      </Modal>
    </div>
  );
}