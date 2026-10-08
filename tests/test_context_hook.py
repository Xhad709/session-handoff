"""Exercise context_hook.py with fake Claude Code and Codex transcripts."""
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HOOK = str(Path(__file__).resolve().parents[1] / "session-handoff" / "scripts" / "context_hook.py")
tmp = Path(tempfile.mkdtemp())
failures = []


def claude_line(tokens, sidechain=False):
    return json.dumps({"type": "assistant", "isSidechain": sidechain, "message": {
        "role": "assistant", "content": [{"type": "text", "text": "hi \"usage\""}],
        "usage": {"input_tokens": 10, "cache_creation_input_tokens": 1000,
                  "cache_read_input_tokens": tokens - 1010 - 200, "output_tokens": 200}}})


def codex_line(used, window=272_000):
    return json.dumps({"timestamp": "2026-10-07T01:00:00Z", "type": "event_msg", "payload": {
        "type": "token_count", "info": {
            "total_token_usage": {"total_tokens": used * 5},
            "last_token_usage": {"input_tokens": used - 500, "cached_input_tokens": 0,
                                 "output_tokens": 500, "reasoning_output_tokens": 0,
                                 "total_tokens": used},
            "model_context_window": window}, "rate_limits": None}})


def run(event_obj, raw=None, args=()):
    stdin = raw if raw is not None else json.dumps(event_obj)
    p = subprocess.run([sys.executable, "-I", HOOK, *args], input=stdin,
                       capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0 or p.stderr:
        failures.append(f"exit={p.returncode} stderr={p.stderr!r}")
    return p.stdout.strip()


def check(name, out, expect):
    """expect: None (no output) or substring of injected context."""
    ok = (not out) if expect is None else (expect in out)
    if out:
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        shown = ctx
    else:
        shown = "(无输出)"
    print(("PASS" if ok else "FAIL"), name, "->", shown)
    if not ok:
        failures.append(name)


def scenario(label, lines_seq, expects, make_event=None, args=()):
    sid = str(uuid.uuid4())
    path = tmp / f"{label}.jsonl"
    content = []
    for i, (lines, expect) in enumerate(zip(lines_seq, expects)):
        content.extend(lines)
        path.write_text("\n".join(content) + "\n", encoding="utf-8")
        ev = {"session_id": sid, "transcript_path": str(path), "hook_event_name": "UserPromptSubmit",
              "prompt": "继续", "cwd": "/x"}
        if make_event:
            ev.update(make_event)
        check(f"{label} step{i + 1}", run(ev, args=args), expect)


# Claude Code, 200k window: 30% -> 55% -> 58% -> 72% -> 75% -> compacted 20% -> 52%
scenario("claude", [
    [json.dumps({"type": "user", "message": {"content": "hi"}}), claude_line(60_000)],
    [claude_line(110_000)],
    [claude_line(116_000)],
    [claude_line(144_000)],
    [claude_line(150_000)],
    [json.dumps({"type": "system", "subtype": "compact_boundary"}), claude_line(40_000)],
    [claude_line(104_000)],
], [None, "已用约 55%", None, "已用约 72%", None, None, "已用约 52%"])

# Sidechain (subagent) usage at the end must be ignored
scenario("sidechain", [[claude_line(60_000), claude_line(180_000, sidechain=True)]], [None])

# Claude Code on a 1M-context model: usage above 200k switches to a 1M window
scenario("claude-1m", [[claude_line(300_000)], [claude_line(560_000)]], [None, "已用约 56%"])

# Custom bands
scenario("custom-warn", [[claude_line(70_000)]], ["已用约 35%"], args=("--warn", "30,60"))

# Codex rollout: window 272k, baseline-normalised like the Codex UI
# (140k-12k)/(272k-12k)=49% -> none ; (150k-12k)/260k=53% -> band1 ; 200k -> 72% band2
scenario("codex", [[codex_line(140_000)], [codex_line(150_000)], [codex_line(200_000)]],
         [None, "已用约 53%", "已用约 72%"])

# Codex token_count with info=null (happens at session start) is skipped gracefully
scenario("codex-null", [[json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": None}})]], [None])

# Subagent event: never inject
scenario("subagent", [[claude_line(150_000)]], [None], make_event={"agent_id": "a1"})

# Robustness: missing transcript, garbage stdin, empty stdin
check("missing transcript", run({"session_id": "s", "transcript_path": "/nope.jsonl"}), None)
check("garbage stdin", run(None, raw="not json"), None)
check("empty stdin", run(None, raw=""), None)

# Big transcript: usage line buried before >4MB of tool output must not crash
big = tmp / "big.jsonl"
big.write_text(claude_line(150_000) + "\n" + ("x" * 5_000_000) + "\n", encoding="utf-8")
check("huge tail, no usage in window", run({"session_id": "big", "transcript_path": str(big)}), None)

print("\nALL PASS" if not failures else f"\nFAILURES: {failures}")

sys.exit(1 if failures else 0)
