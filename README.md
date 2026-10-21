# LeisureLog

本地电脑活动自动记录与分析系统。记录前台应用、网页与离开状态，回看工作、学习、创作、沟通和娱乐，并把不同应用中的活动关联到同一个项目。采用 **模块化单体**：一个进程、一套 SQLite 数据库，模块按职责分开，后续优先扩展接口实现而不是堆叠条件分支。

已实现：ActivityWatch 前台窗口、AFK 与网页数据读取、统一 ActivityEvent / Session、原始数据版本留存、SQLite、Alembic 迁移、FastAPI、自动同步、Session 合并、AFK 时长扣除、配置分类、人工覆盖、可持久化的识别规则、基础分类汇总、本地活动查看页面、玩过看过及名称管理；Playnite 本地导出 Adapter、游戏目录与可插拔游戏分类器支持读取本地游戏资料；游戏统计、主类型与补充标签管理、月度/年度偏好分析已完成。同步及本次记录纠错已支持受影响范围增量重建，日视图和明细列表使用数据库范围查询/分页。AI 分类和手机端暂未实现。

## v0.3：用途整理与可撤销规则

新增“待确认”中心，按应用和网站整理未知用途，支持日期、搜索及分页。保存用途/项目规则前显示全部历史的影响和样例，人工选择优先；活动详情可解释归属来源，规则与归属修改可撤销。项目支持可选累计投入目标，进度按全部历史计算。自动备份独立检查，ActivityWatch 离线或关闭同步时仍可运行。详细使用方法见 [待确认、规则预览与项目目标](docs/confirmation.md)。

当前源码版本 **0.4.0b2**，数据库迁移仍为 **0013**；原有活动与官方插件功能继续保留。

## 0.4.0b2：稳定性与界面收尾（2026-10-22 源码同步）

修正周回顾的凌晨区间和跨日最长 Session、同步期间的写锁等待、异常备份说明处理；提供带校验的恢复命令与轮换日志。升级不增加数据库迁移。日常使用与恢复见 [维护说明](docs/maintenance.md)，工程与验证边界见 [稳定性收尾](docs/stability.md)。

六套界面增加近期活动柱状图、导航分组、风格卡片与弹窗操作栏，统一中文分类名称，并修正侧栏用途、项目复选框、旧电脑标题栏和窄屏筛选布局。当前仍有周图跨时区星期、部分窄屏导航末端渐隐、旧电脑插件页时间文字对比三项待完善，见 [界面复查与已知问题](docs/frontend-review.md)。

本次只更新源码、文档与自动检查，不重建或发布 Windows 安装包。公开历史延续原仓库，个人记录、配置与本机维护历史不包含在内。

## 核心与官方可选功能（2026-10-16）

当前公开源码已接入“核心 + 插件”架构。核心负责 ActivityWatch 记录、统一事件与 Session、计时、用途与项目、人工修正、事务和备份；Playnite 资料与识别、游戏统计与偏好分别由两个随应用提供的官方模块运行。

新增常驻的 [插件管理页面](docs/plugin-management.md)，运行后访问 `/plugins`，可以查看真实运行状态、选择权限、预览依赖影响、启停和撤销权限。已有保存的选择优先；首次没有配置时沿用原游戏功能。游戏页面根据实际授权提供汇总、明细只读和可编辑三种模式。完整 ZIP 备份包括活动库、规则、插件选择与校验值。

本次源码更新保持数据库结构 **0013**，不需要全量重算。已有数据的升级、备份与回退见 [源码运行与升级](docs/local-deployment.md) 和 [回退方案](docs/plugin-rollback.md)。同进程运行边界适用于经过审查的官方代码；独立插件包安装器、在线市场、第三方强隔离、AI 分类和手机端尚未实现。

架构与接口说明：[核心与可选插件](docs/plugin-architecture.md)、[模块边界](docs/plugin-boundaries.md)、[运行管理器](docs/plugin-runtime.md)、[官方功能验收](docs/core-integrity.md)。官方模块代码位于 `src/leisurelog_plugins/`，公共接口位于 `src/leisurelog/plugin_api.py`。

本次只同步源码、文档和自动检查，不发布新的 Windows 安装包；构建配置继续保留。

## Windows 安装版（0.4.0b1，小范围试用）

新增独立桌面入口、系统托盘与首次使用引导。安装版自带 Python 运行环境，默认把程序与个人数据分开放置；首次打开先说明读取范围，确认后才开启 ActivityWatch 同步。独立入口自动建库，旧结构数据库迁移前建立验证备份；失败时恢复升级前数据库。正常升级、重新安装与卸载保留独立的个人数据目录。

构建后安装包输出到 `dist/releases/`。它与原有脚本启动方式并存，不自动搬迁源码运行目录中的历史数据，也不改动原有开机启动项。ActivityWatch 仍需独立安装，浏览器扩展与 Playnite 为可选接入项；首次引导可下载为当前用户数据目录生成的 Playnite 10 扩展。

安装、构建方式及验证边界见 [Windows 安装版](docs/windows-installation.md)。该版本适合小范围试用，尚未在独立干净 Windows 电脑上完成全部兼容性验证，尚未进行发布者代码签名或 GitHub Release 发布。

## 全部活动与项目关联

首页、统计与每周回顾覆盖全部活动。**活动类型**描述视频、游戏、文档等内容；独立的**用途**描述工作、学习、创作等目的。用途不能可靠判断时保留待确认，不把所有视频或网页默认算成娱乐。

在“项目”页创建项目后，可以在活动详情或首页勾选记录，指定用途与项目；支持批量修改。可以记住同一应用、标题、标题关键词、网页地址或网站的归属，自动处理已有和未来的匹配活动。人工选择优先，用途和项目分别保存，修改其中一项不会覆盖另一项。项目可编辑、归档，并查询应用分布、用途分布和活动日期；统计支持用途/项目筛选以及 CSV 导出。

已有内容识别、游戏、偏好、作品库、六套界面和脚本启动继续保留。基础用法及架构见 [活动用途与项目](docs/activity-projects.md)。

六套界面已加入轻柔动画：页面过渡、卡片入场、弹窗开合、按钮反馈和风格切换。可在“界面风格 → 动态效果”开关；偏好在本浏览器保存，并尊重系统的减少动态效果设置。同一查询的定时刷新不重播列表入场。使用与实现边界见 [页面动画](docs/motion.md)。

## 本地运行与数据

从源码创建运行环境后，双击 `start-leisurelog.bat` 即可打开本地网页，地址为 `http://127.0.0.1:8001/`。首次安装步骤见下方“快速运行”。

活动数据库和游戏库导出保存在本机 `data/`，备份在 `data/backups/`。个人活动数据、本机历史截图和私人联调记录不包含在公开仓库中。

已有安装升级到 v0.3 时，先创建并验证完整备份、停止旧服务，执行 `alembic upgrade head`，再启动新版。健康检查应显示 **0.4.0b2 / 0013**。从 v0.2 升级不需要全量重算，详细步骤见 [待确认与项目目标](docs/confirmation.md)；从更早版本升级时，还请按 [活动用途与项目](docs/activity-projects.md) 回填历史用途。

## 快速运行（Windows PowerShell，Python 3.11+）

在本 README 所在目录打开终端：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
Copy-Item .env.example .env
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn leisurelog.main:create_app --factory --host 127.0.0.1 --port 8001
```

如果 `.venv`、依赖和数据库已经准备好，只需运行最后一条启动命令。依赖范围在 `pyproject.toml`，当前验证环境的精确依赖版本另存于 `requirements-lock.txt`；重建同一环境可先 `pip install -r requirements-lock.txt`，再 `pip install --no-deps -e .`。精确版本文件针对本次 Windows / Python 3.13 环境，其他 Python 版本优先使用 pyproject 中的兼容范围。

- 交互接口文档：http://127.0.0.1:8001/docs
- 活动查看首页：http://localhost:8001/（默认端口 8001）
- 健康检查：http://127.0.0.1:8001/health
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

## 项目目录

```text
LeisureLog/
├── README.md                 # 项目入口、启动方法、文档索引
├── config/                   # 分类规则与 Playnite 进程配置
├── data/                     # 本机数据，不提交到 Git
│   ├── leisurelog.db          # 正式活动数据库
│   ├── playnite-library.json  # Playnite 游戏库导出
│   ├── backups/               # 已验证的完整数据库备份
│   ├── logs/                  # 运行日志
│   └── archives/              # 本机维护记录
├── docs/                     # 功能、架构、接口、存储与验证说明
├── integrations/playnite/    # Playnite 扩展源码与打包工具
├── migrations/              # Alembic 数据库迁移，当前 0013
├── packaging/               # Windows 安装与独立程序构建配置
├── scripts/                 # 启动管理、构建、安装验收与性能测量工具
├── src/leisurelog/           # 模块化单体的实现
│   ├── adapters/              # 外部数据源、配置和定时器适配
│   ├── domain/                # 纯业务模型、协议与计算策略
│   ├── services/              # 业务用例
│   ├── repositories/          # 数据库与本地存储实现
│   ├── analytics/             # 只读分析与汇总
│   ├── api/                   # FastAPI 路由及本地网页静态资源
│   └── desktop/               # 独立桌面启动、引导、迁移与系统托盘
├── tests/                   # 自动测试及独立问题复现
├── pyproject.toml           # 项目与依赖配置
├── requirements-lock.txt    # 已验证环境的精确依赖版本
├── alembic.ini              # 迁移入口
├── start-leisurelog.bat      # 双击启动
├── stop-leisurelog.bat       # 双击停止
├── restart-leisurelog.bat    # 双击重启
└── autostart-*.bat           # 开启或关闭开机启动
```

`.venv/` 保存本机运行环境，`.git/` 保存版本历史。它们与 `data/` 一起保留。
`build/`、`dist/`、`outputs/`、`.tmp/` 和开发缓存属于可重新生成的产物，已加入忽略列表；需要时由相应工具创建。

## 文档索引

| 文档 | 内容 |
|---|---|
| [Windows 安装版](docs/windows-installation.md) | 0.4.0b1 安装、用户数据位置、构建与试用边界 |
| [功能与使用说明](docs/features.md) | 活动记录、网页接入、每周回顾、游戏分析、内容条目与六套界面 |
| [活动用途与项目](docs/activity-projects.md) | v0.2 的用途、项目、批量关联、自动规则与迁移说明 |
| [待确认、规则预览与项目目标](docs/confirmation.md) | v0.3 的用途整理、来源解释、可撤销修改、投入目标与独立备份 |
| [架构与数据模型](docs/architecture.md) | 模块职责、依赖方向、原始与派生数据、分类优先级、Session 与增量处理 |
| [核心与插件](docs/plugin-architecture.md) | 官方模块、公共接口、运行与后续安装边界 |
| [插件管理](docs/plugin-management.md) | 权限、计划、启停、撤权与故障反馈 |
| [源码运行与升级](docs/local-deployment.md) | 保留已有记录的源码更新与回退 |
| [基础接口索引](docs/api.md) | 主要 API 与本机交互接口文档入口 |
| [存储、备份与恢复](docs/storage.md) | 自动与手动备份、长期保存、快照整理、独立恢复 |
| [开发与验证](docs/development.md) | 测试方法、工程边界及待修复问题 |
| [验证记录](docs/verification.md) | 公开源码测试、界面验收及已知问题 |
| [界面素材说明](docs/appearance-artwork.md) | 插画、字体和矢量素材的来源与用法 |
| [Playnite 扩展说明](integrations/playnite/README.md) | 本地导出扩展、重新打包和进程匹配边界 |

## 架构原则

一个进程、一套 SQLite 数据库，按 `adapters / domain / services / repositories / analytics / api` 分工。
数据源通过 Adapter 转为统一模型，原始快照与处理结果分离；数据库变更通过 Alembic 迁移。
分类器使用可插拔接口，人工覆盖优先，重新处理保留人工纠错与识别规则。
当前主要在本地运行；云端同步、AI 分类和手机端尚未实现。
