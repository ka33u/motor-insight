"""Server-side access policy, shared by records, exports, analytics and trace."""
from .semantic_schema import schemas

ROLES={'admin':'平台管理员','analyst':'经营分析师','quality':'质量工程师','operations':'生产计划员','finance':'财务分析师','viewer':'业务只读'}
FINANCIAL={'costs','invoices','payments','bi_receivables','ar_opening','ar_events'}
FINANCIAL.update({'purchase_terms','ap_invoices','ap_invoice_lines','ap_payments','ap_payment_plans','ap_allocations','ap_adjustments'})
PERSONNEL={'attendance','skills','labor_entries'}
from .launch_schema import DATASETS as LAUNCH_DATASETS
PERSONNEL.update(LAUNCH_DATASETS)
PERSONNEL.update({'crew_studies','crew_credentials','crew_candidates','crew_windows','crew_blocks'})
PERSONNEL.update({'joint_studies','joint_bindings','joint_demands','joint_supplies'})
PERSONNEL.update({'order_baselines','order_baseline_links','order_baseline_bom'})

def role(user):
    if not user.is_authenticated or not user.is_active:return None
    if user.is_superuser:return 'admin'
    assigned=set(user.groups.values_list('name',flat=True)) & ROLES.keys()
    return next(iter(assigned)) if len(assigned)==1 else ('viewer' if not assigned else None)

def can_money(user):return role(user) in ['admin','analyst','finance']
def can_edit(user):return role(user) in ['admin','analyst']
def can_import(user):return role(user)=='admin'
def allowed(user,dataset):
    if dataset not in schemas():return False
    if dataset in {'device_sources','device_scan_runs','device_file_observations'}:return role(user) in ['admin','quality']
    if dataset in ['kpi_targets','kpi_target_checks']:return can_edit(user)
    if dataset in FINANCIAL:return can_money(user)
    if dataset in PERSONNEL:return role(user) in ['admin','analyst','operations']
    return bool(role(user))

def permitted_fields(user,dataset):
    return [f for f in schemas()[dataset]['fields'] if can_money(user) or 'cents' not in f['name']]

def sanitize(user,dataset,data):
    fields={f['name'] for f in permitted_fields(user,dataset)}
    return {k:v for k,v in data.items() if k in fields}
