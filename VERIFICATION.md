# 验证记录

当前公开源码版本已通过 172 项自动测试，代码规范检查通过，数据库迁移单一 head 为 0011。

测试覆盖数据接入、幂等与原始版本、人工覆盖优先、网页关联、Session 合并、AFK 与计时策略、跨日统计、作品库、Playnite 资料解析、游戏类型与偏好、事务回滚、备份恢复、迁移升降级、增量处理、待分类页面接口、时间线接口、规则重新加载与标题匹配。

测试使用临时数据库及模拟来源；不依赖或包含私人活动数据库。公开仓库不包含本机活动截图、游戏库导出、运行日志、备份和私人联调记录。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests migrations scripts/benchmark_processing.py
```

三年性能样本可用 scripts/benchmark_processing.py 在独立临时数据库中复现；它验证增量结果与完整重处理一致。样本测量与使用边界见 README。
