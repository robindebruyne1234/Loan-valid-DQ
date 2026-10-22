"""Load the control dataset and enforce that it stays frozen.

The shared surface between the three layer agents is this dataset rather than
a Python module, for one reason: a shared ``config.py`` is code that three
agents are each tempted to edit, and a frozen dataset is something they read
and may only change by proposal. The enforcement is here.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: The control dataset ships inside the package, so a layer package depends on
#: the surface as a versioned artefact rather than on a path in a repository.
CONTROL_DATASET_PATH = Path(__file__).with_name("control_dataset.yaml")


class FrozenSurfaceError(RuntimeError):
    """Raised when something tries to modify the frozen control surface.

    Seeing this is the system working: the write should become a proposal
    through :mod:`berka_control.proposals`.
    """


@dataclass(frozen=True)
class LayerSpec:
    """The governance entry for one layer.

    :ivar name: Layer name, one of ``bronze``, ``silver``, ``gold``.
    :ivar package: The Python distribution that implements it.
    :ivar goal: The single sentence the layer is accountable for.
    :ivar owns: Repository paths the layer's agent may write.
    :ivar may_import: Packages it may import.
    :ivar must_not_import: Packages importing which is a scope violation.
    :ivar consumes: Name of the contract it consumes, or ``None`` for bronze.
    :ivar publishes: The contract it publishes, as declared in the dataset.
    """

    name: str
    package: str
    goal: str
    owns: tuple[str, ...]
    may_import: tuple[str, ...]
    must_not_import: tuple[str, ...]
    consumes: str | None
    publishes: dict[str, Any]


class ControlDataset:
    """Read-only access to the governed surface.

    Every accessor returns a copy or an immutable view. There is deliberately
    no setter: an agent that needs a different constant raises a proposal.
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        """Wrap a parsed control dataset.

        :param raw: The parsed YAML document.
        """
        self._raw = raw

    # -- governance ---------------------------------------------------------

    @property
    def frozen(self) -> bool:
        """Whether the surface is frozen against direct modification.

        :returns: ``True`` when changes must go through a proposal.
        """
        return bool(self._raw.get("frozen", True))

    @property
    def version(self) -> int:
        """Version of the control surface.

        :returns: The integer version, bumped whenever a proposal is applied.
        """
        return int(self._raw["version"])

    def set(self, target: str, value: Any) -> None:
        """Refuse a direct change to the frozen surface.

        There is no code path that writes the control dataset. This method
        exists so that an agent reaching for one gets an error that names the
        alternative, rather than an AttributeError it might work around.

        :param target: Dotted path the caller wanted to change.
        :param value: The value it wanted to set.
        :raises FrozenSurfaceError: Always, while the surface is frozen.
        """
        if self.frozen:
            raise FrozenSurfaceError(
                f"the control surface is frozen: '{target}' cannot be set to "
                f"{value!r} from a layer agent. Raise a proposal instead -- "
                "LayerAgent.propose(target, current, proposed, reason) -- and a "
                "human applies it and bumps the surface version."
            )
        raise FrozenSurfaceError("direct writes to the control dataset are not supported")

    def constant(self, name: str) -> Any:
        """Read one shared constant.

        :param name: Key under ``shared_constants``.
        :returns: The value, parsed to a date where it looks like one.
        :raises KeyError: When no such constant is declared.
        """
        value = self._raw["shared_constants"][name]
        if isinstance(value, str) and len(value) == 10 and value[4] == "-":
            try:
                return dt.date.fromisoformat(value)
            except ValueError:
                return value
        return value

    def layer(self, name: str) -> LayerSpec:
        """Return the governance entry for one layer.

        :param name: ``bronze``, ``silver`` or ``gold``.
        :returns: The :class:`LayerSpec`.
        :raises KeyError: When the layer is not declared.
        """
        entry = self._raw["layers"][name]
        return LayerSpec(
            name=name,
            package=entry["package"],
            goal=entry["goal"],
            owns=tuple(entry.get("owns") or ()),
            may_import=tuple(entry.get("may_import") or ()),
            must_not_import=tuple(entry.get("must_not_import") or ()),
            consumes=entry.get("consumes"),
            publishes=dict(entry["publishes"]),
        )

    @property
    def layer_order(self) -> tuple[str, ...]:
        """Layer names in dependency order.

        Derived from the declared ``consumes`` chain rather than hard-coded,
        so inserting a layer does not need a code change here.

        :returns: Layer names, upstream first.
        :raises ValueError: When the declared chain is not a simple sequence.
        """
        layers = {name: self.layer(name) for name in self._raw["layers"]}
        published_by = {spec.publishes["name"]: name for name, spec in layers.items()}
        roots = [name for name, spec in layers.items() if spec.consumes is None]
        if len(roots) != 1:
            raise ValueError(f"expected exactly one root layer, found {roots}")

        order = [roots[0]]
        while len(order) < len(layers):
            upstream_contract = layers[order[-1]].publishes["name"]
            successors = [
                name for name, spec in layers.items()
                if spec.consumes == upstream_contract
            ]
            if len(successors) != 1:
                raise ValueError(
                    f"layer '{order[-1]}' has {len(successors)} successors; "
                    "the control dataset declares a branch, not a chain"
                )
            order.append(successors[0])
        _ = published_by
        return tuple(order)

    # -- the control dataset proper -----------------------------------------

    def source_file(self, name: str) -> str:
        """Return one fixture source file as text.

        :param name: File name, for example ``client.asc``.
        :returns: The file's contents.
        """
        return self._raw["control_dataset"]["source_files"][name]

    @property
    def source_files(self) -> dict[str, str]:
        """All fixture source files.

        :returns: Mapping of file name to contents.
        """
        return dict(self._raw["control_dataset"]["source_files"])

    def expectation(self, layer: str) -> dict[str, Any]:
        """Return the known-correct result for one layer.

        This is what makes a layer verifiable on its own: the agent compares
        what it produced against a stated answer, with no database and no
        upstream run.

        :param layer: Layer name.
        :returns: The expectation block for that layer.
        """
        return dict(self._raw["control_dataset"]["expectations"][layer])


def load(path: Path | None = None) -> ControlDataset:
    """Load the control dataset.

    :param path: Optional override, used by tests that need a variant surface.
    :returns: A read-only :class:`ControlDataset`.
    """
    source = path or CONTROL_DATASET_PATH
    return ControlDataset(yaml.safe_load(source.read_text(encoding="utf-8")))
