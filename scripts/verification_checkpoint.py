"""Anchor historical zero-write checks behind the exact later source increment."""
from functools import lru_cache
from pathlib import Path
@lru_cache(maxsize=1)
def checked_later_increment(root):
 root=Path(root)
 if not (root/'data/device_intake_actual_import.json').exists():return None
 from validate_device_intake_preservation import verify_increment
 return verify_increment()
def historical_database(root):
 proof=checked_later_increment(str(root))
 return Path(proof['parent_database']) if proof else Path(root)/'data/platform.sqlite3'
def historical_runtime(root,name):
 proof=checked_later_increment(str(root))
 if proof and name in ('app/schema.py','app/access.py'):return Path(root)/'data/device-intake-before'/name
 return Path(root)/name
