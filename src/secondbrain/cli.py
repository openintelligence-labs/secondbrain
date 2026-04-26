from __future__ import annotations

import click


@click.group()
def main() -> None:
    """SecondBrain — personal AI memory."""


@main.command()
def index() -> None:
    """Index documents in configured folders."""
    click.echo("Indexing... (not yet implemented)")


@main.command()
@click.argument("query")
def search(query: str) -> None:
    """Search your memory with natural language."""
    click.echo(f"Searching for: {query}")
