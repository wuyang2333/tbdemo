import { useEffect, useRef } from "react";

/** 每天在 hour 点后自动刷新一次（用于经营日报：每天 9 点拉取完整昨日数据）。 */
export function useDailyRefreshAt(refresh: () => void, hour = 9) {
  const ref = useRef(refresh);
  ref.current = refresh;
  const lastDay = useRef("");
  useEffect(() => {
    const check = () => {
      const now = new Date();
      if (now.getHours() >= hour) {
        const key = `${now.getFullYear()}-${now.getMonth() + 1}-${now.getDate()}`;
        if (lastDay.current !== key) {
          lastDay.current = key;
          ref.current();
        }
      }
    };
    check();
    const id = setInterval(check, 30000);
    return () => clearInterval(id);
  }, [hour]);
}
