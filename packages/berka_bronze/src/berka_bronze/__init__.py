"""Bronze layer: land source data verbatim and prove what arrived.

Depends on ``berka_control`` and nothing else. Importing ``berka_silver`` or
``berka_gold`` from here is a scope violation the runtime detects.
"""

from berka_bronze.agent import BronzeAgent

__all__ = ["BronzeAgent"]
