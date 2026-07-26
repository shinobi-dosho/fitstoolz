"""Build a `click.Command` from a `@shinobi.pystep` StepRef.

Replaces scabha's `clickify_parameters` + YAML parser configs: options are
derived from the step's pydantic ``inputs_model`` by shinobi's
``build_options`` (dtype, choices, abbreviations, bool/list handling), so a
step's signature is the single schema authority. Mirrors simms 3.0's
``simms.apps.main._make_command``.
"""

from __future__ import annotations

import click
from shinobi.clickutil import build_options, unflatten_kwargs
from shinobi.steps.dispatch import _dispatch


def make_command(step, *, positional: str | None = None, extra_options=()) -> click.Command:
    """Build a `click.Command` for a `@shinobi.pystep` StepRef.

    Args:
        step: The `StepRef` produced by `@shinobi.pystep`.
        positional: Name of the input field to render as a `click.Argument`
            rather than an option (``build_options`` only emits ``--options``).
            This is the scabha ``policies.positional`` equivalent.
        extra_options: Extra `click.Parameter`s to prepend (eager flags etc.).

    Returns:
        A `click.Command` whose callback re-nests the flat kwargs and
        dispatches the step in-process via shinobi, exactly as
        `shinobi.cli`'s ``run`` command does. ``log_level`` is dropped from
        the options and taken from the root group instead.
    """
    model = step.step.inputs_model
    options = [opt for opt in build_options(model) if opt.name != "log_level"]

    params = list(extra_options)
    for opt in options:
        if opt.name == positional:
            params.append(click.Argument([positional], required=True, type=opt.type))
        else:
            params.append(opt)

    def _callback(**raw):
        ctx = click.get_current_context()
        kwargs = unflatten_kwargs(model, raw)
        kwargs["log_level"] = ctx.obj["log_level"]
        result = _dispatch(step.step, step.func, **kwargs)
        if not result.success:
            raise click.ClickException(f"{step.step.name!r} failed (returncode {result.returncode}).")

    return click.Command(
        name=step.step.name,
        params=params,
        callback=_callback,
        help=step.step.info,
        no_args_is_help=True,
    )
