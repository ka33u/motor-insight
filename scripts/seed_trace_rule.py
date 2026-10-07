"""Seed an editable investigation code rule without replacing user settings."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.db import transaction
from app.models import CodingRule,AuditEvent

with transaction.atomic():
    rule,created=CodingRule.objects.get_or_create(key='trace_case',defaults=dict(name='批次排查记录',prefix='PC',date_format='%Y%m%d',width=5,separator='-',reset_period='day'))
    if created:AuditEvent.objects.create(action='coding.seed',actor='demo_setup',object_type='CodingRule',object_id=str(rule.pk),detail={'key':rule.key,'name':rule.name,'version':rule.version,'purpose':'模拟批次排查快照的可配置编号；保留已有规则。'})
print(json.dumps({'rule_id':rule.pk,'key':rule.key,'version':rule.version,'created':created},ensure_ascii=False))
