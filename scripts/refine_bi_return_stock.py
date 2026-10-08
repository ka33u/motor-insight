"""Add return/lot state reading and explicitly retain missing line-side workflows."""
from collections import Counter
from copy import deepcopy

MARKER=' 退料库存状态：'
STATUS=('新增47号合成Excel的135行、7工单和8笔退料，经正常导入保留来源。单据关联、退料时状态和当前库位证据并列；'
        '同刻不推定先后，错链和原领料库位问题留空。按退料笔数比较当前状态，按唯一物料×批次×库位汇总余额，kg与件分开；'
        '库位余额不归属单笔退料。含待检、释放后再领、隔离、错链、同刻、未来状态和同库位两笔退料。'
        '完整筛选清单CSV与去重库位、原/退流水、两端台账及Excel来源可查。原库存与备料口径保留。'
        '库存状态登记未建立逐退料检验报告或授权有效性证明；线边实盘、借料、移库分配、在制剩余工序与正式批准仍待建设。浏览器、手机与实际下载未验收。')
CONTRACT=dict(revision='return-stock-reading-v1',href='#supply?tab=returns',state=STATUS,
    definition='退料粒度为库存退料流水；库存粒度为物料×批次×库位。按固定业务截止核对，未来状态变更不提前使用。',
    measures='关联可核对笔数/退料笔数、当前证据可核对笔数/退料笔数、退料时状态明确笔数/退料笔数分别阅读。退回量按原单位；目标库位余额先去重再汇总，任何目标可用量未知则同单位合计留空。',
    presentation='范围→退料笔数与唯一目标库位→单据关联×当前状态并列计数→单位内退回量与库位余额→可交叠的证据问题/可用/受限清单→原领料及两端完整台账→Excel行与完整筛选CSV。',
    boundary='本页为已导入模拟状态证据阅读，不批准质量、不释放实物、不替代库存或备料算法；库存余额不能分摊为单笔退料剩余量。线边、借料、调拨和检验授权仍未覆盖。')
ROW=dict(name='退料与库存状态核对',question='退料单据能否关联，退料时与当前库位分别处于什么状态，库位余额是否重复计算？',
         content=CONTRACT['presentation'],action='核对原领料与两端台账→定位缺失或同刻问题→交仓储质量岗位复核原登记',href='#supply?tab=returns',status=STATUS)


def refine_return_stock(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-03','J-01','J-05','J-09'):
                item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
                item['display_design']['availability']=item['display_design']['availability'].split(MARKER)[0]+MARKER+STATUS
                item['presentation_contract']['detail_contract']=item['presentation_contract']['detail_contract'].split(MARKER)[0]+MARKER+STATUS
            if item['id']=='J-09':
                item['implementation']='模拟部分覆盖';item['decision_spec']['implementation']='模拟部分覆盖'
    for page in d['page_blueprints']:
        if page['id']=='P09':page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
    for surface in d['framework']['surfaces']:
        if surface.get('href')=='#supply':surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['surfaces']=[r for r in d['framework']['surfaces'] if r['href']!=ROW['href']]+[deepcopy(ROW)]
    d['framework'].pop('return_stock_reading',None);d['framework']['return_stock_reading']=deepcopy(CONTRACT)
    d['planning_summary']['implementation_counts']=dict(Counter(n['implementation'] for g in d['domains'] for n in g['items']))
    d['planning_summary']['presentation_design']['coverage_counts']=deepcopy(d['planning_summary']['implementation_counts'])
    return d
