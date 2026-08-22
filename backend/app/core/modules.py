"""淘宝运营工作台 · 模块注册表。

新模块加在这里，并在 backend/app/main.py 里挂载对应的路由，
前端会自动出现在侧边栏（frontend/src/lib/modules.ts 同步一份）。
"""

from __future__ import annotations


MODULES: list[dict[str, str]] = [
    {"id": "dashboard", "name": "总览", "description": "店铺核心指标一屏总览", "icon": "dashboard"},
    {"id": "stores", "name": "店铺管理", "description": "多店铺绑定、健康状态、授权管理", "icon": "shop"},
    {"id": "products", "name": "商品管理", "description": "商品库、上下架、价格库存、批量操作", "icon": "product"},
    {"id": "gifts", "name": "礼品单", "description": "礼品订单列表、发货、售后、批量处理", "icon": "order"},
    {"id": "ai", "name": "AI 助手", "description": "AI 对话：问数据、写文案、给建议", "icon": "robot"},
    {"id": "customers", "name": "客户管理", "description": "客户画像、复购分析、私域运营", "icon": "customer"},
    {"id": "analytics", "name": "数据洞察", "description": "流量、转化、销售趋势分析", "icon": "analytics"},
    {"id": "promotions", "name": "推广管理", "description": "直通车/引力魔方/万相台推广计划", "icon": "promotion"},
    {"id": "content", "name": "内容运营", "description": "素材库、内容创作、AI 图文/短视频", "icon": "content"},
    {"id": "monitoring", "name": "竞品监控", "description": "关键词/店铺/商品监控与快照", "icon": "monitor"},
    {"id": "tasks", "name": "系统任务", "description": "后台任务状态、执行历史与重试", "icon": "task"},
    {"id": "model-configs", "name": "模型配置", "description": "AI 模型接入（OpenAI 兼容 / 阿里云百炼等）", "icon": "api"},
    {"id": "settings", "name": "设置", "description": "系统设置与偏好", "icon": "settings"},
    {"id": "profile", "name": "个人中心", "description": "个人资料、头像与密码管理", "icon": "profile"},
    {"id": "accounts", "name": "账号管理", "description": "账号权限、角色与模块可见范围管理", "icon": "accounts"},
    {"id": "logs", "name": "操作日志", "description": "全模块操作审计记录", "icon": "logs"},
]


def get_modules() -> list[dict[str, str]]:
    return list(MODULES)
