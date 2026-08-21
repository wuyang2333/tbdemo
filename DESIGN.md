# 淘宝运营工作台 · 设计系统

> 版本：v3（Linear 专业深色 · 薰衣草蓝）｜适用：`frontend/`（React 19 + Ant Design v6 + Vite）
> 视觉语言参考 awesome-design-md 的 linear.app：近黑画布、炭灰面板、发丝边框、单一强调色。
> 本文件取代旧版「极光 · 淘宝橙」。

---

## 一、品牌方向

- **主色**：薰衣草蓝 `#5e6ad2`（浅/深一致），强调色渐变 `#828fff → #5e6ad2`。
- **氛围**：Linear 专业深色——近黑画布 `#0a0b0f` + 炭灰面板 + 1px 发丝边框 + 顶部极淡的薰衣草光晕；**无玻璃拟态、无大面积渐变**。
- **默认主题**：深色（`DEFAULT_MODE = "dark"`），顶部栏提供「浅色 ⇄ 深色」一键切换，用户选择持久化到 `localStorage("tb-workbench-theme")`。
- **语义色**：涨=绿、跌=红、警告=橙，仅用于增量/状态，不与分类色混用（商品分析按业务约定为涨红跌绿）。

## 二、Token 单一真相源

所有视觉决策集中在 **`frontend/src/lib/theme.ts`**：

| 出口 | 用途 |
|---|---|
| `TOKENS[mode]` | 全部设计变量（深/浅两套） |
| `applyTokens(mode)` | 把 token 写入 `:root`/`body` 为 `--ops-*` CSS 变量 |
| `antdTokens(mode)` | AntD `ConfigProvider` 派生 token（与 CSS 变量同源） |
| `themeComponents(mode)` | AntD 组件级 token（侧栏/菜单/表格/弹窗） |

**规则**：
1. 组件里一律用 `var(--ops-*)`，**不要写死 hex/rgba**（存量写死颜色已清理）。
2. AntD 组件优先用 AntD token；自定义视觉走 CSS 变量。
3. 新颜色先加到 `theme.ts`，再引用；禁止在组件里发明新颜色。

### 常用 CSS 变量（深色/浅色）

| 变量                                 | 深色                                        | 浅色                      |
| ---------------------------------- | ----------------------------------------- | ----------------------- |
| `--ops-bg`                         | `#0a0b0f`                                 | `#f7f8fa`              |
| `--ops-panel`（卡片/面板）               | `#14161b`                                 | `#ffffff`              |
| `--ops-panel-2`                    | `#101216`                                 | `#f2f3f6`              |
| `--ops-border`                     | `rgba(255,255,255,.09)`                   | `rgba(18,24,45,.10)`   |
| `--ops-text`                       | `#f6f7f8`                                 | `#1b1d22`              |
| `--ops-text-2`                     | `#a7adb8`                                 | `#525a66`              |
| `--ops-text-3`                     | `#6f7782`                                 | `#6b7280`              |
| `--ops-accent`                     | `#5e6ad2`                                 | `#5e6ad2`              |
| `--ops-accent-light`               | `#828fff`                                 | `#828fff`              |
| `--ops-accent-soft`                | `rgba(94,106,210,.16)`                    | `rgba(94,106,210,.12)` |
| `--ops-accent-grad`                | `linear-gradient(135deg,#828fff,#5e6ad2)` | 同                       |
| `--ops-up` / `--ops-down`          | `#ff5b5b` / `#37c871`                    | `#dc2626` / `#16a34a` |
| `--ops-warn`                       | `#ffb061`                                 | `#fa8c16`              |
| `--ops-radius` / `--ops-radius-sm` | `12px` / `8px`                           | 同                       |

旧命名（`--ops-card-bg`、`--ops-card-bg-2`、`--ops-text-secondary`、`--ops-hoverbar-*`、`--ops-shadow*`）保留为**别名**，供迁移期兼容；新代码请用新命名。

## 三、图表与数据可视化

- 分类色板（`--ops-cat-0..5`）：薰衣草蓝/蓝/紫/绿/青/粉，用于多系列/漏斗/榜单；**不超过 6 色**。
- 语义色（`--ops-up/--ops-down/--ops-warn`）：只用于环比涨跌、预警状态。
- 图表组件在 `components/analytics/analytics-ui.tsx`（`TrendChart`/`LineChart`/`StoreBars`），颜色读 token，深浅自动切换。
- 商品分析「涨跌幅」遵循 **涨红跌绿**（`--ops-down` 用于上涨提示等按业务定义）；其余通用场景按 **涨绿跌红**。

## 四、圆角 / 间距 / 字体

- 圆角阶梯：`sm=8`（输入/表内）→ `md=12`（卡片内嵌）→ `lg=16`（卡片）→ `pill=999`（按钮/胶囊）。**不要再引入 10/11/14/21 等游离值**。
- 标题：`600` 字重 + **负字距 -0.02em**（Linear 式）；KPI 大数字允许 `700` + `tabular-nums`。
- 正文基准 `14px`（AntD）；字族：`Inter → PingFang SC → Microsoft YaHei → system-ui`。

## 五、组件规范

- **卡片**：`--ops-panel` 底 + `1px var(--ops-border)` 发丝边框 + `lg` 圆角；以轻投影 `--ops-shadow-sm` 提升数据密集页的扫描性，**不使用 inset 高光/玻璃效果**。
- **按钮**：主按钮 = 薰衣草蓝胶囊（`ant-btn-primary`）；次按钮 = 中性描边 + 薰衣草蓝字。
- **标签 Tag**：用 AntD 预设色名（`orange/red/green`），随主题自适应；不要传 `var()` 给 `color`。
- **表格**：表头 `--ops-panel-2`，行 hover 用 `--ops-accent-soft`。
- **空态/加载**：统一 `Empty` + 引导文案（可带「去同步」按钮）；加载用 `Spin/Skeleton`，禁止让页面白屏。

## 六、无障碍

- 图标按钮必须有 `aria-label`（主题切换/通知/退出等）。
- 动效遵循 `prefers-reduced-motion`（`global.css` 已全局处理）。
- 主色 `#5e6ad2` 在深底上对比度良好；浅色场景用于大号文字/图形，小号灰字用 `--ops-text-2/3`。

## 七、改主题的正确姿势

1. 改 token → `theme.ts`（深浅两套一起改）。
2. 需要新 CSS 变量 → 加入 `theme.ts` 的 `CSS_VAR_MAP` + `global.css` 兜底块。
3. 组件引用 → `var(--ops-*)` 或 AntD token。
4. 品牌名/Logo/主色（用户可配）→ `lib/brand.ts` + 后端 `settings.py` 的 `DEFAULT_BRAND`（旧橙/旧蓝缓存由 `brand.ts` 自动迁移到新主色）。
