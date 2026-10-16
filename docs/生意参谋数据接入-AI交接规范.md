# 生意参谋数据接入 · AI 交接规范

> 用途：把「如何接入生意参谋数据」这件事完整交接给另一个 AI，让它能独立实现或扩展。
> 参照实现：`backend/sycm_cli/`（MIT 协议，Copyright (c) 2026 rakei076）。
> 本文档所有参数均取自该实现的真实代码，不是推测值。

---

## 0. 怎么用这份文档

分两种情况，按需取用：

| 场景 | 取用内容 |
| --- | --- |
| **A. 在另一个项目从零实现接入层** | 先让目标 AI 读「第 2 节 技术规范」，再投喂「第 1.1 节 提示词 A」 |
| **B. 在本项目里新增数据维度/页面** | 直接投喂「第 1.2 节 提示词 B」（它已包含读代码的指令） |

两段提示词都是**自包含**的，可以直接整段复制粘贴。**技术规范那部分必须一并给它**——提示词里假设它已读过规范。

---

## 1. 可直接投喂的提示词

### 1.1 提示词 A：从零复刻接入层

```text
任务：在 <目标项目路径> 里实现生意参谋（sycm.taobao.com）数据接入层。

【已确定的方案，不要改成别的路线】
不要用 Selenium / Playwright / Puppeteer 去模拟页面点击抓 DOM。
采用「借浏览器登录态 + 伪造 TLS 指纹直调平台内部 API」方案，理由与实现细节见你已读到的
《生意参谋数据接入 · AI 交接规范》第 2 节。

如果你手上没有那份规范，按下面三条硬约束实现（这三条不可协商）：
1. 用 curl_cffi 发请求，必须 impersonate="chrome120"。普通 requests 的 TLS 特征会被平台识别为脚本。
2. 登录态必须来自真实浏览器，通过 CDP 取已解密 cookie；禁止把用户浏览器的 Cookies 文件整个拷走或解密。
3. 必须有限速、风控嗅探、夜间禁跑三道护栏。没有护栏的实现视为未完成。

【交付物清单】
- auth 模块：CDP 取 cookie + 登录态档案存取（含多店铺命名档案）
- 请求模块：带护栏的 GET 封装，返回解析后的业务 JSON
- 通用探测命令：能对任意 sycm 接口路径发一次请求并打印原始 JSON
- 页面预设注册表：把你实际要用的页面注册成命名 preset
- 字段码字典：字段码 → 中文名 / 格式化方式 / 适用命令，每条带实测日期
- 一份 README 说明如何绑定登录态和排障

【实施顺序，每步都要真跑通再进下一步】
第 1 步：实现 CDP 取 cookie，验证能拿到含 _tb_token_ 的 cookie 字典。
第 2 步：实现 doctor 自检命令，用某一个已知可用接口做一次探测，确认返回非空数据。
第 3 步：实现通用探测命令，然后用它逐个验证你要接的接口。
第 4 步：把验证通过的接口登记为 preset，写清 path / orderBy 或 indexCode / referer。
第 5 步：接入你的业务存储。

【验收标准】
1. doctor 通过，探测接口返回的 count 或记录数不为 0
2. 每个登记的 preset 都真实返回过数据，不允许拿占位数据冒充已接通
3. 模拟响应里出现「滑块」二字时，程序立即中止而不是继续重试
4. 登录态失效时输出人类可读的中文提示，不抛裸堆栈
5. 源码与仓库里不出现任何真实 cookie / token

【必须写进代码注释的内容】
每接入一个接口，注释里记录：抓包日期、该接口认哪些参数、哪些参数传了没用、
响应里数据在哪个字段路径。这些记录是半年后平台改版时唯一能救命的东西。
```

### 1.2 提示词 B：在本项目里扩展新数据维度

```text
任务：在 D:/demo 项目里新增生意参谋的 <目标数据维度> 接入。

先做这三件事，不要直接开始写代码：
1. 读 backend/sycm_cli/sycm_cli.py，重点看 LIST_PRESETS 注册表（约 492-632 行）
   和 _api_get 函数（约 394 行）——理解现有的两代参数风格。
2. 读 backend/sycm_cli/fields.json，看目标维度涉及的字段码是否已在字典里。
3. 读 backend/app/core/sycm.py，理解后端是怎么通过 subprocess 调 CLI 的。

然后按这个流程做：
第 1 步：跑 `python backend/sycm_cli/sycm_cli.py menu --raw` 拿完整菜单地图，
        定位目标数据在生意参谋的哪个页面，记下 menuPath。
第 2 步：打开该页面，用浏览器开发者工具的 Network 面板录下页面发出的 XHR，
        拿到真实请求的 path、参数、Referer。
        ⚠️ 注意：时间选择器停在「实时」档时录到的接口，往往和选「日/7天/30天」档
        打的是完全不同的接口。录的时候要把时间档切到你真正要用的那一档。
第 3 步：用通用探测命令验证：
        `python backend/sycm_cli/sycm_cli.py --store <店名> api <path> --param k=v --referer <页面URL>`
        确认能拿到预期字段。参数一个个加，加到返回数据对为止。
第 4 步：把验证通过的接口登记进 LIST_PRESETS，字段填全
        （path / orderBy / referer / param_style / list_path / total_path / show）。
第 5 步：如果用到新字段码，补进 fields.json，note 字段里写实测日期和结论。
第 6 步：在 backend/app/core/sycm.py 加一个 fetch_xxx 函数，
        内部用 _run_api_json 调 CLI，再做业务字段映射。

【约束】
- 只改与本次目标相关的文件，不要重构无关模块。
- 不确定的接口行为不要猜，先探测；探测不了就在注释里标注「未实测」。
- 不允许用占位数据或假数据让功能「看起来通了」。
- 每次请求之间保持 1.8-3.5 秒间隔，这是硬要求。

完成后告诉我：改了哪些文件、每个接口的实测结果、还有哪些没验证到。
```

---

## 2. 技术规范（实现依据）

### 2.1 认证层：从浏览器借登录态

**Windows 主路径（CDP）**

1. 启动一个**独立的** Chrome/Edge 实例，与用户日常浏览器完全隔离：
   - `--user-data-dir=%LOCALAPPDATA%\sycm-cli\chrome-profile`
   - `--remote-debugging-port=<随机空闲端口>`（用 bind 到 127.0.0.1:0 取端口）
   - `--remote-debugging-address=127.0.0.1`、`--remote-allow-origins=*`
   - `--no-first-run`、`--no-default-browser-check`、`--new-window`
   - 打开 `https://loginmyseller.taobao.com/`（卖家后台统一登录入口，登录后落在 taobao.com 域）
2. 启动前先清理：删除上一轮的端口文件与登录标记文件；用
   `Get-CimInstance Win32_Process` 按命令行里的 profile 路径匹配并结束残留进程
   （只杀占用该专用 profile 的，不能误杀用户日常浏览器）。
3. 取 cookie：`GET http://127.0.0.1:<port>/json/list` 拿 `webSocketDebuggerUrl`，
   连 WebSocket 后发 `{"id":1,"method":"Network.getAllCookies"}`，
   从 `result.cookies` 取。**这是浏览器已解密后的内存态，不涉及解密用户数据库。**
4. 过滤与优先级：只保留 domain 含 `taobao.com` 的；两遍写入，
   先写非 `sycm.taobao.com` 域，再写 `sycm.taobao.com` 域，让目标站点同名 cookie 生效。
5. 登录成功判定：cookie 字典里存在 `_tb_token_`。
   轮询间隔 2 秒，超时默认 300 秒。
6. CDP 探测超时 15 秒；WebSocket 连接 `timeout=5`。

**macOS 路径**：`browser_cookie3.chrome(domain_name="taobao.com")`，
筛选 domain 含 `taobao.com` 的 cookie。

**登录态档案（多店铺隔离）**

- 目录：`~/.taobao-cli/profiles/`，可用 `TAOBAO_CLI_PROFILE_DIR` 覆盖
- 文件：`<店名>.json`，结构
  `{"store": 店名, "domain": "taobao.com", "saved_at": ISO时间, "cookies": {...}}`
- 权限：目录 0700、文件 0600
- 店名校验：不允许含 `/` `\` `..`，不允许以 `.` 开头
- 读取时校验 `_tb_token_` 存在，否则报「保存时可能未登录，请重新导出」
- 后端约定用 `store_<店铺ID>` 作为档案名
- 三种写入档案的方式：`export-profile`（弹窗登录）、`export-default`（读现有浏览器，不弹窗）、
  `import-cookies`（粘贴 cookie，不弹窗）

### 2.2 请求层

| 项 | 值 |
| --- | --- |
| HTTP 库 | `curl_cffi.requests`，`impersonate="chrome120"` |
| 基址 | `https://sycm.taobao.com` |
| 相对路径前缀 | `/csp/api/`（绝对路径以 `/` 开头则不拼） |
| 单请求超时 | 15 秒 |
| User-Agent | `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36` |
| Referer | 必须是目标页面真实 URL，缺省为 `https://sycm.taobao.com/qos/service/frame/performance/detail/new` |
| Accept | `application/json, text/plain, */*` |
| Accept-Language | `zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7` |
| 必备查询参数 | `_` = 当前毫秒时间戳；`token` = cookie 里 `_tb_token_` 的值 |

**必须清掉代理环境变量**：`HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` 及其小写形式。
否则 curl 会走无效代理，报 `curl: (7) Could not connect`。这个坑在代理环境里必踩。

### 2.3 护栏参数（照抄这些数值）

```
MIN_DELAY_SEC        = 1.8      每次请求前随机 sleep uniform(1.8, 3.5)
MAX_DELAY_SEC        = 3.5
夜间禁跑              = 1:00 - 6:00 直接拒绝；绕过用 SYCM_BYPASS_CURFEW=1
RISK_KEYWORDS        = 滑块 / 验证码 / 操作过于频繁 / 请重新登录 / 异常请求 / 风控
                      响应正文命中任一关键词 → 立即抛 RiskTriggered 停止（进程退出码 2）
MAX_RETRIES          = 2        （env SYCM_RETRIES）
RETRY_BASE_SEC       = 1        请求异常/5xx 时指数退避 1s、2s
上层退避              = 10s / 30s / 120s + 最多 20% 抖动（仅瞬时错误，登录错误不重试）
REQUEST_SOFT_WARN_AT = 200      发满 200 次在 stderr 提醒一次，不中断
硬上限                = 默认无；可用 env SYCM_REQUEST_LIMIT 设数字
```

**业务层校验**（HTTP 200 不代表成功）：
- `payload["success"] is False` → 抛错，带上 `code` 和 `message`
- `payload["code"]` 不在 `(None, 0, 200, "0", "200")` → 抛错

**进程退出码约定**：风控触发 `exit 2`，其他错误 `exit 1`，Ctrl+C `exit 130`。
stdout 只输出 JSON（给上层解析），人类可读信息一律走 stderr。

### 2.4 接口层：两代参数风格

**风格一 sycm-v1 —— 老 `/csp/api/*` 列表接口**

```
GET /csp/api/<path>?orderBy=<排序字段>&bizCode=<业务码>&startDate&endDate&page&pageSize
```
- `orderBy` 是找列表的关键参数，**漏了大多返回 0 条**
- 取值路径默认 `data.dataSource`，总数默认 `data.count`

**风格二 cc-v2 —— 新接口族（`/cc/*`、`/flow/*`、部分 `/csp/api/*`）**

```
GET <path>?indexCode=<逗号分隔的指标码>&compareType=cycle&device=0&cateId=0&startDate&endDate
```
- `indexCode` 指定要哪几列指标；`compareType=cycle` 拿环比
- 行数据是 `{value, cycleCrc, syncCrc}` 对比结构，取值要取 `value`
- 取值路径常见 `data.data`（分页信封），总数 `data.recordCount`
- **窗口宽度只认 1 / 7 / 15 / 30 天**，其他宽度服务端返 `code=1003` 拒绝

**已验证的 preset 举例**（可直接作为起点）

| preset | path | 风格 | 说明 |
| --- | --- | --- | --- |
| sale-shop-list | `shop/sale/analysis/list` | v1 | 店铺商品销售排行，orderBy=itemId |
| item-list | `/cc/item/view/top.json` | cc-v2 | 商品排行，orderBy=payAmt，固定返 41 字段 |
| cate-list | `/cc/cockpit/marcro/cate.json` | cc-v2 | 品类 360，list_path=`data` |
| new-product-list | `/cc/new/product/item/list.json` | cc-v2 | 新品追踪，list_path=`data.data` |
| reception-list | `ww/consultation/detail/list` | v1 | 旺旺咨询接待明细 |
| refund-item-list | `shop/refund/item/list` | v1 | 退款商品明细 |

**发现新接口的标准流程**：`menu` 命令拿完整菜单地图 → 浏览器 Network 面板录 XHR →
`api` 通用命令探测 → 登记为 preset。

### 2.5 字段码字典 `fields.json`

182 条记录，每条结构：

```json
"payAmt": {
  "cn": "支付金额",
  "scope": ["home-table", "item-list", "..."],
  "fmt": "amt",
  "status": "verified",
  "note": "支付组 ｜ 2026-08-06 /cc/item/archive/profile.json 客群洞察实测：..."
}
```

- `cn` 中文名，`scope` 该字段在哪些命令/页面可用，`fmt` 格式化方式（amt/int/…）
- `status` 标记验证状态；`note` 记录实测日期与结论
- **新字段必须写实测 note**，这是字典的价值所在

### 2.6 后端集成（若目标项目是 FastAPI 这类服务）

参照 `backend/app/core/sycm.py`：

- **用 subprocess 调 CLI，不要 import**。收益：CLI 崩溃/卡死/依赖冲突不影响主服务，
  超时能干净截断。调用形式 `[python, sycm_cli.py, *args]`，`cwd` 设为 CLI 所在目录，
  环境变量注入 `SYCM_BYPASS_CURFEW=1`、`PYTHONIOENCODING=utf-8`、`PYTHONUTF8=1`
  （中文 Windows 控制台默认 GBK，不设会乱码）。
- CLI 输出 JSON 到 stdout，后端 `json.loads` 解析后做业务映射。
- **进程内抓取互斥**：全局 `threading.RLock()` 包住整个 subprocess 调用，
  避免「用户手动点同步」和「后台定时同步」同时打平台接口。
- **登录失效熔断**：以档案文件的 `(mtime_ns, size)` 作为指纹。
  登录错误 → 记录 `(指纹, 错误消息)`；下次调用前若指纹未变则直接快速失败，
  档案一旦变化（用户重新登录）自动解除。
- **错误翻译**：把 CLI 的英文/技术错误映射成用户可读中文，
  例如「You must login」→「登录已失效，请重新打开浏览器登录」。

---

## 3. 已知的坑（务必转告接手方）

1. **同一页面不同时间档位打的是不同接口**。时间选择器停在「实时」时录到的接口，
   切到「日/7天/30天」后完全不用。录包前先确认时间档。
2. **`/cc/item/portal/itemList.json` 不认 `indexCode`**，无论传几个指标都只返回
   `itmUv/payAmt/payRate` 三个字段。历史档要用 `/cc/item/view/top.json`。
3. **`/cc/item/view/top.json` 同样不认 `indexCode`**，固定返回 41 个字段。
   传它只是为了贴近页面真实请求形态，别指望它按需筛列。
4. **`orderBy` 漏传会导致列表返回 0 条**，且不报错，容易误判为「没权限」。
5. **cc 系接口窗口宽度只认 1/7/15/30 天**，其他宽度一律 `code=1003`。
6. **代理环境变量会让请求报 `curl: (7)`**，接入前先清 `*_PROXY`。
7. **中文 Windows 控制台是 GBK**，带 emoji 的帮助文本会让程序崩，
   需要 `sys.stdout.reconfigure(errors="replace")`。
8. **新登录态首次请求偶发风控**，需要间隔几秒重试几次再判定失败。

---

## 4. 现成实现的位置（可直接引用的资产）

```
backend/sycm_cli/
├── sycm_cli.py      # 主 CLI：认证 / 请求 / preset 注册表 / 通用探测
├── sycm_item.py     # 商品 360 相关命令，import sycm_cli 复用底层
├── fields.json      # 182 条字段码字典（含实测 note）
├── LICENSE          # MIT，Copyright (c) 2026 rakei076
└── requirements.txt # browser-cookie3>=0.20 / curl-cffi>=0.7 / websocket-client>=1.8

backend/app/core/
├── sycm.py              # 后端适配层：subprocess 调用 + 业务映射
├── scrape_guard.py      # 进程内抓取互斥
└── scrape_resilience.py # 退避重试 + 登录熔断
```

若目标项目直接复用这份 MIT 代码：**允许**（MIT 可改、可商用），
但必须保留原有的版权声明与 LICENSE 文件。

---

## 5. 一句话总结给对方

不要模拟点击，用 curl_cffi 伪装指纹直调内部接口；
登录态通过 CDP 从独立浏览器实例借，不碰用户日常浏览器；
所有请求之间随机停 1.8–3.5 秒，遇到风控关键词立刻停；
每接入一个接口都把实测结论写进注释——这是唯一能对抗平台改版的东西。
