import {
  BarChartOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SafetyOutlined,
  ShopOutlined,
  StopOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";
import { PageHeader } from "../components/ui/page-header";
import { StoreCompareModal } from "../components/stores/store-compare";
import { StoreDetailDrawer } from "../components/stores/store-detail";
import type { Store, StoreAlert, StoreLog } from "../types";

const { Text } = Typography;

const CATEGORY_OPTIONS = ["女装", "男装", "美妆", "食品", "数码", "家居", "母婴", "其他"];
const LEVEL_OPTIONS = ["天猫旗舰店", "天猫专卖店", "金冠店", "皇冠店", "五钻店", "四钻店", "其他"];

type StoreFormValues = {
  name: string;
  owner?: string;
  category?: string;
  level?: string;
  location?: string;
  dsr_desc?: number;
  dsr_service?: number;
  dsr_logistics?: number;
  auth_expires_at?: dayjs.Dayjs;
};

function StatusTag({ status }: { status: Store["display_status"] }) {
  if (status === "active") return <Tag color="green">正常</Tag>;
  if (status === "auth_expired") return <Tag color="orange">授权过期</Tag>;
  if (status === "auth_error") return <Tag color="red">授权异常</Tag>;
  return <Tag>已停用</Tag>;
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = dayjs(value);
  return parsed.isValid() ? parsed.format("YYYY-MM-DD") : "—";
}

export function StoresPage() {
  const { stores, currentStore, setCurrent, refresh } = useStores();
  const [form] = Form.useForm<StoreFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Store | null>(null);
  const [saving, setSaving] = useState(false);
  const [detailStore, setDetailStore] = useState<Store | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [alerts, setAlerts] = useState<StoreAlert[]>([]);
  const [inspectedAt, setInspectedAt] = useState<string | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [logs, setLogs] = useState<StoreLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [sycmStore, setSycmStore] = useState<Store | null>(null);
  const [sycmOpen, setSycmOpen] = useState(false);
  const [sycmUsername, setSycmUsername] = useState("");
  const [sycmPassword, setSycmPassword] = useState("");
  const [sycmCookie, setSycmCookie] = useState("");
  const [sycmSaving, setSycmSaving] = useState(false);
  const [sycmTesting, setSycmTesting] = useState(false);
  const [sycmSyncing, setSycmSyncing] = useState(false);

  const ACTION_LABELS: Record<string, string> = {
    bind: "绑定店铺",
    edit: "编辑店铺",
    unbind: "解绑店铺",
    refresh_auth: "刷新授权",
    status: "状态变更",
    current: "切换当前店",
    inspect: "巡检",
    perm: "店铺权限",
  };

  const loadAlerts = async () => {
    try {
      const { data } = await http.get<{ items: StoreAlert[]; inspected_at: string | null }>("/stores/alerts");
      setAlerts(data.items);
      setInspectedAt(data.inspected_at);
    } catch {
      setAlerts([]);
      setInspectedAt(null);
    }
  };

  useEffect(() => {
    loadAlerts();
  }, []);

  const total = stores.length;
  const normal = stores.filter((store) => store.display_status === "active").length;
  const attention = total - normal;

  const openCreate = () => {
    form.resetFields();
    setEditing(null);
    setModalOpen(true);
  };

  const openEdit = (row: Store) => {
    form.setFieldsValue({
      name: row.name,
      owner: row.owner,
      category: row.category || undefined,
      level: row.level || undefined,
      location: row.location,
      dsr_desc: row.dsr_desc,
      dsr_service: row.dsr_service,
      dsr_logistics: row.dsr_logistics,
      auth_expires_at: row.auth_expires_at ? dayjs(row.auth_expires_at) : undefined,
    });
    setEditing(row);
    setModalOpen(true);
  };

  const submit = async (values: StoreFormValues) => {
    setSaving(true);
    try {
      const payload = {
        name: values.name.trim(),
        owner: values.owner?.trim() ?? "",
        category: values.category ?? "",
        level: values.level ?? "",
        location: values.location?.trim() ?? "",
        dsr_desc: values.dsr_desc ?? 0,
        dsr_service: values.dsr_service ?? 0,
        dsr_logistics: values.dsr_logistics ?? 0,
        auth_expires_at: values.auth_expires_at ? values.auth_expires_at.toISOString() : "",
      };
      if (editing) {
        await http.put(`/stores/${editing.id}`, payload);
        message.success("店铺信息已更新");
      } else {
        await http.post("/stores", payload);
        message.success("店铺已绑定");
      }
      setModalOpen(false);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const switchCurrent = async (row: Store) => {
    try {
      await setCurrent(row.id);
      message.success(`当前店铺已切换为「${row.name}」`);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const refreshAuth = async (row: Store) => {
    try {
      await http.post(`/stores/${row.id}/auth`);
      message.success(`「${row.name}」授权已刷新`);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const toggleStatus = async (row: Store) => {
    try {
      const status = row.status === "stopped" ? "active" : "stopped";
      await http.post(`/stores/${row.id}/status`, { status });
      message.success(status === "stopped" ? `「${row.name}」已停用` : `「${row.name}」已启用`);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const unbind = async (row: Store) => {
    try {
      await http.delete(`/stores/${row.id}`);
      message.success(`「${row.name}」已解绑`);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const handleInspect = async () => {
    setInspecting(true);
    try {
      const { data } = await http.post<{
        ok: boolean;
        inspected_at: string | null;
        updated: number;
        alerts_count: number;
      }>("/stores/inspect");
      message.success(`巡检完成：更新 ${data.updated} 家店铺，当前共 ${data.alerts_count} 条提醒`);
      setInspectedAt(data.inspected_at);
      await Promise.all([refresh(), loadAlerts()]);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setInspecting(false);
    }
  };

  const loadLogs = async () => {
    setLogsLoading(true);
    try {
      const { data } = await http.get<{ items: StoreLog[] }>("/stores/logs");
      setLogs(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLogsLoading(false);
    }
  };

  const columns: TableColumnsType<Store> = [
    {
      title: "店铺",
      key: "name",
      render: (_, row) => (
        <Space size={6} align="center">
          <Text strong>{row.name}</Text>
          {row.id === currentStore?.id && <Tag color="orange">当前</Tag>}
        </Space>
      ),
    },
    { title: "掌柜", dataIndex: "owner", render: (value: string) => value || "—" },
    { title: "主营类目", dataIndex: "category", render: (value: string) => value || "—" },
    { title: "等级", dataIndex: "level", render: (value: string) => value || "—" },
    {
      title: "DSR 描述/服务/物流",
      key: "dsr",
      render: (_, row) => `${row.dsr_desc.toFixed(1)} / ${row.dsr_service.toFixed(1)} / ${row.dsr_logistics.toFixed(1)}`,
    },
    { title: "所在地", dataIndex: "location", render: (value: string) => value || "—" },
    {
      title: "健康状态",
      dataIndex: "display_status",
      render: (_, row) => <StatusTag status={row.display_status} />,
    },
    {
      title: "授权到期",
      dataIndex: "auth_expires_at",
      render: (_, row) => {
        const expired = row.display_status === "auth_expired";
        return (
          <Text style={expired ? { color: "#ff4d4f" } : undefined}>
            {formatDate(row.auth_expires_at)}
            {expired && "（已过期）"}
          </Text>
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 340,
      render: (_, row) => {
        const isCurrent = row.id === currentStore?.id;
        return (
          <Space size={4} wrap>
            <Button size="small" icon={<EyeOutlined />} onClick={() => { setDetailStore(row); setDetailOpen(true); }}>
              详情
            </Button>
            <Button size="small" type="primary" ghost disabled={isCurrent} onClick={() => switchCurrent(row)}>
              设为当前
            </Button>
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
              编辑
            </Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => refreshAuth(row)}>
              刷新授权
            </Button>
            <Button
              size="small"
              icon={<BarChartOutlined />}
              type={row.sycm_configured ? "default" : "dashed"}
              onClick={() => openSycm(row)}
            >
              生意参谋{row.sycm_configured ? "" : "·未配置"}
            </Button>
            <Popconfirm
              title={row.status === "stopped" ? `启用店铺 ${row.name}？` : `停用店铺 ${row.name}？`}
              onConfirm={() => toggleStatus(row)}
            >
              <Button size="small" icon={<StopOutlined />}>
                {row.status === "stopped" ? "启用" : "停用"}
              </Button>
            </Popconfirm>
            <Popconfirm
              title={`解绑店铺 ${row.name}？解绑后不可恢复`}
              okText="解绑"
              okButtonProps={{ danger: true }}
              onConfirm={() => unbind(row)}
            >
              <Button size="small" danger icon={<DeleteOutlined />}>
                解绑
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  const openSycm = (row: Store) => {
    setSycmStore(row);
    setSycmUsername(row.sycm_username || "");
    setSycmPassword("");
    setSycmCookie("");
    setSycmOpen(true);
  };

  const saveSycm = async () => {
    if (!sycmStore) return;
    setSycmSaving(true);
    try {
      await http.put(`/stores/${sycmStore.id}/sycm`, {
        username: sycmUsername,
        password: sycmPassword,
        cookie: sycmCookie,
      });
      message.success("生意参谋配置已保存");
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSycmSaving(false);
    }
  };

  const testSycm = async () => {
    if (!sycmStore) return;
    setSycmTesting(true);
    try {
      await http.post(`/stores/${sycmStore.id}/sycm/test`);
      message.success("生意参谋登录正常");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSycmTesting(false);
    }
  };

  const syncSycm = async () => {
    if (!sycmStore) return;
    setSycmSyncing(true);
    try {
      await http.post(`/stores/${sycmStore.id}/sync`);
      message.success("已同步该店铺数据");
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSycmSyncing(false);
    }
  };

  const syncAllSycm = async () => {
    try {
      const { data } = await http.post<{ ok: number; total: number }>("/stores/sync-all");
      message.success(`同步完成：成功 ${data.ok} / 共 ${data.total} 家`);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  return (
    <div>
      <PageHeader
        icon={<ShopOutlined />}
        eyebrow="店铺管理"
        title="店铺管理"
        extra={
          <Space>
            <Button icon={<HistoryOutlined />} onClick={() => { setLogsOpen(true); loadLogs(); }}>
              操作日志
            </Button>
            <Button icon={<BarChartOutlined />} onClick={() => setCompareOpen(true)}>
              多店对比
            </Button>
            <Button icon={<SyncOutlined />} onClick={syncAllSycm}>
              同步数据
            </Button>
            <Button type="primary" icon={<SafetyOutlined />} onClick={openCreate}>
              绑定店铺
            </Button>
          </Space>
        }
      />

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              店铺总数
            </Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2 }}>{total}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              状态正常
            </Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: "#52c41a" }}>{normal}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              需要关注
            </Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: attention > 0 ? "#fa8c16" : undefined }}>
              {attention}
            </div>
          </Card>
        </Col>
      </Row>

      <Card variant="borderless" style={{ marginBottom: 16 }} styles={{ body: { padding: "10px 20px 14px" } }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "6px 0 4px",
          }}
        >
          <Space size={10}>
            <Text strong>经营提醒</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              最近巡检：{inspectedAt ? dayjs(inspectedAt).format("YYYY-MM-DD HH:mm") : "尚未巡检"}
            </Text>
          </Space>
          <Button size="small" icon={<ThunderboltOutlined />} loading={inspecting} onClick={handleInspect}>
            立即巡检
          </Button>
        </div>
        {alerts.length === 0 ? (
          <Empty description="暂无提醒，一切正常" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: "10px 0 4px" }} />
        ) : (
          <div>
            {alerts.slice(0, 6).map((alert) => (
              <div
                key={alert.id}
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "center",
                  padding: "7px 0",
                  borderBottom: "1px solid var(--ops-border)",
                }}
              >
                <Tag
                  color={alert.level === "error" ? "red" : alert.level === "warn" ? "orange" : "default"}
                  style={{ marginInlineEnd: 0, flexShrink: 0 }}
                >
                  {alert.level === "error" ? "严重" : alert.level === "warn" ? "提醒" : "提示"}
                </Tag>
                <Text style={{ fontSize: 13, flex: 1 }}>{alert.message}</Text>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card variant="borderless">
        <Table<Store>
          rowKey="id"
          loading={false}
          columns={columns}
          dataSource={stores}
          pagination={{ pageSize: 10, showTotal: (count) => `共 ${count} 家店铺` }}
          scroll={{ x: 1200 }}
        />
      </Card>

      <Modal
        title={editing ? `编辑店铺：${editing.name}` : "绑定店铺"}
        open={modalOpen}
        onOk={() => form.submit()}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText={editing ? "保存" : "绑定"}
      >
        <Form form={form} layout="vertical" onFinish={submit} style={{ marginTop: 8 }}>
          <Form.Item
            name="name"
            label="店铺名称"
            rules={[
              { required: true, message: "请输入店铺名称" },
              { max: 50, message: "店铺名称不能超过 50 个字符" },
            ]}
          >
            <Input placeholder="如：淘品甄选旗舰店" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="owner" label="掌柜名">
                <Input placeholder="掌柜名" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="category" label="主营类目">
                <Select placeholder="选择类目" options={CATEGORY_OPTIONS.map((value) => ({ value, label: value }))} allowClear />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="level" label="店铺等级">
                <Select placeholder="选择等级" options={LEVEL_OPTIONS.map((value) => ({ value, label: value }))} allowClear />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="location" label="所在地">
                <Input placeholder="如：浙江·杭州" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="dsr_desc" label="DSR 描述">
                <InputNumber min={0} max={5} step={0.1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="dsr_service" label="DSR 服务">
                <InputNumber min={0} max={5} step={0.1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="dsr_logistics" label="DSR 物流">
                <InputNumber min={0} max={5} step={0.1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="auth_expires_at" label="授权到期">
            <DatePicker style={{ width: "100%" }} placeholder="默认 90 天后" />
          </Form.Item>
        </Form>
      </Modal>

      <StoreDetailDrawer
        store={detailStore}
        open={detailOpen}
        alerts={alerts}
        onClose={() => setDetailOpen(false)}
      />
      <StoreCompareModal open={compareOpen} onClose={() => setCompareOpen(false)} />
      <Modal
        title="操作日志"
        open={logsOpen}
        onCancel={() => setLogsOpen(false)}
        footer={null}
        width={760}
      >
        <Table<StoreLog>
          rowKey="id"
          size="small"
          loading={logsLoading}
          dataSource={logs}
          pagination={{ pageSize: 10, showTotal: (count) => `共 ${count} 条` }}
          scroll={{ x: 640 }}
          columns={[
            {
              title: "时间",
              dataIndex: "created_at",
              render: (value: string) => dayjs(value).format("YYYY-MM-DD HH:mm:ss"),
            },
            { title: "操作人", dataIndex: "username" },
            {
              title: "操作",
              dataIndex: "action",
              render: (value: string) => ACTION_LABELS[value] ?? value,
            },
            { title: "对象", dataIndex: "target_name", render: (value: string) => value || "—" },
            { title: "详情", dataIndex: "detail", render: (value: string) => value || "—" },
          ]}
        />
      </Modal>

      <Modal
        title={`生意参谋数据源 · ${sycmStore?.name ?? ""}`}
        open={sycmOpen}
        onCancel={() => setSycmOpen(false)}
        footer={
          <Space>
            <Button icon={<ThunderboltOutlined />} loading={sycmTesting} onClick={testSycm}>
              测试连接
            </Button>
            <Button icon={<SyncOutlined />} loading={sycmSyncing} onClick={syncSycm}>
              同步数据
            </Button>
            <Button type="primary" loading={sycmSaving} onClick={saveSycm}>
              保存
            </Button>
          </Space>
        }
        destroyOnClose
      >
        <div style={{ marginBottom: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            当前状态：
            {sycmStore?.sycm_configured ? (
              <Tag color="green">已配置</Tag>
            ) : (
              <Tag color="orange">未配置</Tag>
            )}
            {sycmStore?.sycm_cookie_masked ? ` Cookie：${sycmStore.sycm_cookie_masked}` : ""}
          </Text>
        </div>
        <Form layout="vertical">
          <Form.Item label="账号">
            <Input
              value={sycmUsername}
              onChange={(event) => setSycmUsername(event.target.value)}
              placeholder="生意参谋登录账号"
            />
          </Form.Item>
          <Form.Item label="密码">
            <Input.Password
              value={sycmPassword}
              onChange={(event) => setSycmPassword(event.target.value)}
              placeholder="留空不修改"
            />
          </Form.Item>
          <Form.Item
            label="登录凭证 Cookie"
            extra="在浏览器登录生意参谋后，从开发者工具复制 Cookie 粘贴到这里；留空不修改"
          >
            <Input.TextArea
              rows={4}
              value={sycmCookie}
              onChange={(event) => setSycmCookie(event.target.value)}
              placeholder="粘贴生意参谋 Cookie"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
