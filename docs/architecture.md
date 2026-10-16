# 架构与数据模型

[返回项目首页](../README.md)

## 目录与依赖边界

```text
LeisureLog/
├── config/rules.yaml          # 有序分类规则
├── migrations/               # Alembic 迁移，当前版本 0013
├── src/leisurelog/
│   ├── domain/               # 纯 Python 实体、接口、分类优先级、Session 策略
│   ├── adapters/             # ActivityWatch HTTP、YAML 规则、固定目录文件读取与工作线程
│   ├── services/             # 同步、重处理、人工覆盖用例
│   ├── repositories/         # SQLAlchemy 模型、SQLite 实现、事务基础设施
│   ├── analytics/            # 只读汇总计算
│   ├── api/                  # 请求验证、路由、事务依赖
│   ├── config.py             # 环境配置
│   ├── game_integration.py   # 固定官方游戏组装、事务与兼容入口
│   └── main.py               # 组装具体实现与应用生命周期
├── src/leisurelog_plugins/   # 通过公共 SDK 的官方 Playnite 与诊断实现
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

插件分支的 Playnite 目录与匹配已通过独立资料协议迁入官方模块，核心处理不查询游戏目录。
普通游戏页面与偏好分析继续保留；当前模块边界、默认选择、匹配身份和回退说明见 [游戏接入迁移](game-plugin-migration.md)。

插件实验分支通过 [可执行的边界检查](plugin-boundaries.md) 约束上述依赖，插件公共入口为 `leisurelog.plugin_api`。现有完整 Repository 仍供内部业务使用；插件只获得按能力授予的窄接口，不直接复用这个大接口。已登记的游戏耦合等待分批移出，没有因为新增协议而自动解耦。

开发分支的 [运行管理器](plugin-runtime.md) 已通过 main 注入分类链及生命周期，services 管理授权/状态，adapters 执行有预算的合作任务，repositories 提供汇总与原子配置存储。宿主控制接口只操作已登记定义，不从请求导入代码。游戏目录、页面和主题贡献仍待独立迁入。

数据库依赖使用 `Depends(service, scope="function")`：写请求在路由执行前获取 SQLite 写锁，提交成功后才发送成功响应；失败时回滚。这样保存项目后立即读取列表不会读到旧状态。API 响应同时设置 `Cache-Control: no-store`。最低 FastAPI 版本为 0.121，依赖退出时机见 [官方说明](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/#early-exit-and-scope)。

## 数据结构与重处理

| 表 | 职责 |
|---|---|
| raw_events | 保存源 payload、源 metadata、接收时间及内容哈希；应用只追加快照，不覆盖已有版本 |
| activity_events | 当前统一事件，含 source、stream、device、起止时间、app、title、url、分类结果，指向所用 raw 快照 |
| idle_events | 独立的 afk / not-afk 状态，关联自己的原始快照；不参与娱乐分类 |
| manual_overrides | 针对稳定事件 ID 的人工内容分类，独立于自动结果 |
| activity_projects | 持久化项目名称、说明、颜色与归档状态，不随重处理清空 |
| context_overrides | 独立的人工用途和项目，绑定事件并保留原窗口锚点 |
| context_rules | 标题、关键词、URL、网站或应用的自动归属规则 |
| sessions | 当前合并结果，可重新生成；记录实际 active_seconds |
| session_events | Session 与统一事件的可追溯关联 |
| content_items | 持久化作品展示名称、分类、备注；不随重处理清空 |
| content_aliases | 应用、分类、识别名称对应作品；唯一约束、支持合并和拆分 |
| game_snapshots | 只追加 Playnite 游戏资料源快照；相同内容重复导入不新增快照 |
| game_catalog | 从最新成功导出得到的当前游戏资料与进程匹配条件 |
| game_type_overrides | 按稳定游戏键保存人工主类型与补充标签，独立于可替换的游戏目录 |

原始数据与处理数据分表。同一源事件通过稳定 ID 幂等更新；原始内容改变时留下新版本。一次同步和派生结果替换在同一 SQLite 事务内完成，失败时整体回滚；`BEGIN IMMEDIATE` 串行化写入，避免并发重建相互覆盖。

`POST /api/reprocess` 从已保存的统一事件重新分类和合并，不需要访问 ActivityWatch，不会删除人工覆盖或原始快照。当前尚无“更换 Adapter 后从原始快照重新标准化”的专用用例，原始数据已为此保留。修改规则文件后可在页面点击重新读取规则文件，或重启服务后调用重处理；错误规则在启动时校验失败，不悄悄忽略。

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

- 仅在同一 source / device / stream 内合并，应用、标题、URL、分类（包括来源）、用途与项目归属及其来源、计时策略必须一致。
- 相邻同类事件间隔不超过配置阈值（默认 60 秒）时合并；中间存在另一种活动会截断。
- Session 的 start/end 表示跨度，`recorded_seconds` 是窗口事件区间的并集，不计合并间隙，不重复计算同一 Session 内重叠部分。
- `afk_seconds` 是窗口记录与同来源、同设备已知 afk 区间的交集；重复 AFK 区间先取并集，不重复扣除。同一时间有冲突状态时 afk 优先。
- `active_seconds = recorded_seconds - afk_seconds`。`unverified_seconds` 是窗口记录中未被任何 AFK 状态覆盖的部分，保留在 active_seconds 中并显式标记；确认 not-afk 的时长可由 active_seconds - unverified_seconds 得到。
- 不延长 AFK 到没有记录覆盖的时间，不把未知设备互相匹配。整段 AFK 的 Session 保留用于核对，active_seconds 为零。离开期间仍可处于同一 Session 跨度，时长计算会扣掉 AFK；当前不按 AFK 强制切分 Session。
- 零时长事件会保留为 ActivityEvent，但不生成 Session。
- 增量处理扩展受影响范围，包含相邻记录及旧 Session 的完整边界，保证跨同步窗口的相邻事件可合并；Session ID 由首事件产生，合并边界变化可能使 ID 改变，所以人工覆盖绑定事件而不是 Session。

已实现 AFK 扣除与前台窗口/网页分段融合；网页只补充内容，不另加时长。跨设备排重与跨不同来源 Session 的重叠冲突裁决尚未实现。汇总的 recorded_seconds_by_category 保持原始窗口时长语义，active_seconds_by_category 为已扣除 AFK 的时长；附带 afk_seconds 和 unverified_seconds。未分类活动仍不应当作娱乐总时长。目前按完整事件标题合并的策略偏保守，窗口标题变化可能切分 Session。

AFK 依据 ActivityWatch 的键鼠输入检测，并不证明使用者实际离开：观看视频、使用手柄时可能长时间没有键鼠输入。当前按 watcher 判断执行扣除，后续需加入内容活动策略。来源状态定义见 [官方数据模型](https://docs.activitywatch.net/en/latest/buckets-and-events.html)，判断实现见 [官方 AFK watcher](https://github.com/ActivityWatch/aw-watcher-afk/blob/master/aw_watcher_afk/afk.py)。

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

**自动采集由 ActivityWatch 负责；LeisureLog 启动后默认每 60 秒自动同步。** 首次启动补取最近 24 小时；后续从数据库保存的成功进度回看 10 分钟，接收仍在延长的 heartbeat。停机后按一天一个窗口补取，失败窗口不推进进度，下轮重试。可以重复同步同一个时间段。同一来源 / bucket / event ID 的重复数据不会重复计数；源事件被 heartbeat 延长时会新增原始快照并更新统一事件。ActivityWatch 会把事件裁剪到请求的时间范围内，跨越多个同步窗口的长事件每次只返回其中一段；适配器会标记哪一端正好落在请求边界上（被裁剪），入库时只在被裁剪的一端与已保存的范围取并集，未被裁剪的一端仍以来源为准（来源缩短或移动事件时照常更新）。2026-10-10 之前的版本没有这样处理，自动同步只保存了长事件的最后约 10 分钟；修复后重新同步历史即可补齐。同步区间外发生的旧数据更改，需要重新同步对应区间。尚不跟踪源端删除。

自动同步随 LeisureLog 服务运行和停止，不是 Windows 开机启动任务。默认使用一个 Uvicorn worker；多进程启动会各自启动调度器，暂不支持多 worker 调度。通过 `GET /api/sync/status` 查看是否启用、是否正在执行、最近成功时间、导入数量和失败状态；状态在内存中，成功进度保存在 `sync_checkpoints` 表中。错误不会让服务退出；恢复 ActivityWatch 后下一轮自动重试。

配置项见 `.env.example`：`AUTO_SYNC_ENABLED`、`AUTO_SYNC_INTERVAL_SECONDS`、`AUTO_SYNC_OVERLAP_SECONDS`、`AUTO_SYNC_INITIAL_HOURS`（均需 `LEISURELOG_` 前缀）。设置 `LEISURELOG_AUTO_SYNC_ENABLED=false` 可关闭自动同步。修改后重启服务。当前迁移版本为 `0012`，已有数据库升级前先停止旧后端，再执行 `alembic upgrade head`。从 AFK 迭代之前升级时，请手动重新同步需补齐 AFK 的历史时间段（每次最多 7 天）；仅增量同步不能补齐此前的全部 AFK 历史。本机已补取最近一天。

本机新版服务运行在 `http://127.0.0.1:8001`，最初因旧服务占用 8000 而使用该端口。查看新版文档使用 `http://127.0.0.1:8001/docs`；手动重新启动可用上述命令的 `--port 8001`。旧版后端的健康检查不认识新版迁移，升级后应使用新版后端（当前 0012）。

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

本机一次测量：1096 天、21,920 个窗口事件，完整重建 17.1696 秒；一次 heartbeat 更新只处理相关 20 个窗口、1 个连续范围，0.0516 秒；重复未变化数据 0.0021 秒、处理窗口 0。增量和完整重处理的活动分类、网页片段、Session、关联及每日事实内容哈希全部一致。这是可分离日期的样本，不是所有场景的速度承诺。正式数据副本的真实来源同步处理 9 个窗口，约 0.0623 秒，也与完整处理一致。详细边界与验证见 [验证记录](verification.md)。

## 独立活动用途与项目（迁移 0012）

活动类型 classification 与活动归属 context 分开。ActivityContext 包含 purpose、project_id、purpose_origin、project_origin；只写入派生的 resolved_events、sessions 与 daily_activity，原始 payload 和统一源事件保持原有格式。归属优先级按字段分别应用，避免只选用途时覆盖项目。

ContextClassifier 接口与原内容 Classifier 分开注册，main.py 组装配置用途分类器；ProcessingService 加载持久归属规则及保守的类型默认，最后应用人工归属。ActivityContextService 通过 ContextStore 协议访问项目与覆盖，在 API 的一致写事务中完成校验、保存和重建。人工归属沿用已有处理范围实现增量重建；全局规则变更重处理历史。

项目和全部活动周汇总使用按日期范围的 SQL 事实聚合，不反序列化完整事件历史；每日用途/项目各有范围查询索引。统计、项目和导出沿用实际 active_seconds，没有新的计时来源。具体规则范围、项目生命周期和升级/回退语义见 [活动用途与项目](activity-projects.md)。
