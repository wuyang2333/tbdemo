import { HolderOutlined, SettingOutlined } from "@ant-design/icons";
import { Button, Checkbox, Popover, Typography } from "antd";
import { useState } from "react";

const { Text } = Typography;

export type ColDef = { key: string; title: string };

/**
 * 通用「字段设置」：拖拽调整列顺序 + 勾选控制列显隐。
 * 与商品分析 / 推广计划保持一致，配置由父组件持久化。
 */
export function ColumnSettings({
  columns,
  hidden,
  order,
  onChange,
}: {
  columns: ColDef[];
  hidden: string[];
  order: string[];
  onChange: (next: { hidden: string[]; order: string[] }) => void;
}) {
  const [dragKey, setDragKey] = useState<string | null>(null);

  const ordered = [...columns].sort((a, b) => {
    const ia = order.indexOf(a.key);
    const ib = order.indexOf(b.key);
    return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
  });

  const toggle = (key: string, checked: boolean) =>
    onChange({
      hidden: checked ? hidden.filter((k) => k !== key) : [...hidden, key],
      order,
    });

  const drop = (target: string) => {
    if (!dragKey || dragKey === target) return;
    const list = ordered.map((c) => c.key);
    const from = list.indexOf(dragKey);
    const to = list.indexOf(target);
    if (from < 0 || to < 0) return;
    list.splice(from, 1);
    list.splice(to, 0, dragKey);
    onChange({ hidden, order: list });
    setDragKey(null);
  };

  return (
    <Popover
      trigger="click"
      placement="bottomRight"
      content={
        <div style={{ width: 240 }}>
          {ordered.map((o) => (
            <div
              key={o.key}
              draggable
              onDragStart={() => setDragKey(o.key)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => drop(o.key)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 6px",
                borderRadius: "var(--ops-radius-xs)",
                cursor: "grab",
                background: dragKey === o.key ? "var(--ops-accent-soft)" : "transparent",
              }}
            >
              <HolderOutlined style={{ color: "var(--ops-text-3)", fontSize: 12 }} />
              <Checkbox checked={!hidden.includes(o.key)} onChange={(e) => toggle(o.key, e.target.checked)}>
                {o.title}
              </Checkbox>
            </div>
          ))}
          <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 6, paddingLeft: 6 }}>
            拖动调整列顺序 · 勾选控制显示
          </Text>
        </div>
      }
    >
      <Button icon={<SettingOutlined />}>字段设置</Button>
    </Popover>
  );
}

export default ColumnSettings;
