def validate_schema(config: dict) -> bool:
    """Validate that config is a non-empty dictionary; preserved helper."""
    return isinstance(config, dict) and len(config) > 0


def resolve_config(
    defaults: dict,
    file_config: dict | None = None,
    cli_args: dict | None = None,
) -> dict:
    """Resolve layered configuration with precedence and falsy preservation."""
    raise NotImplementedError
