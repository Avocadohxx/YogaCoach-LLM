"""Explicit online rule manifest; legacy comparator defaults remain draft fixtures."""
from copy import deepcopy
from functools import lru_cache
import json
import os
from pathlib import Path
from backend.pose_rules_tadasana import validate_ruleset as validate_mountain
from backend.pose_rules_ardhakati import validate_ruleset as validate_side
ROOT=Path(__file__).resolve().parents[1]

@lru_cache(maxsize=16)
def _read(path,mtime,size,pose):
    raw=json.loads(Path(path).read_text())
    return (validate_mountain if pose=='tadasana' else validate_side)(raw)

def active_rules(pose):
    manifest=json.loads((ROOT/'knowledge/rules_manifest.json').read_text())
    item=manifest[pose]
    path=Path(os.getenv(item['environment'],str(ROOT/item['path'])))
    if not path.is_absolute():path=ROOT/path
    stat=path.stat()
    return deepcopy(_read(str(path),stat.st_mtime_ns,stat.st_size,pose)),item
