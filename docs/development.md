# 开发与验证

[返回项目首页](../README.md)

## 验证与当前工程边界

```powershell
python scripts/check_architecture.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe check
```

测试使用临时数据库和模拟 HTTP，不连接真实 ActivityWatch。覆盖幂等、原始版本留存、人工覆盖持久性、规则恢复、Session 间隙与重叠、活动切换、多设备隔离、时间验证、失败回滚、上游离线、迁移升降级以及 ORM/schema 一致性。真实联调状态见 [验证记录](verification.md)。

可执行分层、相对导入与循环依赖检查，以及受限插件接口见 [模块边界与最小接口](plugin-boundaries.md)。自动检查配置位于 `.github/workflows/checks.yml`，覆盖 Windows / Python 3.11、3.13 与前端脚本。公开上一版的远端检查已通过；本轮本地检查单独记录，不沿用旧版成绩，分支保护尚未设置。

当前源码已接入运行管理器，默认以官方模块保留 Playnite 接入，保存的停用选择优先；显式 `plugins=()` 提供空集合实例。测试与接入见 [运行管理](plugin-runtime.md) 和 [游戏迁移对照](game-plugin-migration.md)。开发与测试仍必须显式使用隔离数据目录。

普通同步和本次记录纠错按受影响 source/device/stream 的连续时间范围重建，未变化的数据跳过派生重写。明细在 SQL 中分页，日视图只加载重叠当天的记录。完整重处理、全局规则和游戏目录变更仍使用完整重建，极度碎片化导入也会回退完整重建。手动与自动同步都先读取上游，再获取数据库写锁，共用批次写入逻辑；实际写入和重建期间仍会串行占用写锁。数据含窗口标题和 URL，请把 `data/` 当作个人数据保管，默认已忽略。

ActivityWatch 接口依据：[官方 REST 文档](https://docs.activitywatch.net/en/latest/api/rest.html) 与 [官方服务端实现](https://github.com/ActivityWatch/aw-server/blob/master/aw_server/api.py)。这里通过 Adapter 封装 HTTP，后续可以替换成官方客户端实现，不影响 domain / services。

## 已修复的历史边界问题（2026-10-18）

2026-10-10 发现的下列问题已按独立固定输入复现并修复：

1. 凌晨时长现在对 `[00:00, 05:00)` 内的窗口与 AFK 求实际交集，再应用人工/规则的计时策略，不再按整个 Session 的比例估算。
2. 最长连续 Session 按相同 ID 合计本周内各日片段；跨午夜不截短，跨周只计算该周部分。
3. Playnite 封面匹配保留进程标题条件。缺少证据时不关联；默认回归位于 `tests/test_official_covers.py`。

v0.3 已修复自动备份依赖同步成功的问题，覆盖于 `tests/test_backup_worker.py`。旧 `tests/review_cases.py` 已迁移至默认收集的 `tests/test_review_timing.py`，包括跨日、跨周、凌晨 AFK、人工保留 AFK 和改分类场景：

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
.\.venv\Scripts\python.exe -m pytest tests/test_review_timing.py -q --basetemp .tmp/review-timing
```

历史版本的回归记录保留在 [验证记录](verification.md)。本轮验收与维护边界见 [稳定性收尾](stability.md)，使用和恢复见 [日常维护](maintenance.md)。不能仅凭以前回归通过推断本轮也已通过。

v0.3 完整回归为 **249 项后端测试、21 项 Node 测试通过**，新增只读预览、人工保护、过期预览、分页分组、跨午夜 AFK、撤销冲突/回滚/网页拆分/规则顺序、项目累计目标及独立备份验证。升级前应独立备份并核对结构和数据保留，运行检查见 [v0.3 使用说明](confirmation.md) 与验证记录。


## 临时产物约定

测试和构建的临时文件集中在 `.tmp/`、`build/`、`dist/` 或 `outputs/`，不放进 `src/`、`config/`、项目根目录或正式 `data/`。
这些目录及开发缓存已加入 Git 忽略列表。临时数据库应与正式数据库分开，验证结束后可以删除。
`src/leisurelog.egg-info/` 是当前 editable 安装使用的包元信息，本机运行环境中保留，不作为普通缓存删除。
历史截图在本机 `docs/screenshots/`，验证记录中的 `work/` 路径和旧预览路径是当时的记录，不是当前程序的运行依赖。
