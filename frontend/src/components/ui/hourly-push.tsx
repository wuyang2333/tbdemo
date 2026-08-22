import { SendOutlined, SettingOutlined } from "@ant-design/icons";
import { Alert, Button, InputNumber, Modal, Select, Space, Switch, Typography, message } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../../lib/api";
import { RULE_OPERATORS, ruleText } from "../../lib/alert-rules";
import type { RuleField, RuleModule } from "../../lib/alert-rules";

const { Text } = Typography;

export type HourlyPushScope = "report" | "hours" | "products" | "promotions";

type HourlyRule = {
  id: string;
  field: string;
  operator: "cycle_drop_pct" | "cycle_up_pct" | "lt" | "gt";
  threshold: number;
  compare: "yesterday" | "prev_hour";
  scene: string;
  enabled: boolean;
};

type ScopedHourlyPushCfg = {
  scope: HourlyPushScope;
  scope_label: string;
  enabled: boolean;
  channel: "pushplus" | "webhook" | "both";
  channel_ready: boolean;
  rules: HourlyRule[];
};

type ScopeMeta = {
  label: string;
  module: RuleModule;
  fields: RuleField[];
  compareSelectable: boolean;
  hint: string;
};

const SCOPE_META: Record<HourlyPushScope, ScopeMeta> = {
  report: {
    label: "经营日报",
    module: "hour",
    fields: [
      { key: "sales", label: "销售额", kind: "cycle" },
      { key: "visitors", label: "访客", kind: "cycle" },
      { key: "pv", label: "浏览量", kind: "cycle" },
      { key: "buyers", label: "买家数", kind: "cycle" },
      { key: "orders", label: "订单", kind: "cycle" },
      { key: "conversion_rate", label: "转化率", kind: "cycle", unit: "%" },
      { key: "avg_order_value", label: "客单价", kind: "cycle" },
      { key: "promo_spend", label: "推广花费", kind: "cycle" },
      { key: "promo_sales", label: "推广成交额", kind: "cycle" },
      { key: "promo_roi", label: "推广ROI", kind: "cycle" },
      { key: "add_cart", label: "今日加购数", kind: "value" },
      { key: "refund_amount", label: "今日退款金额", kind: "value" },
      { key: "goal_progress", label: "月目标完成率", kind: "value", unit: "%" },
    ],
    compareSelectable: true,
    hint: "检查经营日报的经营、推广和目标进度指标，不影响其他页面。",
  },
  hours: {
    label: "时段分析",
    module: "hour",
    fields: [
      { key: "sales", label: "销售额", kind: "cycle" },
      { key: "visitors", label: "访客", kind: "cycle" },
      { key: "pv", label: "浏览量", kind: "cycle" },
      { key: "buyers", label: "买家数", kind: "cycle" },
      { key: "orders", label: "订单", kind: "cycle" },
      { key: "conversion_rate", label: "转化率", kind: "cycle", unit: "%" },
      { key: "promo_spend", label: "推广花费", kind: "cycle" },
      { key: "promo_sales", label: "推广成交额", kind: "cycle" },
      { key: "promo_roi", label: "推广ROI", kind: "cycle" },
    ],
    compareSelectable: true,
    hint: "检查上个小时的经营与推广分时指标，可选择昨日同时段或上一小时。",
  },
  products: {
    label: "商品分析",
    module: "product",
    fields: [
      { key: "sales", label: "销售额", kind: "cycle" },
      { key: "visitors", label: "访客", kind: "cycle" },
      { key: "pv", label: "浏览量", kind: "cycle" },
      { key: "buyers", label: "买家数", kind: "cycle" },
      { key: "orders", label: "订单", kind: "cycle" },
      { key: "conversion_rate", label: "转化率", kind: "cycle", unit: "%" },
      { key: "add_cart", label: "加购数", kind: "cycle" },
      { key: "refund_amount", label: "退款金额", kind: "value" },
      { key: "promo_spend", label: "推广花费", kind: "value" },
      { key: "promo_sales", label: "推广成交额", kind: "value" },
      { key: "promo_roi", label: "推广ROI", kind: "value" },
      { key: "promo_net_roi", label: "推广净ROI", kind: "value" },
      { key: "real_roi", label: "真实ROI", kind: "value" },
      { key: "promo_share", label: "推广成交占比", kind: "value", unit: "%" },
    ],
    compareSelectable: false,
    hint: "逐个检查商品实时指标，最多汇总推送 20 条异常商品。",
  },
  promotions: {
    label: "推广计划",
    module: "plan",
    fields: [
      { key: "spend", label: "花费", kind: "cycle" },
      { key: "sales", label: "成交额", kind: "cycle" },
      { key: "roi", label: "ROI", kind: "cycle" },
      { key: "clicks", label: "点击", kind: "cycle" },
      { key: "retained_roi", label: "净投产比", kind: "value" },
      { key: "budget_usage", label: "预算消耗率", kind: "value", unit: "%" },
      { key: "impressions", label: "展现量", kind: "value" },
      { key: "ctr", label: "点击率", kind: "value", unit: "%" },
      { key: "cvr", label: "转化率", kind: "value", unit: "%" },
      { key: "ecpc", label: "点击成本", kind: "value" },
      { key: "orders", label: "成交件数", kind: "value" },
      { key: "refund_amt", label: "退款金额", kind: "value" },
      { key: "retained_sales", label: "留存成交额", kind: "value" },
      { key: "alipay_dir", label: "直接成交额", kind: "value" },
      { key: "alipay_indir", label: "间接成交额", kind: "value" },
    ],
    compareSelectable: false,
    hint: "逐个检查实时推广计划的消耗、转化、预算和成交质量指标，最多汇总推送 20 条异常计划。",
  },
};

const SCENE_OPTIONS = [
  { value: "", label: "全部场景" },
  { value: "wholesite", label: "货品全站推广" },
  { value: "keyword", label: "关键词推广" },
  { value: "crowd", label: "人群推广" },
  { value: "content", label: "内容营销" },
];
const PROMO_FIELDS = ["promo_spend", "promo_sales", "promo_roi"];

const COMPARE_OPTIONS = [
  { value: "yesterday", label: "较昨日同时段" },
  { value: "prev_hour", label: "较上一小时" },
];

const EMPTY_CONFIG: ScopedHourlyPushCfg = {
  scope: "hours",
  scope_label: "时段分析",
  enabled: false,
  channel: "pushplus",
  channel_ready: false,
  rules: [],
};

export function HourlyPushButton({ scope }: { scope: HourlyPushScope }) {
  const navigate = useNavigate();
  const meta = SCOPE_META[scope];
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<ScopedHourlyPushCfg>({ ...EMPTY_CONFIG, scope, scope_label: meta.label });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [newField, setNewField] = useState<string | undefined>(undefined);
  const [newOp, setNewOp] = useState<HourlyRule["operator"]>("cycle_drop_pct");
  const [newTh, setNewTh] = useState(30);
  const [newCompare, setNewCompare] = useState<HourlyRule["compare"]>("yesterday");
  const [newScene, setNewScene] = useState("");

  const openModal = async () => {
    setOpen(true);
    try {
      const { data } = await http.get<ScopedHourlyPushCfg>("/alerts/hourly-push-config", { params: { scope } });
      setCfg(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const save = async (silent = false) => {
    setSaving(true);
    try {
      const { data } = await http.put<ScopedHourlyPushCfg>(
        "/alerts/hourly-push-config",
        { enabled: cfg.enabled, rules: cfg.rules },
        { params: { scope }, timeout: 20000 },
      );
      setCfg(data);
      if (!silent) {
        message.success(`${meta.label}小时推送设置已保存`);
        setOpen(false);
      }
      return data;
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
      const saved = await save(true);
      const { data } = await http.post<{ messages: string[]; pushed: boolean }>(
        "/alerts/hourly-push/check",
        undefined,
        { params: { push: 1, scope }, timeout: 30000 },
      );
      if (!data.messages.length) {
        message.info(`${meta.label}上个小时暂无触发异常的规则`);
      } else if (data.pushed) {
        message.success(`检查到 ${Math.max(data.messages.length - 1, 1)} 条异常，已推送`);
      } else if (!saved.enabled) {
        message.warning("检查到异常，但当前页面的小时推送尚未启用");
      } else {
        message.warning("检查到异常，但统一推送渠道尚未配置完整");
      }
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setChecking(false);
    }
  };

  const addRule = () => {
    if (!newField) return;
    const fieldKind = meta.fields.find((field) => field.key === newField)?.kind;
    const operator = fieldKind === "value" && !["lt", "gt"].includes(newOp) ? "lt" : newOp;
    setCfg((previous) => ({
      ...previous,
      rules: [...previous.rules, {
        id: `hp_${scope}_${Date.now()}_${Math.floor(Math.random() * 10000)}`,
        field: newField,
        operator,
        threshold: Number(newTh),
        compare: newCompare,
        scene: scope === "hours" && PROMO_FIELDS.includes(newField) ? newScene : "",
        enabled: true,
      }],
    }));
    setNewField(undefined);
    setNewOp("cycle_drop_pct");
    setNewTh(30);
    setNewCompare("yesterday");
    setNewScene("");
  };

  const updateRule = (id: string, enabled: boolean) => {
    setCfg((previous) => ({
      ...previous,
      rules: previous.rules.map((rule) => rule.id === id ? { ...rule, enabled } : rule),
    }));
  };

  const selectedField = meta.fields.find((field) => field.key === newField);
  const operatorOptions = selectedField?.kind === "value"
    ? RULE_OPERATORS.filter((option) => ["lt", "gt"].includes(option.value))
    : RULE_OPERATORS;

  return (
    <>
      <Button icon={<SendOutlined />} onClick={openModal}>小时推送</Button>
      <Modal
        title={`${meta.label} · 小时推送设置`}
        open={open}
        onCancel={() => setOpen(false)}
        onOk={() => void save(false)}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        width={620}
        destroyOnHidden
      >
        <div style={{ display: "grid", gap: 14 }}>
          <Alert
            type={cfg.channel_ready ? "info" : "warning"}
            showIcon
            message={cfg.channel_ready ? `统一推送渠道已配置：${cfg.channel}` : "统一推送渠道尚未配置完整"}
            description="本页只保存自己的开关和规则；PushPlus Token 与 Webhook 在系统设置中统一维护。"
            action={<Button size="small" icon={<SettingOutlined />} onClick={() => { setOpen(false); navigate("/settings"); }}>渠道设置</Button>}
          />
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>独立启用</span> <span style={{ marginLeft: 8, fontSize: 12, color: "var(--ops-text-3)" }}>仅控制“{meta.label}”页面，不影响其他页面</span></div>
            <Switch checked={cfg.enabled} onChange={(enabled) => setCfg((previous) => ({ ...previous, enabled }))} checkedChildren="开" unCheckedChildren="关" />
          </div>
          <div style={{ borderTop: "1px solid var(--ops-border)", paddingTop: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{meta.label}独立规则</div>
            <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 10 }}>{meta.hint}</Text>
            {cfg.rules.length === 0 && <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>还没有规则，添加后只会在本页面生效。</Text>}
            <div style={{ display: "grid", gap: 6, marginBottom: 10 }}>
              {cfg.rules.map((rule) => (
                <div key={rule.id} style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius-sm)", padding: "6px 10px" }}>
                  <Text style={{ fontSize: 13, flex: 1 }}>
                    {rule.scene ? `[${SCENE_OPTIONS.find((option) => option.value === rule.scene)?.label || rule.scene}] ` : ""}
                    {ruleText({ id: rule.id, module: meta.module, field: rule.field, operator: rule.operator, threshold: rule.threshold, enabled: rule.enabled })}
                    {meta.compareSelectable && ["cycle_drop_pct", "cycle_up_pct"].includes(rule.operator) ? `（${rule.compare === "prev_hour" ? "较上一小时" : "较昨日同时段"}）` : ""}
                  </Text>
                  <Switch size="small" checked={rule.enabled} onChange={(enabled) => updateRule(rule.id, enabled)} />
                  <Button size="small" danger type="text" onClick={() => setCfg((previous) => ({ ...previous, rules: previous.rules.filter((item) => item.id !== rule.id) }))}>删除</Button>
                </div>
              ))}
            </div>
            <Space wrap>
              <Select size="small" style={{ width: 140 }} placeholder="字段" options={meta.fields.map((field) => ({ value: field.key, label: field.label }))} value={newField} onChange={(field) => { setNewField(field); if (meta.fields.find((item) => item.key === field)?.kind === "value") setNewOp("lt"); }} />
              <Select size="small" style={{ width: 150 }} options={operatorOptions} value={newOp} onChange={setNewOp} />
              {scope === "hours" && PROMO_FIELDS.includes(newField || "") ? <Select size="small" style={{ width: 130 }} options={SCENE_OPTIONS} value={newScene} onChange={setNewScene} /> : null}
              {meta.compareSelectable && selectedField?.kind === "cycle" && ["cycle_drop_pct", "cycle_up_pct"].includes(newOp) ? <Select size="small" style={{ width: 130 }} options={COMPARE_OPTIONS} value={newCompare} onChange={setNewCompare} /> : null}
              <InputNumber size="small" style={{ width: 100 }} placeholder="阈值" value={newTh} min={0} onChange={(value) => setNewTh(Number(value ?? 0))} />
              <Button size="small" type="primary" onClick={addRule} disabled={!newField}>添加规则</Button>
            </Space>
          </div>
          <div style={{ borderTop: "1px solid var(--ops-border)", paddingTop: 12, display: "flex", gap: 10 }}>
            <Button icon={<SendOutlined />} loading={testing} disabled={!cfg.channel_ready} onClick={test}>测试渠道</Button>
            <Button loading={checking} onClick={check}>立即检查本页规则</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
