# Git 使用说明（本仓库是本地私有仓库）

> 建立于 2026-10-24 15:4x。基线提交 `e3b893c`，135 个文件，`.git` 约 1.5 MB。
> **目的只有一个：改坏了能退回去。** 不是用来发布、不是用来协作推送。

---

## §1 出事了先做这三件事

```bash
cd "C:/Users/OTTO/Desktop/来世"
git status                 # 看谁被改了（M=改过，??=新文件）
git diff                   # 看具体改了哪几行
```

然后按情况选一条：

| 情况 | 命令 | 效果 |
|---|---|---|
| 某个文件被改坏，要还原 | `git restore 文件名` | 回到上次提交的样子（**新文件不受影响**） |
| 全部已跟踪文件改坏，全还原 | `git restore .` | 回到上次提交（**不删新文件**） |
| 多出一堆来历不明的临时文件 | `git clean -nd` 先看清单 → 确认后 `git clean -fd` | 删掉未跟踪文件（**不可恢复，先看清单**） |
| 想看看上次提交是什么样 | `git log --oneline -5` | 列存档点 |

**已实测**：`git restore README.md` 能还原被追加内容的文件；`git clean -fd` 能清掉新建文件；两次测试后 `git status` 均为空。

---

## §2 想留一个存档点（改代码前必做）

```bash
git add -A                              # 把当前状态放进待提交区
git commit -m "改了什么、为什么"          # 存档
```

规矩三条：
1. **一次改动一个提交**，别把几件不相干的事塞进一条。出问题时才能只退一半。
2. **提交说明写"为什么"**，不写"更新文件"。半年后你只看得懂原因。
3. **改坏了不要急着 commit**。先 `git status` / `git diff` 看清楚，觉得救不回来就 `git restore`。

---

## §3 什么**没有**进 git（重要，别指望这里有回退）

| 没入库 | 原因 |
|---|---|
| `logs/` | 运行日志，每天变，且体积增长 |
| `data/` 下除探针外全部 | 配置快照、备份、聊天库；其中 `data/backups/` 的 system-config 快照**含 `sk-` 密钥** |
| `个性化语言/聊天记录/` | 真实聊天正文与 QQ 号，18 MB |
| `b50/`、`images/` | 素材图，26 MB |
| NapCat / AstrBot Launcher 二进制副本 | 约 1.8 GB，可重新下载 |
| `knowledge/*.sqlite3` | 知识库构建产物，可由 `knowledge/src/` 重建 |
| `.env` | 本机路径配置 |

**推论的后果**：如果你改坏了 `prompts/system.txt` 以外的**运行配置**（`session_list`、`id_whitelist`、`observer.target_qq`、主动消息参数），**git 帮不了你**——那些在 `data/` 和实例目录里，本来就没入库。改配置前仍要按既有规矩手工留痕（`data/backups/` 那套）。

---

## §4 四条铁律

1. **不推远端。** 本仓库含三个真实 QQ 号（见 §5）。一旦 `git remote add` + `push`，就收不回来了。
2. **不用 `git reset --hard`**，除非你已经 `git status` + `git diff` 看清楚了。它会把未提交的改动直接抹掉，git 不管。
3. **不改写历史**（`rebase -i`、`commit --amend` 堆在已提交的东西上、`filter-repo`）。本项目没有多人分支，改写历史只会让你自己看不懂。
4. **`.gitignore` 不要为了"想提交某个文件"去删规则。** 要放行单个文件，加一行 `!路径`，并在注释里写明为什么。

---

## §5 已知未清：三个 QQ 号在 16 个文件里

| 号码 | 指谁 | 涉及文件数 | 出现处数 |
|---|---|---|---|
| 来世本人 | 服务对象 | **18** | 37 |
| OTTO 本人 | 维护者 | **8** | 19 |
| Miruku 小号 | 机器人 | **8** | 9 |

分布最密的三处：`docs/chat-db.md`（来世号 7 次）、`docs/crisis-alert.md`（OTTO 号 7 次）、`knowledge/src/memes.json`（来世号 7 次）。其余散在 `docs/`、`persona/`、`WORK_LOG.md`、`.workbuddy/memory/`、`build_chat_db.py`、`data/probe_*.py`。

> 以上四个数字由 `git grep --cached -l / -c` 现场统计，不是估的。改动后要重新数——**文档里的计数会漂**。

**为什么没在首次提交前清掉**：这批号码里有一部分是**运行资产与验收断言**——`data/probe_inject_hook.py`、`data/probe_knowledge_adversarial.py` 里的 `assert TARGET != <号码>` 一旦替换成占位符，断言会变成**恒真**，探针就废了；`persona/` 与 `knowledge/src/` 里的出现位置也需要逐个判断是注释还是数据。**批量替换会同时打坏基线和 Codex 正在跑的探针**，所以没有擅自做。

**如果要清（例如将来要推远端或交给外部 AI 看）**，正确顺序是：

```bash
# 1. 先单独做一次脱敏提交（逐个文件判断，跑探针回归）
# 2. 因为要清历史，必须重建仓库（只有基线一个提交时成本极低）
rm -rf .git
git init -b main && git add -A && git commit -m "chore: 脱敏后重建基线"
```

**不能只做第 1 步**——`git log` 里第一次提交仍保留原始号码。

---

## §6 给外部 AI 的约束

`docs/prompt-for-claude.md` 已规定它只能只读审计。补一条 git 相关：

- **允许**：`git status`、`git diff`、`git log`（只读，用来证明它改了什么）。
- **禁止**：`git commit`、`git restore`、`git clean`、`git reset`、`git checkout <分支>`、`git stash`——这些会改动你的工作区，属于写操作。
- 它报"我改了什么"时，**必须贴 `git diff` 原文**，不许只说"已优化"。

---

## §7 一句话备忘

> **改之前想清楚要改哪几个文件；改完先 `git diff` 看一眼；确认好了再 `git commit`。**
> git 只保护它看管的东西——配置、日志、聊天记录都不在里面。
