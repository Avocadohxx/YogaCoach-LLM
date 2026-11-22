"""Verify portable provenance against recorded hashes, without altering evidence."""
from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1]
failed=False
for file in ['knowledge/tadasana_rules.json','knowledge/tadasana_rules_B.json']:
 for label,item in json.loads((root/file).read_text()).get('provenance',{}).items():
  path=root/item['source_file'];ok=path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==item['source_sha256']
  print(file,label,'OK' if ok else 'MISSING_OR_HASH_MISMATCH');failed=failed or not ok
raise SystemExit(1 if failed else 0)
