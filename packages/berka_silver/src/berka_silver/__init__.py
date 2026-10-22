"""Silver layer: type, decode, measure and grade every defect.

Depends on ``berka_control`` only. It consumes Bronze's *artefact*, never
Bronze's code: importing ``berka_bronze`` from here is a scope violation.
"""

from berka_silver.agent import SilverAgent

__all__ = ["SilverAgent"]
