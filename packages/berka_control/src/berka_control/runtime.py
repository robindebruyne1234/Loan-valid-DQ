"""The runtime a layer agent runs inside.

This is the part that makes "three agents" more than an organisational chart.
Every agent, real or simulated, goes through the same five steps:

1. **Scope check** -- did it only import what its layer may import?
2. **Input contract** -- is the upstream artefact actually what was promised?
3. **Work** -- the layer's own transformation, which is all the agent writes.
4. **Output contract** -- does what it produced satisfy what it declared?
5. **Acceptance criteria** -- does it match the known answer in the control
   dataset?

An agent that skips step 5 has no definition of done, which is the failure
mode that matters: an agent with no stopping condition does not stop.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from berka_control.contracts import Contract, verify_contract
from berka_control.dataset import ControlDataset, LayerSpec


class ScopeViolation(RuntimeError):
    """Raised when an agent reaches outside the layer it owns.

    The isolation between layers is only real if crossing it fails loudly.
    """


@dataclass
class AcceptanceCheck:
    """One acceptance criterion and its outcome.

    :ivar name: Short description of what is being checked.
    :ivar passed: Whether it held.
    :ivar detail: What was expected and what was found.
    """

    name: str
    passed: bool
    detail: str = ""

    def render(self) -> str:
        """Render as a checklist line.

        :returns: A line of the form ``[x] name -- detail``.
        """
        box = "x" if self.passed else " "
        return f"  [{box}] {self.name}" + (f"  --  {self.detail}" if self.detail else "")


@dataclass
class LayerArtifact:
    """What one layer hands to the next.

    Artefacts are plain data and are written to disk between layers on
    purpose: a layer can then be re-run on its own against a saved upstream
    artefact, which is what "change one layer, or one intermediate step"
    actually requires.

    :ivar layer: Producing layer name.
    :ivar contract: Name of the contract this satisfies.
    :ivar payload: The data itself.
    :ivar produced_at: UTC timestamp.
    """

    layer: str
    contract: str
    payload: dict[str, Any] = field(default_factory=dict)
    produced_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @property
    def digest(self) -> str:
        """Stable digest of the payload, for idempotence checks.

        :returns: Short SHA-256 hex digest.
        """
        encoded = json.dumps(self.payload, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()[:16]

    def write(self, directory: Path) -> Path:
        """Persist the artefact so a downstream layer can be re-run alone.

        :param directory: Run directory.
        :returns: The path written.
        """
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.layer}.json"
        path.write_text(
            json.dumps(
                {
                    "layer": self.layer,
                    "contract": self.contract,
                    "produced_at": self.produced_at,
                    "digest": self.digest,
                    "payload": self.payload,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return path

    @classmethod
    def read(cls, path: Path) -> "LayerArtifact":
        """Load a previously written artefact.

        :param path: Path to the artefact JSON.
        :returns: The reconstructed :class:`LayerArtifact`.
        """
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            layer=raw["layer"],
            contract=raw["contract"],
            payload=raw["payload"],
            produced_at=raw["produced_at"],
        )


@dataclass
class AgentReport:
    """What an agent reports when it finishes.

    Shaped like the report a real subagent would write back, because the point
    of the simulation is to exercise the handoff, not to pretend the work is
    hard.

    :ivar agent: Agent name.
    :ivar layer: Layer it owns.
    :ivar goal: The single sentence it is accountable for.
    :ivar succeeded: Whether every gate passed.
    :ivar scope_violations: Imports outside the declared scope.
    :ivar input_violations: Ways the upstream artefact broke its contract.
    :ivar output_violations: Ways this layer broke its own contract.
    :ivar acceptance: The acceptance checklist.
    :ivar proposals: Changes raised against the frozen surface.
    :ivar notes: Anything the next layer or the human should know.
    :ivar duration_ms: Wall clock time.
    """

    agent: str
    layer: str
    goal: str
    succeeded: bool
    scope_violations: list[str] = field(default_factory=list)
    input_violations: list[str] = field(default_factory=list)
    output_violations: list[str] = field(default_factory=list)
    acceptance: list[AcceptanceCheck] = field(default_factory=list)
    proposals: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    def render(self) -> str:
        """Render the report the way an agent would write it back.

        :returns: A multi-line plain-ASCII report.
        """
        status = "PASS" if self.succeeded else "FAIL"
        lines = [
            f"--- {self.agent} [{status}] ---",
            f"  layer : {self.layer}",
            f"  goal  : {self.goal}",
            f"  time  : {self.duration_ms:.1f} ms",
        ]
        if self.scope_violations:
            lines.append("  SCOPE VIOLATIONS:")
            lines += [f"    ! {item}" for item in self.scope_violations]
        if self.input_violations:
            lines.append("  INPUT CONTRACT BROKEN BY UPSTREAM:")
            lines += [f"    ! {item}" for item in self.input_violations]
        if self.output_violations:
            lines.append("  OUTPUT CONTRACT BROKEN BY THIS LAYER:")
            lines += [f"    ! {item}" for item in self.output_violations]
        if self.acceptance:
            passed = sum(1 for check in self.acceptance if check.passed)
            lines.append(f"  acceptance criteria: {passed}/{len(self.acceptance)}")
            lines += [check.render() for check in self.acceptance]
        for proposal in self.proposals:
            lines.append(f"  PROPOSAL -> {proposal}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


class LayerAgent(ABC):
    """Base class every layer agent implements.

    Subclasses write exactly two methods: :meth:`work`, which is the layer's
    transformation, and :meth:`acceptance_checks`, which is its definition of
    done. Everything else -- scope, contracts, reporting -- is enforced here and
    is identical for all three, which is what keeps the layers comparable.
    """

    #: Layer this agent owns. Set by the subclass.
    layer: str = ""

    def __init__(self, control: ControlDataset) -> None:
        """Bind the agent to the governed surface.

        :param control: The control dataset. Read-only by construction.
        """
        self.control = control
        self.spec: LayerSpec = control.layer(self.layer)
        self._proposals: list[str] = []

    # -- what a subclass implements -----------------------------------------

    @abstractmethod
    def work(self, upstream: LayerArtifact | None) -> dict[str, Any]:
        """Do this layer's transformation.

        :param upstream: The artefact from the previous layer, or ``None`` for
            the root layer.
        :returns: The payload this layer publishes.
        """

    @abstractmethod
    def acceptance_checks(self, payload: dict[str, Any]) -> list[AcceptanceCheck]:
        """Check the output against the known answer in the control dataset.

        :param payload: What :meth:`work` produced.
        :returns: One :class:`AcceptanceCheck` per criterion.
        """

    # -- what the runtime enforces ------------------------------------------

    def propose(self, target: str, current: str, proposed: str, reason: str) -> None:
        """Raise a change to the frozen surface rather than making it.

        :param target: Dotted path into the control dataset.
        :param current: The present value.
        :param proposed: The value this layer needs.
        :param reason: What stays wrong without it.
        :returns: ``None``.
        """
        from berka_control.proposals import propose as record

        proposal = record(
            raised_by=self.spec.package,
            target=target,
            current=current,
            proposed=proposed,
            reason=reason,
        )
        self._proposals.append(f"{proposal.proposal_id} {target}: {current} -> {proposed}")

    def check_scope(self) -> list[str]:
        """Verify the layer's package does not import outside its scope.

        The check reads the package's own source with :mod:`ast`, rather than
        inspecting what the running process happens to have loaded: the
        orchestrator imports all three layers by definition, so process state
        says nothing about whether a layer is isolated. Parsing the source
        answers the question that matters -- "does anything in this package
        reach across the boundary" -- and it is the same check CI would run.

        :returns: List of violations; empty when the scope holds.
        """
        import ast
        import importlib.util

        violations: list[str] = []
        spec = importlib.util.find_spec(self.spec.package)
        if spec is None or not spec.submodule_search_locations:
            return [f"cannot locate package {self.spec.package} to check its scope"]

        forbidden = set(self.spec.must_not_import)
        for root in spec.submodule_search_locations:
            for source in sorted(Path(root).rglob("*.py")):
                try:
                    tree = ast.parse(source.read_text(encoding="utf-8"))
                except SyntaxError as exc:
                    violations.append(f"{source.name} does not parse: {exc}")
                    continue
                for node in ast.walk(tree):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    for name in names:
                        top = name.split(".")[0]
                        if top in forbidden:
                            violations.append(
                                f"{self.spec.package}/{source.name} line "
                                f"{node.lineno} imports {name}; this layer may "
                                f"not import {top}"
                            )
        return violations

    def run(self, upstream: LayerArtifact | None = None) -> tuple[AgentReport, LayerArtifact | None]:
        """Run the agent through all five gates and report.

        :param upstream: The previous layer's artefact, or ``None``.
        :returns: Tuple of (report, artefact). The artefact is ``None`` when a
            gate failed, so a broken layer cannot hand work downstream.
        """
        from time import perf_counter

        started = perf_counter()
        report = AgentReport(
            agent=f"{self.layer}-agent",
            layer=self.layer,
            goal=self.spec.goal,
            succeeded=False,
        )

        report.scope_violations = self.check_scope()
        if report.scope_violations:
            report.duration_ms = (perf_counter() - started) * 1000
            return report, None

        if self.spec.consumes:
            if upstream is None:
                report.input_violations.append(
                    f"this layer consumes '{self.spec.consumes}' and received nothing"
                )
            elif upstream.contract != self.spec.consumes:
                report.input_violations.append(
                    f"expected contract '{self.spec.consumes}', "
                    f"received '{upstream.contract}'"
                )
            if report.input_violations:
                report.duration_ms = (perf_counter() - started) * 1000
                return report, None

        payload = self.work(upstream)

        contract = Contract(name=self.spec.publishes["name"], declaration=self.spec.publishes)
        report.output_violations = verify_contract(contract, payload)
        report.acceptance = self.acceptance_checks(payload)
        report.proposals = list(self._proposals)
        report.succeeded = (
            not report.scope_violations
            and not report.input_violations
            and not report.output_violations
            and all(check.passed for check in report.acceptance)
        )
        report.duration_ms = (perf_counter() - started) * 1000

        artifact = LayerArtifact(layer=self.layer, contract=contract.name, payload=payload)
        return report, (artifact if report.succeeded else None)
