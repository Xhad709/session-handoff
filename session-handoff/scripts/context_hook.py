#!/usr/bin/env python3
"""session-handoff 的可选 hook：上下文用量跨过档位时，给 agent 递一句提示。

Claude Code 和 Codex 通用，挂在 UserPromptSubmit 事件上。
它从宿主传来的 transcript_path 里读最近一次请求的 token 用量，算出上下文占比。
第一次跨过 50% 和第一次跨过 70% 时，各注入一行提示；其余时候不输出任何东西。
上下文被压缩、占比降下来后，档位会重置，之后再跨过时还会提示。

只读 transcript 里的用量数字，不读对话内容，也不联网。
出现任何异常都静默退出，不影响对话本身。

用法：python3 context_hook.py [--warn 50,70] [--window 200000]
  --warn    提示档位（百分比），默认 50,70
  --window  Claude Code 的上下文窗口大小，默认 200000（用到更大值时自动按 1000000 算）。
            Codex 的 transcript 自带窗口大小，不需要这个参数。
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

TAIL_BYTES = 4_000_000          # 只读 transcript 末尾这么多字节，足够找到最近一次用量
CODEX_BASELINE = 12_000         # 和 Codex 界面一致：扣掉固定开销后再算百分比
STATE_DIR = Path(tempfile.gettempdir()) / "session-handoff-hook"

MESSAGES = {
    1: ("【上下文用量】本对话上下文已用约 {pct}%。按「换对话提醒」规则，"
        "接下来遇到合适时机（阶段切换、方案变化等）就提一次换对话；手上的事不用中断。"),
    2: ("【上下文用量】本对话上下文已用约 {pct}%，快到自动压缩了。"
        "当前这一步做完、处在安全位置时，就提一次换对话。"),
}


def tail_lines(path):
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        lines = f.read().decode("utf-8", "replace").splitlines()
    return lines[1:] if size > TAIL_BYTES else lines   # 第一行可能被截断


def usage_percent(lines, default_window):
    """从最近一条用量记录算出上下文已用百分比；找不到返回 None。"""
    for line in reversed(lines):
        if '"token_count"' not in line and '"usage"' not in line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue

        # Codex：{"type":"event_msg","payload":{"type":"token_count","info":{...}}}
        payload = item.get("payload") or {}
        if payload.get("type") == "token_count":
            info = payload.get("info") or {}
            used = (info.get("last_token_usage") or {}).get("total_tokens") or 0
            window = info.get("model_context_window") or 0
            if used and window > CODEX_BASELINE:
                eff = window - CODEX_BASELINE
                return 100 * max(0, used - CODEX_BASELINE) / eff
            continue

        # Claude Code：{"type":"assistant","message":{"usage":{...}}}；跳过子 agent 的记录
        if item.get("type") == "assistant" and not item.get("isSidechain"):
            u = (item.get("message") or {}).get("usage") or {}
            used = sum(u.get(k) or 0 for k in (
                "input_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens", "output_tokens"))
            if used:
                window = default_window if used <= default_window else 1_000_000
                return 100 * used / window
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warn", default="50,70")
    parser.add_argument("--window", type=int, default=200_000)
    args = parser.parse_args()
    bands = sorted(float(x) for x in args.warn.split(","))[:2]

    event = json.load(sys.stdin)
    if event.get("agent_id"):                       # 子 agent 不提示
        return
    transcript, session = event.get("transcript_path"), event.get("session_id")
    if not transcript or not session or not Path(transcript).is_file():
        return
    pct = usage_percent(tail_lines(transcript), args.window)
    if pct is None:
        return

    level = sum(pct >= b for b in bands)            # 0：没到档位；1、2：到了第几档
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / (hashlib.sha256(session.encode()).hexdigest()[:32] + ".json")
    try:
        notified = json.loads(state_file.read_text())["level"]
    except (OSError, ValueError, KeyError):
        notified = 0

    if level != notified:                           # 升档就提示；降档（被压缩了）只记录
        state_file.write_text(json.dumps({"level": level}))
    if level > notified:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": MESSAGES[level].format(pct=round(pct)),
        }}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        main()
    except Exception:                               # hook 出错也不能打断对话
        pass
    sys.exit(0)
