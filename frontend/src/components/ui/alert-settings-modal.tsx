import { Button, InputNumber, Modal, Select, Switch, Typography } from "antd";
import { useEffect, useState } from "react";

import type { AlertCondition, AlertRule, RuleModule } from "../../lib/alert-rules";
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
  const emptyCondition = (): AlertCondition => ({ module, field: "", operator: "lt", threshold: 0 });
  const [newConditions, setNewConditions] = useState<AlertCondition[]>([emptyCondition()]);

  useEffect(() => {
    if (!open) return;
    const v: Record<string, number> = {};
    for (const f of fields) {
      const group = config[f.group] as unknown as Record<string, number>;
      v[f.key] = group[f.key] ?? 0;
    }
    setValues(v);
    setDraftRules(rules.filter((r) => r.module === module));
    setNewConditions([emptyCondition()]);
  }, [open, fields, config, rules, module]);

  const handleOk = () => {
    const patch = {} as Record<string, unknown>;
    for (const f of fields) {
      const group = (patch[f.group] ?? {}) as Record<string, number>;
      group[f.key] = values[f.key] ?? 0;
      patch[f.group] = group;
    }
    // 允许用户直接点弹窗底部“保存”：如果新建区域已经填好，自动把它收进规则列表，
    // 避免必须先点一次“保存这条规则”再点一次弹窗保存而造成“保存了但没显示”的错觉。
    const pendingConditions = newConditions
      .filter((condition) => condition.field && Number.isFinite(condition.threshold))
      .map((condition) => ({ ...condition, module, threshold: Number(condition.threshold) }));
    const pendingRule: AlertRule | null = pendingConditions.length
      ? {
          id: `rule_${Date.now()}_${Math.floor(Math.random() * 10000)}`,
          module,
          field: pendingConditions[0].field,
          operator: pendingConditions[0].operator,
          threshold: pendingConditions[0].threshold,
          enabled: true,
          conditions: pendingConditions.length > 1 ? pendingConditions : undefined,
        }
      : null;
    const nextRules = pendingRule ? [...draftRules, pendingRule] : draftRules;
    const others = rules.filter((r) => r.module !== module);
    patch.rules = [...others, ...nextRules];
    onSave(patch as Partial<AlertConfig>);
  };

  const updateRule = (id: string, patchRule: Partial<AlertRule>) => {
    setDraftRules((prev) => prev.map((r) => (r.id === id ? { ...r, ...patchRule } : r)));
  };
  const removeRule = (id: string) => {
    setDraftRules((prev) => prev.filter((r) => r.id !== id));
  };
  const updateNewCondition = (index: number, patch: Partial<AlertCondition>) => {
    setNewConditions((prev) => prev.map((condition, i) => (i === index ? { ...condition, ...patch, module } : condition)));
  };
  const removeNewCondition = (index: number) => {
    setNewConditions((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)));
  };
  const canAddRule = newConditions.length > 0 && newConditions.every((condition) => condition.field && Number.isFinite(condition.threshold));
  const addRule = () => {
    if (!canAddRule) return;
    const conditions = newConditions.map((condition) => ({ ...condition, module, threshold: Number(condition.threshold) }));
    const first = conditions[0];
    setDraftRules((prev) => [
      ...prev,
      {
        id: `rule_${Date.now()}_${Math.floor(Math.random() * 10000)}`,
        module,
        field: first.field,
        operator: first.operator,
        threshold: first.threshold,
        enabled: true,
        conditions: conditions.length > 1 ? conditions : undefined,
      },
    ]);
    setNewConditions([emptyCondition()]);
  };

  const fieldOptions = RULE_FIELDS[module].map((f) => ({ value: f.key, label: f.label }));
  const opOptions = RULE_OPERATORS.map((o) => ({ value: o.value, label: o.label }));

  return (
    <Modal title={title} open={open} onCancel={onCancel} onOk={handleOk} okText="保存" cancelText="取消" confirmLoading={saving} destroyOnHidden width={560}>
      <div style={{ display: "grid", gap: 14 }}>
        {fields.map((f) => (
          <div key={f.key}>
            <div style={{ marginBottom: 4 }}>
              <span style={{ fontWeight: 600 }}>{f.label}</span>
              {f.hint && <span style={{ marginLeft: 8, fontSize: 12, color: "var(--ops-text-3)" }}>{f.hint}</span>}
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
        <div style={{ display: "grid", gap: 10, marginBottom: 14 }}>
          {draftRules.map((r) => (
            <div key={r.id} style={{ background: "var(--ops-card-bg-2)", border: "1px solid var(--ops-border)", borderRadius: "var(--ops-radius-sm)", padding: "10px 12px" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
                <Text strong style={{ fontSize: 13 }}>规则</Text>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <Switch size="small" checked={r.enabled} onChange={(c) => updateRule(r.id, { enabled: c })} />
                  <Button size="small" danger type="text" onClick={() => removeRule(r.id)}>删除</Button>
                </div>
              </div>
              <div style={{ display: "grid", gap: 5 }}>
                {(r.conditions?.length ? r.conditions : [{ module: r.module, field: r.field, operator: r.operator, threshold: r.threshold }]).map((condition, index) => (
                  <div key={`${r.id}-${index}`} style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    {index > 0 && <Text type="secondary" style={{ width: 32, textAlign: "center", fontSize: 12 }}>且</Text>}
                    <Text style={{ fontSize: 13 }}>{ruleText({ id: "condition", enabled: true, ...condition })}</Text>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div style={{ border: "1px dashed var(--ops-border)", borderRadius: "var(--ops-radius-sm)", padding: "12px" }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>新建规则</div>
          <div style={{ display: "grid", gap: 8 }}>
            {newConditions.map((condition, index) => (
              <div key={index} style={{ display: "grid", gridTemplateColumns: "minmax(120px, 1fr) minmax(120px, 1fr) 100px auto", alignItems: "center", gap: 8 }}>
                <Text type="secondary" style={{ gridColumn: "1 / -1", fontSize: 12 }}>{index > 0 ? "且 条件" : "条件 1"}{index > 0 ? ` ${index + 1}` : ""}</Text>
                <Select size="small" placeholder="选择字段" options={fieldOptions} value={condition.field || undefined} onChange={(value) => updateNewCondition(index, { field: value })} />
                <Select size="small" options={opOptions} value={condition.operator} onChange={(value) => updateNewCondition(index, { operator: value as AlertCondition["operator"] })} />
                <InputNumber size="small" style={{ width: "100%" }} placeholder="阈值" value={condition.threshold} min={0} onChange={(value) => updateNewCondition(index, { threshold: Number(value ?? 0) })} />
                <Button size="small" danger type="text" onClick={() => removeNewCondition(index)} disabled={newConditions.length <= 1}>移除</Button>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Button size="small" onClick={() => setNewConditions((prev) => [...prev, emptyCondition()])}>+ 添加条件</Button>
            <Button size="small" type="primary" onClick={addRule} disabled={!canAddRule}>保存这条规则</Button>
          </div>
        </div>
        <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 8 }}>
          例：推广ROI 环比跌超 40% → 全部{module === "product" ? "商品" : module === "plan" ? "计划" : "时段"}提醒
        </Text>
      </div>
    </Modal>
  );
}
