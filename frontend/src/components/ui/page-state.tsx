import { ReloadOutlined } from "@ant-design/icons";
import { Button, Result, Spin, Typography } from "antd";
import { Component, type ReactNode } from "react";

const { Text } = Typography;

/** 统一加载态：居中大 Spin + 文案。 */
export function LoadingBlock({ text = "加载中…" }: { text?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "72px 16px", gap: 14 }}>
      <Spin size="large" />
      <Text type="secondary" style={{ fontSize: 13 }}>{text}</Text>
    </div>
  );
}

/** 统一错误态：错误图标 + 说明 + 重新加载按钮。 */
export function ErrorState({
  title = "页面加载出错",
  description = "数据加载失败或页面出现异常，请重新加载。",
  onRetry,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "48px 16px" }}>
      <Result
        status="error"
        title={title}
        subTitle={description}
        extra={
          <Button type="primary" icon={<ReloadOutlined />} onClick={onRetry ?? (() => window.location.reload())}>
            重新加载
          </Button>
        }
      />
    </div>
  );
}

type BoundaryProps = {
  children: ReactNode;
  title?: string;
  description?: string;
};
type BoundaryState = { error: Error | null };

/** 页面级错误边界：任何子组件渲染崩溃时显示友好提示，而不是白屏/黑屏。 */
export class ErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidCatch(error: Error) {
    // 留痕便于排查
    if (typeof console !== "undefined") {
      console.error("[PageErrorBoundary]", error);
    }
  }

  render() {
    if (this.state.error) {
      return (
        <ErrorState
          title={this.props.title ?? "页面出错了"}
          description={this.props.description ?? this.state.error?.message ?? "发生了未预期的错误，请重新加载。"}
        />
      );
    }
    return this.props.children;
  }
}
