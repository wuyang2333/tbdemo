import { Descriptions, Drawer, Tag, Typography } from "antd";
import dayjs from "dayjs";

import type { Store } from "../../types";

const { Text } = Typography;

function StatusTag({ status }: { status: Store["display_status"] }) {
  if (status === "active") return <Tag color="green">正常</Tag>;
  return <Tag color="red">授权异常</Tag>;
}

function LoginStatusTag({ status, error }: { status: Store["sycm_status"]; error: string | null }) {
  if (status === "ok") return <Tag color="green">登录正常</Tag>;
  if (status === "error") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Tag color="red">登录失效</Tag>
        {error ? <Text type="secondary" style={{ fontSize: 12 }}>{error}</Text> : null}
      </div>
    );
  }
  if (status === "not_configured") return <Tag>未绑定</Tag>;
  return <Tag color="orange">检测中</Tag>;
}

function timeAgo(value: string | null): string {
  if (!value) return "从未同步";
  const diff = Date.now() - dayjs(value).valueOf();
  if (!Number.isFinite(diff) || diff < 0) return "从未同步";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "刚刚";
  if (mins < 60) return `${mins} 分钟前`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

export function StoreDetailDrawer({
  store,
  open,
  onClose,
}: {
  store: Store | null;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <Drawer title={store?.name ?? "店铺详情"} open={open} onClose={onClose} size="default">
      {store ? (
        <Descriptions
          size="small"
          column={2}
          items={[
            { key: "status", label: "店铺状态", children: <StatusTag status={store.display_status} /> },
            {
              key: "login",
              label: "生意参谋登录",
              children: <LoginStatusTag status={store.sycm_status} error={store.sycm_error} />,
            },
            { key: "sync", label: "数据更新", children: timeAgo(store.last_sync_at) },
            { key: "created", label: "创建时间", children: dayjs(store.created_at).format("YYYY-MM-DD HH:mm") },
          ]}
        />
      ) : null}
    </Drawer>
  );
}
