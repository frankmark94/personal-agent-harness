"""Approval gates: reversible vs consequential actions.

The gate sits between the model's tool call and the tool's execution.
The model cannot bypass it; a timeout, a "no", or a non-interactive
environment aborts the action.

Classification is by tool name + arguments, because the same tool can be
either: reading a file is reversible, overwriting credentials is not.

Interaction model (``terminal_ask``):
  - Renders an approval card: action, target, arguments, why flagged.
  - Prompts ``[a]pprove / [d]eny / [e]dit-and-approve`` with a timeout
    (default 120s). Timeout = deny, and it is logged.
  - Non-interactive runs: ``HARNESS_AUTO_APPROVE=deny`` denies everything;
    ``HARNESS_AUTO_APPROVE=approve-reversible`` approves reversible
    actions and denies consequential ones. If stdin is not a TTY and the
    env var is unset, the action is denied (fail closed).
  - Every decision is appended to a JSONL log with timestamp, action,
    decision, and reason.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import select
import sys

# Tools that are consequential no matter the arguments.
ALWAYS_CONSEQUENTIAL = {
    "send_message", "send_email", "make_purchase", "book_reservation",
    "use_credential", "network_join", "delete_data",
}

# Per-tool argument rules: (arg_name, predicate, reason).
ARG_RULES = {
    "file_write": [
        ("path", lambda p: "credential" in p.lower() or p.endswith(".pem"),
         "touches secrets"),
    ],
    "shell_exec": [
        ("command", lambda c: any(k in c.lower() for k in
                                 ["curl", "wget", "ssh ", "pip install"]),
         "reaches outside the machine"),
    ],
}

APPROVALS_LOG = os.path.expanduser("~/agent-workspace/approvals/approvals.log")

DEFAULT_TIMEOUT_SECONDS = 120
AUTO_APPROVE_ENV = "HARNESS_AUTO_APPROVE"


class Denied(Exception):
    pass


def classify(tool_name: str, args: dict) -> tuple[str, str]:
    """Returns (reversible | consequential, reason)."""
    if tool_name in ALWAYS_CONSEQUENTIAL:
        return "consequential", f"{tool_name} always requires approval"
    for arg, pred, reason in ARG_RULES.get(tool_name, []):
        if arg in args and pred(str(args[arg])):
            return "consequential", reason
    return "reversible", "no consequential markers"


def _log_decision(tool: str, args: dict, decision: str, reason: str,
                  source: str, level: str) -> None:
    entry = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "tool": tool,
        "args": args,
        "level": level,
        "decision": decision,  # approve | deny
        "reason": reason,
        "source": source,      # interactive | env | timeout | non_tty
    }
    try:
        os.makedirs(os.path.dirname(APPROVALS_LOG), exist_ok=True)
        with open(APPROVALS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        # Logging must never break the gate; the decision itself still stands.
        pass


def render_card(action: dict) -> str:
    """Render the approval card shown before the prompt."""
    args_pretty = json.dumps(action["args"], indent=2)
    line = "─" * 60
    return (
        f"\n┌{line}┐\n"
        f"│ APPROVAL REQUIRED — {action['level'].upper():<38}│\n"
        f"├{line}┤\n"
        f"│ tool:   {action['tool']}\n"
        f"│ why:    {action['reason']}\n"
        f"│ args:\n"
        + "".join(f"│   {l}\n" for l in args_pretty.splitlines())
        + f"└{line}┘"
    )


def _read_line_timeout(timeout: int) -> str | None:
    """Read one line from stdin, or return None on timeout."""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    return sys.stdin.readline().rstrip("\n")


def _edit_args(args: dict, timeout: int) -> dict | None:
    """Interactive edit-and-approve: user pastes revised JSON args.

    Returns the new args dict, or None if the edit was aborted/invalid.
    """
    print("\nCurrent arguments (paste replacement JSON, blank line to finish):")
    print(json.dumps(args, indent=2))
    for attempt in range(3):
        print(f"[attempt {attempt + 1}/3] > ", end="", flush=True)
        lines = []
        while True:
            line = _read_line_timeout(timeout)
            if line is None:
                print("\n(edit timed out)")
                return None
            if line.strip() == "":
                break
            lines.append(line)
        if not lines:
            print("(no changes — keeping original args)")
            return dict(args)
        try:
            new_args = json.loads("\n".join(lines))
        except json.JSONDecodeError as e:
            print(f"invalid JSON: {e}")
            continue
        if not isinstance(new_args, dict):
            print("args must be a JSON object")
            continue
        return new_args
    print("too many invalid edits — denying")
    return None


def terminal_ask(action: dict, timeout: int = DEFAULT_TIMEOUT_SECONDS
                 ) -> tuple[str, dict | None]:
    """Ask the user about a proposed action.

    ``action``: {"tool", "args", "level", "reason"}.
    Returns (decision, new_args) where decision is "approve" | "deny" and
    new_args is the edited args dict when the user chose edit-and-approve.
    """
    tool, args, level, reason = (action["tool"], action["args"],
                                action["level"], action["reason"])

    # --- non-interactive mode via env var ---
    auto = os.environ.get(AUTO_APPROVE_ENV, "").strip().lower()
    if auto == "deny":
        _log_decision(tool, args, "deny", reason,
                      "env:HARNESS_AUTO_APPROVE=deny", level)
        return "deny", None
    if auto == "approve-reversible":
        if level == "reversible":
            _log_decision(tool, args, "approve", reason,
                          "env:HARNESS_AUTO_APPROVE=approve-reversible", level)
            return "approve", None
        _log_decision(tool, args, "deny", reason,
                      "env:HARNESS_AUTO_APPROVE=approve-reversible "
                      "(consequential not auto-approved)", level)
        return "deny", None
    if auto and auto not in ("deny", "approve-reversible"):
        print(f"warning: ignoring unknown {AUTO_APPROVE_ENV}={auto!r}",
              file=sys.stderr)

    # --- fail closed when there is no one to ask ---
    if not sys.stdin.isatty():
        why = (f"stdin is not a TTY and {AUTO_APPROVE_ENV} is unset — "
               "denying (fail closed)")
        print(f"(approval) {why}", file=sys.stderr)
        _log_decision(tool, args, "deny", reason, "non_tty", level)
        return "deny", None

    # --- interactive prompt ---
    print(render_card(action))
    print(f"[a]pprove / [d]eny / [e]dit-and-approve "
          f"(timeout {timeout}s = deny) > ", end="", flush=True)
    answer = _read_line_timeout(timeout)
    if answer is None:
        print("\n(timed out — denying)")
        _log_decision(tool, args, "deny", reason, "timeout", level)
        return "deny", None
    choice = answer.strip().lower()

    if choice in ("a", "approve", "y", "yes"):
        _log_decision(tool, args, "approve", reason, "interactive", level)
        return "approve", None
    if choice in ("e", "edit"):
        new_args = _edit_args(args, timeout)
        if new_args is None:
            _log_decision(tool, args, "deny", reason,
                          "interactive:edit-aborted", level)
            return "deny", None
        _log_decision(tool, new_args, "approve", reason,
                      "interactive:edit-and-approve", level)
        return "approve", new_args
    # anything else (d, deny, empty, garbage) = deny
    _log_decision(tool, args, "deny", reason, "interactive", level)
    return "deny", None


def console_ask(question: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Legacy string-based prompt, kept for backward compatibility.

    Wraps terminal_ask with a minimal action dict.
    """
    action = {"tool": "unknown", "args": {"question": question},
              "level": "consequential", "reason": question}
    decision, _ = terminal_ask(action, timeout)
    return "yes" if decision == "approve" else "no"


def check(tool_name: str, args: dict, policy: dict,
          ask_user=terminal_ask) -> dict:
    """Gate a tool call. Returns the (possibly edited) args to run with.

    Raises Denied unless the action may proceed.
    """
    level, reason = classify(tool_name, args)
    mode = policy.get("policy", "confirm_consequential")
    if mode == "never_confirm":
        return args
    if level == "reversible" and mode == "confirm_consequential":
        return args
    # Consequential (or always_confirm): pause for an explicit yes.
    action = {"tool": tool_name, "args": args,
              "level": level, "reason": reason}
    decision, new_args = ask_user(
        action, timeout=policy.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    final_args = new_args if new_args is not None else args
    if decision != "approve":
        raise Denied(f"user did not approve {tool_name}: {reason}")
    if new_args is not None:
        # Re-classify the edited args: loosening an edit (e.g. removing
        # the secret path) can drop it back to reversible; the approval
        # the user just gave covers the final form either way.
        final_level, final_reason = classify(tool_name, new_args)
        _log_decision(tool_name, new_args, "approve",
                      f"edit-and-approve accepted ({final_level}: {final_reason})",
                      "interactive", final_level)
    return final_args

    # TODO: support scoped standing approvals, e.g. "this scheduled job
    # may send its own emails", stored per-job and revocable.


def self_test() -> None:
    # classification
    assert classify("send_email", {})[0] == "consequential"
    assert classify("file_read", {"path": "x"})[0] == "reversible"
    assert classify("file_write", {"path": "credentials.json"})[0] == "consequential"
    assert classify("shell_exec", {"command": "ls -la"})[0] == "reversible"
    assert classify("shell_exec", {"command": "curl https://x"})[0] == "consequential"
    # reversible actions pass without asking
    assert check("file_read", {"path": "a"}, {"policy": "confirm_consequential"},
                 ask_user=lambda a, timeout=0: (_ for _ in ()).throw(
                     AssertionError("should not ask"))) == {"path": "a"}
    # env deny mode
    os.environ[AUTO_APPROVE_ENV] = "deny"
    try:
        check("send_email", {"to": "x"}, {"policy": "confirm_consequential"})
        raise AssertionError("should have raised Denied")
    except Denied:
        pass
    # env approve-reversible: reversible passes, consequential denied
    os.environ[AUTO_APPROVE_ENV] = "approve-reversible"
    assert check("file_read", {"path": "a"},
                 {"policy": "confirm_consequential"}) == {"path": "a"}
    try:
        check("send_email", {"to": "x"}, {"policy": "confirm_consequential"})
        raise AssertionError("should have raised Denied")
    except Denied:
        pass
    finally:
        del os.environ[AUTO_APPROVE_ENV]
    print("approvals self-test OK")


if __name__ == "__main__":
    self_test()
