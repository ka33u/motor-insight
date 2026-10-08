"""In-process API acceptance on an isolated, normally replayed public Excel DB."""
import argparse,csv,hashlib,io,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);db=parser.parse_args().db.resolve()
    assert db.is_file() and db!=(ROOT/'data/platform.sqlite3').resolve()
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();protected=sha(ROOT/'data/platform.sqlite3')
    sys.path.insert(0,str(ROOT));os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',MOTOR_SQLITE_PATH=str(db))
    import django;django.setup()
    from django.test import Client
    from django.contrib.auth import get_user_model
    from app.models import Record,AuditEvent
    from app import wip_trial_replay
    facts=list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'));audit_before=AuditEvent.objects.count()
    counts=dict(boards=0,exports=0,json_replays=0,paused_rejections=0);roles=[];first_receipt=None
    def get(client,path,query=None,status=200):
        response=client.get(path,query or {});assert response.status_code==status,(path,response.status_code,response.content[:180]);return response
    get(Client(),'/api/wip-trial/WR-261001-001/selection/export',status=401)
    for role in ('admin','analyst','operations','quality','finance','viewer'):
        client=Client();client.force_login(get_user_model().objects.get(username='demo_'+role));allowed=role in ('admin','analyst','operations');roles.append(dict(role=role,allowed=allowed))
        if not allowed:
            get(client,'/api/wip-trial/WR-261001-001/selection/export',dict(receipt=first_receipt),403);continue
        if first_receipt:get(client,'/api/wip-trial/WR-261001-001/selection/export',dict(receipt=first_receipt),409)
        for n in (1,3,4):
            for policy in ('due','priority'):
                base=f'/api/wip-trial/WR-261001-{n:03}';board=get(client,base,dict(policy=policy)).json();counts['boards']+=1
                if first_receipt is None:first_receipt=board['receipt']
                query=dict(policy=policy,receipt=board['receipt']);path=base+'/selection/export'
                if board['state']!='trial':get(client,path,query,400);counts['paused_rejections']+=1;continue
                roots=[t['id'] for t in board['tasks'] if t['root_tasks']==[t['id']]]
                scopes=[dict(job=board['jobs'][0]['id'],state='completed',root=''),dict(job='',state='carried',root=roots[0] if roots else ''),dict(job='',state='blocked',root=roots[0] if roots else '')]
                for scope in scopes:
                    expected=[t['id'] for t in board['tasks'] if (not scope['job'] or t['job_id']==scope['job']) and t['state']==scope['state'] and (not scope['root'] or scope['root'] in t['root_tasks'])]
                    for fmt in ('csv','json'):
                        response=get(client,path,query|scope|dict(format=fmt));counts['exports']+=1
                        assert response['Cache-Control']=='no-store' and response['Content-Disposition'].startswith('attachment;')
                        raw=response.content
                        if fmt=='json':
                            doc=response.json();assert doc['selection']['task_ids']==expected
                            assert wip_trial_replay.replay_selection(doc)==doc['selection'];counts['json_replays']+=1
                            assert doc['result']['tasks']==board['tasks'] and len(doc['sources'])==board['source_count'] and 'receipt' not in doc
                        else:
                            rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));start=rows.index(['筛选任务 · 一行一原任务']);fields=rows[start+1];ids=[]
                            for row in rows[start+2:]:
                                if not row:break
                                ids.append(dict(zip(fields,row))['id'])
                            assert ids==expected and ['完整方案任务数',str(len(board['tasks']))] in rows
                        for forbidden in ('hourly_cents','unit_cost_cents','joint_context'):assert forbidden not in raw.decode()
                        audit=AuditEvent.objects.latest('id');assert audit.action=='wip_trial.selection_export'
                        assert audit.detail['task_count']==len(expected) and audit.detail['file_sha256']==hashlib.sha256(raw).hexdigest() and not audit.detail['business_facts_changed']
                get(client,path,query|dict(receipt='obsolete'),409);get(client,path,status=400)
    assert facts==list(Record.objects.order_by('dataset','business_key').values_list('dataset','business_key','record_hash'))
    assert AuditEvent.objects.count()==audit_before+counts['exports'] and sha(ROOT/'data/platform.sqlite3')==protected
    proof=dict(success=True,roles=roles,**counts,facts=len(facts),facts_unchanged=True,main_database_bytes_unchanged=True,
        reused_public_xlsx_database_version='0.36.0',fresh_xlsx_replay=False,native_network_http=False,browser_acceptance=False,actual_download_acceptance=False)
    (ROOT/'data/wip_selection_api.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof))


if __name__=='__main__':main()
