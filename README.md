# session-handoff

一个轻量的换对话交接 skill，Claude Code 和 Codex 通用。

长任务做到一半，上下文越积越多：早期细节被自动压缩掉，被否决的方案还留在对话里，agent 开始重复问已经定下的事。session-handoff 做两件事：

- **主动提醒**：在合适的时机（阶段切换、方案被推翻、对话已被压缩、换了话题、出现遗忘迹象）建议你换对话。改到一半、排错卡在关键处、马上做完时不会打扰。
- **交接与恢复**：你回复"交接"，它把目标、已定决定、不要再走的路、进度和下一步写进项目根目录的 `HANDOFF.md`，并给出贴合本次任务的开场白。新对话读取背景后，直接完成你指定的任务；只有执行依赖可能变化的外部状态时，才核对相关内容。

## 目录

```
session-handoff/
├── SKILL.md              # 保存交接、在新对话里恢复
├── reminder-rule.md      # 常驻提醒规则，复制进 CLAUDE.md / AGENTS.md
└── scripts/
    └── context_hook.py   # 可选：上下文用量提示 hook
tests/
└── test_context_hook.py  # hook 的测试（Claude Code 与 Codex 两种记录格式）
```

## 安装

一共三步。第 1、2 步是必需的，第 3 步可选。

### 1. 放好 skill 文件夹

把 `session-handoff/` 文件夹复制到：

| 工具 | 位置 |
|---|---|
| Claude Code | `~/.claude/skills/session-handoff/` |
| Codex | `~/.agents/skills/session-handoff/` |

Windows 上的 `~` 指 `C:\Users\<用户名>`。

### 2. 加入常驻提醒规则

主动提醒靠这一步。只装 skill 的话，agent 只在你说"交接"时才会用它，不会主动提醒。

打开 `session-handoff/reminder-rule.md`，把从 `## 换对话提醒` 开始的整段复制，追加到下面的文件末尾（不存在就新建）：

| 工具 | 文件 |
|---|---|
| Claude Code | `~/.claude/CLAUDE.md` |
| Codex | `~/.codex/AGENTS.md` |

### 3. 可选：上下文用量提示

上下文用到 50% 和 70% 时，各给 agent 递一句提示，让提醒更早出现在自动压缩之前。只需要 Python 3，不用装别的依赖。

**Claude Code**：在 `~/.claude/settings.json` 中加入（已经有 `hooks` 的话合并进去）：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "timeout": 5,
        "command": "python3 \"$HOME/.claude/skills/session-handoff/scripts/context_hook.py\"" } ] }
    ]
  }
}
```

**Codex**：在 `~/.codex/hooks.json` 中加入：

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "timeout": 5,
        "command": "python3 \"$HOME/.agents/skills/session-handoff/scripts/context_hook.py\"" } ] }
    ]
  }
}
```

- **Windows**：`$HOME` 在 Windows 的命令行里不一定能展开，命令要写成绝对路径，例如 `py -3 "C:/Users/<用户名>/.agents/skills/session-handoff/scripts/context_hook.py"`（Claude Code 那条把 `.agents` 换成 `.claude`）。
- **生效方式**：Claude Code 改完后新开一个会话即可。Codex 首次加载新 hook 时，需要在 `/hooks` 里确认信任。
- **1M 上下文**：Claude Code 用的是 1M 上下文的模型时，在命令末尾加 `--window 1000000`，否则会提醒得太早。Codex 的记录自带窗口大小，不用设置。
- **调整档位**：在命令末尾加 `--warn 40,65` 这样的参数。

hook 只读记录文件里的 token 用量数字，不读对话内容，不联网；出错时静默退出，不影响对话。

## 使用

1. 正常做多步骤任务。到了合适的时机，回复最后会多一行 `🔄 换对话建议：……`。
2. 回复"交接"，也可以直接说明新对话要做什么，例如"交接，下一个对话简单对比方案 A 和方案 B"。得到 `HANDOFF.md` 和按该任务生成的开场白。
3. 开一个新对话（Claude Code 和 Codex 都可以），粘贴开场白。例如：

   ```
   读取 <项目路径>/HANDOFF.md，根据其中的背景，简单对比方案 A 和方案 B。
   ```

开场白里的对象和要求来自实际对话，不是固定模板。新对话直接给所需结果，不强制先汇报目标、进度或差异。

不想让 `HANDOFF.md` 进 git 的话，把它加进 `.gitignore`。

## 测试

```bash
python3 tests/test_context_hook.py
```
