# 觅码 · 后续模块开发流程（路线图）

日期：2026-09-21 · 用途：`新一轮完善.txt` 八项需求的落地顺序总纲，指导后续各批次 spec 与 plan 的开展
状态：第一批（安全基线）代码完成（含两轮审查修复，215 后端测试全绿），待提交/push 部署；第二至六批未启动
修订：2026-09-22 按路线图审查结论修订——状态刷新、事实纠偏、三处口径统一、隐藏工程上提、前置决策补齐

## 1. 背景与读法

新一轮完善提出八项需求（安全防护 / 管理端 / 用户反馈 / 内嵌评论区 / 作者获星点赞提醒 / 精确筛选 / 手机端优化 / SEO）。经依赖分析归为 **六个批次**：批内默认串行（下文标注「可并行」者为例外），批间有依赖，部分批次互相独立可并行。

本文档是**批次索引与开展要点**，不是设计文档。每批启动时按仓库惯常工作流落两级文档：

1. **spec**：`docs/superpowers/specs/<日期>-<主题>-design.md`（头部带日期/状态/需求来源/上游依据 spec 链接；必含决策记录表、非目标 YAGNI、测试策略、风险表）；
2. **plan**：`docs/superpowers/plans/<对应主题>.md`（Goal / Architecture / Tech Stack / Global Constraints / 按 Task 拆分，TDD 步骤，每任务 Files + Interfaces）。

实现由 subagent 按 plan 逐任务执行，过程产物落 `.superpowers/sdd/<spec 日期-主题>/`。

**一句话顺序**：

> 安全基线 → 评论区 → 反馈渠道 → 管理端 → 作者提醒 →（精确筛选 ∥ 手机端）→ SEO

## 2. 八项需求 → 六批次映射

| 需求 | 模块 | 批次 |
|---|---|---|
| 1 安全防护 | 安全基线（限流 / CSRF / nginx 头 / CI 门禁） | 第一批（代码完成，待部署） |
| 4 内嵌评论区 | 评论区 | 第二批 |
| 3 用户反馈渠道 | 反馈渠道 | 第二批（与评论区同构，可并行） |
| 2 管理端 | 管理端 | 第三批 |
| 5 作者获星点赞提醒 | 作者提醒 | 第四批 |
| 6 精确筛选仓库 | 精确筛选 | 第五批（零依赖，可插队） |
| 7 手机端优化 | 手机端 | 第五批（与精确筛选互相独立） |
| 8 SEO 优化 | SEO | 第六批 |

## 3. 依赖关系

```
安全基线 ──┬─> 评论区 ──┬─> 管理端（评论过筛）──> SEO（/admin noindex、URL 结构稳定）
          │            └─> 作者提醒（回复通知）
          └─> 反馈渠道 ──> 管理端（反馈收件箱）
精确筛选：零依赖，可插队任何空档
手机端：宜在新页面批量就位后统一走查，避免每来一个新页面返工一轮
SEO：robots/sitemap/JSON-LD 依赖 URL 结构稳定（第二、四批之后）；基础 meta 已随手完成
```

排序的两条主线：

- **评论区是一切 UGC 的数据底**：管理端的评论过滤、作者的回复提醒都挂在 comments 表上，必须先行；
- **安全基线必须先行**：站点已上线，LLM 计费端点（`/api/ai-draft`、解读域四端点）原本无配额；评论区/反馈/管理端都会成倍放大攻击面与写库面，先把限流/安全头/CI 门禁立好，后续功能长在底座上，不做返工。

## 4. 批次状态表（随推进更新）

| 批次 | 内容 | 状态 | spec | plan |
|---|---|---|---|---|
| 一 | 安全基线 | 代码完成（8 commits + 两轮审查修复，后端 215 测试全绿）；**待提交/push 部署 + 服务器 nginx reload** | `specs/2026-09-21-觅码-安全基线-design.md` | `plans/2026-09-21-觅码-安全基线.md` |
| 二 | 评论区 → 反馈渠道 | 评论区代码完成（11 Tasks，前后端全绿）；反馈渠道未启动 | `specs/2026-09-24-觅码-评论区-design.md` | `plans/2026-09-24-觅码-评论区.md` |
| 三 | 管理端 | 未启动 | — | — |
| 四 | 作者获星点赞提醒 | 未启动 | — | — |
| 五 | 精确筛选 ∥ 手机端 | 未启动 | — | — |
| 六 | SEO | 未启动（基础 meta 已随第一批完成） | — | — |

## 5. 各批次开展要点

### 第一批 · 安全基线（代码完成，待部署）

- 产出：`backend/app/security.py`（内存滑动窗口限流 + Origin 白名单校验，零新依赖）、nginx 安全响应头 + `/explain-api/` XFF 修复、CI `test` 门禁（`deploy needs: test`）、`index.html` 基础分享 meta、runbook 第 13 节（手动 reload / 验证 / 调参 / 回滚）。
- 审查修复记录（第一轮）：`/api/roots`（通用概念根，同样烧 LLM）与 `GET /api/my/github-repos`（打 GitHub API）补入分桶；CSP 补 `media-src https:`（README 视频渲染）。
- 审查修复记录（第二轮，2026-09-22，未提交）：限流键带桶名（`f"{bucket}:{rate_key}"`，修复跨桶共享计数器——browse 流量会吃掉 llm 配额）；限流器满额改拒新键（先清全过期键再拒），修复键洪水可重置受害者配额；CSP 补 `object-src 'none'`。补 4 条回归用例（跨桶隔离 / 满额拒新 / 既有键不重置 / 过期清槽）。
- **遗留待办**：①第二轮修复 3 文件未提交；本文档、第一批 spec/plan、`新一轮完善.txt`（GB18030，宜转 UTF-8）均 untracked，**审计链断裂，合批入库**；②提交 push 后合回 `feat/frontend-ui` 触发部署；③nginx 手动 reload 后按 runbook §13.2 curl 验证 6 个安全头（CSP 逐项含 object-src / media-src）。

### 第二批 · 评论区 → 反馈渠道

**评论区（先行，核心数据底）**

- 数据模型：`comments` 表（repo_id / user_id / parent_id / content / status / created_at），status 状态机 `pending → visible / hidden / deleted`；先做两层「评论 + 回复」，不做无限嵌套。
- 渲染 sanitize 白名单与 README 一致（`components/ReadmeSection.tsx` 的 rehype-sanitize 方案），防存储型 XSS。
- 替换 `RepoPage.tsx:222-229` 的 giscus 占位；`discussions_open` 探测（`repos.py:68-81`）可退役。
- 安全衔接：`POST /api/repos/{id}/comments` 等新端点必须进 `security.py` 的 `_RATE_RULES` 分桶；验证码在 spec 非目标中已约定「评论区上线后再按需评估」。
- 移动端：建造时即按移动优先（第五批统一走查验收）。

**反馈渠道（与评论区同构，可并行）**

- `feedback` 表（user_id 可空 / type=bug|idea|other / content / contact / status）+ 页脚或悬浮入口表单 + 提交确认。
- 复用评论区的「表 + 表单 + 限流 + 管理端预览」模式，边际成本低。

- 执行记录（2026-09-24）：评论区 11 Tasks 落地（含 spec 计划期修正两项：API 扁平化防 delist 桶冲突、分页对象定为顶层线程）；LLM 异步预审接 `feed/llm.py`；`moderate` cron 待部署后挂载。
- 终审挂账（第三批顺手项）：conftest 级 `_no_bg_file_db` 上收、`moderate_pending` 补 `ORDER BY created_at ASC`、评论区「加载更多」分页 UI、作者判定三处内联（repos.py/submit.py/comments.py）抽单点。

### 第三批 · 管理端

- 管理员鉴权：`users` 表加 `is_admin`，或 `ADMIN_LOGINS` 环境变量白名单（更简，先白名单）；`/admin` 路由组 + `require_admin` 依赖；前端新页面组（可声明桌面优先，降手机端工作量）。
- 四个页面：
  1. **仓库上下架管理**——把 delist（现为 owner **或认领者**可操作，`submit.py:180`）扩展为管理员可操作；**状态流转管理拆独立 Task**：现状态机只有 delist 一条边（published / pending_claim / delisted），扩成双向流转涉及误操作恢复与审计留痕，勿并进页面 Task；
  2. **评论过滤队列**——消费第二批 comments 的 status；
  3. **反馈收件箱**——消费第二批 feedback，bug/idea 状态流转；
  4. **监控看板**——底料已现成：曝光/浏览计数体系 + `feed/jobs/report.py` 达标率日报。
- **LLM 用量记账（独立 Task，勿折叠进看板）**：当前 ai-draft / 精筛无任何花费落账（`llm.py` / `screening.py` 零埋点），需埋点 + 用量表 + 聚合查询，量级接近反馈渠道本身，不是一个括号注释。**决策留痕**：此项显式推翻 `2026-08-24-觅码-收录与浏览-design.md`「指标本身即监控，不额外建看板」——需求 #2 要求网站监控故扩 scope，须写入本批 spec 决策记录表。
- SEO 衔接：`/admin` 全站 noindex（第六批前置依赖）。

### 第四批 · 作者获星点赞提醒

- `notifications` 表；触发点两处现成：点赞在 `_set_interaction_row`（`me.py:102-110` INSERT 分支）、回复在第二批的评论插入路径。
- **里程碑通知去重（spec 前置决策，不定稿 plan 会卡壳）**：`repos` 表只有当前 stars 快照、无 star 历史，「首星 / 10 / 50 / 100 已通知过」必须有落点——建议 `notifications` 表 `(user_id, repo_id, kind, milestone)` 唯一约束，插入即幂等。
- **获星走定时比对，不上 GitHub webhook**：当前 submitted 仓库的 stars 仅在投稿时刷一次（`submit.py:140`），crawl 对已入库仓库整体跳过（`feed/jobs/crawl.py:28-40`）——需一个 star 同步 job 顺带刷新 submitted 仓库 stars 并生成里程碑通知。webhook 方案要 repo scope + 公网 endpoint，成本过高，不做。定时侧复用 runbook 既有 cron 模式（采集/日报同款），加一行即可。
- 前端：TopBar 铃铛 + 通知中心（未读徽标）。
- 顺序理由：放在管理端之后——先有内容治理通路（评论过滤），再放大作者侧触达，否则垃圾评论会直接变成通知 spam。

### 第五批 · 精确筛选 ∥ 手机端（互相独立，可并行）

**精确筛选（零依赖，也可提前插队）**

- `/api/feed`、`/api/search` 扩展过滤参数：language / min_stars / topics / 时间范围；SQL WHERE 扩展，现有 FTS5 trigram + LIKE 回退逻辑不动。
- 前端首页筛选面板（分类胶囊旁，抽屉或下拉）。
- **硬约束（写入本批 spec 决策记录表首条，不是注意事项）**：允许的过滤参数收敛成白名单——URL 参数一旦放出即被外链固化、无法回收，与第六批 canonical / sitemap 直接耦合。

**手机端（存量走查 + 新页面验收）**

- **TopBar 手机导航断裂（可插队，不依赖任何新页面）**：≤720px 时 `.topbar-nav` / `.btn-submit` / `.search-btn` 被 `display:none` 整体隐藏（`components/TopBar.css:133`）且无汉堡/抽屉替代入口——导航与投稿入口在手机上**彻底消失**，是功能性断裂而非样式问题。一条组件 Task 的量级，建议提前做，不必等本批。
- 其余已知问题清单：投稿向导步骤流；仓库页文件树双列（`RepoPage.css:55-57` 单列堆叠点）；**解读画布 d3-force 触屏手势**（拖拽/缩放，`explain/` 模块）是难点。
- 新页面（评论区 / 反馈 / 通知中心）在前批建造时即按移动优先（**管理端例外**，见第三批），本批统一走查验收，避免每来一个新页面返工一轮。

### 第六批 · SEO

- 基础 meta 已随第一批完成（OG/Twitter/canonical，og:image 暂用 icon-512）。
- 本批内容：`robots.txt` + **动态 sitemap**（published 仓库 + 公开用户页；排除 `/admin` 与 `/submit`）+ JSON-LD（SoftwareSourceCode）+ 预渲染评估（首页/热门仓库页静态化；SSR 迁移太重，不做）。
- **两个衔接约束**：
  1. **CSP `script-src 'self'` 禁内联脚本**（nginx 已上线）——JSON-LD 是内联 `<script>`，必须用 nonce/hash 或同步调 CSP 头（改 nginx 需手动 reload，见 runbook §13）；
  2. URL 结构在第二、四批就位后才稳定，sitemap 与预渲染一次到位；评论区 UGC 文本此时也成了可索引内容。
- 分享 banner（1200×630）制作可替换 og:image。

## 6. 跨批次流程清单（每批必过的检查点）

1. **新端点进分桶**：`security.py` 的 `_RATE_RULES` 按新端点补桶（LLM 计费点 → `llm`，GitHub 重操作 → `submit`，UGC 写 → 新桶或 `interact`），配 test_security 用例；第一批审查修复（`/api/roots`、`my/github-repos`）即此类的教训。
2. **UGC 三件套**：评论/反馈落地前定稿 sanitize 方案、限流桶、状态机（pending/visible/hidden/deleted），管理端消费路径同步设计。
3. **移动优先建造**：新页面按移动优先实现（**管理端例外**：桌面优先、降手机端工作量），第五批统一走查，不提前做全站移动优化。
4. **noindex 范围**：管理端与登录后私有页在第六批前确定清单。
5. **CSP 是上线态**：任何内联脚本（JSON-LD 等）或新外域资源需同步改 `deploy/nginx-meecode.conf` 并手动 reload；改完按 runbook §13.2 验证。
6. **CI 门禁已就位**：`deploy needs: test`，每批合回 `feat/frontend-ui` 前必须全绿（pytest + typecheck + vitest）。
7. **分支纪律**：每批从 `feat/frontend-ui` 切 `feat/<批次名>` 开发，CI 全绿后合回；部署分支不堆半成品。
8. **spec 上游链**：每批 spec 头部链接上游依据（第一批起：安全基线 → 评论区 → 管理端/作者提醒；收录与浏览 / 信息流全链路为共同上游）。

## 7. 第一批执行记录（留档）

- 提交序列（`feat/security-baseline`，未 push）：
  1. `9a9bda4` config 安全段（限流分桶参数 + Origin 白名单）
  2. `724e31d` security.py：内存滑动窗口限流 + Origin 校验 + 16 个新用例（conftest autouse 关闭限流保护存量）
  3. `7aa9bd9` main.py 挂载，层序 security 内 CORS 外（429 带 CORS 头）
  4. `f390e83` CI test 门禁 job（pytest 注入 `LLM_MOCK=true GITHUB_MOCK=true`）
  5. `862a3f0` nginx 安全头 + explain-api XFF 修复
  6. `6f120cb` index.html 分享 meta
  7. `c50dec4` runbook 第 13 节（手动 reload / 验证 / 调参 / 回滚）
  8. `de6da37` 审查修复：`/api/roots` 入 llm 桶、`my/github-repos` 入 submit 桶、CSP 补 media-src
- 第二轮审查修复（2026-09-22，未提交）：`backend/app/security.py`（限流键带桶名 + 满额拒新键含过期清扫）、`backend/tests/test_security.py`（淘汰用例替换为 3 条容量用例 + 跨桶隔离回归）、`deploy/nginx-meecode.conf`（CSP 补 `object-src 'none'`）。
- 验证状态：后端全量 **215** 测试全绿（196 存量 + 19 条 test_security）、前端 typecheck / vitest **234** 全绿，均按 CI test job 口径；nginx 响应头待服务器 reload 后按 runbook §13.2 curl 验证。
