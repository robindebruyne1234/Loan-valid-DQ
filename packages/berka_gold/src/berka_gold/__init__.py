"""Gold layer: business meaning, certified metrics and entitled serving.

Depends on ``berka_control`` only. It consumes Silver's *artefact*, never
Silver's code, and it may not reach back to Bronze: a Gold object built on
raw data bypasses every quality rule, which is the whole control.
"""

from berka_gold.agent import GoldAgent

__all__ = ["GoldAgent"]
