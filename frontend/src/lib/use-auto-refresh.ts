import { useEffect, useRef } from "react";

/** 每 intervalMs 毫秒自动调用一次 refresh（用于数据页定时刷新，默认 3 分钟）。 */
export function useAutoRefresh(refresh: () => void, intervalMs = 180000) {
  const ref = useRef(refresh);
  ref.current = refresh;
  useEffect(() => {
    // 挂载后立即拉一次数据，避免页面首次打开为空
    ref.current();
    const id = setInterval(() => {
      ref.current();
    }, intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
}
