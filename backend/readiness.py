from pathlib import Path
import os
from backend.database import connection,get_db_path
from backend.rule_config import active_rules,ROOT

def model_path():
    path=Path(os.getenv('POSE133_MODEL_PATH',str(ROOT/'data/models/rtmw_x_384.onnx')))
    return path if path.is_absolute() else ROOT/path

def readiness():
    from backend import inference_133
    path=model_path();available=False;reason='missing'
    if path.is_file():
        with path.open('rb') as f:prefix=f.read(64)
        reason='lfs_pointer' if prefix.startswith(b'version https://git-lfs.github.com/spec') else 'available'
        available=reason=='available'
    rules={}
    for pose in ('tadasana','ardhakati_chakrasana'):
        try:
            rule,item=active_rules(pose)
            rules[pose]={'version':rule['version'],'reviewed':rule['reviewed'],
                'correction_phases':item['online_phases'] if rule['reviewed'] else []}
        except (OSError,ValueError):rules[pose]={'reviewed':False,'correction_phases':[],'error':'unavailable'}
    try:
        with connection() as conn:conn.execute('SELECT 1')
        database=True
    except Exception:database=False
    key=os.getenv('LLM_API_KEY','');model=os.getenv('LLM_MODEL','')
    return {'status':'ready' if available and database else 'not_ready','mode':'real',
        'model':{'name':path.name,'available':available,'loaded':inference_133.source_model()!='unavailable','reason':reason},
        'rules':rules,'database':{'connected':database},
        'llm':{'configured':bool(key and key!='replace_me' and model and model!='replace_me' and os.getenv('LLM_BASE_URL')),'optional':True}}
