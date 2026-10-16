import { ArrowLeftOutlined, ArrowRightOutlined, EditOutlined, LinkOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Form, Input, List, Modal, Row, Select, Space, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { DecisionBand, MetricRail, WorkspacePage } from "../components/ui/workspace-template";
import http, { getApiErrorMessage } from "../lib/api";
import type { CollectorStatus, CompetitorEvent, CompetitorProduct, CompetitorShop } from "./monitoring-types";
import { formatEventDetail, formatObservedAt, growthColor } from "./monitoring-types";

const { Text } = Typography;

type ShopDetailResponse = { item: CompetitorShop; products: CompetitorProduct[]; events: CompetitorEvent[] };

function itemNeedsLogin(item?: CompetitorShop): boolean {
  return Boolean(item?.last_scan_status === "failed" && /登录|安全验证|滑块|采集浏览器/.test(item.last_scan_error || ""));
}

export function MonitoringShopDetailPage() {
  const { shopId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<ShopDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);
  const [openingCollector, setOpeningCollector] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editForm] = Form.useForm();
  const resumeAfterLoginRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try { const response = await http.get<ShopDetailResponse>(`/monitoring/shops/${shopId}`); setData(response.data); }
    catch (requestError) { setError(getApiErrorMessage(requestError)); }
    finally { setLoading(false); }
  }, [shopId]);

  useEffect(() => { void load(); }, [load]);
  const scan = useCallback(async () => {
    setScanning(true);
    message.loading({ content: "正在逐页扫描店铺，每翻一页都会等待商品加载…", key: "shop-detail-scan", duration: 0 });
    try {
      const response = await http.post(`/monitoring/shops/${shopId}/scan`, undefined, { timeout: 180000 });
      message.success({ content: response.data.baseline ? `已建立商品基线，共发现 ${response.data.scanned} 个商品` : `扫描完成，共识别 ${response.data.scanned} 个商品，发现 ${response.data.new_products} 个新商品`, key: "shop-detail-scan", duration: 6 });
      await load();
    } catch (requestError) { message.error({ content: getApiErrorMessage(requestError), key: "shop-detail-scan", duration: 8 }); await load(); }
    finally { setScanning(false); }
  }, [load, shopId]);
  const openCollector = async () => {
    setOpeningCollector(true);
    resumeAfterLoginRef.current = true;
    try { const response = await http.post(`/monitoring/shops/${shopId}/collector/open`); message.info({ content: `${response.data.message}；完成登录或验证后，系统会自动继续扫描`, duration: 6 }); }
    catch (requestError) { resumeAfterLoginRef.current = false; message.error(getApiErrorMessage(requestError)); }
    finally { setOpeningCollector(false); }
  };
  const saveShop = async (values: Partial<CompetitorShop>) => {
    if (!data) return;
    try {
      await http.put(`/monitoring/shops/${shopId}`, {
        name: values.name || data.item.name,
        url: values.url || "",
        competitor_type: values.competitor_type || data.item.competitor_type,
        priority: values.priority || data.item.priority,
        category: values.category || "",
        price_band: values.price_band || "",
        notes: data.item.notes || "",
        monitor_frequency: values.monitor_frequency || data.item.monitor_frequency,
      });
      message.success("竞店资料已保存"); setEditing(false); await load();
    } catch (requestError) { message.error(getApiErrorMessage(requestError)); }
  };
  useEffect(() => {
    if (!itemNeedsLogin(data?.item)) return undefined;
    let active = true;
    const timer = window.setInterval(async () => {
      if (!resumeAfterLoginRef.current) return;
      try {
        const response = await http.get<CollectorStatus>("/monitoring/collector/status");
        if (active && response.data.login_ready) {
          resumeAfterLoginRef.current = false;
          message.loading({ content: "淘宝登录已完成，正在继续扫描竞店商品…", key: "shop-scan-resume", duration: 0 });
          await scan();
          message.destroy("shop-scan-resume");
        }
      } catch { /* Continue checking while the managed browser is open. */ }
    }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [data?.item, scan]);
  if (error) return <Alert type="error" showIcon title="竞店详情暂时无法加载" description={error} action={<Button onClick={() => navigate("/monitoring/shops")}>返回竞店管理</Button>} />;
  if (!data) return <Card loading={loading} />;
  const { item, products, events } = data;

  return <WorkspacePage kind="management">
    <Space style={{ marginBottom: 12 }}><Button type="link" icon={<ArrowLeftOutlined />} style={{ paddingInline: 0 }} onClick={() => navigate("/monitoring/shops")}>返回竞店管理</Button></Space>
    <DecisionBand ariaLabel={`${item.name}竞店详情`} eyebrow="竞店档案" title={item.name} description={`${item.category || "未设置主营类目"} · ${item.priority}关注 · ${item.monitor_frequency}扫描`} action={<Space>{item.url ? <Button icon={<LinkOutlined />} href={item.url} target="_blank">打开店铺</Button> : null}<Button icon={<EditOutlined />} onClick={() => { editForm.setFieldsValue(item); setEditing(true); }}>编辑竞店</Button><Button loading={scanning} disabled={!item.url} onClick={() => void scan()}>扫描全店商品</Button><Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新</Button></Space>} />
    {!item.url ? <Alert type="warning" showIcon title="还没有店铺链接" description="补充淘宝或天猫店铺链接后，系统才能自动扫描店内商品。" style={{ marginBottom: 16 }} /> : item.last_scan_status === "failed" ? <Alert type="warning" showIcon title="上次目录扫描失败" description={item.last_scan_error || "请重试；如果淘宝要求登录或安全验证，请打开采集浏览器处理。"} action={itemNeedsLogin(item) ? <Button loading={openingCollector} onClick={() => void openCollector()}>打开采集浏览器</Button> : undefined} style={{ marginBottom: 16 }} /> : null}
    <MetricRail columns={4} items={[{ label: "监控商品", value: item.product_count || 0, hint: `上次扫描识别 ${item.last_scan_product_count || 0} 个` }, { label: "本次新发现", value: item.last_new_product_count || 0, hint: item.last_scanned_at ? `扫描于 ${formatObservedAt(item.last_scanned_at)}` : item.last_scan_attempt_at ? `上次尝试 ${formatObservedAt(item.last_scan_attempt_at)}` : "首次扫描只建立基线" }, { label: "正在起量", value: item.rising_product_count || 0, hint: "达到增长阈值" }, { label: "采集异常", value: item.failed_collection_count || 0, hint: item.last_success_at ? `最近成功 ${formatObservedAt(item.last_success_at)}` : "尚无成功采集" }]} />
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={16}><Card variant="borderless" title="店内商品" extra={<Button type="link" onClick={() => navigate(`/monitoring/products?shop_id=${item.id}&view=all`)}>进入跨店商品池</Button>}><Table<CompetitorProduct> rowKey="id" size="small" pagination={{ pageSize: 8 }} dataSource={products} columns={[
        { title: "商品", dataIndex: "display_name", ellipsis: true, render: (value: string, row) => <Space orientation="vertical" size={2}><Text strong>{value}</Text><Text type="secondary" style={{ fontSize: 12 }}>{row.own_product ? `对标：${row.own_product}` : "尚未关联自家商品"}</Text></Space> },
        { title: "增长", key: "growth", width: 150, render: (_: unknown, row) => <Space><Tag color={growthColor(row.growth_level)}>{row.growth_level}</Tag><Text strong>{row.growth_score}</Text></Space> },
        { title: "首次发现", dataIndex: "first_seen_at", width: 170, render: formatObservedAt },
        { title: "快照", dataIndex: "snapshot_count", width: 80, render: (value: number) => `${value}次` },
        { title: "操作", key: "action", width: 100, render: (_: unknown, row) => <Button type="link" icon={<ArrowRightOutlined />} onClick={() => navigate(`/monitoring/products/${row.id}`)}>详情</Button> },
      ]} /></Card></Col>
      <Col xs={24} xl={8}><Card variant="borderless" title="近期店铺动作">{events.length ? <List size="small" dataSource={events.slice(0, 10)} renderItem={(event) => <List.Item onClick={() => event.product_id && navigate(`/monitoring/products/${event.product_id}`)} style={{ cursor: event.product_id ? "pointer" : "default" }}><List.Item.Meta title={<Space><Tag color={event.severity === "high" ? "red" : event.severity === "medium" ? "orange" : "default"}>{event.title}</Tag></Space>} description={`${formatEventDetail(event.detail)} · ${formatObservedAt(event.observed_at)}`} /></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有识别到店铺动作" />}</Card></Col>
    </Row>
    <Modal title="编辑竞店资料" open={editing} onCancel={() => setEditing(false)} onOk={() => editForm.submit()} okText="保存"><Form form={editForm} layout="vertical" onFinish={saveShop}><Form.Item name="name" label="店铺名称" rules={[{ required: true, message: "请输入店铺名称" }]}><Input /></Form.Item><Form.Item name="url" label="淘宝或天猫店铺链接" rules={[{ required: true, message: "自动扫描需要店铺链接" }]}><Input placeholder="https://..." /></Form.Item><Row gutter={12}><Col span={12}><Form.Item name="priority" label="关注级别"><Select options={["核心", "重点", "普通"].map((value) => ({ value, label: value }))} /></Form.Item></Col><Col span={12}><Form.Item name="monitor_frequency" label="目录扫描频率"><Select options={["每小时", "每日", "每周"].map((value) => ({ value, label: value }))} /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="competitor_type" label="竞店类型"><Select options={[{ value: "direct", label: "直接竞店" }, { value: "benchmark", label: "标杆店" }, { value: "price", label: "价格竞争店" }]} /></Form.Item></Col><Col span={12}><Form.Item name="category" label="主营类目"><Input /></Form.Item></Col></Row><Form.Item name="price_band" label="价格带"><Input placeholder="例如：30–80元" /></Form.Item></Form></Modal>
  </WorkspacePage>;
}
