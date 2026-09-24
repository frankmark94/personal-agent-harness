"""Config loading with ${ENV_VAR} interpolation.

Secrets never live in config files. Any string value may reference an
environment variable as ${NAME}; it is resolved at load time. Referencing
an unset variable is a hard error — failing loudly beats silently sending
an empty API key.
"""

from __future__ import annotations

import os
import re

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def interpolate_env(value):
    """Recursively resolve ${VAR} references in strings using os.environ."""
    if isinstance(value, str):
        def repl(match):
            name = match.group(1)
            if name not in os.environ:
                raise ValueError(
                    f"config references unset environment variable: ${{{name}}}"
                )
            return os.environ[name]
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate_env(v) for v in value]
    return value


def load_config(path: str = "config.yaml") -> dict:
    """Load YAML config and interpolate ${ENV_VAR} everywhere."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    # TODO: validate required keys (provider.kind, provider.model, ...)
    # with a clear error message instead of KeyError later.
    return interpolate_env(raw)
