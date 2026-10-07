"""Keep typed object discovery separate from governed traceability and approval."""
from copy import deepcopy
MARKER=' 统一对象检索：'
STATUS='已提供14类常用对象的编码精确、前缀及编码/名称包含查找，保留前导零和同号不同表身份；精确编码优先，完整分页和类型计数对应同一次查询。详情展示权限内原字段、Excel行来源、声明的直接引用和被引用登记，同一行多字段引用只计一次；缺引用和不可访问分开。可进入既有SN履历、生产批次反查和订单行交付工作台。历史/未来/草稿登记不等于当前有效关系或批准；多跳履历、材料批号统一实体、任意名称关系和跨系统别名仍待建设。浏览器/手机及实际下载交互未验收。'
CONTRACT=dict(revision='object-hub-20261007',href='#objects',state=STATUS,
 definition='以业务表类型和完整业务编码共同标识对象；内部记录号仅定位当前库。查找命中、声明引用、实际使用、当前有效状态和批准是不同结论。',
 presentation='对象类型与匹配方式→实际命中字段→原编号/版本与Excel行→直接引用与被引用登记→对象字段→适用业务工作台。数量表示当前可见登记条数，不作为跨表业务合计。',
 boundary='查找14类常用对象；可沿直接字段进入全部权限内原始表记录。仅精确字段关系，不递归推断或自动去除历史版本。搜索条件只保存在当前页面运行会话，详情使用当前库记录定位；凭据10分钟，资料/规则/权限变化要求重新读取。')


def refine_objects(d):
    for domain in d['domains']:
        for need in domain['items']:
            if need['id'] in ('N-01','N-02'):
                need['gap']=need['gap'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['object_hub']=deepcopy(CONTRACT)
    row=dict(href='#objects',name='统一对象检索',question='这个编号是什么对象，它的资料在哪里，哪些登记直接引用它？',content=CONTRACT['presentation'],action='查找完整编号→核对类型与来源→沿声明关系查看对象→进入业务履历',status=STATUS)
    d['framework']['surfaces']=[s for s in d['framework']['surfaces'] if s['href']!='#objects']+[row]
    return d
