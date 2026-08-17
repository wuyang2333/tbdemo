import { SendOutlined } from "@ant-design/icons";
import { Button, Input, InputNumber, Modal, Select, Space, Switch, Typography, message } from "antd";
import { useState } from "react";

import http, { getApiErrorMessage } from "../../lib/api";
import { RULE_FIELDS, RULE_OPERATORS, ruleText } from "../../lib/alert-rules";

const { Text } = Typography;

type HourlyRule = { id: string; field: string; operator: string; threshold: number; compare: string; scene: string; enabled: boolean };
type HourlyPushCfg = {
  enabled: boolean;
  token: string;
  webhook: string;
  channel: "pushplus" | "webhook" | "both";
  rules: HourlyRule[];
};

const SCENE_OPTIONS = [
  { value: "", label: "全部场景" },
  { value: "wholesite", label: "货品全站推广" },
  { value: "keyword", label: "关键词推广" },
  { value: "crowd", label: "人群推广" },
  { value: "content", label: "内容营销" },
];
const PROMO_FIELDS = ["promo_spend", "promo_roi"];

const COMPARE_OPTIONS = [
  { value: "yesterday", label: "较昨日同时段" },
  { value: "prev_hour", label: "较上一小时" },
];

const CHANNEL_OPTIONS = [
  { value: "pushplus", label: "pushplus（微信）" },
  { value: "webhook", label: "Webhook（群机器人）" },
  { value: "both", label: "两者同时推送" },
];

/** 小时异常推送设置（pushplus / Webhook / 同时），供经营日报/商品分析/推广计划共用。 */
export function HourlyPushButton() {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<HourlyPushCfg>({
    enabled: false,
    token: "",
    webhook: "",
    channel: "pushplus",
    rules: [],
  });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [newField, setNewField] = useState<string | undefined>(undefined);
  const [newOp, setNewOp] = useState("cycle_drop_pct");
  const [newTh, setNewTh] = useState(30);
  const [newCompare, setNewCompare] = useState("yesterday");
  const [newScene, setNewScene] = useState("");

  const openModal = async () => {
    setOpen(true);
    try {
      const { data } = await http.get<HourlyPushCfg>("/alerts/hourly-push-config");
      setCfg(data);
    } catch {}
  };
  const save = async (silent = false) => {
    setSaving(true);
    try {
      await http.put("/alerts/hourly-push-config", cfg, { timeout: 20000 });
      if (!silent) {
        message.success("小时推送设置已保存");
        setOpen(false);
      }
    } catch (error) {
      message.error(getApiErrorMessage(error));
      throw error;
    } finally {
      setSaving(false);
    }
  };
  const test = async () => {
    setTesting(true);
    try {
      await save(true);
      await http.post("/alerts/hourly-push/test", undefined, { timeout: 30000 });
      message.success("已发送测试消息，请查收");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setTesting(false);
    }
  };
  const check = async () => {
    setChecking(true);
    try {
      await save(true);
      const { data } = await http.post<{ messages: string[]; pushed: boolean }>("/alerts/hourly-push/check?push=1", undefined, { timeout: 30000 });
      if (data.messages.length) message.success(`检查到 ${data.messages.length} 条异常，已按渠道推送`);
      else message.info("上个小时暂无触发异常的规则");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setChecking(false);
    }
  };
  const addRule = () => {
    if (!newField) return;
    setCfg((p) => ({
      ...p,
      rules: [...p.rules, { id: `hp_${Date.now()}_${Math.floor(Math.random() * 10000)}`, field: newField, operator: newOp, threshold: Number(newTh), compare: newCompare, scene: PROMO_FIELDS.includes(newField) ? newScene : "", enabled: true }],
    }));
    setNewField(undefined);
    setNewOp("cycle_drop_pct");
    setNewTh(30);
    setNewCompare("yesterday");
    setNewScene("");
  };
  const updRule = (id: string, patch: { enabled?: boolean }) =>
    setCfg((p) => ({ ...p, rules: p.rules.map((r) => (r.id === id ? { ...r, ...patch } : r)) }));
  const delRule = (id: string) => setCfg((p) => ({ ...p, rules: p.rules.filter((r) => r.id !== id) }));

  return (
    <>
      <Button icon={<SendOutlined />} onClick={openModal}>小时推送</Button>
      <Modal
        title="小时异常推送设置"
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => save(false)}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        width={560}
        destroyOnHidden
      >
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>启用</span> <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>开启后每小时自动检查上个小时数据，触发规则按所选渠道推送</span></div>
            <Switch checked={cfg.enabled} onChange={(v) => setCfg((p) => ({ ...p, enabled: v }))} checkedChildren="开" unCheckedChildren="关" />
          </div>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>推送渠道</span> <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>可二选一或同时推送</span></div>
            <Select style={{ width: "100%" }} options={CHANNEL_OPTIONS} value={cfg.channel} onChange={(channel) => setCfg((p) => ({ ...p, channel }))} />
          </div>
          {cfg.channel !== "webhook" && (
            <div>
              <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>pushplus Token</span> <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>pushplus.plus 绑定微信后获取</span></div>
              <Input placeholder="pushplus token" value={cfg.token} onChange={(e) => setCfg((p) => ({ ...p, token: e.target.value }))} />
            </div>
          )}
          {cfg.channel !== "pushplus" && (
            <div>
              <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>群机器人 Webhook</span> <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>钉钉 / 企业微信通用</span></div>
              <Input placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." value={cfg.webhook} onChange={(e) => setCfg((p) => ({ ...p, webhook: e.target.value }))} />
            </div>
          )}
          <div style={{ borderTop: "1px solid var(--ops-border)", paddingTop: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>小时级推送规则（较昨日同时段 / 阈值）</div>
            {cfg.rules.length === 0 && <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>还没有规则，添加一条试试。</Text>}
            <div style={{ display: "grid", gap: 6, marginBottom: 10 }}>
              {cfg.rules.map((r) => (
                <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", borderRadius: 8, padding: "6px 10px" }}>
                  <Text style={{ fontSize: 13, flex: 1 }}>
                    {r.scene ? `[${SCENE_OPTIONS.find((x) => x.value === r.scene)?.label || r.scene}] ` : ""}
                    {ruleText({ id: r.id, module: "hour", field: r.field, operator: r.operator as "cycle_drop_pct" | "cycle_up_pct" | "lt" | "gt", threshold: r.threshold, enabled: r.enabled })}
                    {["cycle_drop_pct", "cycle_up_pct"].includes(r.operator) ? `（${r.compare === "prev_hour" ? "较上一小时" : "较昨日同时段"}）` : ""}
                  </Text>
                  <Switch size="small" checked={r.enabled} onChange={(c) => updRule(r.id, { enabled: c })} />
                  <Button size="small" danger type="text" onClick={() => delRule(r.id)}>删除</Button>
                </div>
              ))}
            </div>
            <Space wrap>
              <Select size="small" style={{ width: 130 }} placeholder="字段" options={RULE_FIELDS.hour.map((f) => ({ value: f.key, label: f.label }))} value={newField} onChange={setNewField} />
              <Select size="small" style={{ width: 150 }} options={RULE_OPERATORS.map((o) => ({ value: o.value, label: o.label }))} value={newOp} onChange={setNewOp} />
              {PROMO_FIELDS.includes(newField || "") && (
                <Select size="small" style={{ width: 130 }} options={SCENE_OPTIONS} value={newScene} onChange={setNewScene} />
              )}
              <Select size="small" style={{ width: 130 }} options={COMPARE_OPTIONS} value={newCompare} onChange={setNewCompare} disabled={["lt", "gt"].includes(newOp)} />
              <InputNumber size="small" style={{ width: 100 }} placeholder="阈值" value={newTh} min={0} onChange={(v) => setNewTh(Number(v ?? 0))} />
              <Button size="small" type="primary" onClick={addRule} disabled={!newField}>添加规则</Button>
            </Space>
            <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>例：销售额 环比跌超 30%（较昨日同时段）→ 上个小时销售额较昨日同时段跌超 30% 时推微信；选「较上一小时」则与上上个小时比</Text>
          </div>
          <div style={{ borderTop: "1px solid var(--ops-border)", paddingTop: 12, display: "flex", gap: 10 }}>
            <Button icon={<SendOutlined />} loading={testing} onClick={test}>测试推送</Button>
            <Button loading={checking} onClick={check}>立即检查上个小时</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
