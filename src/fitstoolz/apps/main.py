import click

from .lazy_group import LazyClickGroup

applist = "remove_axis add_axis unstack stack slice stats header".split()
app_dict = dict([(name.replace("_", "-"), f"fitstoolz.apps.{name}.command") for name in applist])


@click.group(cls=LazyClickGroup, lazy_subcommands=app_dict, no_args_is_help=True)
@click.option(
    "--log-level", "-ll", help="Log level", type=click.Choice(["INFO", "WARNING", "CRITICAL", "ERROR"]), default="INFO"
)
@click.pass_context
def cli(ctx, log_level) -> None:
    """Command-line tools for simple operations on FITS files"""

    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level
