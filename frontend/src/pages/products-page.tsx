import {
  AppstoreOutlined,
  CopyOutlined,
  DeleteOutlined,
  DownloadOutlined,
  ExportOutlined,
  EyeOutlined,
  InboxOutlined,
  LinkOutlined,
  ReloadOutlined,
  SaveOutlined,
  SearchOutlined,
  ShopOutlined,
  ShoppingOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Image,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ColumnSettings } from "../components/ui/column-settings";
import { PageHeader } from "../components/ui/page-header";
import http, { getApiErrorMessage } from "../lib/api";
import { useStores } from "../lib/store";

const { Text, Title } = Typography;

type ProductItem = {
  store_id: number;
  store_name: string;
  item_id: string;
  category_id: string;
  title: string;
  image: string;
  price: number;
  stock: number;
  sold_quantity: number;
  monthly_sold: number;
  quality_score: number;
  shelf_at: string;
  status: string;
  detail_url: string;
  edit_url: string;
  synced_at: string;
};

type ProductResponse = {
  items: ProductItem[];
  total: number;
  page: number;
  page_size: number;
  summary: {
    total: number;
    low_stock: number;
    zero_stock: number;
    sold_quantity: number;
    last_sync: string | null;
    stale: boolean;
  };
};

type SyncResult = { store_id: number; store_name: string; ok: boolean; count?: number; synced_at?: string; error?: string };
type SyncResponse = { ok: number; total: number; results: SyncResult[] };
type SavedView = { name: string; storeId?: number; stockStatus: string; salesStatus: string };
type ColumnConfig = { hidden: string[]; order: string[] };

const VIEW_STORAGE_KEY = "tb-product-saved-views";
const COLUMN_STORAGE_KEY = "tb-product-columns";

function productImage(url: string): string {
  if (!url) return "";
  return url.startsWith("//") ? `https:${url}` : url;
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const value = localStorage.getItem(key);
    return value ? JSON.parse(value) as T : fallback;
  } catch {
    return fallback;
  }
}

function csvCell(value: string | number): string {
  return `"${String(value).replace(/"/g, '""')}"`;
}

export function ProductsPage() {
  const { stores, currentStore, setCurrent } = useStores();
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState<ProductResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncResponse | null>(null);
  const [syncModalOpen, setSyncModalOpen] = useState(false);
  const [storeId, setStoreId] = useState<number | undefined>(() => {
    const value = Number(searchParams.get("store_id"));
    return value > 0 ? value : undefined;
  });
  const [stockStatus, setStockStatus] = useState(() => searchParams.get("stock_status") || "all");
  const [salesStatus, setSalesStatus] = useState(() => searchParams.get("sales_status") || "all");
  const [searchValue, setSearchValue] = useState(() => searchParams.get("q") || "");
  const [keyword, setKeyword] = useState(() => searchParams.get("q") || "");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selectedKeys, setSelectedKeys] = useState<React.Key[]>([]);
  const [detail, setDetail] = useState<ProductItem | null>(null);
  const [density, setDensity] = useState<"small" | "middle">("middle");
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => readJson(VIEW_STORAGE_KEY, []));
  const [saveViewOpen, setSaveViewOpen] = useState(false);
  const [viewName, setViewName] = useState("");
  const [columnConfig, setColumnConfig] = useState<ColumnConfig>(() => readJson(COLUMN_STORAGE_KEY, { hidden: [], order: [] }));

  const loadProducts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        stock_status: stockStatus,
        sales_status: salesStatus,
      });
      if (storeId) params.set("store_id", String(storeId));
      if (keyword) params.set("q", keyword);
      const { data: response } = await http.get<ProductResponse>(`/products?${params.toString()}`);
      setData(response);
      setSelectedKeys([]);
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [keyword, page, pageSize, salesStatus, stockStatus, storeId]);

  useEffect(() => {
    loadProducts();
  }, [loadProducts]);

  useEffect(() => {
    if (currentStore || stores.length > 0) {
      setStoreId(currentStore?.id);
      setPage(1);
    }
  }, [currentStore, stores.length]);

  useEffect(() => {
    const timer = setInterval(loadProducts, 180000);
    return () => clearInterval(timer);
  }, [loadProducts]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (storeId) params.set("store_id", String(storeId));
    if (stockStatus !== "all") params.set("stock_status", stockStatus);
    if (salesStatus !== "all") params.set("sales_status", salesStatus);
    if (keyword) params.set("q", keyword);
    setSearchParams(params, { replace: true });
  }, [keyword, salesStatus, setSearchParams, stockStatus, storeId]);

  const syncProducts = async () => {
    setSyncing(true);
    setSyncResult(null);
    setSyncModalOpen(true);
    try {
      const suffix = storeId ? `?store_id=${storeId}` : "";
      const { data: response } = await http.post<SyncResponse>(`/products/sync${suffix}`, {}, { timeout: 240000 });
      setSyncResult(response);
      setPage(1);
      await loadProducts();
    } catch (error) {
      setSyncResult({ ok: 0, total: 1, results: [{ store_id: 0, store_name: "商品同步", ok: false, error: getApiErrorMessage(error) }] });
    } finally {
      setSyncing(false);
    }
  };

  const resetFilters = async () => {
    await setCurrent(null);
    setStoreId(undefined);
    setStockStatus("all");
    setSalesStatus("all");
    setSearchValue("");
    setKeyword("");
    setPage(1);
  };

  const saveCurrentView = () => {
    const name = viewName.trim();
    if (!name) {
      message.warning("请输入视图名称");
      return;
    }
    const next = [...savedViews.filter((view) => view.name !== name), { name, storeId, stockStatus, salesStatus }];
    setSavedViews(next);
    localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(next));
    setSaveViewOpen(false);
    setViewName("");
    message.success(`已保存筛选视图“${name}”`);
  };

  const applyView = async (name: string) => {
    const view = savedViews.find((item) => item.name === name);
    if (!view) return;
    await setCurrent(view.storeId ?? null);
    setStoreId(view.storeId);
    setStockStatus(view.stockStatus);
    setSalesStatus(view.salesStatus);
    setPage(1);
  };

  const deleteView = (name: string) => {
    const removed = savedViews.find((view) => view.name === name);
    const next = savedViews.filter((view) => view.name !== name);
    setSavedViews(next);
    localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(next));
    message.success({
      duration: 6,
      content: (
        <Space>
          <span>已删除视图“{name}”</span>
          {removed ? (
            <Button
              type="link"
              size="small"
              onClick={() => {
                const restored = [...next, removed];
                setSavedViews(restored);
                localStorage.setItem(VIEW_STORAGE_KEY, JSON.stringify(restored));
                message.success("视图已恢复");
              }}
            >
              撤销
            </Button>
          ) : null}
        </Space>
      ),
    });
  };

  const selectedProducts = (data?.items ?? []).filter((item) => selectedKeys.includes(`${item.store_id}-${item.item_id}`));

  const exportProducts = (products: ProductItem[]) => {
    if (products.length === 0) {
      message.warning("请先勾选需要导出的商品");
      return;
    }
    const rows = [
      ["店铺", "商品ID", "标题", "售价", "库存", "累计销量", "月销", "质量分", "状态"],
      ...products.map((item) => [item.store_name, item.item_id, item.title, item.price, item.stock, item.sold_quantity, item.monthly_sold, item.quality_score, item.status]),
    ];
    const csv = `\ufeff${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `在售商品-${dayjs().format("YYYYMMDD-HHmm")}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    message.success(`已导出 ${products.length} 个商品`);
  };

  const copySelectedIds = async () => {
    if (selectedProducts.length === 0) {
      message.warning("请先勾选商品");
      return;
    }
    await navigator.clipboard.writeText(selectedProducts.map((item) => item.item_id).join("\n"));
    message.success(`已复制 ${selectedProducts.length} 个商品 ID`);
  };

  const allColumns: TableColumnsType<ProductItem> = useMemo(() => [
    {
      key: "product",
      title: "商品",
      dataIndex: "title",
      fixed: "left",
      width: 390,
      render: (_, row) => (
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {row.image ? (
            <img src={productImage(row.image)} alt="" loading="lazy" style={{ width: 58, height: 58, borderRadius: 8, objectFit: "cover", border: "1px solid var(--ops-border)" }} />
          ) : (
            <div style={{ width: 58, height: 58, borderRadius: 8, display: "grid", placeItems: "center", background: "var(--ops-panel-2)" }}>
              <ShoppingOutlined style={{ color: "var(--ops-text-secondary)" }} />
            </div>
          )}
          <div style={{ minWidth: 0 }}>
            <Text ellipsis={{ tooltip: row.title }} strong style={{ maxWidth: 280 }}>{row.title || "未命名商品"}</Text>
            <div style={{ marginTop: 5 }}><Text type="secondary" style={{ fontSize: 12 }}>ID {row.item_id}</Text></div>
          </div>
        </div>
      ),
    },
    { key: "store", title: "店铺", dataIndex: "store_name", width: 140, ellipsis: true },
    { key: "price", title: "售价", dataIndex: "price", width: 100, align: "right", render: (value: number) => `¥${value.toFixed(2)}` },
    { key: "stock", title: "库存", dataIndex: "stock", width: 100, align: "right", sorter: (a, b) => a.stock - b.stock, render: (value: number) => <Text type={value <= 0 ? "danger" : value <= 10 ? "warning" : undefined}>{value.toLocaleString("zh-CN")}</Text> },
    { key: "sold", title: "累计销量", dataIndex: "sold_quantity", width: 110, align: "right", sorter: (a, b) => a.sold_quantity - b.sold_quantity, render: (value: number) => value.toLocaleString("zh-CN") },
    { key: "monthly", title: "月销", dataIndex: "monthly_sold", width: 90, align: "right", sorter: (a, b) => a.monthly_sold - b.monthly_sold, render: (value: number) => <Text type={value <= 0 ? "secondary" : undefined}>{value.toLocaleString("zh-CN")}</Text> },
    { key: "quality", title: "质量分", dataIndex: "quality_score", width: 100, align: "center", sorter: (a, b) => a.quality_score - b.quality_score, render: (value: number) => <Tag color={value >= 90 ? "green" : value >= 70 ? "orange" : "red"}>{value || "—"}</Tag> },
    { key: "shelf", title: "上架时间", dataIndex: "shelf_at", width: 150, render: (value: string) => value || "—" },
    { key: "status", title: "状态", dataIndex: "status", width: 90, render: (value: string) => <Tag color="green">{value || "出售中"}</Tag> },
    {
      key: "actions",
      title: "操作",
      fixed: "right",
      width: 132,
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setDetail(row)}>详情</Button>
          {row.edit_url ? <a href={row.edit_url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>编辑</a> : null}
        </Space>
      ),
    },
  ], []);

  const columns = useMemo(() => {
    const position = new Map(columnConfig.order.map((key, index) => [key, index]));
    return allColumns
      .filter((column) => !columnConfig.hidden.includes(String(column.key)))
      .sort((a, b) => (position.get(String(a.key)) ?? 999) - (position.get(String(b.key)) ?? 999));
  }, [allColumns, columnConfig]);

  const updateColumns = (next: ColumnConfig) => {
    setColumnConfig(next);
    localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(next));
  };

  const summary = data?.summary;
  const filtersActive = Boolean(storeId || stockStatus !== "all" || salesStatus !== "all" || keyword);

  return (
    <div>
      <PageHeader
        icon={<ShoppingOutlined />}
        eyebrow="商品与交易"
        title="在售商品"
        description="查看淘宝后台在售状态、库存与经营表现"
        source="淘宝千牛 SellManage"
        updatedAt={summary?.last_sync ? dayjs(summary.last_sync).format("MM-DD HH:mm") : null}
        stale={summary?.stale}
        extra={<Button type="primary" icon={<ReloadOutlined />} loading={syncing} onClick={syncProducts}>从淘宝同步</Button>}
      />

      {summary?.stale && summary.last_sync ? (
        <Alert type="warning" showIcon icon={<WarningOutlined />} message="商品数据可能已过期" description={`最近成功同步：${dayjs(summary.last_sync).format("YYYY-MM-DD HH:mm:ss")}。当前仍展示上次成功数据，可手动重新同步。`} style={{ marginBottom: 16 }} />
      ) : null}

      <div className="ops-metric-strip">
        <div className="ops-metric-strip__item"><Statistic title="在售商品" value={summary?.total ?? 0} prefix={<AppstoreOutlined />} /></div>
        <div className="ops-metric-strip__item"><Statistic title="低库存" value={summary?.low_stock ?? 0} prefix={<WarningOutlined />} /></div>
        <div className="ops-metric-strip__item"><Statistic title="零库存" value={summary?.zero_stock ?? 0} prefix={<InboxOutlined />} /></div>
        <div className="ops-metric-strip__item"><Statistic title="累计销量" value={summary?.sold_quantity ?? 0} prefix={<ShoppingOutlined />} /></div>
      </div>

      <div className="ops-list-panel">
        <div className="ops-list-toolbar">
          <Select allowClear placeholder="全部店铺" value={storeId} onChange={async (value) => { await setCurrent(value ?? null); setStoreId(value); setPage(1); }} style={{ width: 180 }} options={stores.map((store) => ({ label: store.name, value: store.id }))} suffixIcon={<ShopOutlined />} />
          <Select value={stockStatus} onChange={(value) => { setStockStatus(value); setPage(1); }} style={{ width: 138 }} options={[{ label: "全部库存", value: "all" }, { label: "库存正常", value: "normal" }, { label: "低库存 ≤ 10", value: "low" }, { label: "零库存", value: "zero" }]} />
          <Select value={salesStatus} onChange={(value) => { setSalesStatus(value); setPage(1); }} style={{ width: 150 }} options={[{ label: "全部经营状态", value: "all" }, { label: "近月无销量", value: "no_sales" }, { label: "质量分低于 70", value: "low_quality" }]} />
          <Input.Search allowClear value={searchValue} onChange={(event) => setSearchValue(event.target.value)} onSearch={(value) => { setKeyword(value.trim()); setPage(1); }} placeholder="搜索商品标题或商品 ID" enterButton={<SearchOutlined />} style={{ width: 300 }} />
          {filtersActive ? <Button type="text" onClick={resetFilters}>重置</Button> : null}
          <span className="ops-list-toolbar__meta">{summary?.last_sync ? `最近同步 ${dayjs(summary.last_sync).format("MM-DD HH:mm")}` : "尚未同步"}</span>
        </div>

        <div className="ops-list-toolbar" style={{ paddingBlock: 9 }}>
          <Select placeholder="已保存视图" onChange={applyView} style={{ width: 160 }} options={savedViews.map((view) => ({ label: view.name, value: view.name }))} notFoundContent="暂无保存视图" />
          <Button icon={<SaveOutlined />} onClick={() => setSaveViewOpen(true)}>保存当前视图</Button>
          {savedViews.length > 0 ? <Select placeholder="删除视图" onChange={deleteView} style={{ width: 130 }} suffixIcon={<DeleteOutlined />} options={savedViews.map((view) => ({ label: view.name, value: view.name }))} /> : null}
          <div style={{ flex: 1 }} />
          <Select value={density} onChange={setDensity} style={{ width: 110 }} options={[{ label: "标准密度", value: "middle" }, { label: "紧凑密度", value: "small" }]} />
          <ColumnSettings columns={allColumns.map((column) => ({ key: String(column.key), title: String(column.title) }))} hidden={columnConfig.hidden} order={columnConfig.order} onChange={updateColumns} />
        </div>

        {selectedKeys.length > 0 ? (
          <div className="ops-list-selection">
            <Text strong>已选择 {selectedKeys.length} 项</Text>
            <Button size="small" icon={<CopyOutlined />} onClick={copySelectedIds}>复制商品 ID</Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => exportProducts(selectedProducts)}>导出所选</Button>
            <Button size="small" type="text" onClick={() => setSelectedKeys([])}>取消选择</Button>
          </div>
        ) : null}

        <Table<ProductItem>
          rowKey={(row) => `${row.store_id}-${row.item_id}`}
          columns={columns}
          dataSource={data?.items ?? []}
          loading={loading}
          size={density}
          sticky
          rowSelection={{ selectedRowKeys: selectedKeys, preserveSelectedRowKeys: false, onChange: setSelectedKeys }}
          onRow={(row) => ({ onClick: (event) => { if (!(event.target as HTMLElement).closest("a,button,input,.ant-checkbox-wrapper")) setDetail(row); } })}
          scroll={{ x: 1500 }}
          pagination={{ current: page, pageSize, total: data?.total ?? 0, showSizeChanger: true, showQuickJumper: true, showTotal: (total) => `共 ${total} 个在售商品`, onChange: (nextPage, nextPageSize) => { setPage(nextPageSize === pageSize ? nextPage : 1); setPageSize(nextPageSize); } }}
          locale={{ emptyText: <div className="ops-data-empty"><Empty description={filtersActive ? "没有符合当前筛选的商品" : "尚未取得淘宝在售商品"}><Space>{filtersActive ? <Button onClick={resetFilters}>清空筛选</Button> : null}<Button type="primary" icon={<ReloadOutlined />} loading={syncing} onClick={syncProducts}>从淘宝同步</Button></Space></Empty></div> }}
        />
      </div>

      <Drawer title="商品详情" width={480} open={Boolean(detail)} onClose={() => setDetail(null)} extra={detail?.edit_url ? <Button type="primary" icon={<ExportOutlined />} href={detail.edit_url} target="_blank">淘宝后台编辑</Button> : null}>
        {detail ? (
          <div className="ops-product-detail">
            <div className="ops-product-detail__hero">
              {detail.image ? <Image width={92} height={92} src={productImage(detail.image)} style={{ borderRadius: 10, objectFit: "cover" }} /> : null}
              <div style={{ minWidth: 0 }}><Title level={5} style={{ marginTop: 0 }}>{detail.title}</Title><Text type="secondary" copyable={{ text: detail.item_id }}>商品 ID：{detail.item_id}</Text><div style={{ marginTop: 8 }}><Tag color="green">{detail.status || "出售中"}</Tag><Tag>{detail.store_name}</Tag></div></div>
            </div>
            <div className="ops-product-detail__metrics">
              <div className="ops-product-detail__metric"><Statistic title="售价" value={detail.price} precision={2} prefix="¥" /></div>
              <div className="ops-product-detail__metric"><Statistic title="库存" value={detail.stock} valueStyle={detail.stock <= 10 ? { color: "var(--ops-warn)" } : undefined} /></div>
              <div className="ops-product-detail__metric"><Statistic title="累计销量" value={detail.sold_quantity} /></div>
              <div className="ops-product-detail__metric"><Statistic title="近月销量" value={detail.monthly_sold} /></div>
            </div>
            {(detail.stock <= 10 || detail.monthly_sold <= 0 || detail.quality_score < 70) ? <Alert type="warning" showIcon message="经营提示" description={[detail.stock <= 0 ? "商品已无库存" : detail.stock <= 10 ? "商品库存偏低" : "", detail.monthly_sold <= 0 ? "近月暂无销量" : "", detail.quality_score < 70 ? "商品质量分偏低" : ""].filter(Boolean).join("；")} style={{ marginBottom: 16 }} /> : null}
            <Descriptions column={1} size="small" items={[
              { key: "quality", label: "质量分", children: detail.quality_score || "—" },
              { key: "category", label: "类目 ID", children: detail.category_id || "—" },
              { key: "shelf", label: "上架时间", children: detail.shelf_at || "—" },
              { key: "sync", label: "数据同步", children: dayjs(detail.synced_at).format("YYYY-MM-DD HH:mm:ss") },
            ]} />
            <Space style={{ marginTop: 20 }} wrap>{detail.detail_url ? <Button icon={<LinkOutlined />} href={detail.detail_url} target="_blank">打开商品页</Button> : null}{detail.edit_url ? <Button icon={<ExportOutlined />} href={detail.edit_url} target="_blank">淘宝后台编辑</Button> : null}</Space>
          </div>
        ) : null}
      </Drawer>

      <Modal title="保存筛选视图" open={saveViewOpen} onCancel={() => setSaveViewOpen(false)} onOk={saveCurrentView} okText="保存">
        <Input autoFocus value={viewName} onChange={(event) => setViewName(event.target.value)} onPressEnter={saveCurrentView} placeholder="例如：零库存商品、重点店铺" maxLength={30} />
        <Text type="secondary" style={{ display: "block", marginTop: 10 }}>保存当前店铺、库存和经营状态筛选，下次可一键恢复。</Text>
      </Modal>

      <Modal title="在售商品同步" open={syncModalOpen} onCancel={() => { if (!syncing) setSyncModalOpen(false); }} footer={syncing ? null : <Button type="primary" onClick={() => setSyncModalOpen(false)}>完成</Button>} closable={!syncing} maskClosable={!syncing}>
        {syncing ? (
          <div style={{ padding: "32px 0", textAlign: "center" }}><Spin size="large" /><Title level={5}>正在从淘宝千牛读取在售商品</Title><Text type="secondary">同步完成前会继续保留上一次成功数据，请勿重复操作。</Text></div>
        ) : syncResult ? (
          <div><Alert type={syncResult.ok === syncResult.total ? "success" : "error"} showIcon message={syncResult.ok === syncResult.total ? `同步完成，共 ${syncResult.ok} 家店铺成功` : `同步未全部完成，成功 ${syncResult.ok} / ${syncResult.total} 家店铺`} style={{ marginBottom: 14 }} />{syncResult.results.map((result) => <div key={`${result.store_id}-${result.store_name}`} className="ops-sync-row"><div className="ops-sync-row__body"><Text strong>{result.store_name}</Text><Text type={result.ok ? "secondary" : "danger"}>{result.ok ? `已更新 ${result.count ?? 0} 个商品` : result.error || "同步失败"}</Text></div><Tag color={result.ok ? "green" : "red"}>{result.ok ? "成功" : "失败"}</Tag></div>)}</div>
        ) : null}
      </Modal>
    </div>
  );
}
