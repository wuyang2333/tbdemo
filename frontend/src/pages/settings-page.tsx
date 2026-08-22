import {
  BellOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { Alert, Avatar, Button, Card, Col, Form, Input, Row, Select, Space, Switch, Table, Tag, Typography, Upload, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";

const { Text } = Typography;

type ReportPushConfig = {
  enabled: boolean;
  webhook: string;
  hour: number;
  minute: number;
};

type HourlyPushConfig = {
  token: string;
  webhook: string;
  channel: "pushplus" | "webhook" | "both";
  enabled_page_count: number;
  pages: Record<"report" | "hours" | "products" | "promotions", { enabled: boolean; rules: unknown[] }>;
};

const EMPTY_HOURLY_PAGES: HourlyPushConfig["pages"] = {
  report: { enabled: false, rules: [] },
  hours: { enabled: false, rules: [] },
  products: { enabled: false, rules: [] },
  promotions: { enabled: false, rules: [] },
};

const HOURLY_PAGE_LABELS: Record<keyof HourlyPushConfig["pages"], string> = {
  report: "经营日报",
  hours: "时段分析",
  products: "商品分析",
  promotions: "推广计划",
};

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => ({
  value: i,
  label: `${String(i).padStart(2, "0")} 点`,
}));
const MINUTE_OPTIONS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55].map((m) => ({
  value: m,
  label: `${String(m).padStart(2, "0")} 分`,
}));
const HOURLY_CHANNEL_OPTIONS = [
  { value: "pushplus", label: "pushplus（微信）" },
  { value: "webhook", label: "Webhook（群机器人）" },
  { value: "both", label: "两者同时推送" },
];

export function SettingsPage() {
  const [report, setReport] = useState<ReportPushConfig>({ enabled: false, webhook: "", hour: 9, minute: 0 });
  const [hourly, setHourly] = useState<HourlyPushConfig>({
    token: "",
    webhook: "",
    channel: "pushplus",
    enabled_page_count: 0,
    pages: EMPTY_HOURLY_PAGES,
  });
  const [reportSaving, setReportSaving] = useState(false);
  const [hourlySaving, setHourlySaving] = useState(false);
  const [testing, setTesting] = useState<"report" | "hourly" | null>(null);
  const [health, setHealth] = useState<{ db_size_mb: number; disk_free_gb: number; store_count: number; profile_ok: number; last_sync: string | null; backup_count: number; backup_latest: string | null } | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthAt, setHealthAt] = useState("");
  const [brandForm] = Form.useForm();
  const [brandSaving, setBrandSaving] = useState(false);
  const [version, setVersion] = useState<{ name: string; version: string; backend: string; frontend: string } | null>(null);
  const [loopsData, setLoopsData] = useState<{ name: string; last_run: string | null; last_success: string | null; last_error: string | null; error_count: number }[]>([]);
  const [retentionDays, setRetentionDays] = useState(90);
  const [cleanupLoading, setCleanupLoading] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<{ deleted: number; cutoff: string } | null>(null);
  const [logoPreview, setLogoPreview] = useState("");

  const loadHealth = async () => {
    setHealthLoading(true);
    try {
      const { data } = await http.get("/system/healthcheck");
      setHealth(data);
      setHealthAt(dayjs().format("HH:mm:ss"));
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setHealthLoading(false);
    }
  };
  const load = useCallback(async () => {
    try {
      const [reportRes, hourlyRes] = await Promise.all([
        http.get<ReportPushConfig>("/analytics/report/push-config"),
        http.get<HourlyPushConfig>("/alerts/hourly-push-config"),
      ]);
      setReport(reportRes.data);
      setHourly(hourlyRes.data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    load();
    loadBrand();
    loadVersion();
    loadLoops();
    loadCleanupConfig();
  }, [load]);

  const loadBrand = async () => {
    try {
      const { data } = await http.get<{ brand: Record<string, string> }>("/settings/brand");
      brandForm.setFieldsValue(data.brand);
      setLogoPreview(data.brand.logoUrl || "");
    } catch {
      /* 默认品牌 */
    }
  };
  const loadVersion = async () => {
    try {
      const { data } = await http.get("/system/version");
      setVersion(data);
    } catch {
      setVersion(null);
    }
  };
  const loadLoops = async () => {
    try {
      const { data } = await http.get<{ items: { name: string; last_run: string | null; last_success: string | null; last_error: string | null; error_count: number }[] }>("/system/loops");
      setLoopsData(data.items);
    } catch {
      setLoopsData([]);
    }
  };
  const loadCleanupConfig = async () => {
    try {
      const { data } = await http.get<{ retention_days: number }>("/system/cleanup-config");
      setRetentionDays(data.retention_days);
    } catch {
      /* 默认 90 */
    }
  };
  const readLogo = (file: File) => {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      message.error("仅支持 PNG / JPG / WebP 格式的图片");
      return false;
    }
    if (file.size > 2 * 1024 * 1024) {
      message.error("Logo 图片不能超过 2MB");
      return false;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      setLogoPreview(dataUrl);
      brandForm.setFieldsValue({ logoUrl: dataUrl });
      message.success("Logo 已上传，点「保存品牌配置」后生效");
    };
    reader.onerror = () => {
      message.error("Logo 上传失败，请重试");
    };
    reader.readAsDataURL(file);
    return false;
  };
  const saveBrand = async (values: Record<string, string>) => {
    const logoUrl = (brandForm.getFieldValue("logoUrl") as string) || logoPreview || "";
    const payload = { ...values, logoUrl };
    setBrandSaving(true);
    try {
      await http.put("/settings/brand", payload);
      localStorage.setItem("tb-brand", JSON.stringify(payload));
      message.success("品牌配置已保存，即将刷新生效");
      setTimeout(() => window.location.reload(), 800);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setBrandSaving(false);
    }
  };
  const runCleanup = async () => {
    setCleanupLoading(true);
    try {
      const { data } = await http.post<{ deleted: number; cutoff: string }>("/system/cleanup", {});
      setCleanupResult(data);
      message.success(`已清理 ${data.deleted} 条历史数据`);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setCleanupLoading(false);
    }
  };
  const saveReport = async () => {
    setReportSaving(true);
    try {
      const { data } = await http.put<ReportPushConfig>("/analytics/report/push-config", report);
      setReport(data);
      message.success("经营日报推送配置已保存");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setReportSaving(false);
    }
  };

  const saveHourly = async () => {
    setHourlySaving(true);
    try {
      const { data } = await http.put<HourlyPushConfig>("/alerts/hourly-push-config", {
        token: hourly.token,
        webhook: hourly.webhook,
        channel: hourly.channel,
      });
      setHourly(data);
      message.success("小时异常推送配置已保存");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setHourlySaving(false);
    }
  };

  const testPush = async (kind: "report" | "hourly") => {
    setTesting(kind);
    try {
      if (kind === "report") {
        await http.post("/analytics/report/push");
        message.success("日报推送测试已发送，请到群机器人确认");
      } else {
        await http.post("/alerts/hourly-push/test");
        message.success("pushplus 测试消息已发送，请检查微信");
      }
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTesting(null);
    }
  };

  return (
    <div>
      <PageHeader icon={<SettingOutlined />} eyebrow="系统设置" title="设置中心" />

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card
            variant="borderless"
            title={
              <Space size={8}>
                <FileTextOutlined style={{ color: "var(--ops-accent)" }} />
                <Text strong>经营日报推送</Text>
              </Space>
            }
          >
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Text>启用每日推送</Text>
                <Switch
                  checked={report.enabled}
                  onChange={(enabled) => setReport({ ...report, enabled })}
                />
              </div>
              <div>
                <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
                  群机器人 Webhook 地址（钉钉 / 企业微信通用）
                </Text>
                <Input
                  value={report.webhook}
                  onChange={(event) => setReport({ ...report, webhook: event.target.value })}
                  placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                />
              </div>
              <div>
                <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
                  每日推送时间（到点自动生成并推送昨日经营日报）
                </Text>
                <Space>
                  <Select
                    value={report.hour}
                    onChange={(hour) => setReport({ ...report, hour })}
                    options={HOUR_OPTIONS}
                    style={{ width: 110 }}
                  />
                  <Select
                    value={report.minute}
                    onChange={(minute) => setReport({ ...report, minute })}
                    options={MINUTE_OPTIONS}
                    style={{ width: 110 }}
                  />
                </Space>
              </div>
              <Space>
                <Button type="primary" loading={reportSaving} onClick={saveReport}>
                  保存
                </Button>
                <Button
                  icon={<BellOutlined />}
                  loading={testing === "report"}
                  disabled={!report.webhook}
                  onClick={() => testPush("report")}
                >
                  测试推送
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            variant="borderless"
            title={
              <Space size={8}>
                <ThunderboltOutlined style={{ color: "var(--ops-warn)" }} />
                <Text strong>小时异常推送</Text>
              </Space>
            }
          >
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <Alert
                type="info"
                showIcon
                message="这里统一管理接收渠道"
                description="各页面是否启用、监控哪些指标和阈值，分别在对应页面的“小时推送”中设置。"
              />
              <div>
                <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
                  推送渠道（可二选一或同时推送）
                </Text>
                <Select
                  value={hourly.channel}
                  onChange={(channel) => setHourly({ ...hourly, channel })}
                  options={HOURLY_CHANNEL_OPTIONS}
                  style={{ width: "100%" }}
                />
              </div>
              {hourly.channel !== "webhook" && (
                <div>
                  <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
                    pushplus Token（绑定个人微信接收异常提醒）
                  </Text>
                  <Input.Password
                    value={hourly.token}
                    onChange={(event) => setHourly({ ...hourly, token: event.target.value })}
                    placeholder="pushplus token"
                  />
                </div>
              )}
              {hourly.channel !== "pushplus" && (
                <div>
                  <Text type="secondary" style={{ display: "block", marginBottom: 6 }}>
                    群机器人 Webhook 地址（钉钉 / 企业微信通用）
                  </Text>
                  <Input
                    value={hourly.webhook}
                    onChange={(event) => setHourly({ ...hourly, webhook: event.target.value })}
                    placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                  />
                </div>
              )}
              <div>
                <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
                  已启用 {hourly.enabled_page_count} 个页面
                </Text>
                <Space wrap>
                  {(Object.keys(HOURLY_PAGE_LABELS) as Array<keyof HourlyPushConfig["pages"]>).map((scope) => (
                    <Tag key={scope} color={hourly.pages[scope]?.enabled ? "success" : "default"}>
                      {HOURLY_PAGE_LABELS[scope]} · {hourly.pages[scope]?.enabled ? `${hourly.pages[scope].rules.length} 条规则` : "未启用"}
                    </Tag>
                  ))}
                </Space>
              </div>
              <Space>
                <Button type="primary" loading={hourlySaving} onClick={saveHourly}>
                  保存
                </Button>
                <Button
                  icon={<BellOutlined />}
                  loading={testing === "hourly"}
                  disabled={(hourly.channel === "pushplus" && !hourly.token) || (hourly.channel === "webhook" && !hourly.webhook) || (hourly.channel === "both" && (!hourly.token || !hourly.webhook))}
                  onClick={() => testPush("hourly")}
                >
                  测试推送
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>
      </Row>

      <Card variant="borderless" style={{ marginTop: 16 }}>
        <Space>
          <ReloadOutlined style={{ color: "var(--ops-text-secondary)" }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            后台循环状态可在「操作日志」或 /api/system/loops 查看；数据库与登录档案建议定期备份。
          </Text>
        </Space>
      </Card>
      <Card variant="borderless" title="系统体检" style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Space wrap>
            <Button icon={<ReloadOutlined />} loading={healthLoading} onClick={loadHealth}>立即体检</Button>
            {health && <Text type="secondary" style={{ fontSize: 12 }}>最近检查 {healthAt}</Text>}
          </Space>
          {health && (
            <Row gutter={[12, 12]}>
              {[
                { label: "数据库大小", value: `${health.db_size_mb} MB` },
                { label: "磁盘剩余", value: `${health.disk_free_gb} GB` },
                { label: "店铺数", value: health.store_count },
                { label: "登录态正常", value: `${health.profile_ok}/${health.store_count}` },
                { label: "备份数", value: health.backup_count },
                { label: "最近同步", value: health.last_sync ? dayjs(health.last_sync).format("MM-DD HH:mm") : "—" },
              ].map((item) => (
                <Col xs={12} sm={8} key={item.label}>
                  <Card size="small">
                    <Text type="secondary" style={{ fontSize: 12 }}>{item.label}</Text>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>{item.value}</div>
                  </Card>
                </Col>
              ))}
            </Row>
          )}
        </Space>
      </Card>
      <Card variant="borderless" title="外观 / 品牌" style={{ marginTop: 16 }}>
        <Form form={brandForm} layout="vertical" onFinish={saveBrand} style={{ maxWidth: 480 }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="name" label="系统名称">
                <Input placeholder="如：我的运营工作台" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="Logo 图片（可选）">
                <Space direction="vertical">
                  <Space>
                    {logoPreview && <Avatar shape="square" size={40} src={logoPreview} />}
                    <Upload showUploadList={false} accept="image/png,image/jpeg,image/webp" beforeUpload={(file) => readLogo(file)}>
                      <Button icon={<UploadOutlined />}>上传 Logo</Button>
                    </Upload>
                    {logoPreview && (
                      <Button size="small" onClick={() => { setLogoPreview(""); brandForm.setFieldsValue({ logoUrl: "" }); }}>
                        清除
                      </Button>
                    )}
                  </Space>
                </Space>
                <Text type="secondary" style={{ fontSize: 12, display: "block", marginTop: 4 }}>
                  未上传图片时，自动显示系统名称的第一个字
                </Text>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="primaryColor" label="主题色">
                <Space>
                  <Input type="color" style={{ width: 48, padding: 2 }} />
                  <Input placeholder="var(--ops-accent)" />
                </Space>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="tagline" label="标语">
                <Input placeholder="淘宝店铺运营中台" />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" htmlType="submit" loading={brandSaving}>保存品牌配置</Button>
        </Form>
      </Card>

      <Card variant="borderless" title="关于 / 版本" style={{ marginTop: 16 }}>
        {version ? (
          <Space direction="vertical" size={4}>
            <Text>{version.name} v{version.version}</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>后端 {version.backend} · 前端 {version.frontend}</Text>
          </Space>
        ) : (
          <Text type="secondary">加载中…</Text>
        )}
      </Card>

      <Card variant="borderless" title="后台循环状态" style={{ marginTop: 16 }}>
        <Table
          rowKey="name"
          size="small"
          dataSource={loopsData}
          pagination={false}
          columns={[
            { title: "循环", dataIndex: "name" },
            { title: "上次运行", dataIndex: "last_run", render: (v: string | null) => (v ? dayjs(v).format("MM-DD HH:mm:ss") : "—") },
            { title: "上次成功", dataIndex: "last_success", render: (v: string | null) => (v ? dayjs(v).format("MM-DD HH:mm:ss") : "—") },
            {
              title: "状态",
              key: "st",
              render: (_, row: { last_error: string | null; error_count: number }) =>
                row.last_error ? <Tag color="red">异常</Tag> : <Tag color="green">正常</Tag>,
            },
          ]}
        />
      </Card>

      <Card variant="borderless" title="数据管理" style={{ marginTop: 16 }}>
        <Space direction="vertical" style={{ width: "100%" }} size={12}>
          <Text type="secondary" style={{ fontSize: 13 }}>
            历史数据保留 {retentionDays} 天，超过的部分会自动清理（实时数据不清理）。
          </Text>
          <Space wrap>
            <Button type="primary" danger ghost loading={cleanupLoading} onClick={runCleanup}>
              立即清理历史数据
            </Button>
            {cleanupResult && (
              <Text type="secondary" style={{ fontSize: 12 }}>
                上次清理 {cleanupResult.deleted} 条（{cleanupResult.cutoff} 之前）
              </Text>
            )}
          </Space>
        </Space>
      </Card>
    </div>
  );
}
