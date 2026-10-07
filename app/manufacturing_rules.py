"""Shared row-level manufacturing constraints for ingestion and saved scans.

These rules do not prove route feasibility, physical stock or quality release.
Type/required/reference checks remain owned by the schema validator.
"""
from datetime import date,datetime


def parsed(value,kind):
    if not isinstance(value,str):return None
    try:
        out=(date if kind=='date' else datetime).fromisoformat(value)
        if out.isoformat()!=value or kind=='datetime' and out.tzinfo is not None:return None
        return out
    except ValueError:return None


def issues(dataset,row):
    if dataset in {'oee_studies','oee_windows','oee_events','oee_cycles','oee_outputs'}:
        from .oee_contract import issues as oee_issues
        return oee_issues(dataset,row)
    if dataset in {'crew_studies','crew_credentials','crew_candidates','crew_windows','crew_blocks'}:
        from .crew_schedule_contract import issues as crew_issues
        return crew_issues(dataset,row)
    if dataset in {'schedule_studies','schedule_jobs','schedule_tasks','schedule_edges','schedule_options','schedule_windows','schedule_blocks'}:
        from .finite_schedule_contract import issues as schedule_issues
        return schedule_issues(dataset,row)
    if dataset in {'msa_studies','msa_members','msa_observations'}:
        from .msa_source_contract import issues as msa_issues
        return msa_issues(dataset,row)
    if dataset in {'spc_studies','spc_observations','spc_events'}:
        from .spc_source_contract import issues as spc_issues
        return spc_issues(dataset,row)
    result=[]
    def add(code,field,message):result.append({'code':code,'field':field,'message':message})
    if dataset=='work_orders':
        start=parsed(row.get('planned_start'),'date');end=parsed(row.get('planned_end'),'date')
        if start and end and start>end:add('WO_PLAN_ORDER','planned_start','计划开工不能晚于计划完工')
        if type(row.get('planned_qty')) is int and row['planned_qty']<=0:add('WO_PLAN_QTY','planned_qty','工单计划数量必须大于零')
    elif dataset=='batches':
        if type(row.get('qty')) is int and row['qty']<=0:add('BATCH_QTY','qty','生产批次数量必须大于零')
    elif dataset=='operations':
        start=parsed(row.get('started'),'datetime');end=parsed(row.get('finished'),'datetime')
        if start and end and start>=end:add('OP_TIME_ORDER','finished','工序完成时间必须晚于开始时间')
        status=row.get('status')
        if status=='完成' and row.get('finished') in [None,'']:add('OP_FINISH_REQUIRED','finished','完成事件必须有完成时间')
        if status=='进行中' and end:add('OP_RUNNING_FINISHED','finished','进行中事件不能同时登记完成时间')
        fields=['input_qty','good_qty','scrap_qty','rework_qty']
        if all(type(row.get(k)) is int for k in fields):
            entered,good,scrap,rework=(row[k] for k in fields)
            if entered<=0:add('OP_INPUT_QTY','input_qty','报工投入数量必须大于零')
            for key in fields[1:]:
                if row[key]<0:add('OP_NONNEGATIVE_QTY',key,'合格、报废和返工数不能为负数')
            if min(entered,good,scrap,rework)>=0:
                if good+scrap>entered or status=='完成' and good+scrap!=entered:
                    add('OP_OUTPUT_QTY','good_qty','完成事件须满足投入＝合格＋报废；未完成事件的合格＋报废不能超过投入')
                if rework>entered:add('OP_REWORK_SUBSET','rework_qty','返工数是投入的子集，不能超过投入数')
    return result
