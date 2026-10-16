import { ArrowRightOutlined, EyeOutlined, PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Col, Empty, Form, Image, Input, List, Modal, Progress, Row, Select, Space, Table, Tabs, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { DecisionBand, MetricRail, WorkspacePage } from "../components/ui/workspace-template";
import http, { getApiErrorMessage } from "../lib/api";
import type { CollectorStatus, CompetitorEvent, CompetitorProduct, CompetitorShop, MonitoringIntelligence } from "./monitoring-types";
import { confidenceLabel, formatEventDetail, formatObservedAt, growthColor } from "./monitoring-types";

const { Paragraph, Text } = Typography;
const PENDING_SHOP_SCAN_KEY = "tb-monitoring-pending-shop-scan";

const sections: Record<string, { title: string; description: string; objective: string }> = {
  "monitoring-overview": { title: "竞品总览", description: "集中发现竞品店铺的新品和正在起量的商品。", objective: "今天哪些竞品商品值得优先关注？" },
  "competitor-shops": { title: "竞店管理", description: "管理监控店铺、覆盖商品和采集状态。", objective: "我们正在关注哪些店铺，监控是否完整？" },
  "competitor-products": { title: "竞品管理", description: "跨店查看起量商品、新发现商品和全部竞品。", objective: "哪些商品正在起量，背后的信号是什么？" },
  "competitor-reports": { title: "竞品报告", description: "把新品、增长和关键动作整理成可复盘的结论。", objective: "本期竞品发生了什么，我们应该跟进什么？" },
};

function ProductName({ product }: { product: CompetitorProduct }) {
  return <Space align="start" size={10}>{product.image_url ? <Image preview={false} width={44} height={44} style={{ objectFit: "cover", borderRadius: "var(--ops-radius-sm)" }} src={product.image_url} alt="竞品商品主图" /> : null}<div style={{ minWidth: 0 }}><Text strong ellipsis={{ tooltip: product.title }} style={{ display: "block", maxWidth: 300 }}>{product.display_name || product.title}</Text>{product.alias ? <Text type="secondary" ellipsis={{ tooltip: product.title }} style={{ display: "block", maxWidth: 300, fontSize: 12 }}>{product.title}</Text> : null}</div></Space>;
}

function GrowthCell({ product }: { product: CompetitorProduct }) {
  return <Space orientation="vertical" size={3} style={{ width: "100%" }}><Space size={6}><Tag color={growthColor(product.growth_level)}>{product.growth_level}</Tag><Text strong>{product.growth_score}分</Text></Space><Text type="secondary" style={{ fontSize: 12 }}>销量 {product.sales_delta_7d == null ? "待识别" : `+${product.sales_delta_7d}`} · 评价 {product.review_delta_7d == null ? "待识别" : `+${product.review_delta_7d}`}</Text></Space>;
}

function shopNeedsLogin(shop: CompetitorShop): boolean {
  return shop.last_scan_status === "failed" && /登录|安全验证|滑块|采集浏览器/.test(shop.last_scan_error || "");
}

export function MonitoringWorkspacePage({ sectionId }: { sectionId: string }) {
  const navigate = useNavigate();
  const section = sections[sectionId] || sections["monitoring-overview"];
  const [data, setData] = useState<MonitoringIntelligence | null>(null);
  const [loading, setLoading] = useState(true);
  const [shopOpen, setShopOpen] = useState(false);
  const [productOpen, setProductOpen] = useState(false);
  const [collectingAll, setCollectingAll] = useState(false);
  const [collectingId, setCollectingId] = useState<number | null>(null);
  const [openingCollector, setOpeningCollector] = useState(false);
  const [scanningShopId, setScanningShopId] = useState<number | null>(null);
  const [pendingShopScanId, setPendingShopScanId] = useState<number | null>(() => {
    const stored = Number(sessionStorage.getItem(PENDING_SHOP_SCAN_KEY) || 0);
    return stored > 0 ? stored : null;
  });
  const [collector, setCollector] = useState<CollectorStatus>({ connected: false, login_ready: false, state: "not_configured" });
  const autoResumeRef = useRef(false);
  const lastLoginReadyRef = useRef<boolean | null>(null);
  const [shopForm] = Form.useForm();
  const [productForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [intelligence, collectorStatus] = await Promise.all([http.get<MonitoringIntelligence>("/monitoring/intelligence"), http.get<CollectorStatus>("/monitoring/collector/status")]);
      setData(intelligence.data);
      setCollector(collectorStatus.data);
      lastLoginReadyRef.current = Boolean(collectorStatus.data.login_ready);
    } catch (error) { message.error({ content: getApiErrorMessage(error), key: "monitoring-load" }); }
    finally { setLoading(false); }
  }, []);

  const collectAll = useCallback(async (auto = false) => {
    setCollectingAll(true);
    try {
      const result = await http.post("/monitoring/products/collect");
      message.success({ content: `${auto ? "登录完成，已继续采集" : "批量采集完成"}：成功 ${result.data.ok} 个，失败 ${result.data.failed} 个`, key: "monitoring-collect-all", duration: 5 });
      await load();
    } catch (error) { message.error({ content: getApiErrorMessage(error), key: "monitoring-collect-all", duration: 5 }); }
    finally { setCollectingAll(false); }
  }, [load]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (sectionId !== "competitor-products") return undefined;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const response = await http.get<CollectorStatus>("/monitoring/collector/status");
        if (!active) return;
        const ready = Boolean(response.data.login_ready);
        const wasReady = lastLoginReadyRef.current;
        setCollector(response.data);
        lastLoginReadyRef.current = ready;
        if (ready && wasReady === false && !autoResumeRef.current) { autoResumeRef.current = true; void collectAll(true); }
      } catch { /* Short disconnections should not interrupt the operator. */ }
    }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [collectAll, sectionId]);

  const saveShop = async (values: unknown) => {
    try { await http.post("/monitoring/shops", values); message.success("竞品店铺已加入监控"); setShopOpen(false); shopForm.resetFields(); await load(); }
    catch (error) { message.error(getApiErrorMessage(error)); }
  };

  const saveProduct = async (values: { shop_id: number; urls: string; own_product?: string }) => {
    try {
      const urls = String(values.urls || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
      const response = await http.post("/monitoring/products/batch", { shop_id: values.shop_id, urls, own_product: values.own_product || "" });
      message.success(`已加入 ${response.data.created} 个商品，成功采集 ${response.data.collected} 个`);
      setProductOpen(false); productForm.resetFields(); await load();
    } catch (error) { message.error(getApiErrorMessage(error)); }
  };

  const collectProduct = async (product: CompetitorProduct) => {
    setCollectingId(product.id);
    try { const response = await http.post(`/monitoring/products/${product.id}/collect`); message.success(response.data.baseline ? "采集完成，已建立首条基线" : `采集完成，识别到 ${response.data.event_count} 项变化`); await load(); }
    catch (error) { message.error({ content: getApiErrorMessage(error), duration: 5 }); }
    finally { setCollectingId(null); }
  };

  const openCollector = async (shop?: CompetitorShop) => {
    setOpeningCollector(true); autoResumeRef.current = false; lastLoginReadyRef.current = false;
    setPendingShopScanId(shop?.id ?? null);
    if (shop) sessionStorage.setItem(PENDING_SHOP_SCAN_KEY, String(shop.id));
    else sessionStorage.removeItem(PENDING_SHOP_SCAN_KEY);
    try {
      const response = await http.post(shop ? `/monitoring/shops/${shop.id}/collector/open` : "/monitoring/collector/open");
      message.info({ content: `${response.data.message}；登录完成后会自动继续${shop ? "扫描该竞店" : "采集"}`, duration: 6 });
    }
    catch (error) { setPendingShopScanId(null); sessionStorage.removeItem(PENDING_SHOP_SCAN_KEY); message.error(getApiErrorMessage(error)); }
    finally { setOpeningCollector(false); }
  };

  const updateEvent = async (event: CompetitorEvent, status: "read" | "ignored") => {
    try { await http.put(`/monitoring/events/${event.id}`, { status }); await load(); }
    catch (error) { message.error(getApiErrorMessage(error)); }
  };

  const scanShop = useCallback(async (shop: CompetitorShop) => {
    setScanningShopId(shop.id);
    message.loading({ content: `正在逐页扫描 ${shop.name}，每翻一页都会等待商品加载…`, key: `shop-scan-${shop.id}`, duration: 0 });
    try {
      const response = await http.post(`/monitoring/shops/${shop.id}/scan`, undefined, { timeout: 180000 });
      message.success({ content: response.data.baseline ? `已建立店铺商品基线，共发现 ${response.data.scanned} 个商品` : `扫描完成：共识别 ${response.data.scanned} 个商品，发现 ${response.data.new_products} 个新商品`, key: `shop-scan-${shop.id}`, duration: 6 });
      await load();
    } catch (error) {
      message.error({ content: getApiErrorMessage(error), key: `shop-scan-${shop.id}`, duration: 8 });
      await load();
    } finally { setScanningShopId(null); }
  }, [load]);

  useEffect(() => {
    if (sectionId !== "competitor-shops" || pendingShopScanId == null) return undefined;
    let active = true;
    const poll = async () => {
      try {
        const response = await http.get<CollectorStatus>("/monitoring/collector/status");
        if (!active) return;
        const ready = Boolean(response.data.login_ready);
        const wasReady = lastLoginReadyRef.current;
        setCollector(response.data);
        lastLoginReadyRef.current = ready;
        if (ready && wasReady === false && !autoResumeRef.current) {
          const shop = data?.shops.find((item) => item.id === pendingShopScanId);
          if (shop) {
            autoResumeRef.current = true;
            setPendingShopScanId(null);
            sessionStorage.removeItem(PENDING_SHOP_SCAN_KEY);
            message.loading({ content: "淘宝验证已完成，正在继续扫描竞店商品…", key: "shop-scan-resume", duration: 0 });
            await scanShop(shop);
            message.destroy("shop-scan-resume");
          }
        }
      } catch { /* Continue checking while the managed browser is open. */ }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [data?.shops, pendingShopScanId, scanShop, sectionId]);

  const loginFailureShop = data?.shops.find(shopNeedsLogin);
  const hasProductLoginFailure = Boolean(data?.products.some((product) => /登录|安全验证|滑块|打开采集浏览器|未读取到商品信息/.test(product.collection_error || "")));
  const hasLoginFailure = hasProductLoginFailure || Boolean(loginFailureShop);
  const collectorTag = hasLoginFailure ? <Tag color="orange">需要登录或验证</Tag> : collector.login_ready ? <Tag color="green">自动采集可用</Tag> : <Tag>接口优先，按需登录</Tag>;
  const selectedShopId = Number(new URLSearchParams(window.location.search).get("shop_id") || 0);
  const selectedShop = data?.shops.find((shop) => shop.id === selectedShopId);
  const productsForShop = (items: CompetitorProduct[]) => selectedShopId ? items.filter((item) => item.shop_id === selectedShopId) : items;
  const productColumns = useMemo(() => [
    { title: "竞品商品", key: "product", width: 340, render: (_: unknown, row: CompetitorProduct) => <ProductName product={row} /> },
    { title: "竞店", dataIndex: "shop_name", width: 150 },
    { title: "起量判断", key: "growth", width: 230, render: (_: unknown, row: CompetitorProduct) => <GrowthCell product={row} /> },
    { title: "首次发现", dataIndex: "first_seen_at", width: 170, render: (value: string) => formatObservedAt(value) },
    { title: "到手价", dataIndex: "coupon_price", width: 100, render: (value: number | null, row: CompetitorProduct) => value == null && row.price == null ? "—" : `¥${Number(value ?? row.price).toFixed(2)}` },
    { title: "自家对标", dataIndex: "own_product", width: 180, render: (value: string) => value || <Text type="secondary">尚未关联</Text> },
    { title: "操作", key: "action", fixed: "right" as const, width: 150, render: (_: unknown, row: CompetitorProduct) => <Space><Button size="small" type="link" onClick={() => navigate(`/monitoring/products/${row.id}`)}>详情</Button><Button size="small" loading={collectingId === row.id} onClick={() => void collectProduct(row)}>采集</Button></Space> },
  ], [collectingId, navigate]);

  const overview = data ? <Space orientation="vertical" size={16} style={{ width: "100%" }}>
    <Row gutter={[16, 16]}>
      <Col xs={24} xl={14}><Card variant="borderless" title="正在起量" extra={<Button type="link" onClick={() => navigate("/monitoring/products?view=rising")}>查看增长榜</Button>}>{data.rising_products.length ? <List dataSource={data.rising_products.slice(0, 5)} renderItem={(product) => <List.Item actions={[<Button type="link" icon={<ArrowRightOutlined />} onClick={() => navigate(`/monitoring/products/${product.id}`)}>查看依据</Button>]}><List.Item.Meta avatar={product.image_url ? <Image preview={false} width={48} height={48} style={{ objectFit: "cover", borderRadius: "var(--ops-radius-sm)" }} src={product.image_url} /> : undefined} title={<Space><Text strong>{product.display_name}</Text><Tag color={growthColor(product.growth_level)}>{product.growth_level} · {product.growth_score}</Tag></Space>} description={`${product.shop_name} · ${product.growth_reasons.slice(0, 2).join("；")}`} /></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有确认的起量商品"><Button onClick={() => navigate("/monitoring/products?view=all")}>查看观察中的商品</Button></Empty>}</Card></Col>
      <Col xs={24} xl={10}><Card variant="borderless" title="新发现商品" extra={<Button type="link" onClick={() => navigate("/monitoring/products?view=new")}>查看新品库</Button>}>{data.new_products.length ? <List size="small" dataSource={data.new_products.slice(0, 5)} renderItem={(product) => <List.Item onClick={() => navigate(`/monitoring/products/${product.id}`)} style={{ cursor: "pointer" }} extra={<Tag>{product.age_days ?? 0}天</Tag>}><List.Item.Meta title={product.display_name} description={`${product.shop_name} · ${confidenceLabel(product.growth_confidence)}`} /></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="近30天没有首次发现的商品" />}</Card></Col>
    </Row>
    <Card variant="borderless" title="竞争信号" extra={<Text type="secondary">按影响程度排序</Text>}>{data.events.length ? <List dataSource={data.events.filter((event) => event.status === "new").slice(0, 8)} locale={{ emptyText: "没有待判断的新变化" }} renderItem={(event) => <List.Item actions={[event.product_id ? <Button type="link" onClick={() => navigate(`/monitoring/products/${event.product_id}`)}>查看商品</Button> : null, <Button type="link" onClick={() => void updateEvent(event, "read")}>已读</Button>, <Button type="link" onClick={() => void updateEvent(event, "ignored")}>忽略</Button>]}><List.Item.Meta title={<Space><Tag color={event.severity === "high" ? "red" : event.severity === "medium" ? "orange" : "default"}>{event.severity === "high" ? "高影响" : event.severity === "medium" ? "待关注" : "普通"}</Tag><Text strong>{event.title}</Text></Space>} description={`${event.product_title || event.shop_name || "未指定对象"} · ${formatEventDetail(event.detail)} · ${formatObservedAt(event.observed_at)}`} /></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有竞品变化，先添加竞店和商品" />}</Card>
  </Space> : null;

  const shops = data ? <Space orientation="vertical" size={12} style={{ width: "100%" }}>
    {pendingShopScanId ? <Alert type="info" showIcon title="正在等待你完成淘宝登录或安全验证" description="完成后无需再点按钮，页面会自动提示并继续扫描该竞店。请暂时保持本页面打开。" /> : loginFailureShop ? <Alert type="warning" showIcon title={`${loginFailureShop.name}需要完成淘宝登录或安全验证`} description="处理完成后页面会自动继续扫描；验证期间不会清空现有商品，也不会误报新品。" action={<Button loading={openingCollector} onClick={() => void openCollector(loginFailureShop)}>{collector.connected ? "继续验证" : "打开采集浏览器"}</Button>} /> : null}
    <Card variant="borderless" title="监控竞店" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setShopOpen(true)}>添加竞店</Button>}><Table<CompetitorShop> rowKey="id" loading={loading} dataSource={data.shops} pagination={{ pageSize: 10 }} columns={[
    { title: "竞店", dataIndex: "name", render: (value: string, row) => <Space orientation="vertical" size={2}><Text strong>{value}</Text><Text type="secondary" style={{ fontSize: 12 }}>{row.category || "未设置类目"} · {row.competitor_type === "direct" ? "直接竞店" : row.competitor_type}</Text></Space> },
    { title: "关注级别", dataIndex: "priority", width: 110, render: (value: string) => <Tag color={value === "核心" ? "red" : value === "重点" ? "blue" : "default"}>{value}</Tag> },
    { title: "商品覆盖", dataIndex: "product_count", width: 110, render: (value: number) => `${value || 0} 个` },
    { title: "新发现", dataIndex: "new_product_count", width: 100, render: (value: number) => <Text strong>{value || 0}</Text> },
    { title: "正在起量", dataIndex: "rising_product_count", width: 110, render: (value: number) => <Text strong>{value || 0}</Text> },
    { title: "监控频率", dataIndex: "monitor_frequency", width: 110 },
    { title: "目录扫描", key: "scan", width: 190, render: (_: unknown, row) => <Space orientation="vertical" size={2}><Space><Tag color={row.last_scan_status === "success" ? "green" : row.last_scan_status === "failed" ? "red" : "default"}>{row.last_scan_status === "success" ? "正常" : row.last_scan_status === "failed" ? "失败" : row.last_scan_status === "scanning" ? "扫描中" : "未扫描"}</Tag><Text type="secondary">{formatObservedAt(row.last_scanned_at || row.last_scan_attempt_at)}</Text></Space>{row.last_scan_error ? <Text type="danger" ellipsis={{ tooltip: row.last_scan_error }} style={{ maxWidth: 180, fontSize: 12 }}>{row.last_scan_error}</Text> : null}</Space> },
    { title: "操作", key: "action", width: 280, render: (_: unknown, row) => <Space>{shopNeedsLogin(row) ? <Button size="small" loading={openingCollector && pendingShopScanId === row.id} disabled={pendingShopScanId === row.id} onClick={() => void openCollector(row)}>{pendingShopScanId === row.id ? "等待验证" : "处理验证"}</Button> : null}<Button size="small" loading={scanningShopId === row.id} disabled={!row.url || pendingShopScanId === row.id} onClick={() => void scanShop(row)}>扫描全店</Button><Button type="link" icon={<EyeOutlined />} onClick={() => navigate(`/monitoring/shops/${row.id}`)}>详情</Button></Space> },
  ]} /></Card>
  </Space> : null;

  const products = data ? <Space orientation="vertical" size={12} style={{ width: "100%" }}>
    {hasProductLoginFailure ? <Alert type="warning" showIcon title="部分商品需要完成淘宝登录或安全验证" description="完成一次登录后，页面会自动继续采集；失败期间仍保留上一次成功数据。" action={<Button loading={openingCollector} onClick={() => void openCollector()}>{collector.connected ? "继续登录" : "打开采集浏览器"}</Button>} /> : null}
    <Alert type="info" showIcon title={selectedShop ? `当前只看：${selectedShop.name}` : "新品按系统首次发现时间判断"} description={selectedShop ? <Space>已从竞店详情带入筛选。<Button type="link" style={{ padding: 0 }} onClick={() => navigate("/monitoring/products?view=all")}>查看全部竞店</Button></Space> : "公开商品页不一定提供真实上架日期，因此不会把首次发现时间误写成平台上架时间。"} />
    <Card variant="borderless" title="竞品商品池" extra={<Space>{collectorTag}<Button icon={<ReloadOutlined />} loading={collectingAll} disabled={!data.products.length} onClick={() => void collectAll()}>采集全部</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setProductOpen(true)}>添加竞品</Button></Space>}><Tabs defaultActiveKey={new URLSearchParams(window.location.search).get("view") || "rising"} items={[
      { key: "rising", label: `商品增长榜 ${productsForShop(data.rising_products).length}`, children: <Table<CompetitorProduct> rowKey="id" size="small" dataSource={productsForShop(data.rising_products)} columns={productColumns} pagination={{ pageSize: 10 }} scroll={{ x: 1320 }} locale={{ emptyText: "暂时没有达到起量阈值的商品" }} /> },
      { key: "new", label: `新发现商品 ${productsForShop(data.new_products).length}`, children: <Table<CompetitorProduct> rowKey="id" size="small" dataSource={productsForShop(data.new_products)} columns={productColumns} pagination={{ pageSize: 10 }} scroll={{ x: 1320 }} /> },
      { key: "all", label: `全部商品 ${productsForShop(data.products).length}`, children: <Table<CompetitorProduct> rowKey="id" size="small" dataSource={productsForShop(data.products)} columns={productColumns} pagination={{ pageSize: 10 }} scroll={{ x: 1320 }} /> },
    ]} /></Card>
  </Space> : null;

  const reports = data ? <Row gutter={[16, 16]}><Col xs={24} xl={15}><Card variant="borderless" title="本期竞品结论"><Space direction="vertical" size={14} style={{ width: "100%" }}><Alert type={data.rising_products.length ? "warning" : "info"} showIcon message={data.rising_products.length ? `发现 ${data.rising_products.length} 个起量信号` : "暂未发现明确起量信号"} description={data.rising_products[0] ? `${data.rising_products[0].display_name}当前起量分最高（${data.rising_products[0].growth_score}分），建议先核对其价格、活动和评价变化。` : "继续积累销量和评价快照，数据达到判断要求后会自动进入增长榜。"} /><List header={<Text strong>建议跟进</Text>} dataSource={[data.new_products.length ? `检查近30天首次发现的 ${data.new_products.length} 个商品，确认是否属于竞店新品。` : "当前没有新发现商品，检查重点竞店的商品覆盖是否完整。", data.products.some((item) => !item.own_product) ? "为尚未关联的竞品设置自家对标商品，才能判断实际竞争影响。" : "竞品均已关联自家商品，可以进入逐商品对比。", data.summary.failed_collections ? `处理 ${data.summary.failed_collections} 个采集异常，避免趋势判断出现数据断点。` : "采集链路正常，继续保持当前监控频率。"]} renderItem={(item) => <List.Item>{item}</List.Item>} /></Space></Card></Col><Col xs={24} xl={9}><Card variant="borderless" title="数据可信度"><Space direction="vertical" size={16} style={{ width: "100%" }}><div><Text type="secondary">已形成两次以上快照</Text><Progress percent={data.products.length ? Math.round(data.products.filter((item) => item.snapshot_count >= 2).length / data.products.length * 100) : 0} /></div><div><Text type="secondary">已关联自家商品</Text><Progress percent={data.products.length ? Math.round(data.products.filter((item) => item.own_product).length / data.products.length * 100) : 0} /></div><Paragraph type="secondary">起量判断依赖连续快照。样本不足的商品只显示“观察中”，不会被包装成确定结论。</Paragraph></Space></Card></Col></Row> : null;

  const content = sectionId === "competitor-shops" ? shops : sectionId === "competitor-products" ? products : sectionId === "competitor-reports" ? reports : overview;
  const summary = data?.summary || { shops: 0, products: 0, new_products: 0, rising_products: 0, unread_events: 0, failed_collections: 0 };
  return <WorkspacePage kind="management"><DecisionBand ariaLabel={`${section.title}当前结论`} eyebrow="竞品增长情报" title={section.objective} description={section.description} action={<Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>刷新数据</Button>} /><MetricRail columns={4} items={[{ label: "正在起量", value: summary.rising_products, hint: "达到增长阈值" }, { label: "新发现商品", value: summary.new_products, hint: "近30天首次发现" }, { label: "监控竞店", value: summary.shops, hint: `覆盖 ${summary.products} 个商品` }, { label: "待判断信号", value: summary.unread_events, hint: summary.failed_collections ? `${summary.failed_collections} 个采集异常` : "采集状态正常" }]} />{content || <Card loading />}
    <Modal title="添加竞店" open={shopOpen} onCancel={() => setShopOpen(false)} onOk={() => shopForm.submit()} okText="加入监控"><Form form={shopForm} layout="vertical" onFinish={saveShop}><Form.Item name="name" label="店铺名称" rules={[{ required: true, message: "请输入店铺名称" }]}><Input placeholder="例如：RUROME旗舰店" /></Form.Item><Form.Item name="url" label="店铺链接"><Input placeholder="https://..." /></Form.Item><Row gutter={12}><Col span={12}><Form.Item name="priority" label="关注级别" initialValue="重点"><Select options={["核心", "重点", "普通"].map((value) => ({ value, label: value }))} /></Form.Item></Col><Col span={12}><Form.Item name="monitor_frequency" label="采集频率" initialValue="每日"><Select options={["每小时", "每日", "每周"].map((value) => ({ value, label: value }))} /></Form.Item></Col></Row><Row gutter={12}><Col span={12}><Form.Item name="competitor_type" label="竞店类型" initialValue="direct"><Select options={[{ value: "direct", label: "直接竞店" }, { value: "benchmark", label: "标杆店" }, { value: "price", label: "价格竞争店" }]} /></Form.Item></Col><Col span={12}><Form.Item name="category" label="主营类目"><Input placeholder="例如：牙刷" /></Form.Item></Col></Row></Form></Modal>
    <Modal title="添加竞品商品" open={productOpen} onCancel={() => setProductOpen(false)} onOk={() => productForm.submit()} okText="加入商品池"><Form form={productForm} layout="vertical" onFinish={saveProduct}><Form.Item name="shop_id" label="所属竞店" rules={[{ required: true, message: "请选择竞店" }]}><Select options={(data?.shops || []).map((shop) => ({ value: shop.id, label: shop.name }))} /></Form.Item><Form.Item name="urls" label="商品链接" rules={[{ required: true, message: "请至少粘贴一条商品链接" }]}><Input.TextArea rows={5} placeholder="每行一条淘宝或天猫商品链接" /></Form.Item><Form.Item name="own_product" label="对应自家商品"><Input placeholder="可填写自家商品备注名或商品ID" /></Form.Item></Form></Modal>
  </WorkspacePage>;
}
