"""config.py — Re-exports everything from settings.py for backward compatibility."""
from .settings import *  # noqa: F401, F403
from .settings import OS_TYPE  # explicit re-export for import checkers
