import { HistoryOutlined, ReloadOutlined } from "@ant-design/icons";
import { Button, Drawer, Empty, Space, Tag, Timeline, Typography, message } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { canAccessModule } from "../../lib/modules";
import type { OpLog } from "../../types";

const { Text } = Typography;

const MODULE_LABELS: Record<string, string> = {
  stores: "店铺",
  products: "商品",
  gifts: "礼品单",
  promotions: "推广",
  accounts: "账号",
  system: "系统",
  dashboard: "总览",
};

const ACTION_LABELS: Record<string, string> = {
  current: "切换当前店铺",
  retry_sync: "重试同步任务",
  create: "新增",
  edit: "编辑",
  delete: "删除",
  sync: "同步数据",
  perm: "调整权限",
  maintenance_enable: "进入维护模式",
  maintenance_update: "更新维护设置",
  maintenance_resume: "恢复后台任务",
  maintenance_auto_resume: "维护到期自动恢复",
};

export function OperationHistory({ compact = false }: { compact?: boolean }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<OpLog[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: OpLog[] }>("/logs?limit=50");
      setItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [load, open]);

  return (
    <>
      <Button type="text" icon={<HistoryOutlined />} onClick={() => setOpen(true)} aria-label="操作历史">
        {!compact ? "操作历史" : null}
      </Button>
      <Drawer
        title="操作历史"
        width={440}
        open={open}
        onClose={() => setOpen(false)}
        extra={<Button type="text" icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>}
        footer={canAccessModule(user, "logs") ? <Button block onClick={() => { setOpen(false); navigate("/logs"); }}>查看完整操作日志</Button> : null}
      >
        {items.length === 0 && !loading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无操作记录" />
        ) : (
          <Timeline
            items={items.map((item) => ({
              color: item.action === "delete" ? "red" : item.action.includes("sync") ? "blue" : "gray",
              children: (
                <div className="ops-history-item">
                  <Space size={6} wrap>
                    <Tag>{MODULE_LABELS[item.module] ?? item.module}</Tag>
                    <Text strong>{ACTION_LABELS[item.action] ?? item.action}</Text>
                  </Space>
                  {item.target_name ? <Text style={{ display: "block", marginTop: 4 }}>{item.target_name}</Text> : null}
                  {item.detail ? <Text type="secondary" style={{ display: "block", fontSize: 12 }}>{item.detail}</Text> : null}
                  <Text type="secondary" style={{ display: "block", fontSize: 11, marginTop: 4 }}>{item.username} · {dayjs(item.created_at).format("MM-DD HH:mm:ss")}</Text>
                </div>
              ),
            }))}
          />
        )}
      </Drawer>
    </>
  );
}
