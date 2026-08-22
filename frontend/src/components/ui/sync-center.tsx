import { CheckCircleOutlined, CloudSyncOutlined, ExclamationCircleOutlined, HistoryOutlined, LoadingOutlined, ReloadOutlined } from "@ant-design/icons";
import { Badge, Button, Empty, Popover, Segmented, Space, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import http, { getApiErrorMessage } from "../../lib/api";
import { useStores } from "../../lib/store";

const { Text } = Typography;

export type SyncLoopStatus = {
  name: string;
  last_run: string | null;
  last_success: string | null;
  last_error: string | null;
  error_count: number;
  run_count: number;
  last_duration: number;
  running: boolean;
  last_started: string | null;
};

type SyncRun = {
  id: number;
  name: string;
  status: "success" | "error";
  trigger: "auto" | "manual";
  store_id: number | null;
  store_name: string | null;
  started_at: string | null;
  finished_at: string;
  duration: number;
  error: string;
};

const LABELS: Record<string, string> = {
  inspect: "系统巡检",
  realtime_sync: "经营数据同步",
  product_catalog_sync: "在售商品同步",
  report_push: "经营日报推送",
  hourly_push: "小时数据推送",
  promo_daily: "推广数据补录",
  backup: "数据库备份",
  data_cleanup: "历史数据清理",
  log_rotate: "日志轮转",
};

function formatTime(value: string | null): string {
  if (!value) return "尚未成功";
  const date = new Date(value.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

export function SyncCenter({ compact = false }: { compact?: boolean }) {
  const navigate = useNavigate();
  const { currentStore } = useStores();
  const [items, setItems] = useState<SyncLoopStatus[]>([]);
  const [history, setHistory] = useState<SyncRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"status" | "history">("status");
  const [retrying, setRetrying] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await http.get<{ items: SyncLoopStatus[] }>("/system/loops");
      setItems(data.items);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const { data } = await http.get<{ items: SyncRun[] }>("/system/loops/history?limit=30");
      setHistory(data.items);
    } catch {
      setHistory([]);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (open) loadHistory();
  }, [loadHistory, open]);

  const retry = async (name: string) => {
    setRetrying(name);
    try {
      const scope = currentStore && name !== "inspect" ? `?store_id=${currentStore.id}` : "";
      await http.post(`/system/loops/${name}/retry${scope}`, {}, { timeout: 240000 });
      message.success(`${LABELS[name] ?? name}重试成功`);
      await Promise.all([load(), loadHistory()]);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      await Promise.all([load(), loadHistory()]);
    } finally {
      setRetrying(null);
    }
  };

  const abnormal = useMemo(() => items.filter((item) => item.error_count > 0), [items]);
  const running = useMemo(() => items.filter((item) => item.running), [items]);
  const state = abnormal.length > 0 ? "error" : running.length > 0 ? "processing" : "success";
  const label = abnormal.length > 0 ? `${abnormal.length} 项同步异常` : running.length > 0 ? `${running.length} 项同步中` : "数据同步正常";

  return (
    <Popover
      placement="bottomRight"
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      content={(
        <div className="ops-sync-center">
          <div className="ops-sync-center__head">
            <div>
              <Text strong>数据同步中心</Text>
              <Text type="secondary" className="ops-sync-center__caption">统一查看数据来源与后台任务状态</Text>
            </div>
            <Button size="small" type="text" onClick={load} loading={loading}>刷新</Button>
          </div>
          <Segmented
            block
            size="small"
            value={view}
            onChange={(value) => setView(value as "status" | "history")}
            options={[{ label: "当前状态", value: "status", icon: <CloudSyncOutlined /> }, { label: "同步历史", value: "history", icon: <HistoryOutlined /> }]}
            style={{ marginBottom: 10 }}
          />
          {view === "status" && items.length === 0 && !loading ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂时无法取得同步状态" />
          ) : view === "status" ? (
            <div className="ops-sync-center__list">
              {items.map((item) => (
                <div className="ops-sync-row" key={item.name}>
                  <span className={`ops-sync-row__icon ops-sync-row__icon--${item.running ? "running" : item.error_count > 0 ? "error" : "ok"}`}>
                    {item.running ? <LoadingOutlined /> : item.error_count > 0 ? <ExclamationCircleOutlined /> : <CheckCircleOutlined />}
                  </span>
                  <div className="ops-sync-row__body">
                    <Space size={6}>
                      <Text strong>{LABELS[item.name] ?? item.name}</Text>
                      {item.running ? <Tag color="processing">同步中</Tag> : item.error_count > 0 ? <Tag color="error">异常</Tag> : null}
                    </Space>
                    <Text type="secondary">最近成功 {formatTime(item.last_success)} · 耗时 {item.last_duration || 0}s</Text>
                    {item.last_error ? <Text type="danger" ellipsis={{ tooltip: item.last_error }}>{item.last_error}</Text> : null}
                  </div>
                  {(["realtime_sync", "product_catalog_sync", "inspect"].includes(item.name)) ? (
                    <Button size="small" type="text" icon={<ReloadOutlined />} loading={retrying === item.name} disabled={Boolean(retrying) && retrying !== item.name} onClick={() => retry(item.name)}>重试</Button>
                  ) : null}
                </div>
              ))}
            </div>
          ) : history.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无同步历史" />
          ) : (
            <div className="ops-sync-center__list">
              {history.map((run) => (
                <div className="ops-sync-row" key={run.id}>
                  <span className={`ops-sync-row__icon ops-sync-row__icon--${run.status === "success" ? "ok" : "error"}`}>
                    {run.status === "success" ? <CheckCircleOutlined /> : <ExclamationCircleOutlined />}
                  </span>
                  <div className="ops-sync-row__body">
                    <Space size={6}><Text strong>{LABELS[run.name] ?? run.name}</Text><Tag>{run.trigger === "manual" ? "手动" : "自动"}</Tag></Space>
                    <Text type="secondary">{run.store_name || "全部店铺"} · {formatTime(run.finished_at)} · {run.duration}s</Text>
                    {run.error ? <Text type="danger" ellipsis={{ tooltip: run.error }}>{run.error}</Text> : null}
                  </div>
                </div>
              ))}
            </div>
          )}
          <Button
            block
            onClick={() => {
              setOpen(false);
              navigate("/tasks");
            }}
          >
            查看全部任务
          </Button>
        </div>
      )}
    >
      <Badge dot={abnormal.length > 0} status={state} offset={[-3, 3]}>
        <Button type="text" icon={<CloudSyncOutlined />} aria-label="数据同步中心">
          {!compact ? label : null}
        </Button>
      </Badge>
    </Popover>
  );
}
