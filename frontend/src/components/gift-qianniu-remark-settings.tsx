import { FlagOutlined } from "@ant-design/icons";
import { Alert, Card, Space, Switch, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";

import http, { getApiErrorMessage } from "../lib/api";

const { Text } = Typography;

type GiftRemarkConfig = {
  enabled: boolean;
  flag: number;
  memo: string;
  pending: number;
  failed: number;
};

const DEFAULT_CONFIG: GiftRemarkConfig = {
  enabled: false,
  flag: 1,
  memo: "SD",
  pending: 0,
  failed: 0,
};

export function GiftQianniuRemarkSettings() {
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await http.get<GiftRemarkConfig>("/settings/gift-qianniu-remark");
      setConfig(data);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (enabled: boolean) => {
    const previous = config.enabled;
    setConfig((current) => ({ ...current, enabled }));
    setLoading(true);
    try {
      const { data } = await http.put<GiftRemarkConfig>("/settings/gift-qianniu-remark", { enabled });
      setConfig(data);
      message.success(enabled ? "礼品单千牛自动备注已开启" : "礼品单千牛自动备注已关闭");
    } catch (error) {
      setConfig((current) => ({ ...current, enabled: previous }));
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card variant="borderless" title="礼品单 · 千牛自动备注" style={{ marginTop: 16 }}>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Space wrap>
          <FlagOutlined style={{ color: "#f5222d" }} />
          <Text>订单号从腾讯文档回传后，自动查询千牛已卖出商品</Text>
          <Switch checked={config.enabled} loading={loading} onChange={toggle} />
          <Tag color="red">红旗</Tag>
          <Tag>备注 {config.memo}</Tag>
        </Space>
        <Alert
          type={config.failed ? "warning" : "info"}
          showIcon
          message={`等待处理 ${config.pending} 条，失败待重试 ${config.failed} 条`}
          description="只有精确匹配订单并经千牛再次确认红旗和备注后，系统状态才会变为“已备注”。"
        />
      </Space>
    </Card>
  );
}
