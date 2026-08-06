# graphboard

多 agent 科研工作流的图上自动机：一个 MCP server + CLI，在 SQLite 中维护任务图
（节点 + 边），用转移文法裁决节点的派生与生效。控制状态外化到库里，LLM 会话
保持最小上下文；人是调度器，乐观并发，冲突靠廉价重定位消化。

## 它解决什么场景

你在做一个 AI 研究项目，脑中有了创新点。没有 graphboard 时的日常：开着一堆
agent 会话，手动在会话之间复制粘贴上下文，看板笔记散落在仓库里，改一次方向
要挨个通知，agent 的上下文越聊越脏、越聊越笨。

有 graphboard 之后，同一个项目变成这样：

```
你 × gb（导演）  ：「这个项目要做 X，先要一个提案角色」→ gb 起草角色，你确认，落盘
你 × 提案 agent  ：讨论 idea，把它结晶成提案节点 → 你批准
你 × 实现 agent×2：各说一句「pull 你的节点」，两个脑子并行开工，互不干扰
你 × 审阅 agent  ：pull 审阅节点，gb_query 聚合两个分支的产出，裁决通过或打回
中途想法变了     ：直接说，agent 用 note 吸收；节点太大，agent 用 gb_split
                  拆成细原子，其他 agent 来认领碎片
```

你全程只做三类动作：**批准**（决定什么该发生）、**转向**（公告/文法/改 spec）、
**加人手**（开新会话切角色）。会话之间零复制粘贴——它们共享的是图，不是聊天记录。

对应最初的四个痛点：

| 痛点 | 机制 |
|---|---|
| 上下文污染 | 会话常驻 = 身份 + 当前节点 + anchor；其余按需查询，预载即污染 |
| 人类介入困难 | 文法改一处影响所有未来裁决；公告在下次 pull 强制注入 |
| 仓库污染 | board 收进 `.board/`（gitignore）；代码产出留仓库，协调产出进 workdir |
| 多 agent 协调混乱 | 图是唯一事实源；认领原子化不撞活；角色分离 = 上下文分离 |

**图是开放的**：节点类型、角色、转移规则全是项目数据。AI 项目可以长成
「提案→执行」，产品项目可以长成「设计→实现→测试」——由 gb 导演按项目塑形。
任务怎么切，上下文就怎么切：你脑中完成「设计与实现的分离」的那一刻，
agent 们也获得了同样干净的分离。

## 设计理念

1. **人是调度器，不是自动化**。系统不替你决策；它放大你的决策——批准、转向、
   加人手，每个动作一次生效、全局可见。
2. **控制状态外化**。agent 是健忘的一次性脑子，图是项目的长期记忆。会话死了
   重开，pull + anchor 无缝接上。
3. **控制面与信息的解耦**。边只记谱系（谁派生了谁），不决定你该读什么；
   装载靠查询（gb_query 三层旋钮：清单 → 读文件 → 不读）。
4. **创建自由，生效受控**。任何 agent 可以提案（proposed），生效要过文法裁决
   或人批。默认 approve——安全方向上的最大自由。
5. **蒸馏，不倾倒**。跨会话过界的只有蒸馏物（角色文件、契约、产出指针），
   对话永远不过界。
6. **乐观并发**。共享工作副本，不隔离不锁；冲突靠 git 基线 diff 廉价重定位。
7. **server 无域，项目皆数据**。换领域不改一行代码；角色和文法随项目生长。

## 前置条件

- **Python ≥ 3.10**
- **opencode**——目前唯一适配的宿主：`gb init` 生成的是 opencode 的角色文件、
  MCP 配置与权限门控。MCP 层本身是标准协议（其他客户端可手动接线），但脚手架
  与治理门控暂不为其他宿主生成配置。
- **git**（推荐）：项目版本化 + 多 agent 的提交纪律（显式 pathspec、
  `gb <node-id>:` 消息约定、危险 git 操作被权限闸门禁止）。
- 联网（首次安装拉 `mcp`、`PyYAML` 两个依赖）。

## 安装

```bash
# 从 GitHub 安装（推荐，钉版本）
pip install git+ssh://git@github.com/pingyuer/graphboard.git@v0.1.3

# 跟 main 分支
pip install git+ssh://git@github.com/pingyuer/graphboard.git

# 升级
pip install --upgrade git+ssh://git@github.com/pingyuer/graphboard.git@vX.Y.0

# 开发者（本机源码实时生效）
git clone git@github.com:pingyuer/graphboard.git && pip install -e graphboard
```

装后验证：

```bash
gb --help                                # CLI 就位
python -c "import graphboard.server"     # MCP 模块可导入
gb init /tmp/smoke && gb --board /tmp/smoke/.board doctor   # 冒烟
```

私有仓库说明：SSH 方式需目标机配好 GitHub SSH key；也可改用 HTTPS 形式
`git+https://github.com/pingyuer/graphboard.git`（按提示认证）。

## 快速开始（一条命令 + 一场对话）

```bash
cd /path/to/project         # 任何目录，无需已有仓库
gb init                     # 单步脚手架：.board/ + gb 角色 + AGENTS.md + opencode.json
opencode                    # 开 opencode，Tab 切到 gb 角色
```

然后和 gb 对话，它是项目导演：

```
你：这是个 AI 项目，先要一个提案角色，负责细化我的 idea
gb：〈起草角色：Claims/Duties/Loading/Outputs/完成判据〉确认吗？
你：可以 → gb 调 gba_role 落盘
你：提案完成后转执行，执行要人批准
gb：规则草稿 proposal--done-->implementation [approve]，写入吗？
你：写 → gba_grammar 校验后写入
gb：根节点已播下。新开一个会话切到提案角色，说「pull 你的节点」即可开工。
```

**中途要新角色**：回 gb 会话重复上面的三句话。开放图随项目生长。

## 核心概念

- **节点**：一件工作。八态状态机：
  `proposed → pending → active → running → done`，加 `blocked / rejected / canceled`。
  - `active` = agent 正拿在手里（占**注意力**，一个脑子同时只有一份）
  - `running` = 工作自主执行中、agent 已脱身（占**外部资源**，可以有多个）
- **优先级调度**：每个节点带 `priority`（1-9，默认 3，小数先被 pull）。这是
  **调度提示，不是依赖**——不建模先后约束，只决定队列里谁先被认领。submit/split
  派生的子节点继承父优先级；conductor 用 `gba_priority` 重排排队中的节点
  （配合 hold 的"移出队列"，priority 是"队列内排序"）。
- **创建自由，生效受控**：`gb_propose` 恒为 proposed；`gb_submit` 声明的后继由文法
  裁决——`auto` 规则直接 pending，其余等人批。`default: approve` 兜底。
  submit 若漏声明了文法里的 auto 后继，返回里会带 notice 提醒。
- **委托执行（发起→脱身→收割）**：长训练/编译/管道/外部等待这类自主运行的活——
  worker 发起后 `gb_delegate`（声明占用的资源标签 + 怎么检查 + 何时回查）立刻
  脱身干下一个活，**不等**；`check_after` 到期回来用 `gb_submit` 收割，出事了
  `gb_reactivate` 接管。接耗资源的活之前先 `gb_query state=running` 看占用，不抢。
  这是「别抢显存」的泛化：别抢任何共享资源。
- **split 细原子**：节点干到一半太大，`gb_split` 拆成子节点（父节点 blocked 释放
  owner，其他脑子可认领碎片）；子节点全部 done 时父节点自动回到 pending 待收拢。
  任务怎么切，上下文就怎么切。
- **治理动作**：`hold`（推迟排队节点）、`release`（复活 blocked）、
  `cancel`（作废被取代/放弃的节点，终态、留审计）、approve/reject。
- **修复动作（图的纠错能力）**：状态是图对外部世界的承诺，承诺可以被修复——
  `reopen`（终态 done/rejected/canceled 拉回 pending，世界变了就改图，锚点保留、
  events 留痕）、`archive`/`restore`（终态节点收进冷库，活图视图不再扫到，可
  恢复）、`supersede`（原子取代：cancel 旧 + 批准新 + 记 superseded_by，一个
  意图一条审计）。修复永远是留痕的原子操作，绝不静默改写历史。

## 注入平面：薄注入 + 节点一等公民

设计基线：**会话常驻 = 身份（含背景）+ 当前节点（摘要）+ anchor + 增量**。
agent 是连续行为体（像跟进项目的员工），MCP 只做"现在在做什么"的薄注入，
绝不重复灌注它已知的东西。注入追求四条性质：分角色、新鲜、蒸馏、最小。

- **背景一次性注入**：项目章程 `gba_charter`（存 `.board/charter.md`）在
  `gba_role`/`gb role new` 生成角色时**烙进角色文件的 Background 槽**，连同该
  角色认领类型的 contract。worker 出生即知道项目是什么，之后不再重复注入。
- **节点摘要是卡面**：每个节点带 `summary`（propose 显式给、后继取 spec 首行、
  `gba_summary` 可修复）。**pull 只注入 summary**，全文 spec 一律 `gb_status <id>`
  按需取——板面视图（list/query/status）也只显示 summary。
- **pull 注入的完整清单**：summary + anchor + inputs 路径 + 未读 message/公告 +
  workdir/baseline。就这些。contract/facts/全文 spec 都不在 pull 里。
- **anchor 与 message 分离**：`nodes.note` 是 worker 的**锚点**（我在哪、怎么续传），
  仅 owner 可写，release 接管时保留；conductor 的指令/通报走 `gba_message`
  （追加式、带作者与受众、任何状态可写包括 done），在受众下次 pull/status 时投递，
  永不覆盖锚点。
- **受众过滤**：`audience` 可以是 `*`（全体）、角色名（如 experimenter）或 owner
  全名。announce 与 message 都只在受众匹配时投递。
- **facts 层**：`gba_fact` 存少量易变事实（端口、URI、机器清单）。**查询式、按需
  取**（不在 pull 注入）；关键变更用 `gba_announce` 广播。别把环境事实冻进 spec
  或角色文件。
- **认领可撤销**：误 pull / 依赖未就绪，worker 用 `gb_release` 把自己的 active
  节点放回 pending（保锚点）——认领很轻，放回去也一样轻。
- **自我视图**：`gb_status` 传 owner 时优先列出本人 active/running 节点（含锚点），
  会话死亡重开 = 一次确定性的重定位。
- **文法**：`transitions.yaml`，结构化编辑（写前 `gb grammar check` 校验，非法拒绝落盘）。
  引用未声明的节点类型会**自动声明**（占位 contract，doctor 会提醒你补全）；
  闭环无根默认拒绝（错误信息附两条出路），`force` 可显式接受。
- **角色**：按范式生成的数据（`gba_role` / `gb role new`），进 git 可审可回滚。
- **装载三层旋钮**：`gb_query`（清单+摘要）→ 原生 read（具体文件）→ 不读。
  边只记谱系，不决定你该读什么——fan-in 靠查询，不靠布线。
- **上下文洁净**：会话常驻 = 身份 + 当前节点 + anchor。gb 会话的讨论不过界，
  过界的只有蒸馏物（角色文件/契约/文法数据）。工作角色看不见 gba_* 工具。
- **干预三层**：改文法→未来生效判定；announce（可带 TTL）→下次 pull 注入；
  粘贴进会话→即刻。

## 工具命名空间与权力结构

| 命名空间 | 工具 | 谁可用 |
|---|---|---|
| `gb_*` 工作 | pull / release / submit / split / delegate / reactivate / propose / note / status / query / doctor | 全体角色 |
| `gba_*` 治理 | approve / reject / release / cancel / hold / announce / priority / message / fact / charter / summary / reopen / archive / restore / supersede / role / grammar / bootstrap / export | 仅 gb |

`gb init` 生成的 opencode.json 里 `gba_*` 全局禁用、gb 覆盖启用——之后生成的
任何新角色自动无权，零维护保住权力边界。控制面文件（`.board/`、角色文件、
opencode.json）对所有 agent 的文件编辑工具**硬 deny**，只能经 MCP 工具合法修改。

## 项目结构（gb init 产物，全部自包含）

```
<project>/
├── .board/                  # graph.db(gitignore) + yaml + nodes/*/out(进 git)
├── .opencode/agents/gb.md   # 导演角色（工作角色由 gb 对话生成）
├── AGENTS.md                # 五条铁律
├── opencode.json            # MCP 配置 + 治理门控（GB_BOARD/GB_PROJECT/GB_REPO）
└── .gitignore               # 有 git 时自动补 .board/*.db*
```

board 定位优先级：`--board` → `$GB_BOARD` → 从 cwd 向上找 `.board/graph.db`
——**在项目目录里，gb 命令零参数可用**。

## 人类命令速查（CLI = 脚本/急救通道）

```bash
gb init [dir] [--name N] [--template minimal|rd-classic|experiment|branching]
              [--agents gb,proposal,...] [--git] [--force]
gb list [--state S] [--archived] / show <id> / export
gb query --type T --state S --under <id> --owner O [--archived]
gb approve <id> | reject <id> | hold <id> | release <id> | cancel <id>
gb announce "..." [--ttl-days N] [--audience A] [--clear]
gb split <id> --owner O --child TYPE|SPEC [--child ...]
gb delegate <id> --owner O [--resources R] [--note N] [--check-after T]
gb reactivate <id> --owner O
# 调度
gb priority <id> LEVEL [--reason R]          # 1-9，小数先被 pull（默认 3）
# 注入（薄）
gb charter ["..."]                           # 看/设项目章程（烙进角色 Background）
gb summary <id> --text "..."                 # 修复节点摘要（卡面）
gb message <id> --text "..." [--audience A]  # 定向消息，pull/status 投递
gb fact set KEY VALUE | fact remove KEY | fact list   # 查询式，不在 pull 注入
gb release <id> --owner O [--reason R]       # worker 自助退回误认领的节点
# 修复
gb reopen <id> [--reason R]                  # 终态拉回 pending（世界变了）
gb archive <id> [--under] | restore <id>     # 冷库归档 / 恢复
gb supersede OLD NEW [--reason R]            # 原子取代（cancel+approve）
gb role new NAME --repo R --desc D --claims T1,T2 [--background B]  # 手动通道
gb grammar check
gb grammar add --from X --on E --to Y [--activate auto] [--budget N]
gb grammar remove --from X --on E --to Y
gb doctor [--orphan-hours 4] [--stale-hours 24]
```

## 模板（可选起点，不是模具）

| 模板 | 形状 |
|---|---|
| minimal（默认） | 空文法，全由 gb 对话搭建 |
| rd-classic | proposal → implementation → acceptance；fail 自动返工 budget 3 |
| branching | plan → implementation×N → review（查询聚合）→ harvest |
| experiment | hypothesis → experiment → analysis → writeup |

## 委托执行（长时任务不挂 agent）

小时级自主运行的活（训练/编译/管道/外部等待）——agent 的职责是**发起 + 稍后收割**，
不是持续执行。注意力（active）与外部资源（running）是两种并发维度：

```
worker pull 节点 → 起外部执行（如 tmux）→ gb_delegate(resources, note, check_after)
  → 节点 running，worker 脱身去 pull 下一个活（一个脑子 = 1 active + N running）
  → check_after 到期：worker 回来检查 → gb_submit 收割 done，
    或 gb_reactivate 接管（外部执行崩了要修）
```

- `resources` 是轻量标签（如 `gpu:srv1;machine:srv2`），非分配器
- 接耗资源的活前 `gb_query state=running` 看占用，不抢任何共享资源
- doctor 浮现 check_after 已到期的 running 节点；告警同一 owner 多个 active
  （长任务请 delegate，别攥在手里）

## 会话死亡与接管（release 协议）

worker 会话可能死掉。状态图显式管理这件事：

```
1. 发现：doctor 报「possibly orphaned」（active 节点超过 --orphan-hours 无更新）
2. 释放：gb 或人确认会话已死 → gba_release <id> → 节点回 pending，
         owner 清空，anchor note 保留，events 留痕
3. 接管：新 worker pull 到节点 → 读 note 里的锚点（tmux 会话名/server/进度）
         → 确认远端进程还活着 → 继续，用自己的 owner 名 submit
```

配套纪律：worker 有实质进展就 `gb_note` 一次——锚点即心跳，note 的新鲜度
就是 doctor 判断失联的依据。不做自动超时释放：判定死亡是需要上下文的人类判断。
被取代/放弃的节点用 `gba_cancel` 作废（终态、留审计），别用 note 假装标记。

## 多 agent 的 git 管理

board 不隔离工作副本（乐观并发），git 纪律代替分支：

- **pull 给基线**：认领返回 `baseline: <hash> (+N dirty files)`——重定位时
  `git diff <baseline>` 即「这个节点期间世界变了什么」（人和别的 agent 的改动都算）
- **提交纪律**：只提交自己改的文件（显式 pathspec），消息 `gb <node-id>: 摘要`，
  submit 前收尾提交；严禁 `git add -A` / `commit -a`（会把他人半成品扫进来）
- **硬闸门**：init 在 opencode.json 写入 bash 权限——`git push / rebase / merge /
  reset --hard / 切分支 / add -A / commit -a` 全体 agent 物理禁止（不覆盖已有规则）
- **git 可选**：init 默认不 git init（`--git` 显式开）；已有 .git 自动补
  .gitignore（db/wal/shm/server.log/node_modules）；无 git 系统照跑

## 监控与调试

- **事件审计**：所有操作（含被拒的失败调用）记录到 events 表。
  `gb log [--last N] [--tool X] [--owner O] [--node ID]`
- **体检**：`gb doctor`（CLI）或 `gb_doctor`（MCP，gb 会话里对话式体检）——
  db 完整性、文法（含 swap 检测）、owner 格式、workdir、陈旧 proposed、
  假认领、blocked 孤儿、静止链提醒。异常退出码 1。
- **server.log**：`.board/server.log` 每次 MCP 工具调用一行 JSON
  （工具/参数摘要/成败）；`GB_DEBUG=verbose` 记全量参数与返回；
  `GB_DEBUG=0` 关闭。

## 模块结构

```
graphboard/
├── core.py            # 领域核心：pull/submit/split/propose/query/事件（纯函数）
├── grammar.py         # 文法：加载/解析/评估/静态检查/结构化编辑（含 swap 防护）
├── doctor.py          # 体检规则（CLI 与 MCP 共用）
├── scaffold.py        # 项目脚手架：init/agents/AGENTS.md/opencode.json/git 闸门
├── roles.py           # 角色范式：渲染/写入/列表/nodetypes 补全
├── gitutil.py         # git baseline 探测
├── render.py          # 纯文本渲染（预算控制）
├── db.py              # SQLite WAL + schema
├── cli.py             # gb 命令（argparse 薄壳）
├── server.py          # MCP 基础设施（env/缓存/guard/日志）
├── tools_work.py      # gb_* 工作工具注册
└── tools_governance.py# gba_* 治理工具注册
```

## 设计公理

1. **上下文解耦**：预载即污染；一切按需检索。
2. **控制面不变，信息面查询化**：边记谱系，装载靠查询。
3. **图在库，载荷在盘**：代码产出留仓库原位，协调产出进 workdir（pull 给出路径）。
4. **server 无域，项目皆数据**：文法、契约、角色随时生成随时改。
5. **蒸馏，不倾倒**：跨会话的只有蒸馏物，对话不过界。
6. **乐观并发**：共享工作副本，多写不锁；原子认领不撞活；重定位靠 pull/query。
7. **会话一次性**：脏了就杀掉重开，pull + anchor 无缝接上。
8. **注入即薄快照**：agent 是连续行为体，会话常驻 = 身份（含背景）+ 当前节点
   （摘要）+ anchor + 增量。背景在生成角色时一次性烙入；pull 只发"现在在做什
   么"，全文与环境事实一律按需检索。预载即污染，重复灌注同样是污染。
9. **状态可纠错**：图的状态是对外部世界的承诺；承诺失效时有留痕的修复路径
   （reopen/archive/supersede/release），图能自愈，但从不静默改写历史。

## Pilot 检查单

- [ ] 空目录 `gb init` → 产物齐（.board/agents/AGENTS.md/opencode.json）
- [ ] gb 对话先落 charter，再长角色——角色文件 Background 槽含项目背景
- [ ] pull 只回卡面（summary+anchor+增量）；全文走 gb_status，无重复灌注
- [ ] 误认领用 gb_release 放回 pending，锚点保留
- [ ] opencode 切 gb 角色，对话长出 2+ 角色、文法、根节点
- [ ] 新角色会话 pull 到的内容里无 gb 对话残留（上下文洁净验证）
- [ ] 工作角色确认看不到 gba_* 工具
- [ ] 真实任务走完一轮（含并行分支 + review 查询聚合）
- [ ] review fail 触发自动返工；budget 耗尽降级 proposed
- [ ] 中途 announce 约束，下个 pull 收到；`gb export` 快照全图

## 测试

```bash
python3 -m pytest tests/ -q   # 165 tests：竞态认领/批内定序/裁决矩阵/文法检查
                              # （swap/闭环/自动声明）/query/split/委托执行
                              # （delegate/收割/reactivate）/cancel/hold/TTL/
                              # schema 迁移/release 接管/角色生成与更新/治理工具/
                              # init 脚手架与 git 矩阵/e2e 双情景/MCP 层/泛用性守卫
                              # 三平面：priority 调度（继承/排序/重排/hold-release
                              # 保持）、注入（受众匹配/message-anchor 分离/note owner
                              # 守卫/自助 release/审计无损/陈旧公告）、修复（reopen/
                              # archive 原子子树/restore/supersede）
                              # 节点一等公民：summary（显式/兜底/修复/卡面渲染）、
                              # charter（烙进角色 Background+contract）、pull 薄注入
                              # （只 summary，无全文 spec/contract/facts）
                              # + e2e 换机事故剧本
```
