import uuid
from django.db import models

class ImportBatch(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    filename=models.CharField(max_length=255)
    file_hash=models.CharField(max_length=64,db_index=True)
    file_path=models.TextField()
    status=models.CharField(max_length=24,default='staging')
    mapping=models.JSONField(default=dict)
    summary=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)
    committed_at=models.DateTimeField(null=True)

class ImportRow(models.Model):
    batch=models.ForeignKey(ImportBatch,on_delete=models.CASCADE,related_name='rows')
    sheet=models.CharField(max_length=100)
    row_number=models.PositiveIntegerField()
    dataset=models.CharField(max_length=64,db_index=True)
    business_key=models.CharField(max_length=255,blank=True)
    raw=models.JSONField(default=dict)
    normalized=models.JSONField(default=dict)
    record_hash=models.CharField(max_length=64,blank=True)
    status=models.CharField(max_length=24,default='valid',db_index=True)
    issues=models.JSONField(default=list)
    class Meta:
        indexes=[models.Index(fields=['batch','status'])]

class ImportTemplate(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    code=models.CharField(max_length=40,unique=True)
    name=models.CharField(max_length=100)
    department=models.CharField(max_length=80)
    owner=models.CharField(max_length=150)
    revision=models.PositiveIntegerField(default=1)
    current_version=models.PositiveIntegerField(default=0)
    created_at=models.DateTimeField(auto_now_add=True)

class ImportTemplateVersion(models.Model):
    template=models.ForeignKey(ImportTemplate,on_delete=models.PROTECT,related_name='versions')
    number=models.PositiveIntegerField()
    payload=models.JSONField()
    content_hash=models.CharField(max_length=64)
    state=models.CharField(max_length=16,default='draft')
    reason=models.TextField()
    created_by=models.CharField(max_length=150)
    created_at=models.DateTimeField(auto_now_add=True)
    activated_by=models.CharField(max_length=150,blank=True)
    activated_at=models.DateTimeField(null=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['template','number'],name='import_template_number_unique')]

class ImportTemplateUse(models.Model):
    batch=models.ForeignKey(ImportBatch,on_delete=models.PROTECT,related_name='template_uses')
    version=models.ForeignKey(ImportTemplateVersion,on_delete=models.PROTECT,related_name='uses')
    receipt_hash=models.CharField(max_length=64)
    actor=models.CharField(max_length=150)
    evidence=models.JSONField()
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['batch','version','receipt_hash'],name='import_template_use_unique')]

class Record(models.Model):
    dataset=models.CharField(max_length=64)
    business_key=models.CharField(max_length=255)
    values=models.JSONField()
    record_hash=models.CharField(max_length=64)
    source_row=models.ForeignKey(ImportRow,on_delete=models.PROTECT)
    revision=models.PositiveIntegerField(default=1)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['dataset','business_key'],name='record_business_key_unique')]
        indexes=[models.Index(fields=['dataset','business_key'])]

class ImportDecision(models.Model):
    """Append-only review evidence; source rows outlive current Record objects."""
    row=models.OneToOneField(ImportRow,on_delete=models.PROTECT,related_name='decision')
    action=models.CharField(max_length=16,choices=[('keep','保留正式记录'),('replace','批准替换')])
    actor=models.CharField(max_length=150)
    reason=models.TextField()
    candidate_hash=models.CharField(max_length=64)
    before=models.JSONField()
    after=models.JSONField()
    created_at=models.DateTimeField(auto_now_add=True)

class AuditEvent(models.Model):
    action=models.CharField(max_length=80)
    actor=models.CharField(max_length=150,default='local_demo')
    object_type=models.CharField(max_length=80)
    object_id=models.CharField(max_length=255)
    detail=models.JSONField(default=dict)
    created_at=models.DateTimeField(auto_now_add=True)

class CodingRule(models.Model):
    key=models.CharField(max_length=80,unique=True)
    name=models.CharField(max_length=100)
    prefix=models.CharField(max_length=40)
    date_format=models.CharField(max_length=20,default='%Y%m%d')
    width=models.PositiveSmallIntegerField(default=5)
    separator=models.CharField(max_length=4,default='-')
    reset_period=models.CharField(max_length=10,default='day')
    version=models.PositiveIntegerField(default=1)
    enabled=models.BooleanField(default=True)
    revision=models.PositiveIntegerField(default=1)

class CodingRuleVersion(models.Model):
    rule=models.ForeignKey(CodingRule,on_delete=models.PROTECT,related_name='versions')
    version=models.PositiveIntegerField()
    payload=models.JSONField(default=dict)
    status=models.CharField(max_length=20,default='draft')
    effective_from=models.DateField(null=True,blank=True)
    reason=models.TextField(blank=True)
    origin=models.CharField(max_length=30,default='authored')
    created_by=models.CharField(max_length=150)
    created_at=models.DateTimeField(auto_now_add=True)
    activated_by=models.CharField(max_length=150,blank=True)
    activated_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['rule','version'],name='coding_version_unique')]

class CodeCounter(models.Model):
    rule=models.ForeignKey(CodingRule,on_delete=models.PROTECT)
    period=models.CharField(max_length=30)
    value=models.PositiveBigIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['rule','period'],name='coding_rule_period_unique')]

class CodeIssueRequest(models.Model):
    id=models.UUIDField(primary_key=True,editable=False)
    rule=models.ForeignKey(CodingRule,on_delete=models.PROTECT)
    rule_version=models.ForeignKey(CodingRuleVersion,on_delete=models.PROTECT)
    payload_hash=models.CharField(max_length=64)
    actor=models.CharField(max_length=150)
    purpose=models.CharField(max_length=300)
    business_date=models.DateField()
    codes=models.JSONField(default=list)
    created_at=models.DateTimeField(auto_now_add=True)

class CodeAllocation(models.Model):
    code=models.CharField(max_length=100,unique=True)
    rule=models.ForeignKey(CodingRule,on_delete=models.PROTECT)
    rule_version=models.PositiveIntegerField()
    allocated_by=models.CharField(max_length=150)
    created_at=models.DateTimeField(auto_now_add=True)
    request=models.ForeignKey(CodeIssueRequest,on_delete=models.PROTECT,null=True,blank=True)
    business_date=models.DateField(null=True,blank=True)
    period=models.CharField(max_length=30,blank=True)
    sequence=models.PositiveBigIntegerField(null=True,blank=True)
    definition=models.JSONField(default=dict)

class AnalysisModel(models.Model):
    name=models.CharField(max_length=150)
    dataset=models.CharField(max_length=64)
    definition=models.JSONField(default=dict)
    version=models.PositiveIntegerField(default=1)
    owner=models.CharField(max_length=150,default='system')
    is_public=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

class BusinessGrouping(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.CharField(max_length=150)
    code=models.CharField(max_length=64)
    revision=models.PositiveIntegerField(default=1)
    archived=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['owner','code'],name='grouping_owner_code_unique')]

class BusinessGroupingVersion(models.Model):
    grouping=models.ForeignKey(BusinessGrouping,on_delete=models.PROTECT,related_name='versions')
    version=models.PositiveIntegerField()
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_by=models.CharField(max_length=150)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['grouping','version'],name='grouping_version_unique')]

class Topic(models.Model):
    name=models.CharField(max_length=150)
    description=models.TextField(blank=True)
    layout=models.JSONField(default=list)
    filters=models.JSONField(default=dict)
    version=models.PositiveIntegerField(default=1)
    owner=models.CharField(max_length=150,default='system')
    is_public=models.BooleanField(default=False)
    updated_at=models.DateTimeField(auto_now=True)

class IssueDisposition(models.Model):
    key=models.CharField(max_length=255,unique=True)
    status=models.CharField(max_length=20,default='待处理')
    owner=models.CharField(max_length=150,blank=True)
    note=models.TextField(blank=True)
    due_date=models.DateField(null=True,blank=True)
    version=models.PositiveIntegerField(default=1)
    updated_by=models.CharField(max_length=150)
    updated_at=models.DateTimeField(auto_now=True)

class GovernedMetric(models.Model):
    key=models.CharField(max_length=64,unique=True)
    dataset=models.CharField(max_length=64)
    owner=models.CharField(max_length=150)
    created_at=models.DateTimeField(auto_now_add=True)

class MetricVersion(models.Model):
    metric=models.ForeignKey(GovernedMetric,on_delete=models.PROTECT,related_name='versions')
    version=models.PositiveIntegerField()
    revision=models.PositiveIntegerField(default=1)
    status=models.CharField(max_length=16,default='draft')
    payload=models.JSONField(default=dict)
    calculation_hash=models.CharField(max_length=64)
    contributors=models.JSONField(default=list)
    submitted_by=models.CharField(max_length=150,blank=True)
    reviewed_by=models.CharField(max_length=150,blank=True)
    review_note=models.TextField(blank=True)
    evidence=models.JSONField(default=dict)
    published_at=models.DateTimeField(null=True)
    retired_at=models.DateTimeField(null=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['metric','version'],name='metric_version_unique'),models.UniqueConstraint(fields=['metric'],condition=models.Q(status__in=['draft','review']),name='metric_one_open_version')]

class TraceCase(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    code=models.CharField(max_length=100,unique=True)
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    title=models.CharField(max_length=150)
    owner=models.CharField(max_length=150)
    due_date=models.DateField(null=True)
    status=models.CharField(max_length=30,default='排查中')
    note=models.TextField()
    version=models.PositiveIntegerField(default=1)
    snapshot=models.JSONField()
    snapshot_hash=models.CharField(max_length=64)
    created_by=models.CharField(max_length=150)
    updated_by=models.CharField(max_length=150)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

class TopicView(models.Model):
    """Personal query configuration; saves definitions' identities, never result values."""
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='topic_views')
    topic=models.ForeignKey(Topic,on_delete=models.PROTECT,related_name='personal_views')
    name=models.CharField(max_length=120)
    config=models.JSONField(default=dict)
    binding=models.JSONField(default=dict)
    version=models.PositiveIntegerField(default=1)
    archived=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

class TopicSnapshot(models.Model):
    """Immutable personal analysis results and permitted source evidence."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='topic_snapshots')
    topic=models.ForeignKey(Topic,on_delete=models.PROTECT,related_name='result_snapshots')
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    name=models.CharField(max_length=120)
    note=models.TextField()
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)

    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('结果快照不可覆盖，请另存一份')
        return super().save(*args,**kwargs)

class CostScenario(models.Model):
    """Immutable scenario run: fixed facts, explicit assumptions and results."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='cost_scenarios')
    parent=models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True)
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    name=models.CharField(max_length=120)
    note=models.TextField()
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)

    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('已保存情景不可覆盖，请另存一份')
        return super().save(*args,**kwargs)

class DeviceFile(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='device_files')
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    filename=models.CharField(max_length=240)
    kind=models.CharField(max_length=12)
    size=models.PositiveIntegerField()
    file_hash=models.CharField(max_length=64)
    note=models.TextField()
    parsed=models.JSONField()
    metadata_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('检测文件原件和元数据不可覆盖，请另行归档')
        return super().save(*args,**kwargs)

class DeviceFileReview(models.Model):
    file=models.ForeignKey(DeviceFile,on_delete=models.PROTECT,related_name='reviews')
    version=models.PositiveIntegerField()
    session_id=models.CharField(max_length=150)
    action=models.CharField(max_length=20)
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['file','version'],name='device_review_version_unique')]
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('文件关联审核不可覆盖，请追加确认或撤销')
        return super().save(*args,**kwargs)

class FileReadGrant(models.Model):
    """Append-only, owner-issued original-file read grants and revocations."""
    file=models.ForeignKey(DeviceFile,on_delete=models.PROTECT,related_name='read_grants')
    recipient=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='original_read_grants')
    actor=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='original_grant_actions')
    version=models.PositiveIntegerField()
    action=models.CharField(max_length=10)
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['file','version'],name='unique_file_read_grant_version')]

    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('原件授权历史不可覆盖，请追加授权或撤销')
        return super().save(*args,**kwargs)
class DataQualityScan(models.Model):
    """Immutable, value-free structural inspection of committed source records."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    request_id=models.UUIDField(unique=True)
    actor=models.CharField(max_length=150)
    source_revision=models.JSONField()
    engine_hash=models.CharField(max_length=64)
    snapshot=models.JSONField()
    snapshot_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)

class DataMonitorPolicy(models.Model):
    dataset=models.CharField(max_length=64,unique=True)
    owner=models.CharField(max_length=150)
    business_clock=models.CharField(max_length=64,blank=True)
    max_business_lag_days=models.FloatField(null=True)
    max_import_age_hours=models.PositiveIntegerField(null=True)
    note=models.TextField()
    version=models.PositiveIntegerField(default=1)
    updated_by=models.CharField(max_length=150)
    updated_at=models.DateTimeField(auto_now=True)


class AccountAccessState(models.Model):
    user=models.OneToOneField('auth.User',on_delete=models.PROTECT,related_name='access_state')
    revision=models.PositiveIntegerField(default=0)
    session_epoch=models.PositiveIntegerField(default=0)
    updated_by=models.CharField(max_length=150,blank=True)
    updated_at=models.DateTimeField(auto_now=True)

class AccountChangeLock(models.Model):
    """One transaction lock serializes access changes, including last-admin checks."""
    revision=models.PositiveBigIntegerField(default=0)


class ActionTask(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    dataset=models.CharField(max_length=64)
    business_key=models.CharField(max_length=255)
    rule=models.CharField(max_length=40)
    classification=models.CharField(max_length=20)
    title=models.CharField(max_length=150)
    description=models.TextField()
    state=models.CharField(max_length=20,default='reported',db_index=True)
    creator=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='created_action_tasks')
    assignee=models.ForeignKey('auth.User',on_delete=models.PROTECT,null=True,related_name='assigned_action_tasks')
    reviewer=models.ForeignKey('auth.User',on_delete=models.PROTECT,null=True,related_name='review_action_tasks')
    due_date=models.DateField(null=True)
    source_snapshot=models.JSONField()
    submission=models.JSONField(default=dict)
    cycle=models.PositiveIntegerField(default=1)
    version=models.PositiveIntegerField(default=1)
    closed_at=models.DateTimeField(null=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['dataset','business_key','rule'],name='action_task_source_rule_unique')]


class ActionTaskEvent(models.Model):
    task=models.ForeignKey(ActionTask,on_delete=models.PROTECT,related_name='events')
    sequence=models.PositiveIntegerField()
    action=models.CharField(max_length=20)
    actor=models.ForeignKey('auth.User',on_delete=models.PROTECT)
    request_id=models.UUIDField()
    payload_hash=models.CharField(max_length=64)
    note=models.TextField()
    before=models.JSONField()
    after=models.JSONField()
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['task','sequence'],name='action_event_sequence_unique'),
                     models.UniqueConstraint(fields=['actor','request_id'],name='action_request_unique')]


class ActionTaskLock(models.Model):
    revision=models.PositiveBigIntegerField(default=0)


class DeviceCollectionRun(models.Model):
    """Immutable sampled file manifest; ownership does not grant business authority."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='device_collection_runs')
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    source_id=models.CharField(max_length=100)
    context_hash=models.CharField(max_length=64)
    manifest=models.JSONField()
    manifest_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('采集清单不可覆盖，请建立新观察与运行')
        return super().save(*args,**kwargs)


class DeviceCollectionEvent(models.Model):
    """Append-only per-file collection attempts with optimistic versions."""
    run=models.ForeignKey(DeviceCollectionRun,on_delete=models.PROTECT,related_name='events')
    item_key=models.CharField(max_length=64)
    version=models.PositiveIntegerField()
    request_id=models.UUIDField()
    request_hash=models.CharField(max_length=64)
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['run','item_key','version'],name='collection_item_version_unique'),models.UniqueConstraint(fields=['run','item_key','request_id'],name='collection_item_request_unique')]
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('采集回执不可覆盖，请追加重试结果')
        return super().save(*args,**kwargs)


class DeviceTransformTemplate(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='device_transform_templates')
    code=models.CharField(max_length=80)
    name=models.CharField(max_length=160)
    revision=models.PositiveIntegerField(default=0)
    current_version=models.PositiveIntegerField(default=0)
    metadata_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['owner','code'],name='device_transform_owner_code_unique')]


class DeviceTransformVersion(models.Model):
    template=models.ForeignKey(DeviceTransformTemplate,on_delete=models.PROTECT,related_name='versions')
    number=models.PositiveIntegerField()
    state=models.CharField(max_length=20,default='draft')
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    lifecycle_hash=models.CharField(max_length=64)
    activated_request_id=models.UUIDField(null=True,unique=True)
    activated_request_hash=models.CharField(max_length=64,blank=True)
    activated_by=models.CharField(max_length=150,blank=True)
    reason=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['template','number'],name='device_transform_version_unique')]
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            prior=type(self).objects.get(pk=self.pk)
            if any(getattr(prior,k)!=getattr(self,k) for k in ('template_id','number','request_id','request_hash','payload','payload_hash')):raise ValidationError('字段模板版本内容不可覆盖，请新建版本')
        return super().save(*args,**kwargs)


class DeviceTransformReceipt(models.Model):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='device_transform_receipts')
    source_file=models.ForeignKey(DeviceFile,on_delete=models.PROTECT,related_name='source_transforms')
    output_file=models.ForeignKey(DeviceFile,on_delete=models.PROTECT,related_name='derived_transforms')
    template_version=models.ForeignKey(DeviceTransformVersion,on_delete=models.PROTECT,related_name='receipts')
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('转换回执不可覆盖，请建立新转换')
        return super().save(*args,**kwargs)


from django.utils import timezone as spc_timezone

class SPCAnalysisView(models.Model):
    """Personal, version-checked study definition; never edits source facts."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='spc_analysis_views')
    topic=models.ForeignKey(Topic,on_delete=models.PROTECT,null=True,blank=True,related_name='spc_analysis_views')
    code=models.CharField(max_length=80)
    name=models.CharField(max_length=150)
    note=models.TextField()
    study_id=models.CharField(max_length=255)
    definition=models.JSONField()
    definition_hash=models.CharField(max_length=64)
    revision=models.PositiveIntegerField(default=1)
    archived=models.BooleanField(default=False)
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['owner','code'],name='spc_view_owner_code_unique')]

class SPCResultSnapshot(models.Model):
    """Immutable captured result and Excel-row provenance, private to its owner."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='spc_result_snapshots')
    view=models.ForeignKey(SPCAnalysisView,on_delete=models.PROTECT,related_name='snapshots')
    topic=models.ForeignKey(Topic,on_delete=models.PROTECT,null=True,blank=True,related_name='spc_result_snapshots')
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    name=models.CharField(max_length=120)
    note=models.TextField()
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(default=spc_timezone.now,editable=False)
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('受控试验快照不可覆盖，请建立新快照')
        return super().save(*args,**kwargs)

class AnalysisModelCard(models.Model):
    """Personal model identity; no changes to shared analysis definitions."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='analysis_model_cards')
    code=models.CharField(max_length=80)
    revision=models.PositiveIntegerField(default=1)
    archived=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['owner','code'],name='model_card_owner_code_unique')]

class AnalysisModelCardVersion(models.Model):
    card=models.ForeignKey(AnalysisModelCard,on_delete=models.PROTECT,related_name='versions')
    revision=models.PositiveIntegerField()
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    request_id=models.UUIDField(unique=True)
    request_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(default=spc_timezone.now,editable=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['card','revision'],name='model_card_version_unique')]
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('模型口径卡历史版本不可覆盖，请新增版本')
        return super().save(*args,**kwargs)

class TopicPage(models.Model):
    """Private page identity; existing topics and calculation definitions stay intact."""
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='topic_pages')
    topic=models.ForeignKey(Topic,on_delete=models.PROTECT,related_name='page_definitions')
    code=models.CharField(max_length=80)
    revision=models.PositiveIntegerField(default=1)
    current_version=models.PositiveIntegerField(default=1)
    archived=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['owner','code'],name='topic_page_owner_code_unique')]

class TopicPageVersion(models.Model):
    page=models.ForeignKey(TopicPage,on_delete=models.PROTECT,related_name='versions')
    number=models.PositiveIntegerField()
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(default=spc_timezone.now,editable=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['page','number'],name='topic_page_version_unique')]
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('专题页面历史版本不可覆盖，请新增版本')
        return super().save(*args,**kwargs)

class TopicPageRequest(models.Model):
    """Atomic, account-bound idempotence of one normal configuration action."""
    request_id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    owner=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='topic_page_requests')
    page=models.ForeignKey(TopicPage,on_delete=models.PROTECT,related_name='requests')
    action=models.CharField(max_length=20)
    request_hash=models.CharField(max_length=64)
    response=models.JSONField()
    created_at=models.DateTimeField(default=spc_timezone.now,editable=False)

class AnalysisModelChange(models.Model):
    """An immutable checked change; definitions and review evidence, not business results."""
    request_id=models.UUIDField(primary_key=True,editable=False)
    actor=models.ForeignKey('auth.User',on_delete=models.PROTECT,related_name='analysis_model_changes')
    model=models.ForeignKey(AnalysisModel,on_delete=models.PROTECT,related_name='changes')
    from_version=models.PositiveIntegerField()
    to_version=models.PositiveIntegerField()
    request_hash=models.CharField(max_length=64)
    payload=models.JSONField()
    payload_hash=models.CharField(max_length=64)
    created_at=models.DateTimeField(default=spc_timezone.now,editable=False)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['model','to_version'],name='model_change_version_unique')]
    def save(self,*args,**kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('模型变更记录不可覆盖，请预演并保存新版本')
        return super().save(*args,**kwargs)
