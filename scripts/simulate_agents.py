"""Simulate the three layer agents end to end, without calling an LLM.

Why a simulation rather than three real agents: the thing worth testing is
not whether a model can write Python, it is whether the **boundary holds** --
whether a layer can be changed on its own, whether a contract breach is caught
at the handoff instead of three layers later, and whether an agent has a
definition of done it can check itself against. All of that is decidable
without a model in the loop, and decidable in 30 milliseconds.

This module is the only one that imports all three layers. Each layer package
imports ``berka_control`` and nothing else, which is what makes them
independently changeable.

Usage::

    python scripts/simulate_agents.py                 # run bronze, silver, gold
    python scripts/simulate_agents.py --only silver   # re-run one layer alone
    python scripts/simulate_agents.py --fault <name>  # prove a gate catches it

The ``--only`` flag is the point of writing artefacts to disk: a layer is
re-run against the saved upstream artefact, so changing Silver costs a
millisecond and does not require Bronze, a database, or the other two agents.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for package in ("berka_control", "berka_bronze", "berka_silver", "berka_gold"):
    sys.path.insert(0, str(PROJECT_ROOT / "packages" / package / "src"))

from berka_control import LayerAgent, LayerArtifact, load  # noqa: E402
from berka_control.proposals import pending  # noqa: E402

#: Where artefacts and reports land. One directory per run keeps an
#: intermediate step inspectable after the fact.
RUN_DIR = PROJECT_ROOT / ".agentsim" / "last_run"

#: Where the injected scope fault is written. A real agent would add an import
#: to a real module; the simulation adds one to a throwaway module in the same
#: package, so the scope gate sees exactly what it would see in production.
_SCOPE_FAULT_FILE = (
    PROJECT_ROOT / "packages" / "berka_silver" / "src" / "berka_silver" / "_scope_fault.py"
)

#: Faults the harness can inject, to prove each gate actually catches
#: something. A simulation that always passes demonstrates nothing -- the same
#: argument as the defect injector in the production pipeline.
FAULTS: dict[str, str] = {
    "scope": "silver imports berka_gold -- a layer reaching across the boundary",
    "contract": "silver drops a row -- breaking 'this layer never filters'",
    "acceptance": "gold miscomputes a certified metric",
    "dangling-flag": "silver records a flag whose key resolves to no row",
}

#: Scenarios are not faults: they exercise a designed path and are expected to
#: PASS. ``propose`` shows freeze-and-propose working -- an agent needs a
#: different constant, is refused the edit, raises a proposal and carries on.
SCENARIOS: dict[str, str] = {
    "propose": "silver needs a wider balance tolerance and may not edit the surface",
}


def _display(path: Path) -> str:
    """Render a path relative to the project when it is inside it.

    The run directory is overridable, and a test points it at a temporary
    directory outside the repository, so this must not assume containment.

    :param path: Path to display.
    :returns: A repository-relative path, or the absolute path.
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_agents(
    control: Any, fault: str | None, scenario: str | None = None
) -> dict[str, LayerAgent]:
    """Instantiate one agent per layer, optionally with a fault or scenario.

    :param control: The loaded control dataset.
    :param fault: Name of a fault from :data:`FAULTS`, or ``None``.
    :param scenario: Name of a scenario from :data:`SCENARIOS`, or ``None``.
    :returns: Mapping of layer name to agent instance.
    """
    from berka_bronze import BronzeAgent
    from berka_gold import GoldAgent
    from berka_silver import SilverAgent

    agents: dict[str, LayerAgent] = {
        "bronze": BronzeAgent(control),
        "silver": SilverAgent(control),
        "gold": GoldAgent(control),
    }
    if fault:
        agents = _inject(agents, fault)
    if scenario:
        agents = _scenario(agents, scenario)
    return agents


def _scenario(agents: dict[str, LayerAgent], scenario: str) -> dict[str, LayerAgent]:
    """Wrap an agent so it exercises a designed path that should still pass.

    :param agents: The healthy agents.
    :param scenario: Which scenario to run.
    :returns: The agents, one of them exercising the path.
    :raises SystemExit: When the scenario name is unknown.
    """
    if scenario not in SCENARIOS:
        raise SystemExit(f"unknown scenario '{scenario}'; choose from {', '.join(SCENARIOS)}")

    if scenario == "propose":
        from berka_control import FrozenSurfaceError

        silver = agents["silver"]
        original = silver.work

        def proposing_work(upstream: LayerArtifact | None) -> dict[str, Any]:
            current = silver.control.constant("balance_tolerance_czk")
            try:
                # What an agent would reach for first, and must not get.
                silver.control.set("shared_constants.balance_tolerance_czk", 5.00)
            except FrozenSurfaceError:
                silver.propose(
                    target="shared_constants.balance_tolerance_czk",
                    current=str(current),
                    proposed="5.00",
                    reason=(
                        "the source carries one decimal place, so residuals "
                        "accumulate past 1.00 CZK on long-lived accounts; at the "
                        "current tolerance the rounding band and the material "
                        "band cannot be told apart"
                    ),
                )
            return original(upstream)

        silver.work = proposing_work  # type: ignore[method-assign]

    return agents


def _inject(agents: dict[str, LayerAgent], fault: str) -> dict[str, LayerAgent]:
    """Wrap an agent so that it breaks in one specific, realistic way.

    :param agents: The healthy agents.
    :param fault: Which fault to inject.
    :returns: The agents, one of them sabotaged.
    :raises SystemExit: When the fault name is unknown.
    """
    if fault not in FAULTS:
        raise SystemExit(f"unknown fault '{fault}'; choose from {', '.join(FAULTS)}")

    if fault == "scope":
        # An agent "helpfully" imports a sibling layer to reuse something.
        # Nothing about the output is wrong, which is exactly why scope is a
        # separate gate: the damage is to the boundary, not to the numbers.
        # The import is written into the package source, because that is what
        # the scope gate reads; _SCOPE_FAULT_FILE is removed in run()'s finally.
        _SCOPE_FAULT_FILE.write_text(
            '"""Injected by the simulation to violate the layer boundary."""\n'
            "import berka_gold  # noqa: F401\n",
            encoding="utf-8",
        )

    elif fault == "contract":
        silver = agents["silver"]
        original = silver.work

        def filtering_work(upstream: LayerArtifact | None) -> dict[str, Any]:
            payload = original(upstream)
            payload["tables"]["trans"]["rows"] = payload["tables"]["trans"]["rows"][:-1]
            return payload

        silver.work = filtering_work  # type: ignore[method-assign]

    elif fault == "acceptance":
        gold = agents["gold"]
        original_metrics = gold._certified_metrics

        def wrong_metrics(tables: dict[str, Any]) -> dict[str, float]:
            metrics = original_metrics(tables)
            metrics["problematic_loan_pct"] = 0.0
            return metrics

        gold._certified_metrics = wrong_metrics  # type: ignore[method-assign]

    elif fault == "dangling-flag":
        silver = agents["silver"]
        original = silver.work

        def dangling_work(upstream: LayerArtifact | None) -> dict[str, Any]:
            payload = original(upstream)
            payload["flags"].append({
                "table": "trans",
                "business_key": "4",          # a trans_id ...
                "flag": "con_balance_reconciliation_material",
                "reason": "recorded against the wrong table, as in the real bug",
            })
            payload["flags"][-1]["business_key"] = "9999"   # ... that does not exist
            return payload

        silver.work = dangling_work  # type: ignore[method-assign]

    return agents


def run(
    only: str | None = None,
    fault: str | None = None,
    run_dir: Path | None = None,
    scenario: str | None = None,
) -> int:
    """Run the simulated agent chain.

    :param only: Run just this layer, loading its upstream from the last run.
    :param fault: Inject a fault to prove a gate catches it.
    :param run_dir: Override the run directory.
    :param scenario: Exercise a designed path that is expected to pass.
    :returns: Process exit code: ``0`` when every agent passed.
    """
    control = load()
    directory = run_dir or RUN_DIR
    try:
        return _run_chain(control, directory, only, fault, scenario)
    finally:
        # The injected scope fault is a real file in a real package; it must
        # never outlive the run that created it.
        _SCOPE_FAULT_FILE.unlink(missing_ok=True)


def _run_chain(
    control: Any,
    directory: Path,
    only: str | None,
    fault: str | None,
    scenario: str | None = None,
) -> int:
    """Run the chain itself, with cleanup handled by the caller.

    :param control: The loaded control dataset.
    :param directory: Run directory for artefacts.
    :param only: Single layer to run, or ``None`` for the whole chain.
    :param fault: Injected fault name, or ``None``.
    :param scenario: Scenario name, or ``None``.
    :returns: Process exit code.
    """
    agents = build_agents(control, fault, scenario)
    order = list(control.layer_order)

    print("=" * 72)
    print(f"agent simulation | control surface v{control.version} "
          f"| frozen={control.frozen} | layers: {' -> '.join(order)}")
    if fault:
        print(f"FAULT INJECTED  | {fault}: {FAULTS[fault]}")
    if scenario:
        print(f"SCENARIO        | {scenario}: {SCENARIOS[scenario]}")
    print("=" * 72)

    if only:
        if only not in agents:
            raise SystemExit(f"unknown layer '{only}'; choose from {', '.join(order)}")
        order = [only]

    upstream: LayerArtifact | None = None
    failures = 0

    for layer in order:
        agent = agents[layer]
        if agent.spec.consumes and upstream is None:
            # Re-running one layer alone: load the saved upstream artefact.
            producer = next(
                name for name in control.layer_order
                if control.layer(name).publishes["name"] == agent.spec.consumes
            )
            path = directory / f"{producer}.json"
            if not path.exists():
                raise SystemExit(
                    f"'{layer}' consumes '{agent.spec.consumes}' and "
                    f"{path} does not exist -- run the full chain once first"
                )
            upstream = LayerArtifact.read(path)
            print(f"\n(loaded upstream artefact {path.name}, produced {upstream.produced_at})")

        report, artifact = agent.run(upstream)
        print()
        print(report.render())

        if artifact is None:
            failures += 1
            print(f"\n  >> {layer} produced no artefact; the chain stops here.")
            print("     A layer that fails a gate does not hand work downstream.")
            break

        written = artifact.write(directory)
        print(f"  artefact -> {_display(written)} (digest {artifact.digest})")
        upstream = artifact

    outstanding = pending(PROJECT_ROOT / ".agentsim" / "proposals")
    if outstanding:
        print(f"\n{len(outstanding)} proposal(s) awaiting a human on the frozen surface:")
        for proposal in outstanding:
            print(f"  - {proposal.proposal_id} [{proposal.raised_by}] "
                  f"{proposal.target}: {proposal.current} -> {proposal.proposed}")

    print("\n" + "=" * 72)
    if failures:
        print(f"RESULT: {failures} layer(s) failed a gate." if not fault
              else f"RESULT: the injected fault '{fault}' was caught, as intended.")
    else:
        print("RESULT: all layers passed scope, contract and acceptance." if not fault
              else f"RESULT: the injected fault '{fault}' was NOT caught -- the gate is missing.")
    print("=" * 72)

    if fault:
        # With a fault injected, being caught is success.
        return 0 if failures else 1
    return 1 if failures else 0


def main() -> int:
    """Command line entry point.

    :returns: Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", help="run a single layer against the saved upstream artefact")
    parser.add_argument("--fault", help=f"inject a fault: {', '.join(FAULTS)}")
    parser.add_argument("--scenario", help=f"run a designed path: {', '.join(SCENARIOS)}")
    parser.add_argument("--run-dir", type=Path, help="override the run directory")
    args = parser.parse_args()
    return run(only=args.only, fault=args.fault, run_dir=args.run_dir,
               scenario=args.scenario)


if __name__ == "__main__":
    raise SystemExit(main())
