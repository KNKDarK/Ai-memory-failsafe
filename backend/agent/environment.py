"""A deterministic, sandboxed environment for agent tools.

Tools never touch the host system, the network, the filesystem, or any real
service. Everything happens against an in-memory :class:`SimulatedEnvironment`
so behaviour is reproducible and safe to run in CI, on any machine, with or
without a GPU.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimulatedEnvironment:
    """In-memory world state the tools operate on."""

    id: str = "default"
    # Environment variables that ARE present. Anything absent is "missing".
    config: dict[str, str] = field(default_factory=dict)
    # A simulated secret store the agent may explicitly load from.
    secrets: dict[str, str] = field(default_factory=dict)
    # Installed packages: name -> version.
    packages: dict[str, str] = field(default_factory=dict)
    # Package registry: name -> version available for install.
    registry: dict[str, str] = field(default_factory=lambda: {"requests": "2.31.0"})
    # Virtual files: path -> content.
    files: dict[str, str] = field(default_factory=dict)
    # Service behaviours keyed by service name.
    services: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Fault injection knobs (see tools.py for recognised keys).
    faults: dict[str, Any] = field(default_factory=dict)
    # State flags set by successful actions (used to verify task completion).
    flags: set[str] = field(default_factory=set)
    # Deterministic call counters.
    counters: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def bump(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    def set_flag(self, flag: str) -> None:
        self.flags.add(flag)

    def has_flag(self, flag: str) -> bool:
        return flag in self.flags

    def snapshot(self) -> dict[str, Any]:
        """A redaction-friendly view of the environment for traces."""
        return {
            "id": self.id,
            "present_config_keys": sorted(self.config.keys()),
            "installed_packages": dict(sorted(self.packages.items())),
            "files": sorted(self.files.keys()),
            "flags": sorted(self.flags),
        }

    def clone(self) -> SimulatedEnvironment:
        return copy.deepcopy(self)


def default_environment(env_id: str = "default") -> SimulatedEnvironment:
    """A benign environment with no injected faults."""
    return SimulatedEnvironment(
        id=env_id,
        config={"APP_ENV": "production", "DATABASE_URL": "postgres://demo"},
        packages={},
        registry={"requests": "2.31.0", "pandas": "2.2.0", "flask": "3.0.0"},
        files={},
        services={
            "billing_api": {"required_env": ["BILLING_API_KEY"], "mode": "ok"},
            "inventory_api": {"required_env": [], "mode": "ok"},
        },
        faults={},
    )
