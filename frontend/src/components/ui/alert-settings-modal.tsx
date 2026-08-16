import { Button, InputNumber, Modal, Select, Space, Switch, Typography } from "antd";
import { useEffect, useState } from "react";

import type { AlertRule, RuleModule } from "../../lib/alert-rules";
import { RULE_FIELDS, RULE_OPERATORS, ruleText } from "../../lib/alert-rules";
import type { AlertConfig } from "../../lib/use-alert-config";

const { Text } = Typography;

export type AlertField = {
  group: "hour" | "product" | "plan";
  key: string;
  label: string;
  hint?: string;
  min?: number;
  max?: number;
  step?: number;
};

export function AlertSettingsModal({
  open,
  title,
  module,
  fields,
  config,
  rules,
  onCancel,
  onSave,
  saving,
}: {
  open: boolean;
  title: string;
  module: RuleModule;
  fields: AlertField[];
  config: AlertConfig;
  rules: AlertRule[];
  onCancel: () => void;
  onSave: (patch: Partial<AlertConfig>) => void;
  saving?: boolean;
}) {
  const [values, setValues] = useState<Record<string, number>>({});
  const [draftRules, setDraftRules] = useState<AlertRule[]>([]);
  const [newField, setNewField] = useState<string | undefined>(undefined);
  const [newOp, setNewOp] = useState<string>("cycle_drop_pct");
  const [newThreshold, setNewThreshold] = useState<number>(30);

  useEffect(() => {
    if (!open) return;
    const v: Record<string, number> = {};
    for (const f of fields) {
      const group = config[f.group] as unknown as Record<string, number>;
      v[f.key] = group[f.key] ?? 0;
    }
    setValues(v);
    setDraftRules(rules.filter((r) => r.module === module));
  }, [open, fields, config, rules, module]);

  const handleOk = () => {
    const patch = {} as Record<string, unknown>;
    for (const f of fields) {
      const group = (patch[f.group] ?? {}) as Record<string, number>;
      group[f.key] = values[f.key] ?? 0;
      patch[f.group] = group;
    }
    const others = rules.filter((r) => r.module !== module);
    patch.rules = [...others, ...draftRules];
    onSave(patch as Partial<AlertConfig>);
  };

  const updateRule = (id: string, patchRule: Partial<AlertRule>) => {
    setDraftRules((prev) => prev.map((r) => (r.id === id ? { ...r, ...patchRule } : r)));
  };
  const removeRule = (id: string) => {
    setDraftRules((prev) => prev.filter((r) => r.id !== id));
  };
  const addRule = () => {
    if (!newField || !newThreshold) return;
    setDraftRules((prev) => [
      ...prev,
      {
        id: `rule_${Date.now()}_${Math.floor(Math.random() * 10000)}`,
        module,
        field: newField,
        operator: newOp as AlertRule["operator"],
        threshold: Number(newThreshold),
        enabled: true,
      },
    ]);
    setNewField(undefined);
    setNewOp("cycle_drop_pct");
    setNewThreshold(30);
  };

  const fieldOptions = RULE_FIELDS[module].map((f) => ({ value: f.key, label: f.label }));
  const opOptions = RULE_OPERATORS.map((o) => ({ value: o.value, label: o.label }));

  return (
    <Modal title={title} open={open} onCancel={onCancel} onOk={handleOk} okText="保存" cancelText="取消" confirmLoading={saving} destroyOnClose width={560}>
      <div style={{ display: "grid", gap: 14 }}>
        {fields.map((f) => (
          <div key={f.key}>
            <div style={{ marginBottom: 4 }}>
              <span style={{ fontWeight: 600 }}>{f.label}</span>
              {f.hint && <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>{f.hint}</span>}
            </div>
            <InputNumber
              style={{ width: 180 }}
              value={values[f.key]}
              min={f.min ?? 0}
              max={f.max ?? 10000}
              step={f.step ?? 0.1}
              onChange={(v) => setValues((prev) => ({ ...prev, [f.key]: Number(v ?? 0) }))}
            />
          </div>
        ))}
      </div>

      <div style={{ borderTop: "1px solid var(--ops-border)", marginTop: 18, paddingTop: 14 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>自定义监控规则</div>
        {draftRules.length === 0 && (
          <Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
            还没有自定义规则，下面添加一条试试。
          </Text>
        )}
        <div style={{ display: "grid", gap: 6, marginBottom: 10 }}>
          {draftRules.map((r) => (
            <div key={r.id} style={{ display: "flex", alignItems: "center", gap: 8, background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", borderRadius: 8, padding: "6px 10px" }}>
              <Text style={{ fontSize: 13, flex: 1 }}>{ruleText(r)}</Text>
              <Switch size="small" checked={r.enabled} onChange={(c) => updateRule(r.id, { enabled: c })} />
              <Button size="small" danger type="text" onClick={() => removeRule(r.id)}>
                删除
              </Button>
            </div>
          ))}
        </div>
        <Space wrap>
          <Select size="small" style={{ width: 130 }} placeholder="字段" options={fieldOptions} value={newField} onChange={setNewField} />
          <Select size="small" style={{ width: 140 }} options={opOptions} value={newOp} onChange={setNewOp} />
          <InputNumber size="small" style={{ width: 110 }} placeholder="阈值" value={newThreshold} min={0} onChange={(v) => setNewThreshold(Number(v ?? 0))} />
          <Button size="small" type="primary" onClick={addRule} disabled={!newField}>
            添加规则
          </Button>
        </Space>
        <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>
          例：推广ROI 环比跌超 40% → 全部{module === "product" ? "商品" : module === "plan" ? "计划" : "时段"}提醒
        </Text>
      </div>
    </Modal>
  );
}
