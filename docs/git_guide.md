# Wheat 自动率定项目 Git 操作指南

## 仓库与分支信息

- **GitHub 仓库地址**: https://github.com/Lidaeus/Wheat
- **当前工作分支**: `Phase1_Experiment`
- **远端(remote)名称**: `origin`（即 GitHub）

---

## 基础概念

| 术语 | 含义 |
|---|---|
| working tree / 工作区 | 你现在在 VS Code/文件夹里看到的文件 |
| staging area | 暂存区，`git add` 后的内容准备提交 |
| local branch | 本地分支，`git commit` 提交到这里 |
| remote branch | GitHub 上的分支（`origin/Phase1_Experiment` 这样表示） |
| `git push` | 把本地分支的提交上传到 GitHub |
| `git fetch` | 从 GitHub 下载最新分支信息（不下拉代码） |
| `git pull` | `git fetch` + 自动合并，等于下载并合并 |

---

## 日常开发循环（推荐流程）

### 1）开始工作前，先同步最新代码

```bash
git checkout Phase1_Experiment
git pull origin Phase1_Experiment
```

### 2）做完修改后，查看状态

```bash
git status
```

输出示例（各符号含义）：

| 符号 | 含义 |
|---|---|
| `M`（changed in index/staged） | 文件已暂存，待提交 |
| `??`（untracked） | 新文件，Git 还没管理 |
| ` D`（deleted） | 文件被删了 |

### 3）暂存想提交的文件

```bash
# 暂存单个文件
git add mvp_pest_mgda/src/dssat_io.py

# 暂存所有修改（包括新文件，但忽略 .gitignore 里的）
git add -A

# 只暂存已知文件（不包括未跟踪的新文件）
git add -u
```

### 4）提交（本地）

```bash
git commit -m "简短的提交说明（英文或中文均可）"
```

### 5）推送到 GitHub

```bash
git push origin Phase1_Experiment
```

---

## 常用场景

### 场景 A：刚换到一台新电脑，要下载代码

```bash
# 克隆整个仓库
git clone https://github.com/Lidaeus/Wheat.git
cd Wheat

# 切换到工作分支
git checkout Phase1_Experiment
```

### 场景 B：想查看某次提交的改动

```bash
# 列出最近 5 次提交
git log --oneline -5

# 查看某次提交改了什么
git show <commit-hash>   # 例如 git show edae838
```

### 场景 C：想撤销上次 `git add`（还没 commit）

```bash
git reset HEAD mvp_pest_mgda/src/dssat_io.py   # 撤销单个文件
git reset HEAD                                   # 撤销所有暂存
```

### 场景 D：想撤销已 commit 但还没 push 的内容

```bash
# 撤销最后一次提交，保留文件修改
git reset --soft HEAD~1

# 撤销最后一次提交，不保留文件修改（危险！）
git reset --hard HEAD~1
```

### 场景 E：想临时藏起当前修改，去看别的版本

```bash
git stash
# （做其他操作，比如 git checkout another-branch）
# 回来时：
git stash pop
```

### 场景 F：删除 GitHub 上的分支（谨慎！）

需要你手动在 GitHub 网页操作：
1. 打开 https://github.com/Lidaeus/Wheat
2. 进入 **Settings → Branches**
3. 在 "Protected branches" 或直接通过分支列表删除

或在本地执行（不会自动删 GitHub 分支，需要 push）：

```bash
git push origin --delete branch_name
```

### 场景 G：.gitignore 漏加了文件，已推送到 GitHub，想删掉

```bash
# 从 Git 历史和本地都删掉
git rm --cached path/to/file
# 然后更新 .gitignore，再 commit + push
git commit -m "remove accidentally tracked file from git"
git push origin Phase1_Experiment
```

---

## 本项目特别注意事项

### 1）不要把大文件/临时目录 push 上去

以下目录和文件已被 `.gitignore` 忽略，**不要手动 `git add`**：

```
autoresearch_sandbox/phase1_runs/       # 巨大的运行结果目录
.dssat_rt/                               # DSSAT runtime 缓存
*.tsv, *.csv（在大目录下的）             # 各种结果文件
```

如果 `git status` 显示这些目录的变更，说明你之前可能 `git add -A` 过，应该先还原：

```bash
git checkout -- path/to/file
```

### 2）每次正式 commit 前先看 status

```bash
git status
```

确认没有误把临时文件加进去。

### 3）常用完整提交流程

```bash
git status                              # 1. 看状态
git add mvp_pest_mgda/src/dssat_io.py  # 2. 暂存要提交的文件
git status                              # 3. 再确认一次
git commit -m "Fix: description"         # 4. 提交（本地）
git push origin Phase1_Experiment        # 5. 推送到 GitHub
```

### 4）确认 push 成功

看输出是否包含：

```
To https://github.com/Lidaeus/Wheat.git
   <old-hash>..<new-hash>  Phase1_Experiment -> Phase1_Experiment
```

如果看到 `Everything up-to-date` 说明本地没有领先远端的新提交，不需要 push。

---

## 常见错误处理

| 错误信息 | 含义与处理 |
|---|---|
| `Everything up-to-date` | 本地没有新 commit，不需要 push，先 `git add` + `git commit` |
| `failed to push some refs` | 远端有你本地没有的提交，先 `git pull origin Phase1_Experiment` 合并，再 push |
| `Merge conflict` | pull 时有冲突，打开文件手动解决冲突，然后 `git add` + `git commit` + push |
| `Permission denied` | GitHub 认证失败，可能需要重新登录或配置 token |
| `could not connect to server` | 网络问题，检查 VPN 或代理设置 |

---

## 分支管理（高级）

### 查看所有分支

```bash
git branch -a
```

### 创建并切换到新分支（不常用，推荐始终在 Phase1_Experiment 上工作）

```bash
git checkout -b new_branch_name
# 做完修改后：
git push -u origin new_branch_name
```

---

## 快速查询

```bash
# 当前在哪分支
git branch

# 最新的 3 条提交记录
git log --oneline -3

# 远端是否领先本地
git status

# 暂存区还有啥
git diff --cached --stat
```
