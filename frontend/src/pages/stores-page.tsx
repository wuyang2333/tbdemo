import {
  CheckOutlined,
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  HistoryOutlined,
  LoginOutlined,
  ReadOutlined,
  SafetyOutlined,
  ShopOutlined,
  SyncOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { showSyncFeedback } from "../lib/sync-feedback";
import { useStores } from "../lib/store";
import { PageHeader } from "../components/ui/page-header";
import { StoreDetailDrawer } from "../components/stores/store-detail";
import type { Store, StoreLog } from "../types";

const { Text } = Typography;

type StoreFormValues = {
  name: string;
};

function LoginStatusTag({ status, error }: { status: Store["sycm_status"]; error: string | null }) {
  if (status === "ok") return <Tag color="green">登录正常</Tag>;
  if (status === "error") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Tag color="red" style={{ width: "fit-content" }}>登录失效</Tag>
        {error ? (
          <Text type="secondary" style={{ fontSize: 12, maxWidth: 200 }} ellipsis={{ tooltip: error }}>
            {error}
          </Text>
        ) : null}
      </div>
    );
  }
  if (status === "not_configured") return <Tag>未绑定</Tag>;
  return <Tag color="orange">检测中</Tag>;
}

function timeAgo(value: string | null): string {
  if (!value) return "从未同步";
  const diff = Date.now() - dayjs(value).valueOf();
  if (!Number.isFinite(diff) || diff < 0) return "从未同步";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

export function StoresPage() {
  const { stores, currentStore, setCurrent, refresh } = useStores();
  const [form] = Form.useForm<StoreFormValues>();
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Store | null>(null);
  const [bindOpen, setBindOpen] = useState(false);
  const [bindName, setBindName] = useState("");
  const [bindStoreId, setBindStoreId] = useState<number | null>(null);
  const [bindOk, setBindOk] = useState(false);
  const [bindLoggedIn, setBindLoggedIn] = useState(false);
  const [bindBusy, setBindBusy] = useState<null | "login" | "test" | "browser">(null);
  const [cookiesOpen, setCookiesOpen] = useState(false);
  const [cookiesText, setCookiesText] = useState("");
  const [cookiesSaving, setCookiesSaving] = useState(false);
  const [saving, setSaving] = useState(false);
  const [detailStore, setDetailStore] = useState<Store | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);
  const [logs, setLogs] = useState<StoreLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);
  const [bindingId, setBindingId] = useState<number | null>(null);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [syncingId, setSyncingId] = useState<number | null>(null);

  const ACTION_LABELS: Record<string, string> = {
    bind: "绑定店铺",
    edit: "编辑店铺",
    unbind: "解绑店铺",
    current: "切换当前店",
    perm: "店铺权限",
  };

  const total = stores.length;
  const normal = stores.filter((store) => store.display_status === "active").length;
  const attention = total - normal;

  const openCreate = () => {
    setBindName("");
    setBindStoreId(null);
    setBindOk(false);
    setBindLoggedIn(false);
    setBindOpen(true);
  };

  const openEdit = (row: Store) => {
    form.setFieldsValue({
      name: row.name,
    });
    setEditing(row);
    setModalOpen(true);
  };

  const submit = async (values: StoreFormValues) => {
    if (!editing) return;
    setSaving(true);
    try {
      const payload = {
        name: values.name.trim(),
      };
      await http.put(`/stores/${editing.id}`, payload);
      message.success("店铺信息已更新");
      setModalOpen(false);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const bindLogin = async () => {
    const name = bindName.trim();
    if (!name) {
      message.warning("请先填写店铺名称");
      return;
    }
    setBindBusy("login");
    try {
      let storeId = bindStoreId;
      if (!storeId) {
        const { data } = await http.post<{ item: Store }>("/stores", { name });
        storeId = data.item.id;
        setBindStoreId(storeId);
      }
      message.info("已打开 Chrome 登录窗口，请在窗口里用本店铺的淘宝账号登录生意参谋（最长等待 5 分钟）");
      // 登录等待最长 5 分钟：请求超时必须放宽到足够长，否则前端 30s 就放弃等待
      await http.post(`/stores/${storeId}/sycm/bind`, undefined, { timeout: 330000 });
      setBindLoggedIn(true);
      // D 优化：登录成功 → 自动验证 → 通过则直接保存，失败保留手动「测试/保存」
      try {
        await http.post(`/stores/${storeId}/sycm/test`, undefined, { timeout: 60000 });
        setBindOk(true);
        try {
          await http.put(`/stores/${storeId}`, { name });
        } catch {
          /* 名称同步失败不阻塞自动保存 */
        }
        setBindOpen(false);
        setBindStoreId(null);
        setBindOk(false);
        setBindLoggedIn(false);
        refresh();
        message.success("生意参谋登录成功，已自动验证并保存");
      } catch {
        message.warning("登录成功，但自动验证未通过（可能触发风控），请点击「测试」确认后保存");
        setBindOk(false);
        setBindLoggedIn(true);
        refresh();
      }
    } catch (error) {
      const detail = getApiErrorMessage(error);
      // bind 失败但档案已保存（登录其实成功，只是验证/风控问题）：保留店铺，允许手动测试保存
      if (detail.includes("验证失败") || detail.includes("已失效")) {
        setBindLoggedIn(true);
        message.warning("登录成功，但自动验证未通过，请点击「测试」确认后保存");
      } else {
        message.error(detail);
      }
    } finally {
      setBindBusy(null);
    }
  };

  const bindTest = async () => {
    if (!bindStoreId) {
      message.warning("请先点击「登录」完成生意参谋登录");
      return;
    }
    setBindBusy("test");
    try {
      await http.post(`/stores/${bindStoreId}/sycm/test`);
      message.success("生意参谋登录正常");
      // 测试通过 = 登录确实有效，允许保存（bind 首次验证偶发风控失败，不影响实际登录）
      setBindOk(true);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setBindBusy(null);
    }
  };

  const bindFromBrowser = async () => {
    const name = bindName.trim();
    if (!name) {
      message.warning("请先填写店铺名称");
      return;
    }
    setBindBusy("browser");
    try {
      let storeId = bindStoreId;
      if (!storeId) {
        const { data } = await http.post<{ item: Store }>("/stores", { name });
        storeId = data.item.id;
        setBindStoreId(storeId);
      }
      message.info("正在读取当前 Chrome/Edge 的生意参谋登录态（无需弹窗），请确认已在该浏览器登录 sycm.taobao.com");
      await http.post(`/stores/${storeId}/sycm/bind-from-browser`, undefined, { timeout: 180000 });
      setBindLoggedIn(true);
      // 后端已自动验证通过 → 直接保存
      try {
        await http.put(`/stores/${storeId}`, { name });
      } catch {
        /* 名称同步失败不阻塞保存 */
      }
      setBindOpen(false);
      setBindStoreId(null);
      setBindOk(false);
      setBindLoggedIn(false);
      refresh();
      message.success("已读取当前浏览器登录态并保存");
    } catch (error) {
      const detail = getApiErrorMessage(error);
      setBindLoggedIn(true); // 若档案已读取成功则保留店铺，避免误删
      message.error(detail);
    } finally {
      setBindBusy(null);
    }
  };

  const COOKIE_SNIPPET =
    "copy(JSON.stringify(Object.fromEntries(document.cookie.split('; ').map(c => { const i = c.indexOf('='); return [c.slice(0, i), c.slice(i + 1)]; }))));";

  const submitCookies = async () => {
    const name = bindName.trim();
    if (!name) {
      message.warning("请先填写店铺名称");
      return;
    }
    if (!cookiesText.trim()) {
      message.warning("请先粘贴登录态");
      return;
    }
    setCookiesSaving(true);
    try {
      let storeId = bindStoreId;
      if (!storeId) {
        const { data } = await http.post<{ item: Store }>("/stores", { name });
        storeId = data.item.id;
        setBindStoreId(storeId);
      }
      await http.post(`/stores/${storeId}/sycm/bind-from-cookies`, { cookies: cookiesText }, { timeout: 180000 });
      setBindLoggedIn(true);
      try {
        await http.put(`/stores/${storeId}`, { name });
      } catch {
        /* 名称同步失败不阻塞保存 */
      }
      setBindOpen(false);
      setCookiesOpen(false);
      setBindStoreId(null);
      setBindOk(false);
      setBindLoggedIn(false);
      setCookiesText("");
      refresh();
      message.success("登录态已保存并验证通过");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setCookiesSaving(false);
    }
  };

  const bindSave = async () => {
    const name = bindName.trim();
    if (!name) {
      message.warning("请先填写店铺名称");
      return;
    }
    if (!bindStoreId || !bindOk) {
      message.warning("请先点击「登录」并完成生意参谋登录");
      return;
    }
    try {
      // 同步最终店铺名称（创建后用户可能改过输入框）
      await http.put(`/stores/${bindStoreId}`, { name });
    } catch {
      /* 名称同步失败不阻塞保存 */
    }
    setBindOpen(false);
    setBindStoreId(null);
    setBindOk(false);
    setBindLoggedIn(false);
    refresh();
  };

  const closeBind = async () => {
    // 未确认保存就关闭：清理预创建的占位店铺，保持「保存才出现在列表」的语义
    // 若已登录成功（自动验证未通过），保留店铺与其登录档案，避免误删
    if (bindStoreId && !bindLoggedIn) {
      try {
        await http.delete(`/stores/${bindStoreId}`);
      } catch {
        /* 清理失败也不影响（后端已兜底：未登录成功的占位店会自动删除） */
      }
    }
    if (bindLoggedIn) {
      message.info("店铺已登录并保留在列表中，可继续「测试」确认或稍后处理");
    }
    setBindStoreId(null);
    setBindOk(false);
    setBindLoggedIn(false);
    setBindOpen(false);
  };

  const switchCurrent = async (row: Store) => {
    try {
      await setCurrent(row.id);
      message.success(`当前店铺已切换为「${row.name}」`);
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
    {
      title: "生意参谋",
      key: "sycm_status",
      width: 220,
      render: (_, row) => <LoginStatusTag status={row.sycm_status} error={row.sycm_error} />,
    },
    {
      title: "数据更新",
      key: "last_sync_at",
      render: (_, row) => {
        if (!row.last_sync_at) return <Text type="secondary">从未同步</Text>;
        const mins = Math.floor((Date.now() - dayjs(row.last_sync_at).valueOf()) / 60000);
        const color = mins > 24 * 60 ? "#ff4d4f" : mins > 30 ? "#fa8c16" : "#52c41a";
        return <Text style={{ color }}>{timeAgo(row.last_sync_at)}</Text>;
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
            {row.sycm_configured ? (
              <>
                <Button
                  size="small"
                  icon={<LoginOutlined />}
                  loading={bindingId === row.id}
                  onClick={() => bindSycm(row)}
                >
                  重登
                </Button>
                <Button
                  size="small"
                  icon={<ThunderboltOutlined />}
                  loading={testingId === row.id}
                  onClick={() => testSycm(row)}
                >
                  测试
                </Button>
                <Button
                  size="small"
                  icon={<SyncOutlined />}
                  loading={syncingId === row.id}
                  onClick={() => syncSycm(row)}
                >
                  同步
                </Button>
              </>
            ) : (
              <Button
                size="small"
                type="primary"
                ghost
                icon={<LoginOutlined />}
                loading={bindingId === row.id}
                onClick={() => bindSycm(row)}
              >
                登录
              </Button>
            )}
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

  const testSycm = async (row: Store) => {
    setTestingId(row.id);
    try {
      await http.post(`/stores/${row.id}/sycm/test`);
      message.success(`「${row.name}」生意参谋登录正常`);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTestingId(null);
    }
  };

  const bindSycm = async (row: Store) => {
    setBindingId(row.id);
    try {
      message.info("已打开 Chrome 登录窗口，请在窗口里完成登录（最长等待 5 分钟）");
      await http.post(`/stores/${row.id}/sycm/bind`, undefined, { timeout: 330000 });
      try {
        await http.post(`/stores/${row.id}/sycm/test`, undefined, { timeout: 60000 });
        message.success(`「${row.name}」登录成功并已验证`);
      } catch {
        message.warning(`「${row.name}」登录成功，但验证未通过（可能风控），稍后可再点「测试」确认`);
      }
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setBindingId(null);
    }
  };

  const syncSycm = async (row: Store) => {
    setSyncingId(row.id);
    try {
      await http.post(`/stores/${row.id}/sync`);
      message.success(`「${row.name}」已同步该店铺数据`);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSyncingId(null);
    }
  };

  const syncAllSycm = async () => {
    try {
      const { data } = await http.post<{ ok: number; total: number; results?: { store_name: string; ok: boolean; error?: string }[] }>("/stores/sync-all");
      showSyncFeedback("同步", [{ ok: data.ok, total: data.total, results: data.results ?? [] }]);
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

      <Card variant="borderless">
        <Table<Store>
          rowKey="id"
          loading={false}
          columns={columns}
          dataSource={stores}
          pagination={{ defaultPageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (count) => `共 ${count} 家店铺` }}
          scroll={{ x: 1200 }}
        />
      </Card>

      <Modal
        title={`编辑店铺：${editing?.name ?? ""}`}
        open={modalOpen}
        onOk={() => form.submit()}
        onCancel={() => setModalOpen(false)}
        confirmLoading={saving}
        okText="保存"
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
        </Form>
      </Modal>

      <Modal
        title="绑定店铺"
        open={bindOpen}
        onCancel={() => {
          if (bindBusy === "login") {
            message.info("正在等待登录，请先在 Chrome 窗口完成登录；如需取消请直接关闭 Chrome 窗口");
            return;
          }
          closeBind();
        }}
        width={460}
        footer={[
          <Button key="cookies" icon={<CopyOutlined />} onClick={() => setCookiesOpen(true)}>
            粘贴登录态
          </Button>,
          <Button key="browser" icon={<ReadOutlined />} loading={bindBusy === "browser"} onClick={bindFromBrowser}>
            读取当前浏览器
          </Button>,
          <Button key="login" icon={<LoginOutlined />} loading={bindBusy === "login"} onClick={bindLogin}>
            登录
          </Button>,
          <Button
            key="test"
            icon={<ThunderboltOutlined />}
            loading={bindBusy === "test"}
            disabled={!bindStoreId}
            onClick={bindTest}
          >
            测试
          </Button>,
          <Button key="save" type="primary" icon={<CheckOutlined />} disabled={!bindOk} onClick={bindSave}>
            保存
          </Button>,
        ]}
      >
        <div style={{ textAlign: "center", padding: "20px 8px 12px" }}>
          <Space orientation="vertical" size={14} style={{ width: "100%" }}>
            <Text strong style={{ fontSize: 15 }}>两步完成店铺绑定</Text>
            <Input
              placeholder="店铺名称（必填）"
              value={bindName}
              maxLength={50}
              onChange={(event) => setBindName(event.target.value)}
              onPressEnter={bindLogin}
            />
            <Text type="secondary">
              三种方式任选：「粘贴登录态」/「读取当前浏览器」无需弹窗；「登录」会弹专用窗口扫码。成功后都会自动验证并保存。
            </Text>
            {bindBusy === "login" && (
              <Text type="secondary" style={{ fontSize: 13, color: "var(--ops-accent)" }}>
                正在等待登录…最长 5 分钟，请勿关闭本窗口
              </Text>
            )}
            {bindBusy === "test" && (
              <Text type="secondary" style={{ fontSize: 13, color: "var(--ops-accent)" }}>
                正在验证登录状态…
              </Text>
            )}
            <Text type="secondary" style={{ fontSize: 12 }}>
              若自动验证未通过（可能风控），请手动点「测试」确认后「保存」
            </Text>
          </Space>
        </div>
      </Modal>

      <Modal
        title="粘贴登录态（无需弹窗）"
        open={cookiesOpen}
        onCancel={() => setCookiesOpen(false)}
        onOk={submitCookies}
        confirmLoading={cookiesSaving}
        okText="保存并验证"
        width={640}
      >
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Text>
            1. 在浏览器打开并登录 <Text code>sycm.taobao.com</Text>
          </Text>
          <Text>
            2. 按 F12 → Console（控制台），粘贴下面这行并回车（会自动复制到剪贴板）：
          </Text>
          <Space.Compact style={{ width: "100%" }}>
            <Input readOnly value={COOKIE_SNIPPET} />
            <Button
              onClick={() => {
                navigator.clipboard?.writeText(COOKIE_SNIPPET).then(() => message.success("已复制，请到生意参谋控制台运行"));
              }}
            >
              复制
            </Button>
          </Space.Compact>
          <Text>
            3. 回到这里，把控制台输出的内容粘贴到下方：
          </Text>
          <Input.TextArea
            rows={6}
            value={cookiesText}
            onChange={(event) => setCookiesText(event.target.value)}
            placeholder='例如：{"_tb_token_":"...","_m_h5_tk":"..."}'
          />
          <Text type="secondary" style={{ fontSize: 12 }}>
            若提示缺少 _tb_token_：打开 F12 → Application → Cookies，把 taobao 域的 cookie 按“名字=值”分行复制粘贴。
          </Text>
        </Space>
      </Modal>

      <StoreDetailDrawer
        store={detailStore}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      />
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
    </div>
  );
}
