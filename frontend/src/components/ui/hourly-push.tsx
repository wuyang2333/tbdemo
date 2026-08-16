import { SendOutlined } from "@ant-design/icons";
import { Button, Input, InputNumber, Modal, Select, Space, Switch, Typography, message } from "antd";
import { useState } from "react";

import http, { getApiErrorMessage } from "../../lib/api";
import { RULE_FIELDS, RULE_OPERATORS, ruleText } from "../../lib/alert-rules";

const { Text } = Typography;

type HourlyRule = { id: string; field: string; operator: string; threshold: number; enabled: boolean };

/** 小时异常推送设置（pushplus → 微信），供经营日报/商品分析/推广计划共用。 */
export function HourlyPushButton() {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<{ enabled: boolean; token: string; rules: HourlyRule[] }>({ enabled: false, token: "", rules: [] });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [newField, setNewField] = useState<string | undefined>(undefined);
  const [newOp, setNewOp] = useState("cycle_drop_pct");
  const [newTh, setNewTh] = useState(30);

  const openModal = async () => {
    setOpen(true);
    try {
      const { data } = await http.get<{ enabled: boolean; token: string; rules: HourlyRule[] }>("/alerts/hourly-push-config");
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
      message.success("已发送测试消息，请查看微信");
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
      if (data.messages.length) message.success(`检查到 ${data.messages.length} 条异常，已推送微信`);
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
      rules: [...p.rules, { id: `hp_${Date.now()}_${Math.floor(Math.random() * 10000)}`, field: newField, operator: newOp, threshold: Number(newTh), enabled: true }],
    }));
    setNewField(undefined);
    setNewOp("cycle_drop_pct");
    setNewTh(30);
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
        destroyOnClose
      >
        <div style={{ display: "grid", gap: 14 }}>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>启用</span> <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>开启后每小时自动检查上个小时数据，触发规则推送到微信</span></div>
            <Switch checked={cfg.enabled} onChange={(v) => setCfg((p) => ({ ...p, enabled: v }))} checkedChildren="开" unCheckedChildren="关" />
          </div>
          <div>
            <div style={{ marginBottom: 4 }}><span style={{ fontWeight: 600 }}>pushplus Token</span> <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>pushplus.plus 绑定微信后获取</span></div>
            <Input placeholder="pushplus token" value={cfg.token} onChange={(e) => setCfg((p) => ({ ...p, token: e.target.value }))} />
          </div>
          <div style={{ borderTop: "1px solid var(--ops-border)", paddingTop: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>小时级推送规则（较昨日同时段 / 阈值）</div>
            {cfg.rules.length === 0 && <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>还没有规则，添加一条试试。</Text>}
            <div style={{ display: "grid", gap: 6, marginBottom: 10 }}>
              {cfg.rules.map((r) => (
                <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", borderRadius: 8, padding: "6px 10px" }}>
                  <Text style={{ fontSize: 13, flex: 1 }}>{ruleText({ id: r.id, module: "hour", field: r.field, operator: r.operator as "cycle_drop_pct" | "cycle_up_pct" | "lt" | "gt", threshold: r.threshold, enabled: r.enabled })}</Text>
                  <Switch size="small" checked={r.enabled} onChange={(c) => updRule(r.id, { enabled: c })} />
                  <Button size="small" danger type="text" onClick={() => delRule(r.id)}>删除</Button>
                </div>
              ))}
            </div>
            <Space wrap>
              <Select size="small" style={{ width: 130 }} placeholder="字段" options={RULE_FIELDS.hour.map((f) => ({ value: f.key, label: f.label }))} value={newField} onChange={setNewField} />
              <Select size="small" style={{ width: 150 }} options={RULE_OPERATORS.map((o) => ({ value: o.value, label: o.label }))} value={newOp} onChange={setNewOp} />
              <InputNumber size="small" style={{ width: 110 }} placeholder="阈值" value={newTh} min={0} onChange={(v) => setNewTh(Number(v ?? 0))} />
              <Button size="small" type="primary" onClick={addRule} disabled={!newField}>添加规则</Button>
            </Space>
            <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>例：销售额 环比跌超 30% → 上个小时销售额较昨日同时段跌超 30% 时推微信</Text>
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
