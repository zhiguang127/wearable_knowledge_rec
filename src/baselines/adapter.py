"""Read-only baseline output boundary; execution drivers remain unported."""
from .contracts import validate as legacy_validate
from .schemas import SCHEMAS
from ..annotation.validation import validate as schema_validate
from ..common import Blocked


def validate_output(value, case):
    errors = schema_validate(value, SCHEMAS["full"])
    return errors if errors else legacy_validate(value, case)


def run(*args, **kwargs):
    raise Blocked("BLOCKED_NEW_BASELINE_EXECUTION: this migration only provides offline replay and contracts")
