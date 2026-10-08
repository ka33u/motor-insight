"""Document production return reconciliation, not physical WIP or release authority."""
from copy import deepcopy
MARKER=' 生产领退料核对：'
STATUS=('新增46号模拟Excel的114行，经正常导入保留原始来源。退料来源单号关联原领料，核对工单、物料、批次、严格时间先后、整件和累计数量上限；'
        '同一原领料任一退料待核对时不部分抵扣。备料并列累计领料、可核对退料、净领料与待领需求，未知留空；净领料不是实际消耗或在制实存。'
        '仓储仅按原流水入账一次，目标待检库位不增加可用库存；原领料账据异常传递到退料库位。工单详情保留原/退工单和流水、完整Excel来源及单工单CSV，含完工取消工单的退料依据。'
        '全部退料不等于从未领料，不改变冻结BOM整批新开工门槛；没有退料批准、库存写回、线边实盘或在制人机重排。浏览器、手机和实际下载仍未验收。')
CONTRACT=dict(revision='production-return-links-v1',href='#material-planning?q=MO-260928-R',state=STATUS,
    definition='退料关联粒度=原领料流水×退料流水；需求按工单×物料×原单位。原领料为负增减、退料为正增减；同一原领料的全部截止前退料共同核对上限。',
    measures='净领料=累计领料-可核对退料；待领=max(0,BOM整单需求-净领料)。退料已在库存流水中计入，试配不再手工加回库存池；同物料跨BOM分支合并后按整件取整。',
    presentation='工单整单状态→各物料总需求/净领料/待领→累计领料与退料分列→原领料和退料对应、不同库位状态→Excel来源和单工单完整核对CSV。局部清单状态不缩小所选工单明细导出。',
    boundary='仅已导入模拟登记，不证明实物在制存量、实际耗用、退料质量或正式批准。未知量不补零；截止后的退料不提前抵扣，归零不删除历史。')

def refine_material_returns(d):
    for group in d['domains']:
        for item in group['items']:
            if item['id'] in ('F-03','J-01','J-05'):
                item['gap']=item['gap'].split(MARKER)[0]+MARKER+STATUS
                item['display_design']['availability']=item['display_design']['availability'].split(MARKER)[0]+MARKER+STATUS
                item['presentation_contract']['detail_contract']=item['presentation_contract']['detail_contract'].split(MARKER)[0]+MARKER+STATUS
    for page in d['page_blueprints']:
        if page['id'] in ('P03','P09'):page['status']=page['status'].split(MARKER)[0]+MARKER+STATUS
    for surface in d['framework']['surfaces']:
        if surface.get('href') in ('#material-planning','#supply'):surface['status']=surface['status'].split(MARKER)[0]+MARKER+STATUS
    # Earlier refiners remove and append their own sections on every rebuild.
    # Append this section again too, so a second rebuild preserves file order.
    d['framework'].pop('material_return_reading',None)
    d['framework']['material_return_reading']=deepcopy(CONTRACT)
    return d
