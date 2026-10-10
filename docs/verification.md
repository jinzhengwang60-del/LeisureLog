# 验证记录

[返回项目首页](../README.md)

## 2026-10-10 公开源码验证

验证环境为 Windows / Python 3.13.9，数据库迁移单一 head 为 `0011`。

- 192 项后端自动测试通过。
- 16 项 Node 界面行为测试通过，覆盖风格切换与真实时间天空变化。
- Ruff 代码检查及 Python 依赖一致性检查通过。
- 目录整理后另运行 6 项架构、静态页面和备份恢复检查，全部通过。
- 公开文件逐一与已保存的源码提交核对，文档、图片、字体和许可证一并检查。

测试使用独立临时数据库与模拟来源。活动数据库、游戏库导出、运行日志、备份、
本机历史截图和私人联调记录不包含在公开仓库中。

## 已知问题

现有测试通过不代表所有边界均正确。另有 4 项独立问题复现仍然失败：

1. ActivityWatch 离线导致同步失败时，本轮自动备份检查不会执行。
2. 深夜时长按 Session 有效时间比例估算，可能将深夜离开时间计入。
3. 每周回顾的最长 Session 按每日裁剪片段取最大值，跨午夜时会低估。
4. Playnite 封面进程匹配忽略标题条件，共用进程可能关联到其他游戏。

详细复现方式见 [开发与验证](development.md)。`tests/review_cases.py` 不被默认测试收集；
单独运行时，修复前预期有 4 项失败。本次提交保留这些复现，未修复对应业务实现。

## 复现检查

在已经创建运行环境并安装开发依赖的项目目录中执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests migrations scripts integrations
.\.venv\Scripts\python.exe -m pip check
node --test tests/js/appearance.test.cjs tests/js/sky-clock.test.cjs
```

Node 用于独立界面行为测试；日常运行 LeisureLog 无需安装 Node。
三年性能样本可通过 `scripts/benchmark_processing.py` 在独立临时数据库复现。
