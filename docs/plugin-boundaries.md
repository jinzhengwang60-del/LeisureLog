# 可执行的模块边界与最小插件接口

> 本文保留架构开发阶段的设计与验证范围。文中的 `checkpoint/...` 中间标签与 `outputs/...` 证据为本地开发记录，不随公开 Git 历史上传；公开版本的复现与恢复以 [验证记录](verification.md) 和 [回退说明](plugin-rollback.md) 为准。

[设计说明](plugin-architecture.md) · [回退方案](plugin-rollback.md) · [开发验证](development.md)

以下记录边界加固批次。后续运行管理器、授权撤销、真实任务预算及生命周期已在开发分支接入，当前状态与限制见 [运行管理说明](plugin-runtime.md)。
2026-10-15 的 [游戏接入迁移](game-plugin-migration.md) 和 [分析/页面迁移](game-analysis-plugin.md) 已删除下方历史清单的全部 9 处旧耦合例外。
当前只登记 4 处明确的宿主/存储组装许可；新增业务、普通 API 和活动仓库引用仍被拒绝。以下为边界批次的历史说明，当前能力见运行管理文档。

本批在 `feat/core-plugins` 中增加静态依赖检查、公共接口与两种受限调用。
没有改变应用组装、自动同步、分类链顺序、数据库或正在使用的服务。
这是运行管理器接入前的基础，不能据此安装或启用真实插件。

## 依赖检查

`scripts/check_architecture.py` 只解析源码，不导入或执行被检查文件。
递归扫描 `src/` 中的 Python 文件，解析绝对导入、相对导入和包级导入，并检查导入图中的循环。
检查规则也被 `tests/test_architecture.py` 调用，不需要另记一套规则。

| 所在层 | 可以导入的 LeisureLog 层 |
|---|---|
| domain | domain |
| services | domain、services |
| analytics | domain、analytics |
| adapters | domain、adapters |
| repositories | domain、repositories |
| api | 上述六层；可以读取根包的应用/数据库版本常量 |
| plugin_api | domain |

domain、services、analytics 不能直接导入 SQLAlchemy、sqlite3、FastAPI、httpx、requests 或 YAML。
`main`、`runtime` 与 `desktop` 是当前应用的组装/基础设施入口；业务层不能反向导入它们。
现有 API 可以组装服务并管理数据库事务，并不把这些职责转移给插件。

新的插件实现约定放在 `leisurelog_plugins.<包名>`。插件只能通过 `leisurelog.plugin_api` 使用核心接口；
直接导入数据库实现、全局应用、核心私有模块或未列入 `__all__` 的接口会失败。
插件内部可以相互导入。跨插件只能导入已声明依赖的 `api` 公共模块/子包，不能导入它的内部实现。
`check_tree()` 接受宿主提供的包依赖映射；实际发行时，包名、插件 ID 与描述依赖的映射必须由宿主校验。
当前没有真实插件包或加载器，命令行默认不给任何跨插件依赖授权。

插件直接导入数据库、FastAPI 路由、线程、asyncio、进程池或子进程创建接口也会被拒绝；任务与事务应由宿主管理。
核心目前不允许静态导入具体插件；后续加载器需要在专门组装位置实现发现和绑定，不能放到业务层。

检查器登记了 **9 处已有具体游戏实现的依赖**。只保留精确的“引用方 → 实现”例外，新增引用方会失败。
移走原引用后，检查器要求删除对应例外，避免旧豁免长期积累。
这是本次识别出的耦合清单，游戏相关协议、表和分析代码仍在原位置，并未完成整套游戏功能拆分。

AST 检查是开发规则，不是恶意 Python 的安全沙箱。动态导入、运行时反射及第三方库间接访问需要另外审查。
本批的反例测试确认检查器拒绝违规，而不是仅检查当前源码恰好通过。

## 公共接口与受限调用

`src/leisurelog/plugin_api.py` 是插件的公共入口，复用现有 `ActivityEvent`、`Classification` 与 `Classifier`。
不导出原始 `SourceRecord`、完整 Repository、SQLAlchemy 模型或全局 FastAPI app。
类型与协议定义放在 domain；权限调用检查放在 services；后续数据库查询实现由 repositories 提供并由宿主注入。

| 接口 | 已实现边界 |
|---|---|
| SummaryQuery / SummaryReader | 日期与可选用途/项目筛选；日期包含首尾两天，使用宿主时区，没有 90 天或年度范围上限 |
| ActivitySummary / CategoryTotal | 只含有效时长总计及分类分布；不可变、无原始事件、标题、URL 或 SQL 输入 |
| PluginSummaryReader | 调用前验证 analytics 能力和 summary.read 权限；只返回规定的汇总结构 |
| PluginClassifier | 调用前验证 classifier 能力、details.read 与 classification.propose；检查结果格式并由宿主写入来源 |
| ThemeContribution | 描述插件包内 CSS 相对路径；拒绝绝对路径、网络地址、路径穿越及 JS 入口 |
| PluginTask / TaskContext / TaskHandle / TaskBudget | 约定宿主指派的任务归属、合作停止信号、有限预算和明确停止结果 |

汇总读取者只获得注入的汇总提供者。分类器需要活动详情权限，才能收到含应用、标题和 URL 的统一事件。
分类结果来源统一为 `plugin:<插件 ID>@<版本>`，插件提交 `origin="manual"` 也不会冒充人工纠正。
现有 ClassificationPipeline 在调用分类器之前返回人工覆盖；这个行为通过真实分类链与插件包装器联合验证。
分类调用只提出结果，不写数据库。原始数据与人工选择仍由核心持有。

这些包装器可独立调用，但尚未绑定默认程序；测试使用合成提供者。
实际宿主应先通过 Registry 的版本/依赖预检再授予接口，并在停用或撤销权限后撤下调用入口。
当前没有持久化的启用状态、权限撤销管理或插件异常降级；提供者异常仍向调用者抛出，后续运行管理器负责边界处理。

ThemeContribution 只校验路径描述，没有读取或注入 CSS；安装器仍需检查真实文件、符号链接、CSS 外部 URL 和资源总量。
TaskBudget 只验证预算是正的有限数值，尚无调度器执行这些预算。宿主必须分配归属，不能让插件自报归属来领取资源。
`TIMED_OUT` 表示等待结束时任务仍未确认停止，不能当作 `STOPPED`，也不能随后释放它仍在使用的数据库资源。
Python 线程不能靠等待超时被强制终止；同进程官方插件仍需要合作停止，强隔离需要后续进程方案。

## 本地与自动验证

在项目根目录使用已安装项目开发依赖的 Python 环境：

```powershell
python scripts/check_architecture.py
python -m ruff check .
New-Item -ItemType Directory -Force outputs | Out-Null
python -m pytest -q --basetemp outputs/check-temp
node --test tests/js/activity-context.test.cjs tests/js/appearance.test.cjs tests/js/motion.test.cjs tests/js/sky-clock.test.cjs
```

`.github/workflows/checks.yml` 准备了 Windows Python 3.11/3.13 与 Node 24 自动检查，使用现有依赖锁定版本。
本批仅本地验证，不触发 GitHub 工作流，也没有修改仓库分支保护；推送后仍需核对首次远端执行结果。
发布时仍通过清理过的公开副本提交文件，不能直接上传包含私人维护记录的本机 Git 历史。

后续第一项是实现宿主注册、任务启动/停止及异常状态，再将游戏资料接入替换为接口注入。
验收要覆盖重复启动、停止超时、插件抛错、依赖停用和核心持续采集；不会用本批协议测试替代实际生命周期测试。

参考：[Python 相对名称解析](https://docs.python.org/3.13/library/importlib.html#importlib.util.resolve_name)、
[线程与等待超时](https://docs.python.org/3.13/library/threading.html#threading.Thread.join)、
[官方 checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)、
[setup-node](https://github.com/actions/setup-node)。
