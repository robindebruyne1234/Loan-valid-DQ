"""The governed surface shared by the three layer packages.

This package holds what all three layers need and none of them owns: the
control dataset, the contract between layers, and the runtime an agent runs
inside. It depends on nothing else in the project, and the three layer
packages depend only on it -- which is what makes the dependency direction a
straight line rather than a web.
"""

from berka_control.dataset import ControlDataset, FrozenSurfaceError, load
from berka_control.contracts import Contract, ContractViolation, verify_contract
from berka_control.runtime import (
    AcceptanceCheck,
    AgentReport,
    LayerAgent,
    LayerArtifact,
    ScopeViolation,
)

__all__ = [
    "AcceptanceCheck",
    "AgentReport",
    "Contract",
    "ContractViolation",
    "ControlDataset",
    "FrozenSurfaceError",
    "LayerAgent",
    "LayerArtifact",
    "ScopeViolation",
    "load",
    "verify_contract",
]
