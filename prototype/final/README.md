# 管理端定稿模版 · Grail × Notion

> 主题：**Holy Grail 三栏骨架** × **Notion 米白暖色**
> 状态：六页定稿，可直接作为 Vue 端重构的视觉基准。

## 文件

| 文件 | 页面 | 对应后端路由前缀 |
|---|---|---|
| `index.html` | 岗位库（待办/待审/待归属/岗位列表） | `/admin/positions`、`/admin/todos`、`/admin/jds/orphan` |
| `position-detail.html` | 岗位详情（JD 列表 + 导入 JD + 工序留档抽屉） | `/admin/positions/{id}/jds`、`/admin/jds/{jd_id}` |
| `model-review.html` | 模型审核（Σ 校验 + 证据面板 + 可编辑模型树） | `/admin/positions/{id}/model`、`/admin/models/{id}/confirm` |
| `version-history.html` | 版本历史 + 版本 diff | `/admin/positions/{id}/versions`、`/admin/models/{id}/diff` |
| `dict.html` | 能力词典（筛选 + 新增/编辑/合并/删除） | `/admin/dict`、`/admin/dict/merge` |
| `users.html` | 用户管理（新建/启停/重置密码） | `/admin/users` |
| `grail-notion.css` | 共享设计令牌（颜色/按钮/表格/标签/右栏卡片等） | — |

## 主题令牌（grail-notion.css）

- **底**：`--deck:#f7f6f3` 米白台底；**栏体**：`--panel:#ffffff`
- **墨**：`--ink-1:#37352f` / `--ink-2:#6f6e69` / `--ink-3:#9b9a97`
- **粉彩状态**：绿 `#448361/#edf3ec`、琥珀 `#cb912f/#fbf3db`、红 `#e16259/#fdebec`、蓝 `#337ea9/#e7f3f8`、灰 `#f1f1ef`
- **主按钮**：深墨 `--ink-1`（不是蓝）——Notion 习惯
- **字号**：正文 14px / 表格 13px；**圆角**：卡片/表格 8px、tag 10px、按钮 5px
- **骨架**：`grail-head`(50px) / `grail-body`(左 200px / 中自适应 / 右 268px) / `grail-foot`(30px)
- 页面彼此独立滚动（body `overflow:hidden`），右栏上下文常驻

## 原型里对 Element Plus 版做的几处有意 UX 调整

1. **页面顶部"刷新"按钮**替换成页头 meta 行（`3 个岗位 · 53 份 JD · 更新于 …`）——信息密度更高
2. **待办从顶栏大卡挪到右栏常驻 callout**——中栏纵向空间让给数据
3. **行内操作默认 35% 透明**，行 hover 时浮现——减少表格视觉噪音
4. **Dict 页别名/排除项**用 mini-tag（灰/浅红区分排除项）
5. **模型审核 Σ 条**从"红/绿 el-tag"改成完整读数条（label + 进度 bar + 数值 + 容差提示）
6. **版本 diff**用彩色 tag + 删除线/加粗对照（替换 Element Plus 的彩色左边框）
7. **新建账号角色**从 radio 改成双选项卡（候选人 / 管理员 各带一句描述）

## 已注入的样例数据说明

- 岗位库 3 岗（后端开发 active / AI Agent stalled / 高级后端待审）——来自设计文档 §6 的样例
- 模型审核用 AI Agent 岗位 stalled 场景，展示 2 个待裁决项 + Σ=97.5% 不足的状态
- 版本 diff 展示 v1→v2：1 新增（向量数据库）+ 2 字段变更（RAG 等级与权重、跨协作重要性）
- 用户管理 6 个示例账号（含当前 admin 与停用账号）

## 未做（本期范围外）

- 登录/注册页
- 候选人端页面
- M4（黄金集 / 浏览器插件）
