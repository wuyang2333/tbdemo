import { CloseOutlined, CopyOutlined, DeleteOutlined, DownloadOutlined, GiftOutlined, PictureOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Button,
  Card,
  Col,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Key } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageHeader } from "../components/ui/page-header";
import type { Gift, GiftReviewStatus, GiftSettleStatus, Store } from "../types";

const { Text } = Typography;

type GiftFormValues = {
  order_no: string;
  store_id: number;
  keyword: string;
  spec: string;
  price: number;
  commission: number;
  wangwang: string;
  order_time: dayjs.Dayjs;
  review_status: GiftReviewStatus;
  settle_status: GiftSettleStatus;
};

type EditableField =
  | "order_no"
  | "store_id"
  | "keyword"
  | "spec"
  | "price"
  | "commission"
  | "wangwang"
  | "order_time";

const REVIEW_META: Record<GiftReviewStatus, { label: string; color: string }> = {
  none: { label: "未评论", color: "orange" },
  reviewed: { label: "已评论", color: "green" },
};

const SETTLE_META: Record<GiftSettleStatus, { label: string; color: string }> = {
  unsettled: { label: "未结款", color: "orange" },
  settled: { label: "已结款", color: "green" },
};

const REVIEW_OPTIONS = (Object.entries(REVIEW_META) as [GiftReviewStatus, { label: string }][]).map(([value, meta]) => ({
  value,
  label: meta.label,
}));
const SETTLE_OPTIONS = (Object.entries(SETTLE_META) as [GiftSettleStatus, { label: string }][]).map(([value, meta]) => ({
  value,
  label: meta.label,
}));

export function GiftsPage() {
  const [items, setItems] = useState<Gift[]>([]);
  const [stores, setStores] = useState<Store[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [storeFilter, setStoreFilter] = useState<number | undefined>();
  const [reviewFilter, setReviewFilter] = useState<GiftReviewStatus | undefined>();
  const [settleFilter, setSettleFilter] = useState<GiftSettleStatus | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  const [form] = Form.useForm<GiftFormValues>();
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [cellEdit, setCellEdit] = useState<{ id: number; field: EditableField; value: string | number } | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [imageTarget, setImageTarget] = useState<Gift | null>(null);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const enterRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await http.get<{ items: Gift[] }>("/gifts");
      setItems(data.items);
    } catch (error) {
      message.error(getApiErrorMessage(error));
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    http
      .get<{ items: Store[] }>("/stores")
      .then(({ data }) => setStores(data.items))
      .catch(() => {});
  }, []);

  const storeOptions = useMemo(() => {
    const list = stores.map((store) => ({ value: store.id, label: store.name }));
    return [{ value: 0, label: "未关联店铺" }, ...list];
  }, [stores]);

  const storeSelectOptions = useMemo(
    () => storeOptions.filter((option) => option.value !== 0),
    [storeOptions]
  );

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return items.filter((item) => {
      if (storeFilter !== undefined && item.store_id !== storeFilter) return false;
      if (reviewFilter && item.review_status !== reviewFilter) return false;
      if (settleFilter && item.settle_status !== settleFilter) return false;
      if (dateRange && dateRange[0] && dateRange[1]) {
        const start = dateRange[0].startOf("day");
        const end = dateRange[1].endOf("day");
        const ot = item.order_time ? dayjs(item.order_time) : null;
        if (!ot || ot.isBefore(start) || ot.isAfter(end)) return false;
      }
      if (!kw) return true;
      return (
        item.order_no.toLowerCase().includes(kw) ||
        item.wangwang.toLowerCase().includes(kw) ||
        item.keyword.toLowerCase().includes(kw) ||
        item.spec.toLowerCase().includes(kw)
      );
    });
  }, [items, keyword, storeFilter, reviewFilter, settleFilter, dateRange]);

  const resetFilters = () => {
    setKeyword("");
    setStoreFilter(undefined);
    setReviewFilter(undefined);
    setSettleFilter(undefined);
    setDateRange(null);
  };

  const getCellValue = (row: Gift, field: EditableField): string | number => {
    if (field === "store_id" || field === "price" || field === "commission") {
      return Number(row[field] ?? 0);
    }
    if (field === "order_time") {
      return row.order_time || "";
    }
    return String(row[field] ?? "");
  };

  const saveCell = async (row: Gift, field: EditableField, value: string | number) => {
    setCellEdit(null);
    setPickerOpen(false);
    const payload = {
      order_no: field === "order_no" ? String(value).trim() : row.order_no,
      store_id: field === "store_id" ? Number(value) : row.store_id,
      keyword: field === "keyword" ? String(value).trim() : row.keyword,
      spec: field === "spec" ? String(value).trim() : row.spec,
      price: field === "price" ? Number(value) : row.price,
      commission: field === "commission" ? Number(value) : row.commission,
      wangwang: field === "wangwang" ? String(value).trim() : row.wangwang,
      order_time: field === "order_time" ? String(value) : row.order_time || "",
      review_status: row.review_status,
      settle_status: row.settle_status,
    };
    try {
      await http.put(`/gifts/${row.id}`, payload);
      message.success("已保存");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const startCellEdit = (row: Gift, field: EditableField) => {
    enterRef.current = false;
    setCellEdit({ id: row.id, field, value: getCellValue(row, field) });
    if (field === "order_time") setPickerOpen(true);
  };

  const moveToNext = async (row: Gift, field: EditableField, value: string | number) => {
    const idx = filtered.findIndex((item) => item.id === row.id);
    const next = idx >= 0 ? filtered[idx + 1] : undefined;
    await saveCell(row, field, value);
    if (next) {
      setCellEdit({ id: next.id, field, value: getCellValue(next, field) });
      if (field === "order_time") setPickerOpen(true);
    } else {
      setCellEdit(null);
    }
  };

  const renderEditableCell = (row: Gift, field: EditableField, display: React.ReactNode) => {
    const active = cellEdit?.id === row.id && cellEdit?.field === field;
    if (!active) {
      return (
        <span
          style={{ cursor: "text", display: "inline-block", minWidth: 56, minHeight: 20 }}
          onClick={() => startCellEdit(row, field)}
          title="点击修改"
        >
          {display}
        </span>
      );
    }
    if (field === "order_time") {
      return (
        <DatePicker
          size="small"
          showTime
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          value={cellEdit.value ? dayjs(String(cellEdit.value)) : undefined}
          onChange={(value) => {
            saveCell(row, "order_time", value ? value.format("YYYY-MM-DD HH:mm:ss") : "");
          }}
          style={{ width: 160 }}
        />
      );
    }
    if (field === "store_id") {
      return (
        <Select
          size="small"
          autoFocus
          value={Number(cellEdit.value)}
          options={storeSelectOptions}
          onChange={(value) => saveCell(row, "store_id", value)}
          onBlur={() => setCellEdit(null)}
          style={{ minWidth: 130 }}
        />
      );
    }
    if (field === "price" || field === "commission") {
      return (
        <InputNumber
          size="small"
          autoFocus
          min={0}
          value={Number(cellEdit.value)}
          onChange={(value) =>
            setCellEdit((prev) => (prev ? { ...prev, value: value ?? 0 } : prev))
          }
          onBlur={() => {
            if (enterRef.current) return;
            saveCell(row, field, Number(cellEdit.value ?? 0));
          }}
          onPressEnter={() => {
            enterRef.current = true;
            moveToNext(row, field, Number(cellEdit.value ?? 0));
          }}
          style={{ width: 100 }}
        />
      );
    }
    return (
      <Input
        size="small"
        autoFocus
        value={String(cellEdit.value ?? "")}
        onChange={(event) => {
          const raw = event.target.value;
          const next = field === "order_no" ? raw.replace(/\D/g, "") : raw;
          setCellEdit((prev) => (prev ? { ...prev, value: next } : prev));
        }}
        onBlur={() => {
          if (enterRef.current) return;
          saveCell(row, field, String(cellEdit.value ?? ""));
        }}
        onPressEnter={() => {
          enterRef.current = true;
          moveToNext(row, field, String(cellEdit.value ?? ""));
        }}
        onPaste={(event) => {
          if (field !== "keyword") return;
          const items = event.clipboardData?.items;
          if (!items) return;
          for (const item of items) {
            if (item.type.startsWith("image/")) {
              event.preventDefault();
              const file = item.getAsFile();
              if (file) {
                setCellEdit(null);
                uploadImage(row, file);
              }
              return;
            }
          }
        }}
        maxLength={field === "order_no" ? 40 : 100}
        style={{ minWidth: 110 }}
      />
    );
  };

  const toggleReview = async (row: Gift) => {
    const next: GiftReviewStatus = row.review_status === "reviewed" ? "none" : "reviewed";
    try {
      await http.post(`/gifts/${row.id}/review`, { status: next });
      message.success(`「${row.order_no || row.wangwang || "该单"}」已标记为「${REVIEW_META[next].label}」`);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const toggleSettle = async (row: Gift) => {
    const next: GiftSettleStatus = row.settle_status === "settled" ? "unsettled" : "settled";
    try {
      await http.post(`/gifts/${row.id}/settle`, { status: next });
      message.success(`「${row.order_no || row.wangwang || "该单"}」已标记为「${SETTLE_META[next].label}」`);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const batchSet = async (
    field: "review_status" | "settle_status",
    value: GiftReviewStatus | GiftSettleStatus
  ) => {
    if (selectedKeys.length === 0) return;
    try {
      await http.post("/gifts/batch", {
        ids: selectedKeys,
        [field]: value,
      });
      message.success(`已批量更新 ${selectedKeys.length} 单`);
      setSelectedKeys([]);
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const submitGift = async (values: GiftFormValues) => {
    setSaving(true);
    try {
      const payload = {
        order_no: values.order_no?.trim() ?? "",
        store_id: values.store_id ?? 0,
        keyword: values.keyword?.trim() ?? "",
        spec: values.spec?.trim() ?? "",
        price: values.price ?? 0,
        commission: values.commission ?? 0,
        wangwang: values.wangwang?.trim() ?? "",
        order_time: values.order_time ? values.order_time.format("YYYY-MM-DD HH:mm:ss") : "",
        review_status: values.review_status ?? "none",
        settle_status: values.settle_status ?? "unsettled",
      };
      await http.post("/gifts", payload);
      message.success("礼品单已创建");
      setCreateOpen(false);
      form.resetFields();
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const removeGift = async (row: Gift) => {
    try {
      await http.delete(`/gifts/${row.id}`);
      message.success("礼品单已删除");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const pickImage = (row: Gift) => {
    setImageTarget(row);
    fileInputRef.current?.click();
  };

  const uploadImage = async (row: Gift, file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    try {
      await http.post(`/gifts/${row.id}/image`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      message.success("图片已上传");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const removeImage = async (row: Gift) => {
    try {
      await http.post(`/gifts/${row.id}/image/clear`);
      message.success("图片已移除");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const copyTable = async () => {
    if (filtered.length === 0) {
      message.warning("当前没有可复制的数据");
      return;
    }
    const headers = ["日期", "下单时间", "店铺", "关键词", "规格", "金额", "佣金", "旺旺号", "订单编号", "评论状态", "结款状态"];
    const lines = [headers.join("\t")];
    for (const row of filtered) {
      const ot = row.order_time ? dayjs(row.order_time) : null;
      lines.push(
        [
          ot ? ot.format("YYYY-MM-DD") : "",
          ot ? ot.format("HH:mm") : "",
          row.store_name,
          row.keyword,
          row.spec,
          Number(row.price).toFixed(2),
          Number(row.commission).toFixed(2),
          row.wangwang,
          row.order_no,
          REVIEW_META[row.review_status].label,
          SETTLE_META[row.settle_status].label,
        ].join("\t")
      );
    }
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      message.success(`已复制 ${filtered.length} 行，可直接粘贴到 Excel`);
    } catch {
      message.error("复制失败，请手动选择后复制");
    }
  };

  const exportExcel = async () => {
    try {
      const params = new URLSearchParams();
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (storeFilter !== undefined) params.set("store_id", String(storeFilter));
      if (reviewFilter) params.set("review_status", reviewFilter);
      if (settleFilter) params.set("settle_status", settleFilter);
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.set("date_from", dateRange[0].format("YYYY-MM-DD"));
        params.set("date_to", dateRange[1].format("YYYY-MM-DD"));
      }
      const token = localStorage.getItem("tb-workbench-token") ?? "";
      const response = await fetch(`/api/gifts/export?${params.toString()}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        message.error((data as { detail?: string }).detail || "导出失败");
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `礼品单_${dayjs().format("YYYYMMDD_HHmm")}.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch {
      message.error("导出失败，请稍后重试");
    }
  };

  const total = filtered.length;
  const unreviewed = filtered.filter((item) => item.review_status === "none").length;
  const unsettled = filtered.filter((item) => item.settle_status === "unsettled").length;

  const columns: TableColumnsType<Gift> = [
    {
      title: "日期",
      key: "date",
      width: 100,
      render: (_, row) => (row.order_time ? dayjs(row.order_time).format("YYYY-MM-DD") : "-"),
    },
    {
      title: "下单时间",
      key: "order_time",
      width: 72,
      render: (_, row) =>
        renderEditableCell(
          row,
          "order_time",
          row.order_time ? dayjs(row.order_time).format("HH:mm") : "-"
        ),
    },
    {
      title: "店铺",
      dataIndex: "store_name",
      width: 140,
      filters: storeOptions.map((option) => ({ text: option.label, value: option.value })),
      onFilter: (value, row) => row.store_id === value,
      render: (_, row) => {
        const label = row.store_name === "未关联店铺" ? <Text type="secondary">未关联店铺</Text> : row.store_name;
        return renderEditableCell(row, "store_id", label);
      },
    },
    {
      title: "关键词",
      dataIndex: "keyword",
      width: 130,
      render: (_, row) => (
        <Space size={4}>
          {row.image ? (
            <>
              <img
                src={row.image}
                alt="图片"
                height={28}
                style={{ cursor: "zoom-in", borderRadius: 4, verticalAlign: "middle" }}
                onClick={() => setPreviewImage(row.image)}
                title="点击查看大图"
              />
              <Button
                size="small"
                type="text"
                icon={<CloseOutlined />}
                onClick={() => removeImage(row)}
                title="移除图片"
              />
            </>
          ) : (
            <>
              {renderEditableCell(row, "keyword", row.keyword || <Text type="secondary">-</Text>)}
              <Button
                size="small"
                type="text"
                icon={<PictureOutlined />}
                onClick={() => pickImage(row)}
                title="上传 / 粘贴图片"
              />
            </>
          )}
        </Space>
      ),
    },
    {
      title: "规格",
      dataIndex: "spec",
      width: 110,
      render: (_, row) => renderEditableCell(row, "spec", row.spec || "-"),
    },
    {
      title: "金额",
      dataIndex: "price",
      width: 90,
      render: (_, row) => renderEditableCell(row, "price", `¥${Number(row.price).toFixed(2)}`),
    },
    {
      title: "佣金",
      dataIndex: "commission",
      width: 90,
      render: (_, row) => renderEditableCell(row, "commission", `¥${Number(row.commission).toFixed(2)}`),
    },
    {
      title: "旺旺号",
      dataIndex: "wangwang",
      width: 120,
      render: (_, row) => renderEditableCell(row, "wangwang", row.wangwang || "-"),
    },
    {
      title: "订单编号",
      dataIndex: "order_no",
      width: 160,
      render: (_, row) => renderEditableCell(row, "order_no", row.order_no ? <Text code>{row.order_no}</Text> : <Text type="secondary">未填写</Text>),
    },
    {
      title: "评论状态",
      dataIndex: "review_status",
      width: 90,
      render: (_, row) => (
        <Tag color={REVIEW_META[row.review_status].color} style={{ cursor: "pointer" }} onClick={() => toggleReview(row)}>
          {REVIEW_META[row.review_status].label}
        </Tag>
      ),
    },
    {
      title: "结款状态",
      dataIndex: "settle_status",
      width: 90,
      render: (_, row) => (
        <Tag color={SETTLE_META[row.settle_status].color} style={{ cursor: "pointer" }} onClick={() => toggleSettle(row)}>
          {SETTLE_META[row.settle_status].label}
        </Tag>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 80,
      render: (_, row) => (
        <Popconfirm
          title={`删除 ${row.order_no || row.wangwang || "该单"}？删除后不可恢复`}
          okText="删除"
          okButtonProps={{ danger: true }}
          onConfirm={() => removeGift(row)}
        >
          <Button size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        icon={<GiftOutlined />}
        eyebrow="礼品单台账"
        title="礼品单"
        extra={
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              form.resetFields();
              setCreateOpen(true);
            }}
          >
            新增礼品单
          </Button>
        }
      />

      <Card variant="borderless" style={{ marginBottom: 16 }} styles={{ body: { padding: "12px 20px" } }}>
        <Space size={12} wrap>
          <Input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            prefix={<SearchOutlined style={{ color: "var(--ops-text-secondary)" }} />}
            placeholder="搜索订单编号 / 旺旺号 / 关键词 / 规格"
            allowClear
            style={{ width: 260 }}
          />
          <Select
            value={storeFilter}
            onChange={setStoreFilter}
            placeholder="按店铺筛选"
            allowClear
            options={storeOptions}
            style={{ width: 180 }}
          />
          <Select
            value={reviewFilter}
            onChange={setReviewFilter}
            placeholder="评论状态"
            allowClear
            options={REVIEW_OPTIONS}
            style={{ width: 120 }}
          />
          <Select
            value={settleFilter}
            onChange={setSettleFilter}
            placeholder="结款状态"
            allowClear
            options={SETTLE_OPTIONS}
            style={{ width: 120 }}
          />
          <DatePicker.RangePicker
            value={dateRange}
            onChange={setDateRange}
            style={{ width: 260 }}
          />
          <Button icon={<CopyOutlined />} onClick={copyTable}>
            复制表格
          </Button>
          <Button type="primary" ghost icon={<DownloadOutlined />} onClick={exportExcel}>
            导出 Excel
          </Button>
          <Button icon={<ReloadOutlined />} onClick={resetFilters}>
            重置
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            💡 点单元格直接编辑，回车跳下一行；关键词格可 Ctrl+V 粘贴图片
          </Text>
        </Space>
      </Card>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>礼品单总数</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2 }}>{total}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>未评论</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: "#fa8c16" }}>{unreviewed}</div>
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card variant="borderless" styles={{ body: { padding: "16px 20px" } }}>
            <Text type="secondary" style={{ fontSize: 12 }}>未结款</Text>
            <div style={{ fontSize: 26, fontWeight: 700, marginTop: 2, color: "#1677ff" }}>{unsettled}</div>
          </Card>
        </Col>
      </Row>

      {selectedKeys.length > 0 && (
        <Card
          variant="borderless"
          style={{ marginBottom: 16, background: "#fff7e6", border: "1px solid #ffd591" }}
        >
          <Space wrap>
            <Text strong>已选 {selectedKeys.length} 单</Text>
            <Button size="small" type="primary" ghost onClick={() => batchSet("review_status", "reviewed")}>
              标记已评论
            </Button>
            <Button size="small" onClick={() => batchSet("review_status", "none")}>
              标记未评论
            </Button>
            <Button size="small" type="primary" ghost onClick={() => batchSet("settle_status", "settled")}>
              标记已结款
            </Button>
            <Button size="small" onClick={() => batchSet("settle_status", "unsettled")}>
              标记未结款
            </Button>
            <Button size="small" onClick={() => setSelectedKeys([])}>
              取消选择
            </Button>
          </Space>
        </Card>
      )}

      <Card variant="borderless">
        <Table<Gift>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={filtered}
          rowSelection={{
            selectedRowKeys: selectedKeys,
            onChange: (keys) => setSelectedKeys(keys),
          }}
          pagination={{ pageSize: 10, showTotal: (count) => `共 ${count} 单` }}
          scroll={{ x: 1360 }}
        />
      </Card>

      <Modal
        title="新增礼品单"
        open={createOpen}
        onOk={() => form.submit()}
        onCancel={() => setCreateOpen(false)}
        confirmLoading={saving}
        okText="创建"
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={submitGift} style={{ marginTop: 8 }}>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="order_time" label="下单时间">
                <DatePicker showTime style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="store_id" label="店铺" rules={[{ required: true, message: "请选择店铺" }]}>
                <Select options={storeSelectOptions} placeholder="请选择店铺" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="keyword" label="关键词" rules={[{ required: true, message: "请输入关键词" }]}>
                <Input placeholder="如：礼品 女装" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="spec" label="规格">
                <Input placeholder="如：S 码 / 红色" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="price"
                label="金额（元）"
                rules={[
                  { required: true, message: "请输入金额" },
                  {
                    validator: (_, value) =>
                      typeof value === "number" && value > 0
                        ? Promise.resolve()
                        : Promise.reject(new Error("金额需大于 0")),
                  },
                ]}
              >
                <InputNumber min={1} step={1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="commission" label="佣金（元）" initialValue={0}>
                <InputNumber min={0} step={1} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="wangwang" label="旺旺号">
            <Input placeholder="买家旺旺号" />
          </Form.Item>
          <Form.Item name="order_no" label="订单编号" extra="仅支持数字，请手动填写">
            <Input
              placeholder="请输入淘宝订单号（仅数字）"
              maxLength={40}
              onChange={(event) => {
                const digits = event.target.value.replace(/\D/g, "");
                if (digits !== event.target.value) form.setFieldValue("order_no", digits);
              }}
            />
          </Form.Item>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="review_status" label="评论状态" initialValue="none">
                <Select options={REVIEW_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="settle_status" label="结款状态" initialValue="unsettled">
                <Select options={SETTLE_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && imageTarget) uploadImage(imageTarget, file);
          event.target.value = "";
        }}
      />

      <Modal
        title="图片预览"
        open={Boolean(previewImage)}
        footer={null}
        onCancel={() => setPreviewImage(null)}
        width={360}
      >
        {previewImage && (
          <div style={{ textAlign: "center" }}>
            <img src={previewImage} alt="图片" style={{ maxWidth: "100%", borderRadius: 8 }} />
          </div>
        )}
      </Modal>
    </div>
  );
}
