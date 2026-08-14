import { AppstoreOutlined, CloseOutlined, GiftOutlined, PictureOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  AutoComplete,
  Button,
  Card,
  Col,
  DatePicker,
  Divider,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  TimePicker,
  Typography,
  message,
} from "antd";
import type { MenuProps, TableColumnsType } from "antd";
import dayjs from "dayjs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Key } from "react";

import http, { getApiErrorMessage } from "../lib/api";
import { PageFooter } from "../components/ui/page-footer";
import { PageHeader } from "../components/ui/page-header";
import type { Gift, GiftReviewStatus, GiftSettleStatus, Store } from "../types";

const { Text } = Typography;

type GiftFormValues = {
  date: dayjs.Dayjs;
  start_time: dayjs.Dayjs;
  store_name: string;
  keyword: string;
  spec: string;
  price: number;
  commission: number;
  quantity: number;
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
  const [storeFilter, setStoreFilter] = useState<string | undefined>();
  const [reviewFilter, setReviewFilter] = useState<GiftReviewStatus | undefined>();
  const [settleFilter, setSettleFilter] = useState<GiftSettleStatus | undefined>();
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(() => [
    dayjs().startOf("day"),
    dayjs().endOf("day"),
  ]);
  const [form] = Form.useForm<GiftFormValues>();
  const [createOpen, setCreateOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Key[]>([]);
  const [page, setPage] = useState(1);
  const [cellEdit, setCellEdit] = useState<{ id: number; field: EditableField; value: string | number } | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [imageTarget, setImageTarget] = useState<Gift | null>(null);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  const [formImage, setFormImage] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const formFileInputRef = useRef<HTMLInputElement>(null);
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

  const storeFilterOptions = useMemo(() => {
    const names = new Map<string, string>();
    stores.forEach((store) => names.set(store.name, store.name));
    items.forEach((item) => {
      if (item.store_name && item.store_name !== "未关联店铺") {
        names.set(item.store_name, item.store_name);
      }
    });
    return Array.from(names.values()).map((name) => ({ value: name, label: name }));
  }, [stores, items]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return items.filter((item) => {
      if (storeFilter && item.store_name !== storeFilter) return false;
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

  const pageSize = 10;
  const pageRows = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, page]);
  const amountSubtotal = pageRows.reduce((sum, row) => sum + Number(row.price), 0);
  const commissionSubtotal = pageRows.reduce((sum, row) => sum + Number(row.commission), 0);
  const selectedRows = useMemo(
    () => filtered.filter((item) => selectedKeys.includes(item.id)),
    [filtered, selectedKeys]
  );
  const selectedAmount = selectedRows.reduce((sum, row) => sum + Number(row.price), 0);
  const selectedCommission = selectedRows.reduce((sum, row) => sum + Number(row.commission), 0);
  const selectedTotal = selectedAmount + selectedCommission;

  useEffect(() => {
    setPage(1);
  }, [keyword, storeFilter, reviewFilter, settleFilter, dateRange]);

  const resetFilters = () => {
    setKeyword("");
    setStoreFilter(undefined);
    setReviewFilter(undefined);
    setSettleFilter(undefined);
    setDateRange([dayjs().startOf("day"), dayjs().endOf("day")]);
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
        <TimePicker
          size="small"
          format="HH:mm"
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          value={cellEdit.value ? dayjs(String(cellEdit.value)) : undefined}
          onChange={(value) => {
            if (!value) return;
            const base = row.order_time ? dayjs(row.order_time) : dayjs();
            const merged = base.hour(value.hour()).minute(value.minute()).second(0);
            saveCell(row, "order_time", merged.format("YYYY-MM-DD HH:mm:ss"));
          }}
          style={{ width: 92 }}
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
    if (selectedKeys.length === 0) {
      message.warning("请先在表格里勾选要操作的订单");
      return;
    }
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
      const { data } = await http.post<{ items: Gift[] }>("/gifts/batch-create", {
        date: values.date ? values.date.format("YYYY-MM-DD") : "",
        start_time: values.start_time ? values.start_time.format("HH:mm") : "",
        store_id: 0,
        store_name: values.store_name?.trim() ?? "",
        keyword: values.keyword?.trim() ?? "",
        spec: values.spec?.trim() ?? "",
        price: values.price ?? 0,
        commission: values.commission ?? 0,
        quantity: values.quantity ?? 1,
        image: formImage,
      });
      message.success(`已生成 ${data.items.length} 条礼品单`);
      setCreateOpen(false);
      form.resetFields();
      setFormImage("");
      load();
    } catch (error) {
      message.error(getApiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const uploadFormImage = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const { data } = await http.post<{ url: string }>("/gifts/image-upload", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setFormImage(data.url);
      message.success("图片已添加，将应用到生成的礼品单");
    } catch (error) {
      message.error(getApiErrorMessage(error));
    }
  };

  const handleKeywordPaste = (event: React.ClipboardEvent) => {
    const items = event.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (item.type.startsWith("image/")) {
        event.preventDefault();
        const file = item.getAsFile();
        if (file) uploadFormImage(file);
        return;
      }
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
    const rows = filtered.filter((item) => selectedKeys.includes(item.id));
    if (rows.length === 0) {
      message.warning("请先在表格里勾选要复制的订单");
      return;
    }
    const headers = ["日期", "下单时间", "店铺", "关键词", "规格", "金额", "佣金", "旺旺号", "订单编号", "评论状态", "结款状态"];
    const lines = [headers.join("\t")];
    for (const row of rows) {
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
      message.success(`已复制 ${rows.length} 行，可直接粘贴到 Excel`);
    } catch {
      message.error("复制失败，请手动选择后复制");
    }
  };

  const batchDelete = () => {
    if (selectedKeys.length === 0) {
      message.warning("请先在表格里勾选要删除的订单");
      return;
    }
    Modal.confirm({
      title: `确定删除选中的 ${selectedKeys.length} 单？`,
      content: "删除后不可恢复",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          await http.post("/gifts/batch-delete", { ids: selectedKeys });
          message.success(`已删除 ${selectedKeys.length} 单`);
          setSelectedKeys([]);
          load();
        } catch (error) {
          message.error(getApiErrorMessage(error));
        }
      },
    });
  };

  const batchMenuItems: MenuProps["items"] = [
    { key: "reviewed", label: "标记已评论", onClick: () => batchSet("review_status", "reviewed") },
    { key: "unreviewed", label: "标记未评论", onClick: () => batchSet("review_status", "none") },
    { key: "settled", label: "标记已结款", onClick: () => batchSet("settle_status", "settled") },
    { key: "unsettled", label: "标记未结款", onClick: () => batchSet("settle_status", "unsettled") },
    { type: "divider" },
    { key: "copy", label: "复制勾选订单", onClick: () => copyTable() },
    { key: "export", label: "导出勾选订单（Excel）", onClick: () => exportExcel() },
    { type: "divider" },
    { key: "delete", label: "删除勾选订单", danger: true, onClick: () => batchDelete() },
    { type: "divider" },
    { key: "clear", label: "取消选择", onClick: () => setSelectedKeys([]) },
  ];

  const exportExcel = async () => {
    if (selectedKeys.length === 0) {
      message.warning("请先在表格里勾选要导出的订单");
      return;
    }
    try {
      const params = new URLSearchParams();
      params.set("ids", selectedKeys.join(","));
      if (storeFilter) params.set("store_name", storeFilter);
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
      filters: storeFilterOptions.map((option) => ({ text: option.label, value: option.value })),
      onFilter: (value, row) => row.store_name === value,
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
              setFormImage("");
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
            options={storeFilterOptions}
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
          <Button size="small" onClick={() => setDateRange([dayjs().startOf("day"), dayjs().endOf("day")])}>
            今日
          </Button>
          <Button
            size="small"
            onClick={() =>
              setDateRange([
                dayjs().subtract(1, "day").startOf("day"),
                dayjs().subtract(1, "day").endOf("day"),
              ])
            }
          >
            昨日
          </Button>
          <Button
            size="small"
            onClick={() =>
              setDateRange([dayjs().subtract(6, "day").startOf("day"), dayjs().endOf("day")])
            }
          >
            近七日
          </Button>
          <DatePicker.RangePicker
            value={dateRange}
            onChange={setDateRange}
            style={{ width: 260 }}
          />
          <Button icon={<ReloadOutlined />} onClick={resetFilters}>
            重置
          </Button>
          <Divider type="vertical" />
          <Dropdown menu={{ items: batchMenuItems }}>
            <Button type="primary" ghost icon={<AppstoreOutlined />}>
              批量操作
            </Button>
          </Dropdown>
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
          pagination={{
            pageSize,
            current: page,
            onChange: (next) => setPage(next),
            showTotal: (count) => (
              <span>
                {selectedKeys.length > 0 && (
                  <span style={{ marginRight: 14 }}>
                    <span style={{ marginRight: 12 }}>佣金总额 ¥{selectedCommission.toFixed(2)}</span>
                    <span style={{ marginRight: 12 }}>金额总额 ¥{selectedAmount.toFixed(2)}</span>
                    <span style={{ color: "#ff5000", fontWeight: 700, marginRight: 12 }}>
                      总金额 ¥{selectedTotal.toFixed(2)}
                    </span>
                  </span>
                )}
                <span style={{ color: "#ff5000", fontWeight: 700, marginRight: 10 }}>
                  已选 {selectedKeys.length} 单
                </span>
                共 {count} 单
              </span>
            ),
          }}
          summary={() => (
            <Table.Summary.Row>
              <Table.Summary.Cell index={0} colSpan={1} />
              <Table.Summary.Cell index={1} colSpan={5}>
                <Text strong>本页小计</Text>
              </Table.Summary.Cell>
              <Table.Summary.Cell index={6}>
                <Text strong>¥{amountSubtotal.toFixed(2)}</Text>
              </Table.Summary.Cell>
              <Table.Summary.Cell index={7}>
                <Text strong>¥{commissionSubtotal.toFixed(2)}</Text>
              </Table.Summary.Cell>
              <Table.Summary.Cell index={8} colSpan={5} />
            </Table.Summary.Row>
          )}
          scroll={{ x: 1360 }}
        />
      </Card>

      <PageFooter>💡 点单元格直接编辑，回车跳下一行；关键词格可 Ctrl+V 粘贴图片</PageFooter>

      <Modal
        title="新增礼品单"
        open={createOpen}
        onOk={() => form.submit()}
        onCancel={() => {
          setCreateOpen(false);
          setFormImage("");
        }}
        confirmLoading={saving}
        okText="创建"
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={submitGift} style={{ marginTop: 8 }}>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="date" label="下单日期" rules={[{ required: true, message: "请选择下单日期" }]}>
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="start_time"
                label="时间"
                rules={[{ required: true, message: "请选择开始时间" }]}
              >
                <TimePicker format="HH:mm" style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item
                name="quantity"
                label="下单数量"
                initialValue={1}
                rules={[{ required: true, message: "请输入下单数量" }]}
              >
                <InputNumber min={1} max={100} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                name="store_name"
                label="店铺"
                rules={[{ required: true, message: "请选择或输入店铺" }]}
              >
                <AutoComplete
                  options={stores.map((store) => ({ value: store.name }))}
                  placeholder="选择或输入店铺名称"
                  filterOption={(input, option) =>
                    (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                  }
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="keyword"
                label="关键词"
                rules={[
                  {
                    validator: (_, value) =>
                      String(value ?? "").trim() || formImage
                        ? Promise.resolve()
                        : Promise.reject(new Error("请填写关键词或粘贴图片")),
                  },
                ]}
              >
                <Input
                  placeholder="如：礼品 女装（也可 Ctrl+V 粘贴图片）"
                  onPaste={handleKeywordPaste}
                />
              </Form.Item>
            </Col>
          </Row>
          {formImage ? (
            <Space style={{ marginBottom: 16 }}>
              <img src={formImage} alt="关键词图片" height={40} style={{ borderRadius: 4 }} />
              <Button size="small" icon={<CloseOutlined />} onClick={() => setFormImage("")}>
                移除图片
              </Button>
            </Space>
          ) : (
            <Button
              size="small"
              icon={<PictureOutlined />}
              onClick={() => formFileInputRef.current?.click()}
              style={{ marginBottom: 16 }}
            >
              粘贴 / 上传图片
            </Button>
          )}
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="spec" label="规格">
                <Input placeholder="如：S 码 / 红色" />
              </Form.Item>
            </Col>
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
          </Row>
          <Form.Item name="commission" label="佣金（元）" initialValue={0}>
            <InputNumber min={0} step={1} style={{ width: "100%" }} />
          </Form.Item>
          <Text type="secondary" style={{ fontSize: 12 }}>
            将按下单数量生成对应行数，下单时间从所选时间开始，每行相隔 15 分钟（每小时最多 4 行）；订单编号、旺旺号可在表格里逐行填写。
          </Text>
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
      <input
        ref={formFileInputRef}
        type="file"
        accept="image/*"
        style={{ display: "none" }}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) uploadFormImage(file);
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
