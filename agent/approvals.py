"""Approval gates: reversible vs consequential actions.

The gate sits between the model's tool call and the tool's execution.
The model cannot bypass it; a timeout or "no" aborts the action.

Classification is by tool name + arguments, because the same tool can be
either: reading a file is reversible, overwriting credentials is not.
"""

from __future__ import annotations


class Denied(Exception):
    pass


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


def classify(tool_name: str, args: dict) -> tuple[str, str]:
    """Returns (reversible | consequential, reason)."""
    if tool_name in ALWAYS_CONSEQUENTIAL:
        return "consequential", f"{tool_name} always requires approval"
    for arg, pred, reason in ARG_RULES.get(tool_name, []):
        if arg in args and pred(str(args[arg])):
            return "consequential", reason
    return "reversible", "no consequential markers"


def check(tool_name: str, args: dict, policy: dict, ask_user) -> None:
    """Raises Denied unless the action may proceed."""
    level, reason = classify(tool_name, args)
    mode = policy.get("policy", "confirm_consequential")
    if mode == "never_confirm":
        return
    if level == "reversible" and mode == "confirm_consequential":
        return
    # Consequential (or always_confirm): pause for an explicit yes.
    question = (f"Approve {tool_name}({args})?\n"
                f"Reason flagged as consequential: {reason}\n"
                f"Reply 'yes' to proceed, anything else aborts.")
    answer = ask_user(question, timeout=policy.get("timeout_seconds", 300))
    if answer.strip().lower() not in ("yes", "y", "approve"):
        raise Denied(f"user did not approve {tool_name}: {reason}")
    # TODO: support scoped standing approvals, e.g. "this scheduled job
    # may send its own emails", stored per-job and revocable.


def console_ask(question: str, timeout: int = 300) -> str:
    # TODO: real implementation should enforce the timeout (e.g. select
    # on stdin) and route through the chat UI, not stdin.
    print(question)
    return input("> ")
