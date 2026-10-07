"""Describe a partial scope-navigation increment without inflating coverage."""
from copy import deepcopy

MARKER = ' 临时跨专题探索：'
STATUS = '已提供不依赖个人页面的临时探索：先核对目标每张卡的条件、日期角色与权限，再选择完整继承、保留当前对象后重选日期及对照、或明确开始新范围。完整继承不丢条件；对象方式保留当前产品族/客户和两侧直接身份联动，清除日期、整个对照及自定义名称。进入和返回均重核账号、定义与规则；返回原专题临时分析并恢复原已应用条件。保留目标模型局部条件和发布指标，结果读取当前事实。仅当前标签页保存临时路径，不写业务事实、原模型、私有页面/视角或快照。任意跨表推断、多值刷选、共享探索路径及浏览器/手机交互验收仍待完成。'
CONTRACT = dict(revision='topic-journey-20261007', needs=['X-07'], href='#topics', state=STATUS,
    definition='跨专题探索只传递分析条件；指标、计算模型、页面布局、数据状态和结果快照分别管理。不同主题的日期名称不同，不能只因日期数字相同就认为可比。',
    presentation='已应用范围→目标专题→每卡适用说明与日期角色→三种方式及清除清单→当前结果→来源与下一步探索→返回原范围。',
    boundary='完整继承要求全部目标卡支持全部当前/对照及直接身份条件，有日期时来源和目标日期角色集合一致。新范围允许进入但不会修复暂停卡。返回恢复条件不恢复旧数值或原私有布局。预览10分钟、路径2小时、当前标签页最多20条；刷新会重载该路径起始范围，修改后可另存个人视角。')


def refine_journey(d):
    # Replace the older blanket statement; arbitrary cross-topic joins remain pending.
    def wording(value):
        if isinstance(value, str):
            return value.replace('和跨专题联动仍待建设', '和任意跨专题关系推断仍待建设')
        if isinstance(value, list):
            return [wording(v) for v in value]
        if isinstance(value, dict):
            return {k: wording(v) for k, v in value.items()}
        return value
    d = wording(d)
    for domain in d['domains']:
        for need in domain['items']:
            if need['id'] == 'X-07':
                assert need['implementation'] == '模拟部分覆盖'
                need['gap'] = need['gap'].split(MARKER)[0]+MARKER+STATUS
    d['framework']['topic_journey'] = deepcopy(CONTRACT)
    row = ['跨专题范围预览', '换到下一个专题时哪些条件还成立？', CONTRACT['presentation'], STATUS]
    d['framework']['presentation'] = [r for r in d['framework']['presentation'] if r[0] != row[0]]+[row]
    return d
