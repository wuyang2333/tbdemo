import type { ReactNode } from "react";

/** 页面底部提示条：所有操作提示统一放这里。 */
export function PageFooter({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        marginTop: 20,
        padding: "14px 4px 0",
        borderTop: "1px solid var(--ops-border)",
        color: "var(--ops-text-secondary)",
        fontSize: 12,
        lineHeight: "20px",
        textAlign: "center",
      }}
    >
      {children}
    </div>
  );
}
