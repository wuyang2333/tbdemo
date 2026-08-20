# 淘宝运营工作台

无恙按照工作台形态搭建的淘宝运营平台，还在完善中。FastAPI + React/Vite/Antd + SQLite，
核心数据（店铺、礼品单、推广、商品）通过内置的生意参谋/万相台抓取组件实时同步。

> 注意：本 README 于 2026-08-17 更新，对齐当前真实代码状态。原 README 描述（"框架骨架"）已过时。

## 模块清单（2026-08-17 实测）

| 模块    | 路径               | 状态    | 说明                                                    |
| ----- | ---------------- | ----- | ----------------------------------------------------- |
| 总览    | `/dashboard`     | ⚠️ 部分 | 前端完整（模块导航+KPI 卡），后端接口仍为示例数据                           |
| 店铺管理  | `/stores`        | ✅ 已实现 | 多店铺 CRUD、健康巡检（5 分钟自动）、授权管理、生意参谋绑定与数据同步、列表登录状态/数据新鲜度展示 |
| 商品管理  | `/products`      | ⬜ 占位  | 待开发（数据表 `store_item_daily` 已有商品数据，商品分析见数据洞察）          |
| 礼品单   | `/gifts`         | ✅ 已实现 | 礼品订单台账：列表/新增/发货/审核/结款/批量操作/导出/图片                      |
| AI 助手 | `/ai`            | ✅ 已实现 | AI 对话：问数据、写文案、给建议（依赖模型配置）                             |
| 客户管理  | `/customers`     | ⬜ 占位  | 待开发                                                   |
| 数据洞察  | `/analytics`     | ✅ 已实现 | 6 个子页：概览/预警/经营日报/AI 洞察/时段分析/商品分析                      |
| 推广管理  | `/promotions`    | ✅ 已实现 | 2 个子页：推广数据/推广计划（全站/关键词/人群/内容营销，含 AI 洞察）               |
| 内容运营  | `/content`       | ⬜ 占位  | 待开发                                                   |
| 竞品监控  | `/monitoring`    | ⬜ 占位  | 待开发                                                   |
| 任务中心  | `/tasks`         | ⬜ 占位  | 待开发                                                   |
| 模型配置  | `/model-configs` | ✅ 已实现 | OpenAI 兼容接入（OpenAI/DeepSeek/百炼/月之暗面/自定义）              |
| 设置    | `/settings`      | ⬜ 占位  | 待开发（注意：后端未挂载 settings 路由，前端有占位页）                      |
| 个人中心  | `/profile`       | ✅ 已实现 | 花名/密码/头像                                              |
| 账号管理  | `/accounts`      | ✅ 已实现 | 账号 CRUD、角色、模块权限、店铺权限（管理员）                             |
| 操作日志  | `/logs`          | ✅ 已实现 | 全模块操作审计（管理员）                                          |

## 目录结构

```
taobao-workbench/
├── backend/                    # FastAPI
│   ├── app/
│   │   ├── main.py             # 应用入口，挂载所有模块路由 + 4 个后台循环
│   │   ├── core/               # db.py(建表/迁移/种子数据)、modules.py(模块注册表)、
│   │   │                       # ai_client.py(OpenAI 兼容调用)、sycm.py、alimama.py(抓取封装)
│   │   └── api/                # 每个模块一个路由文件（10 个真实实现，6 个占位）
│   ├── sycm_cli/               # 生意参谋抓取 CLI（MIT，读专用 Chrome 登录态）
│   ├── alimama_cli/            # 万相台推广抓取 CLI（MIT，复用淘宝登录档案）
│   └── data/taobao.db          # SQLite 单文件数据库
├── frontend/                   # React + Vite + Ant Design
│   └── src/
│       ├── app/                # 主题 Provider、路由（含权限守卫）
│       ├── components/         # layout(侧边栏+顶栏)、各模块 UI 组件
│       ├── lib/                # 品牌、模块注册表、API 客户端、认证
│       └── pages/              # 模块页面（16 个模块；其中 6 个为占位）
└── requirements.txt
```

## 启动

**一键启动（推荐）**：双击项目根目录的 `start-lan.bat`，后端 + 前端以**静默模式**（无窗口）在后台拉起并自动打开浏览器（已装好依赖的前提下）。

- 停止服务：双击 `stop.bat`
- 服务日志：`logs/backend.log`（后端）、`logs/frontend.log`（前端）
- `start-lan.bat` 会检测端口占用，重复双击不会起重复服务；日志目录 `logs/` 随服务增长，可定期清理

手动启动（端口 8008）：

```bash
cd taobao-workbench
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8008
```

前端（端口 5178，已配置 `/api` 代理到 8008）：

```bash
cd taobao-workbench/frontend
npm install
npm run dev
```

访问 http://127.0.0.1:5178

首次启动自动建库并写入种子数据（4 家演示店铺、礼品单样例、操作日志）；
**第一个注册的账号自动成为超级管理员**。默认已有账号见 HANDOFF.md。

## 后台自动任务（main.py lifespan）

| 任务     | 周期      | 说明                                                                        |
| ------ | ------- | ------------------------------------------------------------------------- |
| 店铺健康巡检 | 5 分钟    | 检查授权状态与店铺健康                                                               |
| 全量数据同步 | 3 分钟    | 店铺日数据 + 分时(今日/昨日) + 推广实时分时 + 商品实时 + 商品级推广实时（**单点隔离**：5 类数据各自提交，单个失败不影响其他） |
| 经营日报推送 | 每分钟检查   | 到点（默认 9:00）且已配置 webhook 时推送日报到群机器人                                        |
| 小时异常推送 | 整点过 5 分 | 命中小时规则时推送到 pushplus 绑定的微信                                                 |

**循环状态可观测**（不再静默失败）：
- 运行状态：`GET /api/system/loops`（需登录）返回每个循环的最近运行/成功时间、连续失败次数、错误信息、耗时
- 错误日志：失败写 `logs/loops.log`（成功不落盘，避免刷屏）
- 失败告警：连续失败 ≥3 次（3 的倍数）时，若配置了 pushplus token，推送微信告警（10 分钟内同循环至多一次）

## 数据对接

- **生意参谋**（`backend/app/core/sycm.py` + `backend/sycm_cli/`）：Windows 通过 CDP 读取专用 Chrome 窗口登录态，
  每个店铺一份登录档案（`~/.taobao-cli/profiles/store_<店铺id>.json`，**勿入 git**）。
  今日走实时接口，历史日期走数据概览接口。
- **万相台推广**（`backend/app/core/alimama.py` + `backend/alimama_cli/`）：复用店铺淘宝登录档案，
  场景覆盖全站/关键词/人群/内容营销。

### 同步结果反馈

所有同步接口（店铺/分时/商品/历史补拉/推广/推广计划）遍历**全部店铺**，不再静默跳过：
未配置生意参谋登录档案的店铺会显式返回失败原因 `生意参谋未登录（未配置登录档案）`，
抓取报错时原样带出错误信息（登录过期、接口异常等）。

前端统一反馈规则（`frontend/src/lib/sync-feedback.ts`）：
- 全部成功 → 绿色提示「xxx完成：全部 N 家店铺成功」
- 有失败 → 红色提示列出具体原因（最多 3 条）+ 失败总数，如「同步未完成：尹颜森林旗舰店：生意参谋未登录…，共 1 次失败」
- 没有店铺 → 提示先添加店铺并配置登录档案

## 如何添加一个功能

1. **后端**：在 `backend/app/api/` 新建/修改对应模块的路由（如 `products.py`），在 `backend/app/main.py` 挂载
   （需要权限控制时加 `dependencies=[Depends(require_module("xxx"))]`）。
2. **前端**：把 `frontend/src/pages/<模块>-page.tsx` 的占位页换成真实页面，在 `frontend/src/lib/api.ts` 添加接口函数。
3. **导航**：新模块在 `frontend/src/lib/modules.ts` 和 `backend/app/core/modules.py` 各注册一条，侧边栏与接口自动出现。
4. **建表/迁移**：在 `backend/app/core/db.py` 的 `init_db()` 里加 `CREATE TABLE IF NOT EXISTS` 与 `_migrate_xxx`。

## 品牌

名称、标语、主题色集中在 `frontend/src/lib/brand.ts`，改一处全局生效。
