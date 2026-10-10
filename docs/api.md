# 基础接口索引

[返回项目首页](../README.md)

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

## 完整接口文档

服务启动后打开 [本机交互接口文档](http://127.0.0.1:8001/docs)。它由当前代码生成，包含每周回顾、重复条目合并、存储与备份等全部接口。
具体功能的接口与参数也记录在 [功能说明](features.md) 和 [存储说明](storage.md) 中。
