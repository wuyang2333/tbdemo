# 分享包说明（给朋友用）

> 本包已剔除所有私人数据：真实数据库、日志、缓存、凭据都不在里面。
> 朋友拿到的是一个"全新演示版"：首次启动自动生成演示店铺/礼品单，第一个注册的账号自动成为超级管理员。

## 朋友怎么跑

### 方式 A：有 Python 3.12 / Node 20+

```bash
cd taobao-workbench
pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

另开一个终端：

```bash
cd taobao-workbench/frontend
npm install
npm run dev
```

打开 http://127.0.0.1:5173 ，先注册一个账号（第一个注册的自动成为超级管理员）。

### 方式 B：用 Codex / 其他 AI 助手

把项目路径告诉它，让它"把项目跑起来"，它会自动处理依赖。

## 注意

- `start.bat` / `stop.bat` 里的路径是作者机器的（`D:\demo`、个人 Python 路径），朋友需要按自己机器修改，或直接用手动方式跑。
- 推送配置（pushplus / webhook）默认是空的，朋友需要自己填。
- 想重置成全新状态：删掉 `backend/data/taobao.db`，重启后自动重建演示数据。
- 想用自己的真实数据：把你自己实例的 `backend/data/taobao.db` 放回 `backend/data/` 即可（数据库结构一致）。
- 生意参谋/万相台实时数据需要登录档案（`~/.taobao-cli/profiles/`），朋友没有档案时同步会提示"生意参谋未登录"，不影响其余功能。
