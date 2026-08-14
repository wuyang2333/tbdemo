# 淘宝运营工作台（框架骨架）

仿照 XHS_ALL_IN_ONE 的工作台形态搭建的淘宝运营平台空壳。当前只有框架：
侧边栏导航 + 每个模块的占位页 + 后端模块路由，**具体功能后续逐个填充**。

## 模块清单

| 模块 | 路径 | 说明 |
|---|---|---|
| 总览 | `/dashboard` | 店铺核心指标一屏总览 |
| 店铺管理 | `/stores` | 多店铺绑定、健康状态、授权管理 |
| 商品管理 | `/products` | 商品库、上下架、价格库存、批量操作 |
| 礼品单 | `/gifts` | 礼品订单列表、发货、售后、批量处理 |
| 客户管理 | `/customers` | 客户画像、复购分析、私域运营 |
| 数据洞察 | `/analytics` | 流量、转化、销售趋势分析 |
| 推广管理 | `/promotions` | 直通车/引力魔方/万相台推广计划 |
| 内容运营 | `/content` | 素材库、内容创作、AI 图文/短视频 |
| 竞品监控 | `/monitoring` | 关键词/店铺/商品监控与快照 |
| 任务中心 | `/tasks` | 全量任务审计、调度器状态、重试 |
| 模型配置 | `/model-configs` | AI 模型接入（OpenAI 兼容 / 阿里云百炼等） |
| 设置 | `/settings` | 系统设置与偏好 |

## 目录结构

```
taobao-workbench/
├── backend/                    # FastAPI
│   └── app/
│       ├── main.py             # 应用入口，挂载所有模块路由
│       ├── core/modules.py     # 模块注册表（后端侧）
│       └── api/                # 每个模块一个占位路由
├── frontend/                   # React + Vite + Ant Design
│   └── src/
│       ├── app/                # 主题 Provider、路由
│       ├── components/layout/  # 侧边栏 + 顶栏外壳
│       ├── components/ui/      # 占位页通用组件
│       ├── lib/                # 品牌、模块注册表、API 客户端
│       └── pages/              # 每个模块一个页面（当前为占位）
└── requirements.txt
```

## 启动

后端（端口 8000）：

```bash
cd taobao-workbench
pip install -r requirements.txt
uvicorn backend.app.main:app --reload
```

前端（端口 5173，已配置 `/api` 代理到 8000）：

```bash
cd taobao-workbench/frontend
npm install
npm run dev
```

访问 http://127.0.0.1:5173

## 如何添加一个功能

1. **后端**：在 `backend/app/api/` 新建/修改对应模块的路由（如 `products.py`），在
   `backend/app/main.py` 挂载。
2. **前端**：把 `frontend/src/pages/<模块>-page.tsx` 的占位页换成真实页面，在
   `frontend/src/lib/api.ts` 添加接口函数。
3. **导航**：新模块在 `frontend/src/lib/modules.ts` 和 `backend/app/core/modules.py`
   各注册一条，侧边栏与接口自动出现。

## 品牌

名称、标语、主题色集中在 `frontend/src/lib/brand.ts`，改一处全局生效。
