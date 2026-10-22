"""Tests for the three-agent layer simulation.

The simulation exists to answer one question: does the boundary hold? These
tests answer it in both directions -- the healthy chain passes, and each
deliberately broken chain is caught by the gate that is supposed to catch it.
A harness that only ever passes proves nothing, which is the same argument as
the defect injector in the production pipeline.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from berka_bronze import BronzeAgent
from berka_control import FrozenSurfaceError, LayerArtifact, load
from berka_control.proposals import pending
from berka_gold import GoldAgent
from berka_silver import SilverAgent

import scripts.simulate_agents as sim

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


@pytest.fixture()
def control():
    """Load the control dataset.

    :returns: The read-only control dataset.
    """
    return load()


# ---------------------------------------------------------------------------
# The governed surface
# ---------------------------------------------------------------------------

def test_the_control_surface_is_frozen(control) -> None:
    """The shared surface refuses a direct write and names the alternative."""
    assert control.frozen is True
    with pytest.raises(FrozenSurfaceError) as excinfo:
        control.set("shared_constants.balance_tolerance_czk", 5.00)
    assert "proposal" in str(excinfo.value).lower()


def test_layer_order_is_derived_from_the_declared_contracts(control) -> None:
    """The run order comes from the contract chain, not from a hard-coded list.

    Inserting a layer should be a change to governed data, not to code.
    """
    assert control.layer_order == ("bronze", "silver", "gold")
    assert control.layer("bronze").consumes is None
    assert control.layer("silver").consumes == control.layer("bronze").publishes["name"]
    assert control.layer("gold").consumes == control.layer("silver").publishes["name"]


def test_every_layer_declares_ownership_and_import_rules(control) -> None:
    """Each layer must say what it owns and what it may not import."""
    for name in control.layer_order:
        spec = control.layer(name)
        assert spec.owns, f"{name} owns nothing"
        assert spec.goal.endswith("."), f"{name} has no stated goal"
        assert "berka_control" in spec.may_import
        assert spec.package not in spec.must_not_import


# ---------------------------------------------------------------------------
# Isolation: the packages are independently changeable, or they are not
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("layer", ["bronze", "silver", "gold"])
def test_layer_package_imports_nothing_it_may_not(control, layer: str) -> None:
    """No layer package may import a sibling layer.

    This is what "isolated packages" has to mean to be worth anything: the
    dependency direction is a straight line into ``berka_control``, verified
    by reading the source rather than by asking the process what it loaded.

    :param layer: Layer under test.
    """
    spec = control.layer(layer)
    forbidden = set(spec.must_not_import)
    offenders: list[str] = []
    root = PACKAGES / spec.package / "src" / spec.package
    for source in sorted(root.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [
                f"{source.name}:{node.lineno} -> {name}"
                for name in names
                if name.split(".")[0] in forbidden
            ]
    assert not offenders, f"{spec.package} reaches across the boundary: {offenders}"


@pytest.mark.parametrize("layer", ["bronze", "silver", "gold"])
def test_each_layer_package_declares_only_the_control_dependency(layer: str) -> None:
    """A layer's distribution must depend on the surface and nothing else.

    :param layer: Layer under test.
    """
    text = (PACKAGES / f"berka_{layer}" / "pyproject.toml").read_text(encoding="utf-8")
    dependencies = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "berka-control" in dependencies
    for sibling in ("berka-bronze", "berka-silver", "berka-gold"):
        if sibling != f"berka-{layer}":
            assert sibling not in dependencies, f"{layer} depends on {sibling}"


# ---------------------------------------------------------------------------
# The healthy chain
# ---------------------------------------------------------------------------

def test_the_full_chain_passes_every_gate(control, tmp_path: Path) -> None:
    """Bronze, Silver and Gold each pass scope, contract and acceptance."""
    assert sim.run(run_dir=tmp_path) == 0
    for layer in control.layer_order:
        assert (tmp_path / f"{layer}.json").exists(), f"{layer} wrote no artefact"


def test_each_agent_has_acceptance_criteria_it_can_check(control, tmp_path: Path) -> None:
    """No agent may finish without a definition of done it evaluated itself.

    An agent with no stopping condition does not stop; this is the test that
    makes that structural rather than hoped for.
    """
    upstream = None
    for layer, agent_class in (
        ("bronze", BronzeAgent), ("silver", SilverAgent), ("gold", GoldAgent)
    ):
        report, artifact = agent_class(control).run(upstream)
        assert report.acceptance, f"{layer} declared no acceptance criteria"
        assert report.succeeded, report.render()
        assert all(check.passed for check in report.acceptance)
        upstream = artifact


def test_a_layer_can_be_rerun_alone_from_a_saved_artefact(tmp_path: Path) -> None:
    """Changing one layer must not require re-running the others.

    This is the practical payoff of the split: Silver is verified against a
    saved Bronze artefact, with no database and no upstream execution.
    """
    assert sim.run(run_dir=tmp_path) == 0
    bronze_before = (tmp_path / "bronze.json").read_text(encoding="utf-8")
    assert sim.run(only="silver", run_dir=tmp_path) == 0
    assert (tmp_path / "bronze.json").read_text(encoding="utf-8") == bronze_before


def test_artefacts_round_trip(tmp_path: Path) -> None:
    """An artefact written to disk reloads identically, digest included."""
    assert sim.run(run_dir=tmp_path) == 0
    artifact = LayerArtifact.read(tmp_path / "silver.json")
    assert artifact.contract == "silver_conformed"
    assert artifact.payload["tables"]["trans"]["rows"]


# ---------------------------------------------------------------------------
# The broken chains: each gate must catch its own fault
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fault", sorted(sim.FAULTS))
def test_each_injected_fault_is_caught(fault: str, tmp_path: Path) -> None:
    """Every fault the harness can inject is caught by some gate.

    :param fault: Name of the injected fault.
    """
    # run() returns 0 for a caught fault: being stopped is the success.
    assert sim.run(fault=fault, run_dir=tmp_path) == 0, (
        f"fault '{fault}' was not caught -- the corresponding gate is missing"
    )


def test_the_scope_fault_leaves_no_residue(tmp_path: Path) -> None:
    """The injected scope violation is removed however the run ends."""
    sim.run(fault="scope", run_dir=tmp_path)
    assert not sim._SCOPE_FAULT_FILE.exists()


def test_a_failed_layer_hands_nothing_downstream(tmp_path: Path) -> None:
    """A layer that fails a gate must not produce an artefact.

    Passing broken work on is how one layer's defect becomes three layers'
    debugging.
    """
    sim.run(fault="contract", run_dir=tmp_path)
    assert (tmp_path / "bronze.json").exists()
    assert not (tmp_path / "silver.json").exists()
    assert not (tmp_path / "gold.json").exists()


def test_the_scope_gate_is_independent_of_output_correctness(control) -> None:
    """A scope violation fails the run even though the numbers are right.

    Scope is about the boundary, not the result, so it is checked separately
    and before the work.
    """
    sim._SCOPE_FAULT_FILE.write_text("import berka_gold  # noqa: F401\n", encoding="utf-8")
    try:
        report, artifact = SilverAgent(control).run(
            LayerArtifact(layer="bronze", contract="bronze_landing",
                          payload=BronzeAgent(control).work(None))
        )
        assert not report.succeeded
        assert report.scope_violations
        assert not report.acceptance, "work ran despite a scope violation"
        assert artifact is None
    finally:
        sim._SCOPE_FAULT_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Freeze and propose
# ---------------------------------------------------------------------------

def test_an_agent_refused_a_change_raises_a_proposal(tmp_path: Path) -> None:
    """The designed path: refused the edit, raises a proposal, carries on."""
    proposals_before = len(pending(Path(".agentsim") / "proposals"))
    assert sim.run(scenario="propose", run_dir=tmp_path) == 0
    outstanding = pending(Path(".agentsim") / "proposals")
    assert len(outstanding) == proposals_before + 1
    latest = outstanding[-1]
    assert latest.raised_by == "berka_silver"
    assert latest.target == "shared_constants.balance_tolerance_czk"
    assert len(latest.reason) > 60, "a proposal must say what stays wrong without it"
