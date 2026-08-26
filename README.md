# 淘宝运营工作台

面向淘宝、天猫店铺日常经营的本地运营工作台。项目将店铺、商品、礼品单、评价、经营分析、推广数据和运营策略集中在一个界面中，并提供多店铺权限、后台任务、AI 分析与第三方数据同步能力。

项目仍在持续开发。已有业务模块可以直接使用；内容运营、竞品监控、市场洞察等模块目前已完成页面与接口框架，后续会逐步接入真实数据和业务动作。

## 技术栈

- 后端：FastAPI、SQLite、Pydantic
- 前端：React 19、TypeScript、Vite 7、Ant Design 6
- 数据接入：生意参谋、万相台、腾讯文档
- 运行环境：Windows、Python、Node.js

## 功能模块

### 已具备业务能力

| 模块 | 入口 | 主要能力 |
| --- | --- | --- |
| 总览 | `/dashboard` | 核心指标、经营待办、异常提醒和快捷入口 |
| 店铺管理 | `/stores` | 多店铺管理、生意参谋绑定、健康检查和数据同步 |
| 商品管理 | `/products` | 商品列表、价格库存、经营状态和商品数据同步 |
| 礼品单 | `/gifts` | 新增、编辑、批量处理、审核、结款、图片和导出 |
| 评价管理 | `/customers` | 评价同步、情感与问题分析、处理状态、AI 回复草稿和知识沉淀 |
| 数据洞察 | `/analytics` | 今日总览、经营日报、AI 解读、时段分析、商品分析和指标口径 |
| 推广管理 | `/promotions` | 推广数据、计划管理、分时表现、商品推广和 AI 洞察 |
| AI 助手 | `/ai` | 基于已配置模型进行数据问答、文案创作和经营建议 |

### 已完成框架，等待业务数据接入

| 工作区 | 入口 | 子页面 |
| --- | --- | --- |
| 内容运营 | `/content` | 运营总览、选题策划、内容日历、素材库、创作工作台、发布效果复盘 |
| 竞品监控 | `/monitoring` | 监控总览、竞品店铺库、商品追踪、价格活动、动作雷达、分析报告 |
| 市场洞察 | `/market` | 选品与市场机会、关键词运营中心、经营机会雷达 |
| 增长实验室 | `/growth-lab` | 商品策略、价格与促销、经营沙盘、营销实验、素材洞察 |
| 运营知识库 | `/ops-knowledge` | 经营复盘、运营决策档案、知识库与 SOP、运营自动化 |

框架页面已经包含导航、权限、业务目标、计划数据源、预期产出和后端占位接口。这里的“已完成框架”不代表已经接入实时平台数据。

### 系统管理

| 模块 | 入口 | 主要能力 |
| --- | --- | --- |
| 系统任务 | `/tasks` | 后台循环状态、执行历史、错误详情、重试和维护模式 |
| 模型配置 | `/model-configs` | OpenAI 兼容模型、阿里云百炼等模型接入与连接测试 |
| 设置 | `/settings` | 品牌设置、腾讯文档同步和礼品单千牛备注设置 |
| 个人中心 | `/profile` | 花名、头像、密码和登录会话管理 |
| 账号管理 | `/accounts` | 账号、角色、模块权限、店铺权限和子账号管理 |
| 操作日志 | `/logs` | 管理员操作审计 |

## 快速开始

### 1. 环境要求

建议使用：

- Windows 10 或 Windows 11
- Python 3.11 或更高版本
- Node.js 20 或更高版本
- Chrome，用于需要登录态的数据同步

### 2. 安装依赖

在项目根目录安装后端依赖：

```powershell
python -m pip install -r requirements.txt
```

安装前端依赖：

```powershell
cd frontend
npm install
cd ..
```

### 3. 一键启动

双击项目根目录的 `start.bat`。脚本会在后台启动前后端、检查服务状态并打开浏览器。

- 工作台：http://127.0.0.1:5178
- 后端接口：http://127.0.0.1:8008
- API 文档：http://127.0.0.1:8008/docs
- 局域网访问：启动成功后终端会显示当前局域网地址
- 停止服务：双击 `stop.bat`
- 运行日志：`logs/backend.log`、`logs/backend.err.log`、`logs/frontend.log`、`logs/frontend.err.log`

`start.bat` 不会自动安装依赖。首次运行前必须先完成上一节的安装步骤。

### 4. 手动启动

后端：

```powershell
python -m uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8008
```

前端另开一个终端：

```powershell
cd frontend
npm run dev -- --host 0.0.0.0 --port 5178
```

前端开发服务器会把 `/api` 请求代理到 `http://127.0.0.1:8008`。如需修改后端地址，可设置 `VITE_API_TARGET`。

### 5. 首次登录

首次启动会自动初始化 SQLite 数据库。第一个完成注册的账号会成为超级管理员，之后可在账号管理中审批成员并分配模块和店铺权限。

## 常用配置

### 模型配置

进入“模型配置”添加 OpenAI 兼容服务、阿里云百炼或其他支持的模型，测试连接后设为默认模型。AI 助手、经营解读、评价分析等功能会使用默认模型。

不要把 API Key 写入源码或提交到 Git。模型配置保存在本机数据库中，前端不会回显完整密钥。

### 店铺与生意参谋

1. 在“店铺管理”中添加店铺。
2. 为店铺绑定生意参谋登录态。
3. 使用“测试登录”确认授权有效。
4. 按需同步店铺、商品、分时、历史和推广数据。

登录档案默认保存在用户目录下的 `.taobao-cli/profiles/`，属于本机敏感数据，不应提交到 Git 或发送给其他人。

### 腾讯文档礼品单同步

礼品单可以与腾讯在线表格双向同步。系统会写入礼品单信息，并从腾讯文档回填旺旺号、订单号等字段。

#### 官方 API

1. 在腾讯文档开放合作平台创建并审核 Web 应用，申请在线表格读写权限。
2. 配置回调地址：`https://你的域名/api/settings/tencent-docs/oauth/callback`。
3. 在“设置”中填写 Client ID、Client Secret、文档链接和回调地址。
4. 完成授权、测试连接并启用同步。

如果平台直接提供 `client_id`、`access_token` 和 `open_id`，也可以直接填写。此模式无法自动刷新 Access Token，到期后需要重新生成并保存。

系统内礼品单发生新增、编辑、状态、图片或删除变化时会进入同步队列；定时任务每 15 分钟处理增量变化。官方接口额度耗尽后会暂停自动请求，避免持续失败。

#### 浏览器备用通道

官方 API 不可用时，可以在“设置”中启用浏览器备用通道。该通道连接本机已登录腾讯文档的 Chrome 调试实例，只作为官方 API 失败后的备用方式。

```powershell
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\tencent-docs-chrome"
```

启动后，在该 Chrome 窗口中登录腾讯文档、打开目标表格并切换到配置的工作表，再回到设置页面测试连接。

备用通道支持文本单元格的读取、写入和清除。图片上传仍需等待官方 API 恢复。Chrome 未启动、未登录或工作表不匹配时，系统会返回明确错误，不会静默报告成功。

## 后台任务

应用启动后会运行店铺巡检、实时数据同步、商品同步、评价同步、腾讯文档同步、礼品单备注、经营报告推送、小时预警、推广同步、数据库备份、数据清理和日志轮转等后台任务。

可在“系统任务”中查看最近运行时间、连续失败次数、错误详情和执行历史，也可以手动重试或进入维护模式。后台任务失败会写入 `logs/loops.log`。

## 测试与构建

后端测试需要安装 pytest：

```powershell
python -m pip install pytest
python -m pytest backend/tests -q -p no:cacheprovider
```

前端类型检查：

```powershell
cd frontend
npm run typecheck
```

前端正式构建：

```powershell
cd frontend
npm run build
```

## 项目结构

```text
taobao-workbench/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI 业务接口
│   │   ├── core/           # 数据库、同步、模型与公共能力
│   │   └── main.py         # 应用入口与后台任务
│   ├── sycm_cli/           # 生意参谋数据接入
│   ├── alimama_cli/        # 万相台数据接入
│   ├── data/               # SQLite、头像和业务图片等本机数据
│   └── tests/              # 后端测试
├── frontend/
│   ├── src/
│   │   ├── app/            # 路由、权限守卫和全局 Provider
│   │   ├── components/     # 布局和复用组件
│   │   ├── lib/            # API 客户端、模块定义和公共逻辑
│   │   └── pages/          # 页面模块
│   └── package.json
├── service.ps1             # Windows 服务启停逻辑
├── start.bat               # 一键启动
├── stop.bat                # 一键停止
└── requirements.txt
```

## 开发新模块

1. 在 `backend/app/api/` 添加接口，并在 `backend/app/main.py` 注册路由。
2. 在 `frontend/src/pages/` 添加页面，并在 `frontend/src/app/router.tsx` 注册路由。
3. 在 `backend/app/core/modules.py` 与 `frontend/src/lib/modules.ts` 同步模块定义。
4. 数据表和迁移统一维护在 `backend/app/core/db.py`。
5. 新增真实业务流程时同步补充测试、权限和错误状态。

## 数据与安全

- `backend/data/taobao.db` 是本机运行数据库，可能包含账号、店铺和业务数据。
- `backend/data/images/` 与 `backend/data/avatars/` 可能包含用户上传内容。
- `.taobao-cli/profiles/` 包含平台登录档案。
- 日志、数据库、登录档案、访问令牌和用户图片不应上传到公开仓库。
- 分享问题日志前，应先移除 Cookie、Token、手机号、订单号等敏感信息。

## 常见问题

### `start.bat` 提示缺少前端依赖

进入 `frontend` 执行 `npm install`，完成后重新启动。

### 8008 或 5178 端口被占用

先运行 `stop.bat`。如果仍然占用，使用以下命令查看进程：

```powershell
netstat -ano | findstr ":8008 :5178"
```

### 页面正常打开，但新接口不可用

确认当前 8008 端口运行的是最新后端，并打开 http://127.0.0.1:8008/docs 检查接口是否已经注册。修改后端代码后，需要重启非 `--reload` 模式启动的服务。

### 数据同步提示未登录

进入店铺管理重新绑定对应店铺的生意参谋登录态，然后执行“测试登录”。每个店铺使用独立登录档案。

### 腾讯文档同步失败

先在设置页面查看授权和同步状态。若为额度或令牌问题，等待自动恢复或重新授权；使用浏览器备用通道时，同时确认 Chrome 调试端口、登录状态、目标文档和工作表。
