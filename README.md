# LeisureLog

本地娱乐活动自动记录与分析系统，逐步扩展的本地 MVP。采用 **模块化单体**：一个进程、一套 SQLite 数据库，模块按职责分开，后续优先扩展接口实现而不是堆叠条件分支。

已实现：ActivityWatch 前台窗口、AFK 与网页数据读取、统一 ActivityEvent / Session、原始数据版本留存、SQLite、Alembic 迁移、FastAPI、自动同步、Session 合并、AFK 时长扣除、配置分类、人工覆盖、可持久化的识别规则、基础分类汇总、本地活动查看页面、作品与内容库及名称管理；Playnite 本地导出 Adapter、游戏目录与可插拔游戏分类器已完成真实安装和游戏库接入。已核对现有历史游玩记录；游戏统计、主类型与补充标签管理、月度/年度偏好分析已完成。同步及本次记录纠错已支持受影响范围增量重建，日视图和明细列表使用数据库范围查询/分页。AI 分类和手机端暂未实现。

## 快速运行（Windows PowerShell，Python 3.11+）

在本 README 所在目录打开终端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
Copy-Item .env.example .env
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn leisurelog.main:create_app --factory --host 127.0.0.1 --port 8000
```

如果 `.venv`、依赖和数据库已经准备好，只需运行最后一条启动命令。依赖范围在 `pyproject.toml`，当前验证环境的精确依赖版本另存于 `requirements-lock.txt`；重建同一环境可先 `pip install -r requirements-lock.txt`，再 `pip install --no-deps -e .`。精确版本文件针对本次 Windows / Python 3.13 环境，其他 Python 版本优先使用 pyproject 中的兼容范围。

- 交互接口文档：http://127.0.0.1:8000/docs
- 活动查看首页：http://localhost:8000/（本机当前服务使用 8001，见下方说明）
- 健康检查：http://127.0.0.1:8000/health
- SQLite 默认文件：`data/leisurelog.db`
- 不自动建表、不在应用启动时偷偷改表；必须先执行迁移。
- 所有相对路径以运行目录为基准，请从项目根目录启动。环境变量优先于 `.env`。
- 服务默认只监听本机；这一阶段不包含账号系统或互联网部署配置。

## 日常使用：双击启动（2026-10-02）

项目根目录有几个可以直接双击的文件（第一次使用仍需先按上面的“快速运行”建好 `.venv` 并执行迁移）：

| 文件 | 作用 |
|---|---|
| `start-leisurelog.bat` | 后台启动 LeisureLog（端口 8001，不留黑窗口）并打开首页；已经在运行时只打开首页 |
| `stop-leisurelog.bat` | 停止 8001 上的 LeisureLog；只会结束健康检查确认是 LeisureLog 的进程 |
| `restart-leisurelog.bat` | 停止后重新启动（更新代码后用；只改 `config/rules.yaml` 时用页面上的“重新读取规则文件”即可） |
| `autostart-on.bat` / `autostart-off.bat` | 开启 / 关闭登录 Windows 后自动在后台启动（在“启动”文件夹放一个快捷方式，不需要管理员权限） |

运行日志写在 `data/logs/server.out.log` 和 `server.err.log`，每次启动覆盖。脚本本体是 `scripts/leisurelog.ps1`，也支持 `-Action status`。ActivityWatch 需要单独设置开机自启。启动脚本不会自动执行数据库迁移；版本不对时会提示运行 `alembic upgrade head`。

## 待分类页面

打开 http://127.0.0.1:8001/unclassified（导航“待分类”，或首页时间带图例里的“未分类”）。按应用列出全部历史中的未分类时长、片段数和常见窗口标题；选一个分类（游戏、视频等可同时填写内容名称）后保存，会生成一条“这个应用的所有活动”识别规则并完整重新处理，以前和以后的记录都会归入该分类。

- 只保存规则，不把记录标成人工修改；已有的人工分类仍然优先。规则可在首页“数据与设置 → 已记住的规则”删除，删除后恢复未分类。
- 浏览器（Chrome、Edge 等）单独列出，不能整体分类（接口返回 422），请在活动详情里按网站域名记住。列表显示各浏览器有网址的片段比例；没有网址通常表示该浏览器尚未安装 ActivityWatch Web Watcher 扩展。
- 接口：`GET /api/unclassified`，`POST /api/classification/app-rules`（`source`、`app`、`category`、可选 `content`）。

## 数据接入

先独立安装并运行 ActivityWatch，让窗口 watcher 正常采集。LeisureLog 只通过 HTTP GET 读取，不修改 ActivityWatch 数据库。

默认数据源地址为 `http://127.0.0.1:5600`。修改 `.env` 中的 `LEISURELOG_ACTIVITYWATCH_URL` 可切换地址。调用示例：

```powershell
$body = @{
  start = '2026-09-29T00:00:00+08:00'
  end = '2026-09-30T00:00:00+08:00'
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/sync/activitywatch' -ContentType 'application/json' -Body $body
Invoke-RestMethod 'http://127.0.0.1:8000/api/events?limit=100&offset=0'
Invoke-RestMethod 'http://127.0.0.1:8000/api/sessions'
```

可加 `buckets: ["aw-watcher-window_你的电脑名"]` 显式选择。默认选择全部 `currentwindow` 类型 bucket，并读取同一 hostname 的 `afkstatus` bucket。AFK 状态单独保存，不进入应用事件列表；同时读取 web.tab.current 网页 bucket，网页信息仅补充前台窗口，不独立累计时长。时间必须带时区，单次窗口大于零且不超过 7 天；历史导入可分段调用。内部统一保存 UTC，保留事件完整边界，不按请求窗口裁剪源事件。同步返回的 fetched / changed 包含窗口、AFK 和网页三种来源记录，events 仅统计窗口事件。

**自动采集由 ActivityWatch 负责；LeisureLog 启动后默认每 60 秒自动同步。** 首次启动补取最近 24 小时；后续从数据库保存的成功进度回看 10 分钟，接收仍在延长的 heartbeat。停机后按一天一个窗口补取，失败窗口不推进进度，下轮重试。可以重复同步同一个时间段。同一来源 / bucket / event ID 的重复数据不会重复计数；源事件被 heartbeat 延长时会新增原始快照并更新统一事件。同步区间外发生的旧数据更改，需要重新同步对应区间。尚不跟踪源端删除。

自动同步随 LeisureLog 服务运行和停止，不是 Windows 开机启动任务。默认使用一个 Uvicorn worker；多进程启动会各自启动调度器，暂不支持多 worker 调度。通过 `GET /api/sync/status` 查看是否启用、是否正在执行、最近成功时间、导入数量和失败状态；状态在内存中，成功进度保存在 `sync_checkpoints` 表中。错误不会让服务退出；恢复 ActivityWatch 后下一轮自动重试。

配置项见 `.env.example`：`AUTO_SYNC_ENABLED`、`AUTO_SYNC_INTERVAL_SECONDS`、`AUTO_SYNC_OVERLAP_SECONDS`、`AUTO_SYNC_INITIAL_HOURS`（均需 `LEISURELOG_` 前缀）。设置 `LEISURELOG_AUTO_SYNC_ENABLED=false` 可关闭自动同步。修改后重启服务。当前迁移版本为 `0011`，已有数据库升级前先停止旧后端，再执行 `alembic upgrade head`。从 AFK 迭代之前升级时，请手动重新同步需补齐 AFK 的历史时间段（每次最多 7 天）；仅增量同步不能补齐此前的全部 AFK 历史。本机已补取最近一天。

本机新版服务运行在 `http://127.0.0.1:8001`，最初因旧服务占用 8000 而使用该端口。查看新版文档使用 `http://127.0.0.1:8001/docs`；手动重新启动可用上述命令的 `--port 8001`。旧版后端的健康检查不认识新版迁移，升级后应使用新版后端（当前 0011）。

## 本地活动查看页面

打开 **http://localhost:8001/** 查看当前运行的首页。页面由同一个 FastAPI 服务提供，不需要单独启动前端、安装 Node.js 或访问第三方字体和资源。

- 默认展示北京时间今天的记录；可选择日期、前一天、后一天或回到今天。
- 按应用、分类和窗口标题搜索筛选，顶部汇总随筛选变化。显示原始记录时长、已扣除 AFK、扣除后时长与状态待确认时长。
- 每页 50 条，最近活动在前。页面每分钟刷新列表与同步状态；详情打开时暂停刷新列表。
- 点击“查看”可核对组成 Session 的窗口事件及相关 AFK 状态。列表跨午夜记录按当天边界裁剪，并重新计算时间交集；AFK 状态详情展示原始区间，并注明只扣除重叠部分。
- 无记录、无匹配结果或后端不可达时给出提示。缺少 AFK 状态的时间保留并单独标记。
- 点击活动“查看”后可直接纠正分类，填写内容名称和逗号分隔的标签，或“恢复自动分类”。保存后列表、筛选和统计立即更新，列表显示人工标记。
- 修改作用于详情中当前显示的活动事件；跨日事件会同时影响其他日期部分。默认只修改本次记录，也可在“自动识别范围”中选择记住规则。批量人工修改、保存规则和重建在一个事务内完成；任一事件无效或保存失败都整体回滚。

静态资源位于 `src/leisurelog/api/static/`，界面只调用本地 API。日期筛选及当天时长重算位于 `analytics/query.py`，避免将计算政策写进前端。展示查询在一致的数据库读事务中获取事件、Session 和 AFK 状态。

## 目录与依赖边界

```text
LeisureLog/
├── config/rules.yaml          # 有序分类规则
├── migrations/               # Alembic 迁移，当前版本 0011
├── src/leisurelog/
│   ├── domain/               # 纯 Python 实体、接口、分类优先级、Session 策略
│   ├── adapters/             # ActivityWatch HTTP、YAML 规则分类器、Playnite 本地导出
│   ├── services/             # 同步、重处理、人工覆盖用例
│   ├── repositories/         # SQLAlchemy 模型、SQLite 实现、事务基础设施
│   ├── analytics/            # 只读汇总计算
│   ├── api/                  # 请求验证、路由、事务依赖
│   ├── config.py             # 环境配置
│   └── main.py               # 组装具体实现与应用生命周期
├── tests/                    # 隔离临时数据库 + 模拟上游 HTTP
├── pyproject.toml
└── alembic.ini
```

```text
ActivityWatch → Adapter → SourceRecord(ActivityEvent + 原始 payload)
                              ↓
API → services → domain 接口 ← repositories 的 SQLite 实现
          ↓
     人工覆盖 → 可插拔 Classifier 链 → unknown
          ↓
     Session 合并 → 持久化 → analytics → API
```

约束：domain 不导入 FastAPI、SQLAlchemy、httpx；services 依赖 domain 中的 Repository / ActivitySource / Classifier / LibraryStore 协议；analytics 定义只读查询并通过协议获取数据库汇总；具体实现由 main 和 API 事务依赖组装，API 负责提交和回滚。新增来源实现 ActivitySource，新增分类器实现 Classifier，然后在组装入口注册。不要让业务层识别具体 watcher 的 JSON。

## 数据结构与重处理

| 表 | 职责 |
|---|---|
| raw_events | 保存源 payload、源 metadata、接收时间及内容哈希；应用只追加快照，不覆盖已有版本 |
| activity_events | 当前统一事件，含 source、stream、device、起止时间、app、title、url、分类结果，指向所用 raw 快照 |
| idle_events | 独立的 afk / not-afk 状态，关联自己的原始快照；不参与娱乐分类 |
| manual_overrides | 针对稳定事件 ID 的人工分类，独立于自动结果 |
| sessions | 当前合并结果，可重新生成；记录实际 active_seconds |
| session_events | Session 与统一事件的可追溯关联 |
| content_items | 持久化作品展示名称、分类、备注；不随重处理清空 |
| content_aliases | 应用、分类、识别名称对应作品；唯一约束、支持合并和拆分 |
| game_snapshots | 只追加 Playnite 游戏资料源快照；相同内容重复导入不新增快照 |
| game_catalog | 从最新成功导出得到的当前游戏资料与进程匹配条件 |
| game_type_overrides | 按稳定游戏键保存人工主类型与补充标签，独立于可替换的游戏目录 |

原始数据与处理数据分表。同一源事件通过稳定 ID 幂等更新；原始内容改变时留下新版本。一次同步和派生结果替换在同一 SQLite 事务内完成，失败时整体回滚；`BEGIN IMMEDIATE` 串行化写入，避免并发重建相互覆盖。

`POST /api/reprocess` 从已保存的统一事件重新分类和合并，不需要访问 ActivityWatch，不会删除人工覆盖或原始快照。当前尚无“更换 Adapter 后从原始快照重新标准化”的专用用例，原始数据已为此保留。修改规则文件后重启服务，再调用重处理；错误规则在启动时校验失败，不悄悄忽略。

未来模型变更：修改 ORM → `alembic revision --autogenerate -m "说明"` → 人工检查迁移 → `alembic upgrade head`。初始迁移是独立冻结的 schema，不引用随开发变化的 ORM 来创建表。升级部署同步更新健康检查中的预期版本。

## 分类规则与人工覆盖

优先级固定为 **人工覆盖 > 用户记住的规则 > 注册的分类器（当前为 YAML 规则） > unknown**。示例规则见 `config/rules.yaml`。支持 app 精确匹配、domain 及其子域匹配、title_contains 子串匹配；大小写不敏感，同一条规则中的条件全部满足才命中，第一条命中的规则生效。每个规则必须有唯一 ID 和至少一个匹配条件。分类记录 `origin`，便于判断是人工、哪条规则或 fallback。

修改 `config/rules.yaml` 后不必重启：在首页“数据与设置 → 重新读取规则文件”（`POST /api/classification/reload-rules`），会校验文件、按新规则完整重新处理全部历史，并同时更新后台自动同步使用的规则；文件有错误时返回 422，原规则继续生效。

浏览器没有网址时（例如 Edge 未安装 Web Watcher），网址规则无法命中。`rules.yaml` 在网址规则之后提供按窗口标题匹配的备用规则（哔哩哔哩漫画/视频、YouTube、哔哩哔哩其他页面），内容名称提取与网址规则一致；浏览器里打开的 LeisureLog 页面归入“其他”。

```powershell
$events = Invoke-RestMethod 'http://127.0.0.1:8000/api/events'
$id = $events[0].id
$override = @{ category = 'game'; content = '我的游戏'; tags = @('RPG') } | ConvertTo-Json
Invoke-RestMethod -Method Put -Uri "http://127.0.0.1:8000/api/events/$id/override" -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($override))
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/reprocess'
```

单条覆盖仅针对一个事件。页面批量保存可另含 `remember_scope`，支持 `app`、`title`、`domain`：

- `app`：来源与应用精确匹配，应用名大小写不敏感，适合用途固定的应用。选择浏览器意味着所有网页都使用此分类，界面明确提示。
- `title`：同一来源、同一应用、完全相同的原始标题，标题大小写敏感；标题变化不会匹配。
- `domain`：同一来源、同一应用、完全相同的 URL hostname，域名大小写不敏感，不自动包含其他子域名。没有 URL 时不可选择；当前窗口 watcher 多数记录没有 URL。

规则保存到独立 `learned_rules` 表，`LearnedRuleClassifier` 实现可插拔 Classifier 接口，由 ProcessingService 在每次重建时从 Repository 加载，因此同步、重新处理和服务重启都会使用最新规则。匹配不限制设备，同一来源的同应用可复用。具体标题或域名优先于整个应用；同等精度按最近保存顺序决定，更新同一匹配条件会替换规则，而非产生重复规则。来源标记 `learned`。

保存规则立即重新分类全部已有匹配记录，并用于未来导入；所有单独的人工覆盖仍然优先。主页“已记住的规则”可以查看和删除；删除会重建自动分类，但保留人工覆盖与原始数据。修改已有规则可以再次在活动详情中选同一识别范围保存。

删除覆盖：`DELETE /api/events/{id}/override`，会恢复自动分类并重建 Session；仍可能命中已记住的规则。若要完全撤回一次纠错，需删除对应规则并恢复相关事件的自动分类。

## Session 语义

- 仅在同一 source / device / stream 内合并，应用、标题、URL、分类（包括来源）必须一致。
- 相邻同类事件间隔不超过配置阈值（默认 60 秒）时合并；中间存在另一种活动会截断。
- Session 的 start/end 表示跨度，`recorded_seconds` 是窗口事件区间的并集，不计合并间隙，不重复计算同一 Session 内重叠部分。
- `afk_seconds` 是窗口记录与同来源、同设备已知 afk 区间的交集；重复 AFK 区间先取并集，不重复扣除。同一时间有冲突状态时 afk 优先。
- `active_seconds = recorded_seconds - afk_seconds`。`unverified_seconds` 是窗口记录中未被任何 AFK 状态覆盖的部分，保留在 active_seconds 中并显式标记；确认 not-afk 的时长可由 active_seconds - unverified_seconds 得到。
- 不延长 AFK 到没有记录覆盖的时间，不把未知设备互相匹配。整段 AFK 的 Session 保留用于核对，active_seconds 为零。离开期间仍可处于同一 Session 跨度，时长计算会扣掉 AFK；当前不按 AFK 强制切分 Session。
- 零时长事件会保留为 ActivityEvent，但不生成 Session。
- 增量处理扩展受影响范围，包含相邻记录及旧 Session 的完整边界，保证跨同步窗口的相邻事件可合并；Session ID 由首事件产生，合并边界变化可能使 ID 改变，所以人工覆盖绑定事件而不是 Session。

已实现 AFK 扣除，但没有浏览器与窗口融合、跨设备排重或跨不同活动 Session 的重叠冲突裁决。汇总的 recorded_seconds_by_category 保持原始窗口时长语义，active_seconds_by_category 为已扣除 AFK 的时长；附带 afk_seconds 和 unverified_seconds。未分类活动仍不应当作娱乐总时长。目前按完整事件标题合并的策略偏保守，窗口标题变化可能切分 Session。

AFK 依据 ActivityWatch 的键鼠输入检测，并不证明使用者实际离开：观看视频、使用手柄时可能长时间没有键鼠输入。当前按 watcher 判断执行扣除，后续需加入内容活动策略。来源状态定义见 [官方数据模型](https://docs.activitywatch.net/en/latest/buckets-and-events.html)，判断实现见 [官方 AFK watcher](https://github.com/ActivityWatch/aw-watcher-afk/blob/master/aw_watcher_afk/afk.py)。

## API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | /health | 数据库迁移状态 |
| POST | /api/sync/activitywatch | 拉取指定时间窗口并处理 |
| GET | /api/sync/status | 自动同步运行状态及最近结果 |
| GET | /api/events | 统一事件，limit / offset 分页 |
| GET | /api/idle-events | AFK 状态记录，limit / offset 分页 |
| GET | /api/sessions | 合并结果，limit / offset 分页 |
| PUT / DELETE | /api/events/{id}/override | 设置 / 删除人工分类 |
| PUT / DELETE | /api/events/overrides | 批量设置 / 删除人工分类；event_ids，PUT 另含 category / content / tags，可选 remember_scope |
| GET | /api/classification/rules | 查看已记住的规则 |
| DELETE | /api/classification/rules/{id} | 删除规则并重建自动分类 |
| POST | /api/reprocess | 对所有统一事件重新分类、合并 |
| GET | /api/games/playnite | 游戏库接入状态、游戏列表和自动识别依据 |
| POST | /api/games/playnite/import | 导入配置的本地 SDK 导出文件，事务内更新目录并重新分类 |
| GET | /api/stats/summary | 基础分类记录时长汇总，附统计口径 |
| GET | /api/dashboard | 北京时间 day、app、category、query 筛选；limit / offset；返回当天汇总和列表 |
| GET | /api/sessions/{id}/details | 必填 day，查看当天活动片段的窗口与 AFK 状态依据 |

输入错误返回 422；不存在的覆盖目标返回 404；上游不可达、无效响应或无效 bucket 返回 502；未迁移的健康检查返回 503。事件/Session 响应含 classification 与时间字段，Swagger 展示输入结构。

## 验证与当前工程边界

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe check
```

测试使用临时数据库和模拟 HTTP，不连接真实 ActivityWatch。覆盖幂等、原始版本留存、人工覆盖持久性、规则恢复、Session 间隙与重叠、活动切换、多设备隔离、时间验证、失败回滚、上游离线、迁移升降级以及 ORM/schema 一致性。真实联调状态见 `VERIFICATION.md`。

普通同步和本次记录纠错已按受影响 source/device/stream 的连续时间范围重建，未变化的数据跳过派生重写。明细列表在 SQL 中分页，日视图只加载重叠当天的记录。完整重处理、全局识别规则变更和游戏目录变更仍使用完整重建，极度碎片化导入也会回退完整重建；详见下方增量处理说明。自动同步先读取上游，再获取数据库写锁；手动同步仍在持有写锁时等待上游响应，大批量写入会阻塞其他写入。数据会包含窗口标题和源提供的 URL，请把 `data/` 当作个人数据保管，默认已加入忽略列表。

ActivityWatch 接口依据：[官方 REST 文档](https://docs.activitywatch.net/en/latest/api/rest.html) 与 [官方服务端实现](https://github.com/ActivityWatch/aw-server/blob/master/aw_server/api.py)。这里通过 Adapter 封装 HTTP，后续可以替换成官方客户端实现，不影响 domain / services。

## Playnite 本地游戏资料接入（2026-10-02）

当前数据库迁移为 **0009**；停止旧服务并执行 `alembic upgrade head` 后运行新版。游戏目录与源快照独立存储，分类优先级为人工覆盖 > 用户记住的规则 > YAML 分类规则 > Playnite 游戏分类器 > unknown。游戏资料不产生时间记录，时长仍来自 ActivityWatch；不叠加 Playnite 或 Steam 的历史累计时间。未安装条目仅用于查看，进程匹配冲突时保持未识别。

Playnite 运行时锁定其 LiteDB 库，采用官方 SDK 连接扩展导出本地 JSON；应用不直接读取或修改该库。2026-10-02 已获用户授权并完成安装、真实导出、网页导入以及后台自动导入验证。源码、安装包生成方法及限制见 [连接说明](integrations/playnite/README.md)。已有资料导出后，每分钟自动同步会读取最新完整文件；也可在首页“Playnite 游戏库”点击“读取最新游戏资料”。读取失败保持最后成功目录，并继续 ActivityWatch 同步。安装包位于 `dist/LeisureLog-Playnite.pext`。

通过启动器启动的游戏，在 `config/playnite-processes.yaml` 配置实际游戏进程；共享进程必须附加标题条件。当前为绝区零、英雄联盟和 Minecraft 提供配置。仅配置了进程并不代表已经验证真实游玩；需要在真实资料导入后检查识别依据和实际活动。没有明确进程的游戏在列表显示“待补充游戏进程”。


## 本地存储与备份

主页“存储与备份”查看全部日期的数据数量、最早/最新记录时间、数据库绝对路径、主数据库/WAL/SHM 的逻辑文件大小及备份目录占用。WAL 是尚未回收的写入日志，主文件大小不能单独代表当前占用；占用会随写入和 checkpoint 改变，不是逐日增长测量。全部日期的活动历史继续保留；可手动整理已被更新版本替代的原始快照，不按日期删除活动，未设置容量上限或自动定时备份。

点击“创建本地备份”使用 SQLite online backup 生成一致快照，无须停止自动同步。随后将快照恢复到独立临时数据库，检查 integrity_check、foreign_key_check、schema、数据库迁移版本和全部业务表的行数与内容哈希。只有验证成功才发布备份文件。失败不会替换或修改运行数据库，未完成输出会清理；同一应用进程内重复备份返回 409。当前仍使用单个 worker。

默认备份位置为数据库旁的 `backups/`。可用 `LEISURELOG_BACKUP_DIR` 指定其他位置。每份保存 `.db` 快照、`.rules.yaml` 配置副本、`.json` 验证报告和包含三者的 `.zip`；不保存账号凭据或整个环境配置。页面下载完整 ZIP，包含：

- `leisurelog.db`：原始快照、ActivityEvent/IdleEvent/Session、人工分类、用户识别规则、同步进度和迁移版本。
- `config/rules.yaml`：配置分类器规则。用户通过页面保存的规则已经在数据库内。
- `verification.json`：恢复验证记录和表数据摘要。

备份覆盖 LeisureLog 已导入的数据，不包含 ActivityWatch 自己的数据库或 LeisureLog 项目程序。备份增加硬盘占用，尚未实现备份自动轮换；默认同盘副本不能应对整块硬盘损坏，可将 ZIP 复制到其他磁盘。界面不会覆盖当前数据库，暂未提供一键原地恢复。

### 恢复到独立位置

1. 将完整 ZIP 解压到一个新的目录，例如 `D:/LeisureLogRestore/2026-09-30/`，避免覆盖现有数据。
2. 使用当前版本的 LeisureLog，在项目目录设置 `LEISURELOG_DATABASE_URL=sqlite:///D:/LeisureLogRestore/2026-09-30/leisurelog.db`，`LEISURELOG_RULES_PATH=D:/LeisureLogRestore/2026-09-30/config/rules.yaml`，先设置 `LEISURELOG_AUTO_SYNC_ENABLED=false`。
3. 在该配置下执行 `alembic upgrade head`，再用空闲端口启动服务。确认健康检查、活动记录、人工分类和识别规则；使用不同数据库路径，不复制到正在运行的主库旁，也不带入旧库 WAL/SHM 文件。
4. 恢复核对成功后再决定切换主服务和开启同步；恢复后的同步进度以备份时刻为准，之后会补取 ActivityWatch 仍保留的活动。

新增 API：`GET /api/storage` 查看占用与备份列表，`POST /api/storage/backups` 创建并验证，`GET /api/storage/backups/{name}/archive` 下载完整 ZIP，`GET /api/storage/backups/{name}/download` 下载单独数据库。下载名严格限定为服务生成的文件名。

实现边界：StorageService 依赖纯 domain 的 StorageStore 接口；SQLiteStorage 负责数据库和本地文件，API 负责入口及下载响应。没有数据库结构变更。本地存储仍是当前主存储，云端同步未实现。


## 原始更新快照整理与空间回收

“存储与备份”页面显示可整理的原始更新快照数，并提供“备份并整理旧快照”。仅移除属于仍存在活动、且不被任何 ActivityEvent/IdleEvent 当前引用的原始版本。每个活动的最新原始记录、所有日期的统一活动与 Session、人工分类、识别规则、同步进度保持不变；孤立原始数据保守保留。不按日期设置期限，不删除往年的活动。

执行顺序：创建完整备份并独立恢复验证 → 从该备份取得可整理 ID → 获取 SQLite 写锁，重新检查引用并在单事务中删除 → 尝试 VACUUM 和 WAL checkpoint 回收空间。仅删除存在于已验证备份的候选版本，备份后新产生的旧版本留到下次。备份失败不开始删除；删除失败整体回滚。VACUUM 在删除提交后独立执行，失败时保留整理结果并提示空间回收延后，不能把整理完成与空间回收完成混为一谈。

整理后的自动同步仍保存更新快照，用户可以按需再次整理，尚未定时自动整理。整理移除了运行库的部分原始更新历史，无法在运行库中逐版本回放这些旧修订；这些版本仍保存在整理前备份中。导入数据源若回到旧版本，Adapter/Repository 会重新保存对应快照。

每次整理会增加一份完整备份；原库变小不代表本地总占用一定减少。页面分别显示运行库与备份目录占用，未自动删除旧备份。VACUUM 可能短暂阻塞写入，且需要额外临时空间，适用于当前本地小数据量；备份操作与整理在单进程内互斥。新增 `POST /api/storage/compact`，返回整理数量、备份、操作前后文件大小及回收状态。没有待整理版本时不创建新备份。


## 统计与趋势

主页链接“统计与趋势”进入 `/statistics`。提供本周（周一至今天）、本月（1 日至今天）、今年（1 月 1 日至今天），也可选自定义起止日期。日期以北京时间解释，首尾日期均包含；最多查询 3660 天。趋势粒度支持自动、按天、按月，自动在范围达到 91 天时切换为月汇总。按天趋势可以点击进入对应日期的活动记录。

页面展示全部活动扣除 AFK 后的时长、娱乐分类时长、未分类时长和工作时长；分类分布的百分比以全部 active_seconds 为分母，应用和内容排行各取前 20 项。内容按应用与 content 名称汇总，缺少名称的记录不伪装成已识别内容。娱乐分类限定 game/video/film/anime/reading/music/social/live/browsing；其他及自定义分类仍计入全部活动和分布，但不自动计入娱乐。分类表示当前规则及人工判断，不证明真实用途。待确认时长保留在 active_seconds 内，图表区分已确认与待确认部分；不跨设备或来源排重。

无记录日期与有记录但扣除后为零的日期分别显示。实际有记录日期范围和天数明确展示，不将数据开始之前的日期当作零使用。月汇总仅包含所选起止范围内的日期，当前月可能尚未结束，不能把已有一天的记录当作完整年度行为。

每日数据由纯 domain 的 daily_activity 从每个 Session 所关联的实际事件区间并集生成，跨午夜按北京时间切分；分别与 AFK/已知状态区间相交，合并间隙不计入，冲突 AFK 优先，未知设备不匹配。Migration 0005 新增派生 daily_activity 表及日期索引；升级已有数据库后执行 `POST /api/reprocess` 回填每日统计（无需 ActivityWatch 在线）；增量同步仅更新受影响范围，不能代替旧版本全历史回填。本机已回填。它不替代原始数据，可随算法变化重建。

ProcessingService 在同一事务内重建 Session 和每日数据。SQLiteRepository 执行日期范围 WHERE / GROUP BY / SUM；analytics 负责分类口径和补齐时间轴，API 校验参数。年度查询不调用全量 events()/sessions()，不在网页加载全部历史明细。普通同步与本次记录纠错已采用增量处理；全局规则/游戏目录变更仍完整重建。

新增 `GET /api/statistics?start=2026-01-01&end=2026-12-31&granularity=auto`，返回 totals、coverage、categories、apps、contents、trend 和统计口径。此次备份和恢复验证自动包括 daily_activity，升级前完整备份已保存。


## Edge / Chrome 网页接入（迁移 0006）

在实际使用的 Edge 和 Chrome 中分别安装官方 [ActivityWatch Web Watcher](https://chromewebstore.google.com/detail/activitywatch-web-watcher/nglaklhklhcoonedhgnpgddginnjdadi)，保持本机 ActivityWatch 运行。官方 [watcher 文档](https://docs.activitywatch.net/en/latest/watchers.html) 列出了 Chrome 与 Edge 支持。首页“浏览器接入”显示网页 bucket、已导入记录及关联片段数量；未安装或尚无上报时明确显示等待状态。LeisureLog 不自动安装浏览器扩展。

只导入普通 HTTP/HTTPS 页面，过滤明确标记 incognito 的记录和浏览器内部页。扩展本身的采集/隐私设置由浏览器中的扩展管理，LeisureLog 不修改 ActivityWatch 原始记录。`audible` 作为来源信息保存，但后台音频不单独计时。当前网页信息包含完整网址（包括查询参数），仅本地保存，并随数据库备份；支持配置驱动的页面标题名称提取，没有网页抓取、作品元数据解析或 AI 内容识别。

```text
ActivityWatch 窗口 → ActivityEvent ──────────┐
ActivityWatch 网页 → BrowserEvent ──────────┼→ ResolvedActivity → 分类 → Session → 每日统计
ActivityWatch 离开 → IdleEvent ─────────────┘                   ↓ 扣除 AFK
各来源原始 payload → RawEvent 版本快照，独立保存
```

- 原始窗口保留自己的标题和 URL；网页来源独立保存于 browser_events。派生关联保存在 resolved_events，并记录 window_event_id / browser_event_id 以追溯依据。Session 关联派生片段，不将网页来源作为额外活动叠加。
- 仅同来源、同设备、浏览器应用和页面标题匹配且时间重叠时，关联网页；窗口区间按网页边界分段，窗口总时长守恒。中文 Edge 标题的“和另外 N 个页面”、浏览器后缀与零宽字符正常处理。标题不匹配、数据缺失、多个不同页面冲突时保留窗口信息。
- Chromium 扩展可能将 Edge 识别为 chrome，甚至共用 bucket，因此不能按 bucket 数断言两个浏览器均安装成功。Chrome 类型候选允许 Chrome/Edge，但仍需要前台标题匹配；无法区分的同标题不同网址记录保守不关联。
- hostname 缺失/unknown 且 ActivityWatch 只有一个已知窗口设备时，绑定到该设备，绑定写入快照元数据。多设备不猜测，保持 unknown 不参与融合；可在 `.env` 使用 `LEISURELOG_BROWSER_DEVICE_BINDINGS={"网页bucket ID":"设备hostname"}` 指定映射。
- 原窗口人工分类在网页接入后继续优先；具体网页片段可单独纠错，并记住“同一应用 + 同一网站域名”。恢复自动分类时可对该片段抑制继承的窗口覆盖，而不删除其他片段的窗口纠错。重建后边界或来源 ID 发生变化的旧片段覆盖保留但不会强行套到新片段；需要持久泛化时使用记住规则。
- YAML 新增可组合 `path_prefix` 条件：哔哩哔哩漫画→阅读、直播→直播、番剧路径→动漫、视频路径→视频，首页→网络闲逛；YouTube 视频/短视频路径与知乎也有基础规则。未知网站继续保留未分类。修改配置后重启后端，再重处理已有数据。
- 原始快照整理保护网页最新 raw 引用，备份自动包含新表。迁移升级保留窗口历史、Session 关联和既有人工分类。降级 0005 会移除新派生数据、网页标准化表及网页片段覆盖；raw 快照及原窗口覆盖保留，降级前须备份，升级后可重新导入/处理。

`GET /api/events` 返回用于分类和计时的派生活动；Session details 同时返回对应原窗口与网页来源。`GET /api/browser/status` 查看接入状态。扩展安装前的历史没有网址，不能仅靠窗口标题还原；后续自动同步接收新增数据，若接入已有历史网页 bucket，使用时间范围导入补取，单次最多 7 天。


## 具体内容名称与按页面纠错

网页已关联且分类规则匹配时，`content_title_pattern` 可从标题提取名称。该字段为带 `(?P<content>...)` 命名组的正则表达式：启动时编译并验证，纯 domain 的 TitleContentExtractor 使用全文匹配，限定标题输入 1000 字符、结果 300 字符。规则没有配置、标题不匹配、提取为空或超长时，继续使用规则的固定站点名称，不猜测作品。网站/路径分类与名称提取都在 YAML 中配置，RuleClassifier 仍遵守可插拔 Classifier 接口。

默认支持哔哩哔哩漫画阅读页标题（去除数字章节编号和固定后缀）、哔哩哔哩视频固定后缀、YouTube 视频/短视频固定后缀。漫画标题中的有意义副标题和版本信息保留；个人中心、首页不会被当作作品。不同漫画章节名称格式符合规则时，content 名称相同，在已有统计中汇总；Session 仍依据实际页面/标题区间区分。内容排行当前按应用与名称汇总，不是跨平台的作品库，也不自动合并同名作品或不同版本。

纠错界面新增“记住：同一应用 + 这个页面地址”。`remember_scope=url` 使用同来源、同应用、HTTP/HTTPS 页面完整地址匹配，忽略页内 fragment，保留查询参数，避免不同 YouTube `v` 内容混淆。该范围适用于标题变化但页面地址相同；其他章节/地址以及不同查询参数需另行识别。优先级：人工覆盖 > 用户页面地址规则 > 用户相同标题规则 > 用户域名规则 > 用户应用规则 > YAML > unknown；同等范围保持新规则优先。新范围沿用 learned_rules 表，无需新增迁移。

识别后的名称显示在活动列表、详情纠错默认值及内容排行榜中；原始标题、网址和快照保留，时长计算保持原有口径。若配置发生变化，重启服务再 `POST /api/reprocess` 即可重算名称。安装网页扩展之前或网页无法关联的窗口历史不凭空还原网址/作品。


## 计时策略与修正（迁移 0007）

活动详情新增“修正计时方式”，可选择默认/配置策略、按离开状态扣除（afk）、按前台时长计入（foreground）、前台网页有声音时保留（audible）。所有活动默认 afk，不依据内容类别自动取消扣除。通过 `PUT /api/events/timing` 保存所选活动 event_ids 及 policy；policy=null 恢复配置/default。修正、Session 重建与每日汇总处于同一写事务，任何错误整体回滚。

- afk：按已知离开区间交集扣除，仍沿用原有冲突 AFK 优先策略。
- foreground：保留实际前台窗口区间内的离开时间，适用于用户确认的观看/阅读/手柄误扣；会计入真正挂机的前台时间，不能证明持续关注。
- audible：只有同设备、前台标题与时间已经关联的网页、且来源 audible=true 的区间保留离开时间。静音/缺少网页依据回退扣除，后台音频没有独立计时。声音只是辅助依据。
- 没有 AFK 覆盖的时间，继续保留并标为 unverified；新策略不凭空补充覆盖证据。

`detected_afk_seconds` 保存源端检测到的离开交集，`retained_afk_seconds` 保存计时策略保留的部分；原有 `afk_seconds` 继续表示实际扣除。恒等式为 detected = retained + afk、active = recorded - afk。三者同时在详情显示，统计页显示对应汇总；有状态记录不等于确认真实观看。Session 保存 timing_policy/timing_origin，不同策略/来源及不同声音依据不混合合并；合并间隙始终不计入。每日汇总在北京时间午夜按真实区间拆分，活动页与日/月/年统计使用相同口径。

全局策略配置沿用 `config/rules.yaml`（完整备份已包含）：`timing_policies` 是有序规则列表，默认空列表。规则包含 id、policy，以及至少一个 app/category 条件，所有条件 AND、首条匹配生效。例如：

```yaml
timing_policies:
  - id: reading-foreground
    category: reading
    policy: foreground
  - id: video-audible
    category: video
    policy: audible
```

上面是可选示例，项目默认未启用这些规则。配置修改后重启并重新处理。人工计时选择优先于配置，分类改变后配置会重新匹配，但独立的人工计时选择仍保留。该阶段提供配置文件与按活动修正，尚未提供全局策略编辑页面。

人工策略独立保存于 timing_overrides，锚定原窗口，不依赖临时 Session ID，因此同步与重建不会清除；原窗口的选择在后续网页关联后可继承，具体网页片段可恢复默认而不删除其他片段的窗口选择。来源 ID/分段边界改变时，不强行将旧片段策略套到不同活动。修改作用于当前详情显示的完整事件；跨日事件其他日期也会更新，来源 heartbeat 延长的同一事件会沿用选择。

Migration 0007 新增 timing_overrides 和派生计时依据列；升级 backfill 旧 detected=afk，默认统计口径不变，应用重处理生成网页声音依据。原始窗口/网页/AFK 和快照不修改；备份包含计时选择。降级会移除人工计时策略并将派生汇总恢复到 AFK 扣除，原始数据和人工分类保留；降级前须备份，策略配置及派生结果需按目标版本重新处理。

## 作品与内容库（迁移 0008）

打开 **http://127.0.0.1:8001/library**，或从活动/统计页面进入“作品与内容库”。只汇集分类结果已有非空 content 名称的活动；全部电脑活动仍在原活动与统计页面。列表支持名称/关联名称搜索、分类筛选、最近使用或累计计入排序，每页 50 项。尚无法识别具体作品时，条目可能只是站点名称。

详情展示全部历史累计原始/计入时长、检测与扣除 AFK、策略保留、状态待确认、有记录日期数、去重 Session 数、首次和最近活动时间、所有有记录月份、分页使用日期以及最近 20 个片段。日期和月份依据已有 daily_activity 计算，北京时间分日；跨日 Session 只计一个片段，不按跨度分摊间隙。无数据日期不补为零；不同设备或重叠来源尚未排重。

作品身份由 `(app, category, content)` 精确匹配产生的稳定 ID 确定。不同应用/分类、大小写或实际识别字符串不同的名称先独立保存，不根据相似标题猜测作品关系。展示名称和备注存于 content_items；名称关系存于 content_aliases；原始快照、分类结果、计时选择及每日事实不因作品库操作改写。

- 改名：修改作品库展示名称和备注，原识别名称仍可搜索。已有活动页面和范围内容排行榜继续使用活动分类中的原名称。
- 合并：在目标作品详情搜索同分类条目，将来源的全部名称关联移到目标；跨应用合并必须人工发起。汇总即时更新，同步/重处理继续使用这组关系。
- 拆分：将一个关联名称移回独立条目。当该名称的原条目仍存在且已无其他名称使用时，恢复原条目的展示名称和备注；否则建立独立条目。目标其余名称保留。一个条目只有一个名称时无需拆分。
- 关联新名称：按应用与本作品分类登记一个识别名称，即使尚未出现活动也可以预先建立关系。不会自动识别未知网页；先由分类器或人工纠错得出匹配的 content 名称。已属于其他作品的名称要求通过合并操作处理。
- 条目和名称关系不随重处理删除。暂时没有活动的已关联条目保留为零；合并后没有名称的来源条目从列表隐藏，其原详情及备注仍保留。不会自动按年份清除。

模块边界：domain/library.py 定义身份和去重注册；services/library.py 管理改名/合并/拆分用例；repositories/library.py 实现持久化和 SQL 聚合；analytics/library.py 调度只读查询；api/library.py 验证请求与管理一致读事务、BEGIN IMMEDIATE 写事务；静态页面只显示结果。每日事实通过 `(app, category, content)` 唯一名称索引关联作品，不给原始事件植入可变作品信息。新增每日内容组合索引加快关联；查询不载入全部原始事件或 Session 对象。

接口：`GET /api/library`（query/category/sort/limit/offset），`GET /api/library/{id}`（日期分页 limit/offset），`PATCH /api/library/{id}`（name/notes），`POST /api/library/{id}/merge`（source_id），`POST /api/library/{id}/aliases`（app/name），`POST /api/library/{id}/aliases/{alias_id}/split`。查询最多每页 100 项，详情日期默认 30 天。修改与返回查询在同一事务完成，任何错误回滚。

升级前创建并验证完整备份，停止旧服务，再运行 `alembic upgrade head`，启动新版后调用 `POST /api/reprocess` 注册已有内容（正常同步也会注册）；不在应用启动时自动迁移。Migration 0008 创建作品和名称表以及 daily_activity 组合索引。降级会移除作品库的展示名称/备注/人工名称关系，原始活动与分类数据保留；须先备份。标准完整备份会包含作品库全部数据，重新处理保留这些用户设置。当前没有作者、封面、发行年份等外部元数据，也不做跨版本自动匹配。

## 游戏统计

打开 `/games`，或在活动、作品库、统计页点击“游戏统计”。列表默认展示有记录的游戏，以及已安装且具备识别依据的 Playnite 条目。可搜索名称，按累计时长或最近游玩排序，切换到仅有记录或全部库条目。没有活动的条目明确显示“暂无记录”，游戏目录本身不会生成游玩时间。全部库范围可能包含软件。

详情显示累计计入、原始时长、有记录天数、游玩片段数、首次/最近记录、每月累计、每日分布及最近 20 个片段。日期每页 30 项、列表每页 50 项；点击日期回到当天活动，点击“查看记录依据”直接打开该片段的窗口/网页及离开状态明细，可使用已有人工纠错和计时修正功能。自动同步和重处理后，刷新页面查看更新。

计时沿用 `daily_activity`：北京时间分日、实际活动区间并集、合并间隙不计、按现有策略扣除 AFK，待确认时长仍保留并单列。跨日 Session 计一次片段，两天分别分配时长。人工分类优先，改成其他分类的活动不再计入游戏；原始记录保留。Steam/Playnite 历史累计时间不叠加，跨设备重叠尚未排重，没有记录的日期不代表没有游玩。

游戏库分类器的活动以 `playnite:<game-id>` 汇集，目录改名/暂时移除后仍可追溯已识别历史。配置或人工命名的游戏，仅在名称与当前目录精确且唯一匹配时关联；有歧义或无匹配时按应用与名称独立统计，避免同名不同游戏自动混合。修改名称前形成且没有游戏 ID 的活动不会自动推断成改名后的游戏。此处使用识别名称与游戏 ID，不使用作品库的展示名称和人工合并关系。

模块边界：`domain/ports.py` 定义 GameStatisticsStore 协议，`repositories/game_statistics.py` 从每日事实执行 SQL 汇总，`analytics/games.py` 调度查询，`api/games.py` 校验参数并使用一致读事务，静态页面仅展示结果。仅加载当前游戏目录和汇总，不读取全部原始事件或 Session 对象；详情日期与最近片段在 SQL 中分页。游戏时长统计最初没有新增持久表；随后类型管理增加独立覆盖表，当前数据库版本为 0011。

接口：`GET /api/game-statistics`（query、scope=tracked/recorded/all、sort=time/recent、limit、offset）；`GET /api/game-statistics/{key}`（日期 limit、offset）。每页最多 100 项，未知游戏键返回 404；详情返回 item、days、months、recent_sessions 与 day_total。键必须 URL 编码，避免名称中的空格、斜杠或中文改变请求路径。


## 游戏类型与偏好（迁移 0010）

打开 `/game-preferences`，或在活动、游戏、作品库、统计页点击“类型与偏好”。可按本月、今年、去年、指定年份或自选起止日期查看，最多 3660 天。页面显示游戏累计计入、有记录游戏数、类型待补充时长、主类型分布、月度组成，以及按主类型筛选的游戏列表。点击类型分布仅筛选下方游戏，不改变所选时间范围和总体占比。月份仅统计落在起止日期内的活动；没有活动、已有其他活动但未采集游戏、有游戏活动但计入为零分别展示。实际有游戏记录的日期范围明确标注，不把尚未采集的月份当作零游玩。

游戏详情新增“游戏类型与标签”。自动建议使用当前游戏目录标签；目录标签为空或已移除时，参考已分类活动标签。纯 domain 中的声明式词表支持英文/中文别名、NFKC 与大小写归一、标签去重；未支持的标签原样保留。优先顺序为具体类型随后宽泛类型，例如 ARPG 优先于 RPG，卡牌优先于策略。这只是来源资料的确定性建议，不按游戏名称推断，也不宣称唯一正确的类型。选择其他主类型或类型待补充均可。

主类型是唯一的时长统计维度，补充标签不再累加时间。每段游戏活动只计一次；未知类型和未命名游戏均包含在分母，未知占比不会被隐藏。全 AFK 导致计入为零时仍显示有记录，占比返回 null；未命名游戏没有虚构的作品或游戏数量，可以在活动记录中补充名称。计时沿用当前策略、北京时间分日及 AFK/状态待确认规则，不叠加 Playnite/Steam 历史累计，尚未跨设备排重。

人工主类型和补充标签保存于 game_type_overrides，以稳定统计键关联，没有依赖可替换目录的外键。保存只更新该表，不修改源标签、分类、计时或原始活动，也无需重建全部 Session。重新导入、目录改名/移除、正常同步、重处理与重启均保留该选择；恢复自动只撤销此处的类型元数据。类型变化使用当前选择回看历史，因此过去月份的类型分布也会改变，不是按当时类型冻结的快照。旧名称没有稳定游戏 ID、或精确名称出现歧义时，沿用游戏统计的独立身份规则，不强行迁移覆盖到不同游戏。

模块边界：domain/game_types.py 定义词表、归一与优先级；services/game_types.py 管理保存/恢复用例并依赖 GamePreferencesStore；repositories/game_preferences.py 复用稳定游戏身份，从 daily_activity 按游戏和月份 SQL 汇总；analytics/game_preferences.py 计算占比、总量和缺失月份；api/game_preferences.py 管理输入验证与事务；静态页只展示和提交选择。不会载入全历史事件或 Session 对象。人工写入、存在性检查和响应查询在 BEGIN IMMEDIATE 事务中完成，错误整体回滚；报表在一致读事务内查询。

接口：`GET /api/game-types` 返回主类型选项；`PUT /api/game-types/{key}` 保存 `{primary, tags}`，标签最多 50 项，每项 1–80 字符；`DELETE /api/game-types/{key}` 恢复自动。游戏键必须 URL 编码。`GET /api/game-preferences?start=2026-01-01&end=2026-12-31` 返回 totals、coverage、types、games、trend、未命名/未知类型时长及口径说明；未知游戏返回 404，无效类型/日期/标签返回 422。游戏统计返回的 game_type 明确区分 source=manual/automatic，并保留原来源标签及自动建议。

升级前创建并验证完整备份，停止旧服务，执行 `alembic upgrade head` 后启动新版。Migration 0010 只新增独立类型覆盖表，不改动已有资料。完整数据库备份自动包含该表，并验证独立恢复后的所有表内容；存储概览增加覆盖条目数。降级 0009 会移除人工主类型与标签选择，原始活动和游戏库资料保留，降级前须备份。当前服务使用 0011，不在启动时自动迁移。


## 长期运行与增量处理（迁移 0011）

日常使用流程不变：ActivityWatch 自动采集，LeisureLog 后台同步，查看当天记录、年度统计、游戏统计和偏好页面。此次优化不需要重新安装 watcher 或扩展。

- 普通同步只追踪实际变化的窗口、AFK、网页事件，同时记录变更前后的设备、来源、stream 和完整时间边界；heartbeat 延长、缩短、移动和旧版本恢复都能清理原有派生范围。元数据中的 bucket last_updated 单独变化不算活动版本变更。
- Repository 用 SQL 找出受影响的窗口流，再扩展到与其重叠或间隔不超过合并阈值的当前窗口和旧 Session，直到边界稳定。网页和 AFK 变化会涵盖同一来源/设备的相关窗口流。浏览器和 AFK 读取保留完整事件边界，不按查询范围裁剪后丢失上下文。
- 仅重新分类、拆分、合并及替换这些范围中的 Session、关联和每日事实；其他范围的历史行不删除、不重写。关联失效的旧网页片段只在受影响的原窗口范围清理。人工分类、计时覆盖、识别规则、内容库关系、游戏类型选择和原始版本仍独立保存。
- 无变化或没有可关联窗口的网页/AFK 数据跳过派生处理，返回 SQL 统计的全局 events/sessions 数量。自动同步仍提交成功检查点，失败时原始事件、覆盖选择、Session、每日事实和同步进度一起回滚。
- 本次记录的分类/计时纠错只重建相关范围；选“记住规则”、删除识别规则、游戏目录变化、手动完整重新处理会完整重建，以应用可能影响全历史的匹配变化。修改 rules.yaml 后用“重新读取规则文件”；修改合并阈值仍须重启并调用 `POST /api/reprocess`。
- 为避免 SQLite 的表达式/参数上限，超过 128 个独立处理范围的单次极度碎片化导入回退完整重建。范围采用保守的连续区间，不声称只修改一个 Session；长时间连续记录可能扩展较大。完整重处理自身仍加载全历史，年度查询不因此改变。

`GET /api/events`、`/api/sessions`、`/api/idle-events` 在 SQL 中分页；当天列表、详情只读当天重叠区间及相关原窗口/网页 IDs，跨午夜仍按北京时间切分。全局分类汇总与浏览器接入状态使用 SQL 聚合，不再加载全部历史对象。`GET /api/sync/status` 的 `last_result.processing` 提供 processed_windows / incremental_runs / full_runs / unchanged_runs，duration_seconds 包括本轮来源读取和数据库操作；不暴露私人标题或 URL。手动同步响应继续使用原 fetched/changed/events/sessions 字段。

模块职责：`domain/processing.py` 定义受影响区间及合并；`repositories/processing_scope.py` 负责 SQL 范围规划和查询；`services/processing.py` 复用相同业务流水线执行完整/增量处理；`runtime.py` 组织后台同步与提交；`analytics/query.py` 使用按日范围读取。业务层不引入 SQLAlchemy 或来源 SDK。

Migration 0011 只增加范围查询及原窗口关联索引，不创建新的采集数据、不改变已有业务表内容。升级前创建并验证备份，停止旧后端，执行 `alembic upgrade head`，再启动新版。此次升级不需要全历史回填。降级到 0010 只移除新增索引；对应旧代码的健康检查与数据库版本须一致。

可复现性能样本：从项目根目录运行（只在独立临时数据库生成合成数据，退出后清理）：

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_processing.py --days 1096 --events-per-day 20
```

本机一次测量：1096 天、21,920 个窗口事件，完整重建 17.1696 秒；一次 heartbeat 更新只处理相关 20 个窗口、1 个连续范围，0.0516 秒；重复未变化数据 0.0021 秒、处理窗口 0。增量和完整重处理的活动分类、网页片段、Session、关联及每日事实内容哈希全部一致。这是可分离日期的样本，不是所有场景的速度承诺。正式数据副本的真实来源同步处理 9 个窗口，约 0.0623 秒，也与完整处理一致。详细边界与验证见 VERIFICATION.md。
