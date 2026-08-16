import { InputNumber, Modal } from "antd";
import { useEffect, useState } from "react";

import type { AlertConfig } from "../../lib/use-alert-config";

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
  fields,
  config,
  onCancel,
  onSave,
  saving,
}: {
  open: boolean;
  title: string;
  fields: AlertField[];
  config: AlertConfig;
  onCancel: () => void;
  onSave: (patch: Partial<AlertConfig>) => void;
  saving?: boolean;
}) {
  const [values, setValues] = useState<Record<string, number>>({});
  useEffect(() => {
    if (!open) return;
    const v: Record<string, number> = {};
    for (const f of fields) {
      const group = config[f.group] as unknown as Record<string, number>;
      v[f.key] = group[f.key] ?? 0;
    }
    setValues(v);
  }, [open, fields, config]);

  const handleOk = () => {
    const patch = {} as Record<string, Record<string, number>>;
    for (const f of fields) {
      patch[f.group] = patch[f.group] ?? {};
      patch[f.group][f.key] = values[f.key] ?? 0;
    }
    onSave(patch as Partial<AlertConfig>);
  };

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onCancel}
      onOk={handleOk}
      okText="保存"
      cancelText="取消"
      confirmLoading={saving}
      destroyOnClose
    >
      <div style={{ display: "grid", gap: 14 }}>
        {fields.map((f) => (
          <div key={f.key}>
            <div style={{ marginBottom: 4 }}>
              <span style={{ fontWeight: 600 }}>{f.label}</span>
              {f.hint && (
                <span style={{ marginLeft: 8, fontSize: 12, color: "rgba(128,128,128,0.7)" }}>{f.hint}</span>
              )}
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
    </Modal>
  );
}
