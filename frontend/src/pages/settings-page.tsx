import {
  BellOutlined,
  FileTextOutlined,
  ReloadOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Button, Card, Col, Input, Row, Select, Space, Switch, Typography, message } from "antd";
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
  enabled: boolean;
  token: string;
  webhook: string;
  channel: "pushplus" | "webhook" | "both";
  rules: unknown[];
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
    enabled: false,
    token: "",
    webhook: "",
    channel: "pushplus",
    rules: [],
  });
  const [reportSaving, setReportSaving] = useState(false);
  const [hourlySaving, setHourlySaving] = useState(false);
  const [testing, setTesting] = useState<"report" | "hourly" | null>(null);

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
  }, [load]);

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
      const { data } = await http.put<HourlyPushConfig>("/alerts/hourly-push-config", hourly);
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
                <FileTextOutlined style={{ color: "#1677ff" }} />
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
                <ThunderboltOutlined style={{ color: "#fa8c16" }} />
                <Text strong>小时异常推送</Text>
              </Space>
            }
          >
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Text>启用小时级推送</Text>
                <Switch
                  checked={hourly.enabled}
                  onChange={(enabled) => setHourly({ ...hourly, enabled })}
                />
              </div>
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
              <Text type="secondary" style={{ fontSize: 12 }}>
                已配置 {hourly.rules.length} 条小时规则；规则明细请到「数据洞察 → 小时推送」维护。
              </Text>
              <Space>
                <Button type="primary" loading={hourlySaving} onClick={saveHourly}>
                  保存
                </Button>
                <Button
                  icon={<BellOutlined />}
                  loading={testing === "hourly"}
                  disabled={!hourly.token}
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
    </div>
  );
}
