"""Raise a change to the frozen surface instead of making it.

An agent that needs a different constant, a new contract guarantee or a wider
ownership scope writes a proposal here and stops. A human applies it, bumps
the control dataset version, and re-runs the affected layers.

The mechanism is deliberately boring -- a JSON file per proposal -- because its
value is the discipline, not the machinery.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Where proposals land. One file each, so two agents proposing at once cannot
#: lose each other's work.
PROPOSAL_DIR = Path(".agentsim") / "proposals"


@dataclass
class ChangeProposal:
    """A requested change to the governed surface.

    :ivar proposal_id: Unique identifier.
    :ivar raised_by: The layer agent raising it.
    :ivar target: What in the control dataset should change.
    :ivar current: The value today, as the agent read it.
    :ivar proposed: The value the agent needs.
    :ivar reason: Why, in terms of what breaks without it.
    :ivar blocks: Whether the agent cannot finish until this is applied.
    :ivar raised_at: UTC timestamp.
    """

    proposal_id: str
    raised_by: str
    target: str
    current: str
    proposed: str
    reason: str
    blocks: bool
    raised_at: str


def propose(
    raised_by: str,
    target: str,
    current: str,
    proposed: str,
    reason: str,
    blocks: bool = False,
    directory: Path | None = None,
) -> ChangeProposal:
    """Record a proposed change to the frozen surface.

    :param raised_by: Name of the layer agent.
    :param target: Dotted path into the control dataset, for example
        ``shared_constants.balance_tolerance_czk``.
    :param current: The present value, as the agent observed it.
    :param proposed: The value the agent is asking for.
    :param reason: What breaks or stays wrong without the change.
    :param blocks: ``True`` when the agent cannot meet its acceptance criteria
        until the change is applied.
    :param directory: Override for the proposal directory, used by tests.
    :returns: The recorded :class:`ChangeProposal`.
    """
    target_dir = directory or PROPOSAL_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    proposal = ChangeProposal(
        proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
        raised_by=raised_by,
        target=target,
        current=current,
        proposed=proposed,
        reason=reason,
        blocks=blocks,
        raised_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    path = target_dir / f"{proposal.proposal_id}.json"
    path.write_text(json.dumps(asdict(proposal), indent=2), encoding="utf-8")
    return proposal


def pending(directory: Path | None = None) -> list[ChangeProposal]:
    """List the proposals waiting for a human.

    :param directory: Override for the proposal directory.
    :returns: Proposals, oldest first.
    """
    target_dir = directory or PROPOSAL_DIR
    if not target_dir.exists():
        return []
    proposals = [
        ChangeProposal(**json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(target_dir.glob("prop_*.json"))
    ]
    return sorted(proposals, key=lambda p: p.raised_at)
