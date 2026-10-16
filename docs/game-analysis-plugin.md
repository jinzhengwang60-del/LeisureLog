# 游戏分析与页面迁移（批次 05）

> 本文保留架构开发阶段的设计与验证范围。文中的 `checkpoint/...` 中间标签与 `outputs/...` 证据为本地开发记录，不随公开 Git 历史上传；公开版本的复现与恢复以 [验证记录](verification.md) 和 [回退说明](plugin-rollback.md) 为准。

本轮延续模块化单体：核心保存活动、事务和人工修正，插件负责可撤下的分析算法和页面资源。数据库继续使用 0013，不新增迁移，也不读取日常使用的数据目录。

## 设计约定

- `leisurelog.playnite` 继续接入资料和识别游戏；新增 `leisurelog.game-analysis` 提供游戏统计、类型与偏好。分析插件不依赖 Playnite 的运行状态，已经保存的历史和其他来源的游戏活动都能分析。
- 公共接口只接受有大小限制的 JSON 快照、分析参数和声明式页面贡献。插件不能获得 FastAPI Request、Router、app.state、Repository、数据库连接或 SQL。
- 宿主准备三种游戏投影：累计条目、单个条目的分日/分月/最近片段、指定日期的类型偏好事实。投影不包含原始采集载荷、URL、安装目录或任意文件路径；最近片段标题需要详情权限。
- 分析贡献按名称登记；页面只声明名称、标题和相对资源清单。宿主决定兼容 URL 和资源根目录，检查重复名称、路径逃逸、未列出的资源和与核心路由的冲突。
- 分析调用有独立的受控工作通道和预算。停用、撤权、超时或异常撤下分析及页面，核心记录、自动同步和 Playnite 识别继续工作。旧调用结果不能跨越启用代数使用。
- 人工类型操作只是有界的修改建议。宿主验证已有类型词表、条目存在性和写入权限，在自己的事务内保存；响应构造失败、插件停用或代数变化都会撤回本次修改。词表和校验暂留在统一领域契约，保证旧版能解释已保存的人工类型。
- 数据投影的最低权限由宿主独立检查。插件贡献的权限声明不能削减这个最低要求，也不能把只读操作改成人工写入。
- 共用导航从宿主读取当前可用页面，不在各个核心页面硬编码游戏菜单。停用后的旧书签显示清楚的不可用提示，API 返回明确的状态。

## 配置与回退

没有插件状态文件时，内置两个官方插件以兼容已有功能。存在状态文件时严格服从已保存的选择；旧版文件不会被静默增加新授权，新分析插件可通过已有插件控制 API 显式启用。配置格式仍是 version 1。

保留 `checkpoint/core-plugins-playnite-04` 和所有更早的标签。完成实际验证后保存新的本地提交及 `checkpoint/core-plugins-analysis-05`。回退源码时使用与该版本匹配的插件配置副本；不覆盖当前活动数据库，也不把旧备份直接恢复到日常数据目录。

本轮不做插件中心、在线安装、第三方插件隔离、前端风格重做或新的安装包。官方插件在同一个 Python 进程中执行，受控接口和静态检查不是操作系统沙箱。

## 接入下一种功能

插件只通过公开 SDK 返回 `AnalyticsContribution` 与 `PageContribution`。受审查的宿主组装使用 `HostExtensionBindings` 指定端点、资源根目录和数据提供者，通过 `create_app(..., plugins=..., extensions=...)` 注入；增加一个受审查的模块无需修改 main 的注册逻辑。绑定、提供者工厂和激活凭据不导出给插件，也不能由 HTTP 或配置文件指定代码路径。新领域需要宿主显式实现相应投影和最低权限，没有任意查询接口。

参数快照最多 16 KiB，数据/结果快照最多 8 MiB，页面单个资源最多 2 MiB。投影只包含查询所需的处理数据；异常原文不进入插件状态。独立分析工作通道不占用同插件的分类通道，但共同服从全局工作上限。

兼容网址：`/games`、`/game-preferences`、`/api/game-statistics`、`/api/game-types`、`/api/game-preferences`。通用页面在 `/plugins/{id}/pages/{name}`，资源在 `/plugin-assets/{id}/{asset}`，可用菜单由 `/api/plugin-navigation` 提供。不可用功能的 API 返回 503，旧页面书签显示保留记录的提示。

已有配置中的新分析模块可通过 `POST /api/plugins/leisurelog.game-analysis/enable` 启用，完整官方授权如下；这属于隔离开发实例的控制接口，目前还没有图形插件中心：

```json
{
  "grants": {
    "leisurelog.game-analysis": [
      "activity.summary.read", "games.statistics.read",
      "activity.details.read", "games.types.write"
    ]
  }
}
```

可以只授予汇总与游戏统计权限查看列表和偏好；详情与人工类型操作分别要求详情、写入权限。保存过的空集合或停用选择仍优先。分析不要求游戏接入插件启用。

## 验收

使用隔离 SQLite 和固定活动比较批次 04 与本轮的游戏列表、详情、偏好、人工类型、时间统计和原始数据。验证没有 Playnite、停用分析、撤权、损坏贡献、超时、重复路径和故障恢复。执行本轮架构检查、Python 回归、前端脚本检查，记录本次真实结果；旧版通过的测试不算本轮证据。

2026-10-15 最终验证：Python **466 passed / 1 warning**，Node **32 passed**，25 个前端脚本解析通过；架构、Ruff、空白检查通过。151 个 Python/构建文件通过 3.11 语法检查，实际完整运行使用 Python 3.13。Starlette/httpx 弃用提示及开发文档中的既有待修问题保留。

对照脚本使用批次 04 的实际归档源码与最终代码，12 个阶段的活动、Session、时长、来源、列表、详情、偏好、人工类型与原始快照完全一致。将新版合成库在线复制后，用批次 04 源码及配套旧配置读取和重处理，结果一致，完整性检查通过，结构仍为 0013。

另从公开源文件构建 wheel，并从解包后的 wheel 独立导入运行；两张页面、四个脚本/样式请求、动态导航、统计与偏好 API 正常。6 个页面资源属于插件包，核心包没有旧副本。此 wheel 仅是隔离验证产物，未安装到日常环境，也未重建 Windows 安装程序。

本机证据位于 `outputs/game-analysis-validation/final-regression.xml`、`final-parity/report.json`、`final-package-check/report.json`。可在新的输出目录复现：

```powershell
python scripts/verify_game_migration.py --analysis --baseline checkpoint/core-plugins-playnite-04 --output outputs/analysis-parity-new
python scripts/verify_extension_package.py --output outputs/analysis-package-new
```
