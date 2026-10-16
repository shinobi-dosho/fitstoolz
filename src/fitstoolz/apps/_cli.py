"""Build native Click commands and optional workflow adapters from typed functions."""

from __future__ import annotations

import inspect
import logging
import types
from typing import Annotated, Literal, Union, get_args, get_origin, get_type_hints

import click
from pydantic import ConfigDict, create_model

from fitstoolz import LOGGER


def inputs_from_signature(func):
    """Keep defaults, validators and descriptions in the function signature."""
    hints = get_type_hints(func, include_extras=True)
    fields = {name: (hints[name], param.default) for name, param in inspect.signature(func).parameters.items()}
    return create_model(f"{func.__name__}Inputs", __config__=ConfigDict(extra="forbid"), **fields)


def _leaves(annotation):
    origin = get_origin(annotation)
    if origin is Annotated:
        return _leaves(get_args(annotation)[0])
    if origin in (Union, types.UnionType, list, tuple):
        return [leaf for arg in get_args(annotation) if arg is not type(None) for leaf in _leaves(arg)]
    return [annotation]


def _is_list(annotation):
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        return all(_is_list(arg) for arg in get_args(annotation) if arg is not type(None))
    return origin in (list, tuple)


def build_options(model):
    """Render fitstoolz's flat schemas as Click options, including their short aliases."""
    options = []
    for name, field in model.model_fields.items():
        default = None if field.is_required() else field.default
        leaves = _leaves(field.annotation)
        multiple = _is_list(field.annotation)
        flag = "--" + name.replace("_", "-")
        kwargs = {"required": field.is_required(), "help": field.description}
        if bool in leaves and not multiple:
            flag += "/--no-" + name.replace("_", "-")
            kwargs.update(is_flag=True, default=bool(default))
        else:
            choices = next((get_args(leaf) for leaf in leaves if get_origin(leaf) is Literal), None)
            scalars = set(leaves) & {str, int, float, bool}
            scalar = next(iter(scalars)) if len(scalars) == 1 else str
            kwargs.update(type=click.Choice(choices) if choices else scalar, multiple=multiple)
            if default is not None:
                kwargs["default"] = default
        metadata = field.json_schema_extra or {}
        abbrev = metadata.get("abbreviation")
        options.append(click.Option([flag, *(["-" + abbrev] if abbrev else [])], **kwargs))
    return options


def optional_step(func, *, name, info):
    """Load the optional workflow adapter only when its public export is requested."""
    try:
        from shinobi import pystep
    except ModuleNotFoundError as exc:
        if exc.name != "shinobi":
            raise
        raise ImportError(
            "The workflow adapter requires fitstoolz[ninja]; install it with uv pip install 'fitstoolz[ninja]'."
        ) from exc
    return pystep(name=name, info=info)(func)


def configure_logging(level: str | int = "INFO") -> None:
    """Attach fitstoolz's console handler, at `level`.

    Called once per command invocation, from the callback below, so every
    subcommand is configured -- `slice`, `unstack` and `sanitise` declare
    ``--log-level`` like the rest but never called ``set_logger``, so the
    level they were given did nothing.

    An unrecognised name lands on INFO. It used to land on 10 (DEBUG), so a
    typo turned the logging all the way *up* -- the same fallback simms
    corrected in shinobi-dosho/simms#197.

    Args:
        level: A level name (``"INFO"``, ``"DEBUG"``, ...), or a logging level.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger(LOGGER)
    logger.setLevel(level)

    if not any(not isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s-%(name)s-%(levelname)-8s| %(message)s"))
        logger.addHandler(handler)
    for handler in logger.handlers:
        handler.setLevel(level)


def make_command(func, *, name, info, model, positional: str | None = None, extra_options=()) -> click.Command:
    """Build a native command from a typed application function and its generated model."""
    params = list(extra_options)
    for opt in build_options(model):
        if opt.name == "log_level":
            continue
        if opt.name == positional:
            params.append(click.Argument([positional], required=True, type=opt.type))
        else:
            params.append(opt)

    def _callback(**raw):
        ctx = click.get_current_context()
        kwargs = {key: value for key, value in raw.items() if value is not None and value != ()}
        kwargs["log_level"] = ctx.obj["log_level"]
        configure_logging(kwargs["log_level"])
        validated = model(**kwargs)
        return func(**{key: getattr(validated, key) for key in model.model_fields})

    return click.Command(name=name, params=params, callback=_callback, help=info, no_args_is_help=True)
