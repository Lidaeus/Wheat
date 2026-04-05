# Git Worktree 实施规范与流程 (Wheat 项目)

在 Wheat 项目中，我们可能需要同时进行多项研究或测试（例如：早停机制开发、规模参数调整、不同作物的模型适配等）。使用传统的 `git checkout` 切换分支会覆盖当前工作目录的文件，导致运行中的实验被中断，或者需要频繁地 stash/commit 代码。

**Git Worktree** 允许你在同一台机器上为同一个 Git 仓库检出多个工作目录（即每个分支拥有独立的文件夹），从而实现**并行开发和测试，互不干扰**。

## 1. 目录结构设计规范

为了保持 D 盘根目录或项目区域的整洁，建议将原始仓库作为“主仓库”（或者称为“裸仓库/基础仓库”），并将各个 worktree 检出到同级或子目录中。对于本项目的 `D:\Wheat\Wheat`，推荐如下结构：

```text
D:\Wheat\
 ├── Wheat\                   # 当前的主仓库（默认工作树，通常保持在 main 或 master 分支）
 ├── Wheat_early_stopping\    # Worktree 1: 用于开发早停机制
 ├── Wheat_scale_tuning\      # Worktree 2: 用于测试规模参数调整
 └── Wheat_crop_maize\        # Worktree 3: 用于其他作物的适配实验
```

## 2. 常用操作流程

### 2.1 添加新的 Worktree

假设你当前在 `D:\Wheat\Wheat` 目录下，想要开始开发“早停机制”（分支名为 `feature/early-stopping`），你可以执行以下命令：

```powershell
# 进入主仓库
cd D:\Wheat\Wheat

# 创建一个新的 worktree 和对应的分支
# 语法: git worktree add <路径> -b <新分支名>
git worktree add ../Wheat_early_stopping -b feature/early-stopping
```

执行后，Git 会在 `D:\Wheat\Wheat_early_stopping` 处克隆一份当前代码的物理副本，并自动切换到 `feature/early-stopping` 分支。你可以在这个新目录中自由修改代码、运行长耗时的 DSSAT 模拟，**这完全不会影响 `D:\Wheat\Wheat` 中的内容**。

### 2.2 在 Worktree 中开发与提交

进入新的 worktree 目录，像平常一样使用 Git：

```powershell
cd D:\Wheat\Wheat_early_stopping

# 进行代码修改...
# 运行实验...

# 提交修改
git add .
git commit -m "feat: 实现早停机制的基础逻辑"
```

### 2.3 查看当前的 Worktrees

如果你忘记了当前有哪些 worktree 正在运行，可以在任意一个 worktree 目录（或主仓库）中运行：

```powershell
git worktree list
```

输出示例：
```text
D:/Wheat/Wheat                  1234abc [main]
D:/Wheat/Wheat_early_stopping   5678def [feature/early-stopping]
```

### 2.4 清理与移除 Worktree

当一个实验或功能开发完成，分支合并后，你不再需要这个独立的工作目录时，可以将其安全移除。

```powershell
# 确保你没有在要删除的目录中
cd D:\Wheat\Wheat

# 移除 worktree
git worktree remove ../Wheat_early_stopping
```
*注：移除 worktree 并不会删除该分支，它只是删除了文件系统上的物理目录。如果该目录中有未跟踪的文件（如 DSSAT 运行产生的庞大临时文件），Git 可能会阻止删除，此时可以加上 `-f` 强制删除（请先确保重要数据已备份）。*

## 3. 针对本项目的特殊注意事项

1. **虚拟环境 (Venv)：** 
   - Python 虚拟环境（如 `mvp_pest_mgda\.venv`）**通常不会**通过 Git 同步。
   - 当你创建一个新的 worktree 时，你可能需要重新创建虚拟环境，或者复制主仓库的 `.venv` 目录到新 worktree 中。
   - 建议在新的 worktree 中运行：`python -m venv mvp_pest_mgda\.venv`，并重新 `pip install -r requirements.txt`。

2. **DSSAT 根目录配置：**
   - 目前项目已经改为**优先解析可配置的 DSSAT 根目录**，不再把 `C:\DSSAT48` 作为唯一硬编码入口。
   - 推荐做法是为每个实验机准备一个 `DSSAT_ROOT` 环境变量，或在仓库旁边放置 `local_dssat` 目录；代码会按“环境变量/配置 → 本地镜像 → 旧的 `C:\DSSAT48` 兼容回退”顺序解析。
   - **重要：** 我们的代码中通过沙盒机制（`sandbox` 目录拷贝）来运行 DSSAT。只要确保不同 worktree 在各自独立的 sandbox 路径下运行，就不会产生文件冲突。

3. **IDE 配置 (Trae / VSCode)：**
   - 建议通过 Trae/VSCode 的 `文件 -> 打开文件夹` 直接打开对应的 worktree 目录（如 `D:\Wheat\Wheat_early_stopping`）作为独立的工作区，这样 IDE 的 linter 和 typechecker 就能正确解析当前分支的代码。
