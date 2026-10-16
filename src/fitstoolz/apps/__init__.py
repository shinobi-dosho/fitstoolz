"""The `fitstoolz` command-line apps, one module per subcommand.

Each native `click.Command` derives from a typed function through
`_cli.make_command`; `main.py` assembles the lazy group. Named workflow
steps and their uniform `step` aliases load only with the optional ninja extra.
"""

from ._outputs import FitsOutputs, outfits_name

__all__ = ["FitsOutputs", "outfits_name"]
