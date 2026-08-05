# graphboard

多 agent 科研工作流的图上自动机：一个 MCP server + CLI，在 SQLite 中维护任务图
（节点 + 边），用转移文法裁决节点的派生与生效。控制状态外化到库里，LLM 会话
保持最小上下文；人是调度器，乐观并发，冲突靠廉价重定位消化。

**图是开放的**：节点类型、角色、转移规则全是项目数据。AI 项目可以长成
「提案→执行」，产品项目可以长成「设计→实现→测试」——由 gb 导演按项目塑形。

## 安装

要求：Python ≥ 3.10、git、联网（拉 `mcp`、`PyYAML` 两个依赖）。

```bash
# 从 GitHub 安装（推荐，钉版本）
pip install git+ssh://git@github.com/pingyuer/graphboard.git@v0.1.0

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

- **节点**：一件工作。`proposed → pending → active → done | blocked`（另有 rejected）。
- **创建自由，生效受控**：`gb_propose` 恒为 proposed；`gb_submit` 声明的后继由文法
  裁决——`auto` 规则直接 pending，其余等人批。`default: approve` 兜底。
- **split 细原子**：节点干到一半太大，`gb_split` 拆成子节点（父节点 blocked 释放
  owner，其他脑子可认领碎片）；子节点全部 done 时父节点自动回到 pending 待收拢。
  任务怎么切，上下文就怎么切。
- **文法**：`transitions.yaml`，结构化编辑（写前 `gb grammar check` 校验，非法拒绝落盘）。
- **角色**：按范式生成的数据（`gba_role` / `gb role new`），进 git 可审可回滚。
- **装载三层旋钮**：`gb_query`（清单+摘要）→ 原生 read（具体文件）→ 不读。
  边只记谱系，不决定你该读什么——fan-in 靠查询，不靠布线。
- **上下文洁净**：会话常驻 = 身份 + 当前节点 + anchor。gb 会话的讨论不过界，
  过界的只有蒸馏物（角色文件/契约/文法数据）。工作角色看不见 gba_* 工具。
- **干预三层**：改文法→未来生效判定；announce→下次 pull 注入；粘贴进会话→即刻。

## 工具命名空间与权力结构

| 命名空间 | 工具 | 谁可用 |
|---|---|---|
| `gb_*` 工作 | pull / submit / split / propose / note / status / query / doctor | 全体角色 |
| `gba_*` 治理 | approve / reject / announce / role / grammar / bootstrap / export | 仅 gb |

`gb init` 生成的 opencode.json 里 `gba_*` 全局禁用、gb 覆盖启用——之后生成的
任何新角色自动无权，零维护保住权力边界。

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
gb list / show <id> / export
gb query --type T --state S --under <id> --owner O
gb approve <id> | reject <id> | announce "..."
gb split <id> --owner O --child TYPE|SPEC [--child ...]
gb role new NAME --repo R --desc D --claims T1,T2   # gb 对话之外的手动通道
gb grammar check
gb grammar add --from X --on E --to Y [--activate auto] [--budget N]
gb grammar remove --from X --on E --to Y
```

## 模板（可选起点，不是模具）

| 模板 | 形状 |
|---|---|
| minimal（默认） | 空文法，全由 gb 对话搭建 |
| rd-classic | proposal → implementation → acceptance；fail 自动返工 budget 3 |
| branching | plan → implementation×N → review（查询聚合）→ harvest |
| experiment | hypothesis → experiment → analysis → writeup |

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

## Pilot 检查单

- [ ] 空目录 `gb init` → 产物齐（.board/agents/AGENTS.md/opencode.json）
- [ ] opencode 切 gb 角色，对话长出 2+ 角色、文法、根节点
- [ ] 新角色会话 pull 到的内容里无 gb 对话残留（上下文洁净验证）
- [ ] 工作角色确认看不到 gba_* 工具
- [ ] 真实任务走完一轮（含并行分支 + review 查询聚合）
- [ ] review fail 触发自动返工；budget 耗尽降级 proposed
- [ ] 中途 announce 约束，下个 pull 收到；`gb export` 快照全图

## 测试

```bash
python3 -m pytest tests/ -q   # 90 tests：竞态认领/裁决矩阵/文法检查/query/
                              # split 生命周期与重激活/角色生成/治理工具/
                              # init 脚手架与 git 矩阵/e2e 双情景/MCP 层
```
