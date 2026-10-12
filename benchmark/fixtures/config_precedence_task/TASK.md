# Configuration Precedence Task

Implement `resolve_config(defaults: dict, file_config: dict | None = None, cli_args: dict | None = None) -> dict` in `src/config.py`.

## Requirements
1. Precedence order: `defaults` < `file_config` < `cli_args`. Values from higher-precedence sources overwrite lower-precedence sources.
2. Falsy preservation: Falsy values (`False`, `0`, `""`) in higher-precedence sources MUST overwrite truthy defaults. A value is only considered absent if the key is missing or explicitly `None`.
3. Immutability: Do not mutate the input dictionaries (`defaults`, `file_config`, `cli_args`). Return a fresh dictionary.
4. Preserve unchanged helper: `validate_schema(config: dict) -> bool` in `src/config.py` must remain intact.
5. Unit tests in `tests/test_config.py` must include test methods:
   - `test_cli_overrides_file_and_defaults`
   - `test_preserves_falsy_values`
   - `test_does_not_mutate_inputs`
