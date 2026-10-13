# 开发与验证

[返回项目首页](../README.md)

## 验证与当前工程边界

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\alembic.exe check
```

测试使用临时数据库和模拟 HTTP，不连接真实 ActivityWatch。覆盖幂等、原始版本留存、人工覆盖持久性、规则恢复、Session 间隙与重叠、活动切换、多设备隔离、时间验证、失败回滚、上游离线、迁移升降级以及 ORM/schema 一致性。真实联调状态见 [验证记录](verification.md)。

普通同步和本次记录纠错已按受影响 source/device/stream 的连续时间范围重建，未变化的数据跳过派生重写。明细列表在 SQL 中分页，日视图只加载重叠当天的记录。完整重处理、全局识别规则变更和游戏目录变更仍使用完整重建，极度碎片化导入也会回退完整重建；详见下方增量处理说明。自动同步先读取上游，再获取数据库写锁；手动同步仍在持有写锁时等待上游响应，大批量写入会阻塞其他写入。数据会包含窗口标题和源提供的 URL，请把 `data/` 当作个人数据保管，默认已加入忽略列表。

ActivityWatch 接口依据：[官方 REST 文档](https://docs.activitywatch.net/en/latest/api/rest.html) 与 [官方服务端实现](https://github.com/ActivityWatch/aw-server/blob/master/aw_server/api.py)。这里通过 Adapter 封装 HTTP，后续可以替换成官方客户端实现，不影响 domain / services。

## 已知待修复问题（2026-10-10 检查）

以下三项问题已用独立测试数据复现，仍待修复；旧版周回顾指标接口保留相应边界：

1. 深夜娱乐按整个 Session 的有效时间比例估算，可能将 0–5 点内的离开时间误计入。
2. 每周回顾的“最长的一次”按每日裁剪后的片段取最大值，跨午夜的连续 Session 会被低估。
3. Playnite 封面按进程匹配时忽略标题条件，共用进程可能关联到其他游戏的封面。

v0.3 已修复自动备份依赖同步成功的问题，验证纳入默认收集的 `tests/test_backup_worker.py`。其余复现保存在 `tests/review_cases.py`，该名称不会被默认自动测试收集。修复前单独运行它，预期仍有 3 项失败：

```powershell
New-Item -ItemType Directory -Force .tmp | Out-Null
.\.venv\Scripts\python.exe -m pytest tests/review_cases.py -q --basetemp .tmp/review-cases
```

2026-10-10 检查时的 192 项后端测试和 16 项 Node 界面行为测试通过。2026-10-12 v0.2 最终验证为 **224 项后端测试、20 项 Node 测试通过**，同时完成真实备份副本和正式库迁移核验；完整证据见 [验证记录](verification.md)。这不代表上述边界问题已修复。

v0.3 完整回归为 **249 项后端测试、21 项 Node 测试通过**，新增只读预览、人工保护、过期预览、分页分组、跨午夜 AFK、撤销冲突/回滚/网页拆分/规则顺序、项目累计目标及独立备份验证。真实库副本与正式库升级至 0013 均保留既有数据，运行检查见 [v0.3 使用说明](confirmation.md) 与验证记录。


## 临时产物约定

测试和构建的临时文件集中在 `.tmp/`、`build/`、`dist/` 或 `outputs/`，不放进 `src/`、`config/`、项目根目录或正式 `data/`。
这些目录及开发缓存已加入 Git 忽略列表。临时数据库应与正式数据库分开，验证结束后可以删除。
`src/leisurelog.egg-info/` 是当前 editable 安装使用的包元信息，本机运行环境中保留，不作为普通缓存删除。
历史截图在本机 `docs/screenshots/`，验证记录中的 `work/` 路径和旧预览路径是当时的记录，不是当前程序的运行依赖。
