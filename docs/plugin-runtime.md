# 官方插件运行管理器：开发版

> 本文保留架构开发阶段的设计与验证范围。文中的 `checkpoint/...` 中间标签与 `outputs/...` 证据为本地开发记录，不随公开 Git 历史上传；公开版本的复现与恢复以 [验证记录](verification.md) 和 [回退说明](plugin-rollback.md) 为准。

[设计说明](plugin-architecture.md) · [接口边界](plugin-boundaries.md) · [回退方案](plugin-rollback.md)

本轮运行管理器已接入独立开发分支的 FastAPI 生命周期、分类链和管理接口。
当前默认登记 Playnite 资料/匹配与游戏分析/页面两个官方模块，首次默认授权用于保留既有内置功能，保存过的选择优先。存在旧配置时不静默加入新分析授权。
核心常驻的 `/plugins` 页面管理已登记功能，操作前显示只读计划和权限；全部停用后仍能访问。页面和可复现验收见 [本机插件管理](plugin-management.md)。
显式 `plugins=()` 可运行空集合核心实例；ActivityWatch、计时、人工修正、统计及备份继续由核心持有。
这不是安装中心：HTTP 请求和配置文件都不能指定模块路径、上传 Python 或安装第三方代码。
`src/leisurelog_plugins/diagnostics.py` 是用于验证接入的源码诊断插件，需由组装入口显式登记，不自动加载，也没有发布成独立安装包。

## 模块职责

| 位置 | 职责 |
|---|---|
| domain/plugin_runtime.py | 定义、贡献、任务声明、配置快照、执行与存储协议 |
| services/plugin_runtime.py | 版本/依赖预检、授权、启停、分类顺序、故障撤下与状态 |
| services/plugin_policy.py / plugin_management.py | 与执行共用的最低授权政策、只读操作计划及影响范围 |
| services/plugin_access.py | 每次激活创建独立授权；读取前后检查，停用后旧接口永久失效 |
| adapters/plugin_workers.py | 有上限的真实线程、每次任务预算、合作停止与真实存活检查 |
| repositories/plugin_state.py | 版本化 JSON、配置代数检查、同目录临时文件及原子替换 |
| repositories/plugin_summary.py | 对已有 daily_activity 做 SQL 汇总，不读取原始标题或 URL |
| api/plugins.py / api/plugin_management.py | 本机状态、计划、启停、撤权和常驻页面；继承桌面入口的本地会话保护 |
| domain/plugin_extensions.py / services/plugin_extensions.py | 有界分析请求、人工类型建议、声明页面、激活代数和受控分析调用 |
| analysis_integration.py / repositories/game_views.py | 宿主准备统计投影，自行验证最低权限，人工类型事务与提交前撤销检查 |
| adapters/plugin_pages.py / api/plugin_features.py | 固定资源根、启动前资源验证、URL 冲突检查、页面与资源服务和当前可用导航 |
| main.py / api/rules_reload.py | 注入宿主、与规则分类链共存、退出时按实际任务状态清理资源 |

现在支持 analytics、classifier、task、game-catalog、page；目录文件只通过固定路径接口读取，不接受任意文件或网络能力。
活动 source 与 theme 尚未接受运行；目录不是另一套活动来源。
新插件仍需通过公共 API，不获得完整 Repository、数据库连接或全局应用。
游戏接入及分析/页面两批迁移完成，原有 9 处旧耦合例外已全部删除。4 处明确的存储/宿主许可分别覆盖目录组装、投影组装及两条仓库内部依赖，普通 API、活动处理和活动仓库仍不能引用游戏实现。
新的 SDK、默认选择、兼容身份、事务与验证见 [游戏接入迁移](game-plugin-migration.md) 和 [分析与页面](game-analysis-plugin.md)，仍复用 0013 表。

## 启用、恢复和故障

先检查整组依赖、应用与接口版本、贡献能力、显式授权，再在受控调用中构建贡献。
依赖方不会自动获得未批准的数据权限。正在运行的依赖保留既有授权，变更授权需先停用。
全部工厂成功且配置保存成功后，才启动声明任务。工厂失败或配置写入失败会撤回新贡献，已有运行集合保持可用。
保存以后发生任务异常属于运行故障：状态转为 failed、授权撤销、分类器撤下，并向本插件及依赖方的任务发出停止信号。
无关插件及核心继续运行，失败插件不会在每个事件或每次状态查询时无限重试。

`enabled` 表示保存的启用意图，`state` 表示本次真实运行状态：
disabled、starting、running、stopping、failed 或 unavailable。因此 enabled=true / failed 是可能的，不能当成“仍在正常运行”。
状态中提供声明能力、权限、依赖、实际授权、错误码和每个工作项的真实存活情况，不返回异常原文、原始活动或窗口标题。

下次启动按已保存选择尝试恢复，每个失败依赖只尝试一次；缺失、不兼容或失败插件单独标记不可用，不阻止健康插件和核心。
恢复工厂共用 5 秒预算；一次手动启用的工厂也共用 5 秒，每个工厂默认最多 2 秒。
配置损坏或未知格式时保留原文件、显示 configuration_invalid、拒绝管理写入，核心照常启动。

## 资源与停止

宿主最多登记 64 个插件，每个插件最多贡献 4 个分类器、8 个命名任务、16 个分析和 16 个页面，默认最多同时占用 32 个工作槽。
任务按插件 ID、激活代数、工作种类和名称归属，单个周期任务不会重叠运行；重复启用正常插件不启动第二份任务。
分类器按宿主的显式优先级与稳定 ID 排序，始终位于人工覆盖、用户记忆规则和 YAML 规则之后。
单个活动的全部插件分类调用共用默认 0.25 秒预算，预算用完使用后续核心回退；规则重载保留同一个宿主。
分类器建议继续使用 `plugin:<ID>@<版本>` 来源，不能冒充人工选择。启停不会自动改写历史，人工纠错与原始记录继续保留。
目录匹配由宿主验证 ID 并保留 `playnite:<UUID>`；分类、资料和分析使用三个有上限的通道，同一插件的同类调用串行，仍共同服从总工作槽上限。一次分析请求的全部调用默认共用 2 秒；在途人工写入的提交也检查同一激活代数。

任务预算针对每次 run(context)，宿主监视超时并发送停止信号；任务可用 wait_for_stop() 结束等待。
停用先撤销访问与分类贡献、向所有相关任务发停止信号，再按任务声明的停止预算及宿主总预算等待。
超时后保留工作记录和已占用槽，显示 stop_timeout，直到旧工作真正退出前都不能重新启动同一插件。
上限不足时拒绝新工作；临时繁忙的分类调用使用核心回退，不排队积累无界请求。
旧代数的延迟错误通知不会撤下重新激活后的新实例。

线程等待超时不会强制终止插件。退出应用时先撤销全部访问；仍有插件工作未返回时，SQLite 引擎的释放延后到这些工作结束。
提供者读取结束后还会检查授权，避免停用后的迟到读取或分类结果进入正常调用返回。
已经交给插件的数据无法追溯收回；同进程权限检查不是系统沙箱，CPU、内存、恶意反射和致命进程崩溃仍需后续强隔离方案。
目前仅面向受审查的官方代码，不作为任意第三方 Python 的安全执行器。

## 配置与本机接口

默认配置文件为当前 SQLite 数据文件同目录的 `plugin-state.json`；源码模式可通过 `LEISURELOG_PLUGIN_STATE_PATH` 单独指定。
文件只存格式版本、配置代数和启用 ID/授权，不保存运行线程、代码路径或原始活动。
临时文件与目标文件在同目录，刷盘后原子替换；代数不一致拒绝写入。一个数据目录只允许一个管理宿主；源码多进程模式不提供跨进程配置锁。
完整 ZIP 备份已包含 config/plugin-state.json，单独的 .db 下载不包含它。没有配置文件时备份明确记录当前默认集合；已有损坏文件保留原文，超过 1 MiB 拒绝处理。恢复方法见 [存储说明](storage.md)；独立包版本及其他环境配置仍需另存。

| 接口 | 用途 |
|---|---|
| GET /api/plugins | 实际运行状态、配置代数、声明权限与依赖 |
| GET /plugins | 核心常驻的管理页面，空集合和全部停用时也可访问 |
| GET /api/plugins/{id}/plan | 无副作用的启用、停用或撤权计划；接受 operation、permission 和 expected_revision |
| POST /api/plugins/{id}/enable | 启用登记的插件及依赖，接受 grants 与可选 expected_revision |
| POST /api/plugins/{id}/disable | 停用；有依赖方时需显式 cascade=true |
| DELETE /api/plugins/{id}/permissions/{permission} | 撤销权限并共同停用该插件及依赖方 |

启用诊断插件的请求示例（仅适用于已登记该定义的隔离开发实例）：

```json
{
  "grants": {"leisurelog.diagnostics": ["activity.summary.read"]},
  "expected_revision": 0
}
```

重新启用已经撤销授权的插件需要重新提交授权；缓存的旧读取接口不会随新实例恢复访问。
宿主定义可声明额外必需权限；它们必须属于该插件声明，并在工厂执行前校验。计划与实际启用共用政策，不以运行插件工厂探测权限。官方游戏分析必需汇总与游戏统计读取，活动详情与人工类型写入可取消；仅保存人工类型时还需要详情权限。正在运行的依赖沿用实际授权，失败重试沿用保存的选择，不自动扩大范围。
状态接口分别返回本次 `permissions` 和已保存的 `saved_permissions`。网页提交计划中的配置代数，拒绝过期操作；网络失联后只读取状态，不自动重复发送修改。
404 表示未登记，409 表示依赖/兼容/授权/运行状态冲突，503 表示本次配置未能保存；参数错误返回 422。
桌面入口仍要求本地会话及允许的请求来源，首次引导未完成时拒绝管理写操作。

源码组装示例：

```python
from importlib import import_module
from pathlib import Path
from leisurelog.adapters.plugin_manifest import read_plugin_manifest
from leisurelog.domain.plugin_runtime import PluginDefinition
from leisurelog.main import create_app

manifest = read_plugin_manifest(Path("integrations/plugins/examples/diagnostics.json"))
diagnostic = PluginDefinition(
    manifest,
    lambda context: import_module("leisurelog_plugins.diagnostics").create(context),
)
# settings 必须指定已经迁移到 0013 的隔离数据库与规则路径。
app = create_app(settings, plugins=(diagnostic,))
```

固定绑定由宿主组装，不从 JSON 动态导入字符串；工厂中的延迟导入也受启动调用预算控制。
现有插件例子中 game-library、game-analysis、theme-pack 仍是未来描述，不能据此启动真实功能。

## 验证与后续

`tests/test_plugin_runtime.py` 使用真实线程验证归属、重复启用、停止超时、权限撤销、资源上限、共享分类预算、代数与恢复。
`tests/test_plugin_state.py` 验证原子写失败、旧文件保留、过期代数及歧义/未知配置拒绝。
`tests/test_plugin_api.py` 使用真实 FastAPI 和隔离 SQLite，验证诊断读取、重启恢复、规则重载、人工优先，以及插件异常/无效结果/超时后核心仍保存原始活动、生成 Session 并继续同步。
默认旧功能仍需通过完整回归，不能仅凭插件用例宣布兼容。

Playnite 资料/识别、游戏统计/偏好与页面贡献已通过迁移对照，既有游戏路由例外已经删除。管理页的隔离 API 和实际浏览器验收见 `tests/test_plugin_management.py` 与 [本机插件管理](plugin-management.md)。
主题包贡献、真实插件安装、独立包回退与第三方隔离仍待实现。本机管理页面不等同于可下载、安装任意插件的中心。官方功能完整流程和后续安装门槛见 [核心与官方功能验收](core-integrity.md)。

参考：[Python 线程限制与 join](https://docs.python.org/3.13/library/threading.html#threading.Thread.join)、
[os.replace](https://docs.python.org/3.13/library/os.html#os.replace)。
