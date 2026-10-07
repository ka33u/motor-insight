"""Compact reading guide, a static design diagram, and a portable design bundle.

The optional Pillow diagram is not an application screenshot or UI acceptance.
The bundle contains planning materials, never a database or user credentials.
"""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def guide(d):
    partial=sum(n['implementation']=='模拟部分覆盖' for g in d['domains'] for n in g['items'])
    lines=[
        '电机制造企业：BI展示深化 · 简明方案（2026-10-07）', '',
        '适用现状：用友U8；momo MES准备上线、供应商接口待确认；全流程自制；平均约900台/日；小批量定制；低预算、IT人员不足。',
        '当前业务演示为合成Excel资料，真实U8/MES尚未接入。本方案是可裁剪的候选设计，不能穷尽未来需求。', '',
        '1. 怎样定义BI',
        'BI是企业按岗位提供决策支持的数据服务：把分散记录整理成统一指标、可比分析和可追溯证据，帮助人找到对象、作出决定并复查效果。',
        '定义结构：需求 → 业务对象和关系 → 指标 → 分析模型 → 专题/页面 → 视角/快照 → 行动与复查。',
        '例如“今天哪些订单需要协调”是一项需求；“到期计划行”是对象范围；OTIF是指标；延期分布和阻断分析是模型；交付工作台是呈现；协调记录和后续兑现是复查。',
        'U8、MES继续管理业务单据与执行。数据平台统一采集、身份、关系、版本和来源；BI统一定义、计算和呈现。真实边界须与厂商和部门核实。', '',
        '2. 展示哪些内容',
        '全景：26个领域、382项候选需求、63项建议指标、17页蓝图。完整逐项需求在《BI完整382项需求清单.txt》，不只列指标名称。',
        '每项均列业务定义、粒度、来源、维度、责任、频率、数据前提、展示方式、行动、验收及缺口；本次增加18类方法的候选选型。',
    ]
    lines += [g['code']+' '+g['name']+'｜'+str(len(g['items']))+'项' for g in d['domains']]
    lines += ['', '3. 怎样组织首屏',
        '经营驾驶舱：少量交付、首次质量、结账盈利和现金结果；样本及数据覆盖并列；进入责任部门处理。没有结账资料时不展示实际毛利。',
        '岗位工作台：先展示待办对象与期限，再看趋势；对象、缺口、影响、责任、下一节点、来源是主要列。',
        '专题分析：围绕一个问题，用同配置比较、分布、趋势、差异桥或资源时间轴解释；未知、排除与不可比条件同时显示。',
        '对象履历：搜索订单、工单、批次或SN，显示确认关系、有效版本、事件时间线、检测与原件；断点和候选关系分开。',
        '自由分析：受控字段与关系，选择维度、指标、方法和比较；先生成可复核草稿，经业务评审后发布，避免任意连接导致重复数量。',
        '手机：查号/扫码、单对象状态、证据及待办；复杂建模留在桌面。车间屏：本班进度与关键阻断，带更新时间和断网状态。',
        '数据可信页：新鲜度、错号、缺关联、模板漂移、单位和对账；资料未知不填零，不自动判为正常。', '',
        '统一阅读顺序：范围与数据时间 → 1—3个主结果 → 解释与可比性 → 同范围对象 → 原始来源/版本 → 责任与复查。',
        '例会结果可以冻结快照；个人视角只保存条件，两者分别标注。手机、打印、导出、明细和图形沿用同一口径与权限。', '',
        '4. 17页怎样分工',
    ]
    lines += [p['id']+' '+p['name']+'｜'+p['question'] for p in d['page_blueprints']]
    lines += ['', '5. 分析模型怎样选',
        '18类：'+'、'.join(m['name'] for m in d['framework']['method_workshop']['methods'])+'。',
        '每种方法列问题、输入字段、计算约定、图形、进入条件及暂停条件。完整定义、17页预演和全部382项选型在《BI分析方法与页面预演_20261007.txt》。',
        '小批量多品种：先按配置、规范、方法、单位和工况分层；整机、定转子和材料保持自己的单位与粒度；复测不抹掉首次失败。',
        'SPC：真实采样先后、固定基线、合理子组/单值策略及测量条件先核实，控制限与公差分开。Cp/Cpk另核实稳定性、测量系统和分布/抽样依据。',
        '预测：有可比历史和回测才叫预测；情景页清楚列基线与假设；优化须先标定资源和约束。模拟演练不证明真实产能或收益。', '',
        '6. 适合本厂的创新',
        '一单多岗位：销售看承诺、计划看缺口、质量看检测、仓库看出库条件，均回到同一订单身份。',
        '数字旁看证据：直接解释分母、排除、未知、来源行和版本，减少跨部门对表。',
        '方法门槛可见：分布、控制和能力分开；有数值也能明确说明为何暂时不能算。',
        '数字变化可解释：业务变化、补录、更正、指标版本和权限变化分列；保留当时范围复盘。',
        '需求目录可维护：先判断适用性，再看决策价值和维护成本；业务部门确认口径、模板和来源，IT维护通用能力与权限，明确替补人。', '',
        '7. 建设顺序',
        '首批四页：P02订单交付、P05质量试验、P06对象履历、P15数据可信；计划和在制作为交付解释入口。先拿真实订单及SN把查单、检测关联、来源和处理串起来。',
        '部门深化：计划/在制、物料齐套、采购、库存、设备、人员工时、成本和财务对账，按来源成熟度逐项加入。',
        '条件专题：曲线、MSA、SPC、过程能力、特殊产品、认证、出口和委外按实际适用性启用。',
        '成熟分析：可靠历史、回测和约束齐备后再推进预测、优化及投资情景；不把所有候选一次排成开发任务。', '',
        '8. 当前边界与阅读入口',
        f'需求状态为{partial}项模拟部分覆盖、{382-partial}项待建设，没有新增完整验收项。方法推荐本身不增加指标发布或保存模型；独立采样增量新增750行合成事实及I-MR候选试算，详见《BI过程稳定性_试算说明_20261007.txt》。',
        '网页入口：http://127.0.0.1:8765/#catalog?tab=methods（需已启动本地平台并登录）。',
        '《BI需求与呈现方案.html》已加入相同方法页，文件内含数据、样式和脚本，无须本地应用服务；不能打开网页时直接读本TXT及完整需求TXT。',
        '《BI展示深化_一图概括_20261007.png》是设计图，不是应用验收截图。',
        '《BI深化设计_20261007_离线资料包.zip》是设计资料包，不是应用恢复备份；旧的BI v9资料包保留为历史版本。',
        '核对：需求引用、幂等生成、原目录字段与指标保留、68条样例来源及均值/中位数/超限/同刻记录；既有8项BI草稿测试通过。新增浏览器、手机筛选与实际下载未验收。', '',
        '参考：Microsoft语义模型与BI内容规划、NIST单值控制图和过程能力方法。来源链接与适用边界在完整方法说明中。',
    ]
    return '\n'.join(lines)+'\n'


def diagram(d):
    try:
        from PIL import Image,ImageDraw,ImageFont
    except ImportError:
        return None
    regular='/System/Library/Fonts/STHeiti Light.ttc'
    medium='/System/Library/Fonts/STHeiti Medium.ttc'
    if not Path(regular).exists():return None
    image=Image.new('RGB',(1800,1450),'#f6f7f0');pen=ImageDraw.Draw(image)
    ink='#233d33';muted='#617267';green='#306650';line='#d0ddcd'
    fonts={n:ImageFont.truetype(regular,n) for n in (20,22,24,26,30,34,46)}
    bold={n:ImageFont.truetype(medium,n) for n in (24,26,30,34,46)}
    def write(x,y,text,size=24,color=ink,strong=False):
        pen.text((x,y),text,font=(bold if strong else fonts)[size],fill=color)
    def wrap(text,width,size=22):
        out=[];current=''
        for char in text:
            if pen.textlength(current+char,font=fonts[size])>width and current:
                out.append(current);current=char
            else:current+=char
        if current:out.append(current)
        return out
    def card(x,y,w,h,title,text,size=22):
        pen.rounded_rectangle((x,y,x+w,y+h),radius=12,fill='white',outline=line,width=2)
        write(x+18,y+15,title,26,strong=True)
        for j,t in enumerate(wrap(text,w-36,size)):
            write(x+18,y+58+j*(size+8),t,size,muted)
    write(65,38,'电机制造 BI：从分散数据到可复查的决定',46,strong=True)
    write(65,103,'U8 · MES待上线 · 约900台/日 · 全流程自制 · 小批量定制 · 低预算与少IT人员',24,muted)
    for i,(title,text) in enumerate([('U8 ERP','订单、采购、库存、财务'),('MES（待上线）','工单、报工、流转、执行'),('部门 Excel','计划、工艺、质量、经营'),('纸质资料','检验、签核、证书、交接'),('设备检测文件','原数值、曲线、会话、SN')]):
        card(65+i*338,164,320,109,title,text)
    write(65,304,'接入与治理（规划）',30,green,strong=True)
    write(65,351,'身份和关系  →  标准模板/单位  →  生效版本  →  数据核对  →  来源行与原件  →  权限',26)
    for i,(title,text) in enumerate([('业务模型','一行是什么、怎样关联、哪些对象可比较'),('指标定义','公式、分母、单位、日期、范围、版本'),('分析模型','问题、方法、样本、基线、假设、门槛'),('专题与页面','主结果、解释、对象、证据、行动、复查')]):
        card(65+i*423,414,405,122,title,text)
    write(65,573,'按岗位与任务呈现',30,green,strong=True)
    for i,(title,text) in enumerate([('经营驾驶舱','结果与目标 / 跨部门事项'),('岗位工作台','待办与阻断 / 责任期限'),('专题分析','同类比较 / 解释与验证'),('对象履历','查订单、工单、批次、SN'),('自由分析','受控字段、方法与草稿'),('手机与车间屏','查号扫码 / 本班状态')]):
        card(65+i*282,628,264,135,title,text,20)
    write(65,800,'26个领域 · 382项候选需求 · 63项建议指标 · 17页蓝图',30,green,strong=True)
    names={g['code']:g['name'] for g in d['domains']}
    for i,g in enumerate(d['coverage_groups']):
        text=' / '.join(names[c] for c in g['domains'])
        card(65+(i%4)*423,858+(i//4)*136,405,121,g['name'],text,20)
    write(65,1154,'分析门槛随结果显示',30,green,strong=True)
    write(65,1205,'描述分布 ≠ 稳定过程；控制限 ≠ 产品公差；校准有效 ≠ MSA；假设情景 ≠ 实际预测',24)
    write(65,1251,'首批：订单交付 P02  →  质量试验 P05  →  对象履历 P06  →  数据可信 P15',30,green,strong=True)
    write(65,1310,'统一阅读：范围与可信度 → 主结果 → 解释 → 对象 → 证据 → 行动与效果复查',26)
    write(65,1361,'候选设计，可按实际业务裁剪；图中不是已上线范围。完整382项及18类方法见离线文字资料。',22,muted)
    output=ROOT/'outputs/BI展示深化_一图概括_20261007.png';image.save(output)
    return output


def main():
    d=json.loads((ROOT/'data/bi_design.json').read_text())
    (ROOT/'outputs/BI需求与定义数据_v9.json').write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
    quick=guide(d);(ROOT/'outputs/BI展示深化_简明方案_20261007.txt').write_text(quick)
    if d['framework'].get('spc_workspace'):
        quick+='\n个人受控试验视角：自定义编码、定义版本、完整观测与来源冻结、当前资料核对和个人专题关联。入口 #spc-workspace，演示样例属于 demo_quality；其他账号可以保存自己的视角。计算依据变化和基线更正分别呈现；不按共同名称推断改善或因果。详见《BI个人试验视角与快照说明_20261007.txt》。\n'
        (ROOT/'outputs/BI展示深化_简明方案_20261007.txt').write_text(quick)
    if d['framework'].get('msa_trial'):
        quick+='\n测量系统交叉采样：11个合成试验、141成员、930条观测，采样完整性、交互均值、保留交互的ANOVA与三类百分比分开；来源逐行可核对。入口 #msa；4个完整试验可试算，7个异常试验暂停；真实MSA资格尚未审定，详见《BI测量系统交叉采样说明_20261007.txt》。\n'
        (ROOT/'outputs/BI展示深化_简明方案_20261007.txt').write_text(quick)
    (ROOT/'docs/BI展示深化_简明方案.txt').write_text(quick)
    picture=diagram(d)
    chosen=['BI展示深化_简明方案_20261007.txt','BI分析方法与页面预演_20261007.txt',
            'BI完整382项需求清单.txt','BI需求与呈现方案.html','BI需求与定义数据_v9.json',
            'BI展示内容与交互设计_完善版.txt','BI建设分层与页面内容_实施补充.txt',
            'BI定义与呈现_快速阅读版.txt','BI一页概览.html','BI过程稳定性_试算说明_20261007.txt']
    if picture:chosen.append(picture.name)
    if d['framework'].get('spc_workspace'):chosen.append('BI个人试验视角与快照说明_20261007.txt')
    if d['framework'].get('msa_trial'):chosen.append('BI测量系统交叉采样说明_20261007.txt')
    path=ROOT/'outputs/BI深化设计_20261007_离线资料包.zip'
    files={name:(ROOT/'outputs'/name).read_bytes() for name in chosen}
    files['证据/检测样例门槛预检.json']=(ROOT/'data/bi_method_readiness_sample.json').read_bytes()
    files['证据/方法设计初始核对_采样增量前.json']=(ROOT/'data/bi_method_design_validation.json').read_bytes()
    files['证据/受控采样当前来源与保留核对.json']=(ROOT/'data/spc_release_validation.json').read_bytes()
    files['证据/受控采样原生HTTP核对_非浏览器.json']=(ROOT/'data/spc_http_validation.json').read_bytes()
    if d['framework'].get('spc_workspace'):
        files['证据/个人视角与快照来源保留核对.json']=(ROOT/'data/spc_workspace_release.json').read_bytes()
        files['证据/个人视角与快照原生HTTP核对_非浏览器.json']=(ROOT/'data/spc_workspace_http_validation.json').read_bytes()
    if d['framework'].get('msa_trial'):
        files['证据/测量试验当前来源与保留核对.json']=(ROOT/'data/msa_release.json').read_bytes()
        files['证据/测量试验原生HTTP核对_非浏览器.json']=(ROOT/'data/msa_http_validation.json').read_bytes()
    manifest={name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    files['资料清单与SHA256.json']=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
        for name,data in files.items():bundle.writestr(name,data)
    with zipfile.ZipFile(path) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist())==set(files)
        for name,digest in manifest.items():assert hashlib.sha256(bundle.read(name)).hexdigest()==digest
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    Path(str(path)+'.sha256').write_text(digest+'  '+path.name+'\n')
    evidence=dict(success=True,package=str(path),sha256=digest,files=len(files),
                  all_archive_bytes_checked=True,contains_database_or_credentials=False,
                  diagram_is_design_not_browser_acceptance=True)
    (ROOT/'data/bi_method_design_package.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(evidence,ensure_ascii=False))


if __name__=='__main__':main()
