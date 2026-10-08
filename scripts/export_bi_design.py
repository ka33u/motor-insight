"""Portable design catalog with labelled synthetic trial scope; no live queries."""
import json,html
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
d=json.loads((ROOT/'data/bi_design.json').read_text());f=d['framework'];h=html.escape
count=sum(len(x['items']) for x in d['domains'])
from bi_design_sections import render_extra, EXTRA_STYLE, EXTRA_SCRIPT
from bi_planning_sections import render_planning
from bi_execution_sections import execution_text
from bi_presentation_sections import presentation_text
from bi_reader_guide import reader_guide_text
from refine_bi_methods import workshop_text,method_reading_note
planning_html,planning_css,planning_js=render_planning(d)

def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+h(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+h(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
def section(key,title,body):return f'<section id="{key}"><h2>{h(title)}</h2>{body}</section>'
parts=[f'<header><small>电机制造企业 · BI设计 v{d["version"]} · {d["designDate"]}</small><h1>BI 需求、定义与呈现方案</h1><p>{len(d["domains"])}个领域 / {count}项候选需求 / {len(d["metrics"])}个指标定义 / {len(d["page_blueprints"])}个页面蓝图</p><p>{h(d["notice"])}</p></header>',
'<nav>'+''.join(f'<a href="#{key}">{label}</a>' for key,label in [('decision-reading','先读这一页'),('method-workshop','方法门槛与页面预演'),('content-design','展示内容规划'),('decision-design','一页读懂与场景'),('review-design','呈现与逐项评审'),('coverage','需求矩阵'),('specification','分析定义'),('definition','BI定义'),('presentation','呈现方式'),('pages','页面蓝图'),('interaction','交互设计'),('requirements','需求目录'),('metrics','指标口径'),('roles','角色工作台'),('mvp','首期范围'),('phases','实施验收')])+'</nav>']
from bi_decision_reading import render_reading,export_text
parts.append(render_reading(d,table,section))
export_text(d)
parts.append(planning_html)
parts.append(section('definition','BI 的定义与构成',f'<blockquote>{h(f["definition"])}</blockquote><p>{h(f["factory_focus"])}</p><div class="flow">'+''.join(f'<article><small>{i+1:02d}</small><h3>{h(s["name"])}</h3><p>{h(s["question"])}</p></article>' for i,s in enumerate(f['surfaces']))+'</div>'+table(['对象','定义','要点'],f['objects'])+'<h3>统一指标契约</h3>'+table(['契约项','具体定义'],f['metric_contract'])+f'<p class="note">{h(f["boundary"])}</p>'))
parts.append(section('presentation','BI 的呈现方式',table(['界面','回答的问题','内容','下一步动作','现状'],[[s[k] for k in ['name','question','content','action','status']] for s in f['surfaces']])+'<h3>图形与使用条件</h3>'+table(['形式','问题','条件','状态'],f['presentation'])+'<p>推荐页面顺序：'+h(' → '.join(f['first_screen']))+'</p><p>交互设计参考：'+' · '.join(f'<a href="{h(s["url"])}">{h(s["title"])}</a>' for s in d['sources'])+'。具体业务口径为本工厂方案设计。</p>'))
extras=render_extra(d,table,section)
parts.insert(3,extras[0])
parts.extend(extras[1:3])
items=[]
for domain in d['domains']:
    content=[]
    for x in domain['items']:
        rows=[('业务定义',x['definition']),('呈现 / 行动',x['view']+' / '+x['action']),('来源 / 粒度',x['source']+' / '+x['grain']),('责任 / 频率',x['owner']+' / '+x['frequency']),('候选展示维度',' / '.join(x['display_design']['dimensions'])),('维度边界',x['display_design']['scope_note']),('前提',x['prerequisite']),('适用条件',x['applicability']),('验收',x['acceptance']),('当前差距',x['gap']),('关联页面',' / '.join(x['page_ids']))]
        if x.get('delivery_proposal'):
            proposal=x['delivery_proposal']
            rows.extend([('建议建设包',proposal['package_id']+' '+proposal['package_name']),('建议进入条件',proposal['entry_gate']),('部门决定 / 节奏',proposal['decision_context']+' / '+proposal['review_cadence']),('建议试点范围',proposal['first_scope']),('分类边界',proposal['review_state'])])
        if x.get('analysis_methods'):
            method_names={m['id']:m['name'] for m in f['method_workshop']['methods']}
            rows.extend([('分析方法候选',' / '.join(method_names[i] for i in x['analysis_methods'])),('选型边界',x['analysis_method_note'])])
        content.append(f'<article class="need" data-need="{h(x["id"])}" data-priority="{h(x["priority"])}" data-status="{h(x["implementation"])}"><h4>{h(x["id"]+" · "+x["need"])}</h4><p class="badge">{h(x["priority"]+" · "+x["implementation"])}</p><dl>'+''.join(f'<dt>{h(a)}</dt><dd>{h(b)}</dd>' for a,b in rows)+'</dl></article>')
    items.append(f'<details class="domain" data-code="{h(domain["code"])}"><summary>{h(domain["code"]+" · "+domain["name"])} · {len(domain["items"])}项</summary>'+''.join(content)+'</details>')
parts.append(section('requirements','完整候选需求目录',f'<div class="filters"><input id="search" placeholder="搜索订单、库存、复测、权限等需求" aria-label="搜索需求"><button id="expand">展开全部</button><button id="collapse">收起</button><span id="count">{count} 项</span></div>'+''.join(items)))
parts.append(section('metrics','指标口径建议','<div class="filters"><input id="metric-search" placeholder="搜索指标、公式、来源" aria-label="搜索指标"><span id="metric-count"></span></div><p>全部口径须经业务负责人审定；缺失不视为0，分母为零不显示0%，比率汇总后相除。</p>'+''.join(f'<details class="metric" id="metric-{h(m["id"])}"><summary>{h(m["id"]+" · "+m["name"])}</summary><dl>'+''.join(f'<dt>{label}</dt><dd>{h(m[key])}</dd>' for key,label in [('formula','计算'),('grain','粒度'),('clock','时间'),('source','来源'),('owner','责任'),('refresh','刷新'),('pitfalls','边界'),('implementation','实施状态')])+'</dl></details>' for m in d['metrics'])))
parts.append(section('roles','角色工作台',table(['角色','核心问题','内容','呈现','下钻','节奏','行动'],[[r[k] for k in ['role','question','content','surface','drill','cadence','action']] for r in d['roles']])))
parts.append(extras[3])
parts.append(section('phases','实施顺序与验收',''.join(f'<article><h3>{h(p["name"])}</h3><p>{h(p["items"])}</p><p class="note">验收：{h(p["gate"])}</p></article>' for p in f['phases'])+'<p>真实资料待核实：全设备OEE、正式自动排程、产品实测能耗、实际财务毛利和预测性维护。已有模拟资源日历；仍需核实真实容量、分配依据、结账和可靠历史。</p><p>本文件离线可读，可用浏览器打印留档。候选清单按真实流程删减与补充。</p>'))
parts.append(extras[4])
style='''*{box-sizing:border-box}body{font:15px/1.75 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:#253b32;background:#f4f6ee;margin:0}main{max-width:1250px;margin:auto;padding:36px 25px 70px}header{padding:25px 0}h1{font-size:32px;line-height:1.3}h2{font-size:24px;margin-top:0}h3{margin:26px 0 10px}h4{margin:0}header small,.note{color:#647862}header p{font-size:13px}nav{display:flex;flex-wrap:wrap;gap:10px;position:sticky;top:0;background:#f4f6ee;padding:12px 0;z-index:2}a{color:#1d6551}nav a,button{background:white;border:1px solid #dce4d5;padding:8px 14px;border-radius:6px;text-decoration:none;cursor:pointer;color:#1d6551}section{scroll-margin-top:75px;padding:28px;background:white;margin:20px 0;border:1px solid #dce4d5;border-radius:10px}blockquote{margin:0;padding:18px;border-left:4px solid #1d6551;background:#f0f5e9;font-size:19px}.flow{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.flow article{border:1px solid #dce4d5;background:#f5f8ef;border-radius:8px;padding:15px}.flow p{font-size:12px}.flow h3{font-size:16px;margin:8px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}td,th{padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #dce4d5;min-width:140px}th{background:#f1f5eb}details{margin:14px 0;padding:14px 0;border-bottom:1px solid #dce4d5}summary{cursor:pointer;font-weight:600}.need{background:#f7f9f3;padding:20px;border-radius:6px;margin-top:16px}.badge{font-size:12px;color:#8b653d}dl{display:grid;grid-template-columns:120px 1fr;gap:8px;font-size:13px}dt{color:#667761}dd{margin:0}input{padding:10px;width:min(460px,100%);border:1px solid #dce4d5;border-radius:5px;font:inherit}.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:15px 0}button{font:inherit}.note{font-size:13px;background:#f5f7ef;padding:15px}[hidden]{display:none!important}@media(max-width:720px){main{padding:18px 12px}.flow{grid-template-columns:1fr 1fr}section{padding:18px}dl{grid-template-columns:1fr}dd{margin-bottom:8px}h1{font-size:27px}}@media print{body{background:white}main{padding:0}nav,.filters{display:none}section{border:0;break-before:page}.need{break-inside:avoid}.flow{grid-template-columns:repeat(5,1fr)}details>*{display:block!important}.scroll{overflow:visible}td,th{min-width:0}header{break-after:page}}'''
script='''const domains=[...document.querySelectorAll('.domain')],search=document.querySelector('#search');function filter(){const q=search.value.trim().toLowerCase();let n=0;domains.forEach(d=>{let found=0;d.querySelectorAll('.need').forEach(x=>{x.hidden=!x.textContent.toLowerCase().includes(q);if(!x.hidden)found++});d.hidden=found===0;if(q)d.open=true;n+=found});document.querySelector('#count').textContent=n+' / '+document.querySelectorAll('.need').length+' 项'}search.addEventListener('input',filter);document.querySelector('#expand').onclick=()=>domains.forEach(d=>d.open=true);document.querySelector('#collapse').onclick=()=>domains.forEach(d=>d.open=false);let printState=[];window.addEventListener('beforeprint',()=>{printState=[...document.querySelectorAll('details')].map(d=>[d,d.open]);printState.forEach(([d])=>d.open=true)});window.addEventListener('afterprint',()=>printState.forEach(([d,s])=>d.open=s));'''
style+=EXTRA_STYLE+planning_css
style+='@media(max-width:720px){nav{flex-wrap:nowrap;overflow-x:auto;gap:7px;padding:9px 0;max-width:100%}nav a{white-space:nowrap;flex:0 0 auto;font-size:12px;padding:7px 10px}section{scroll-margin-top:65px}}'
script+=EXTRA_SCRIPT+planning_js
if f.get('spc_trial'):
    spc=f['spc_trial'];status=next(v['status'] for v in f['surfaces'] if v['href']=='#spc')
    parts.append('<section id="spc-trial"><h2>受控采样：已经验证的合成候选试算</h2><p>'+h(status)+'</p><p>完整说明：《BI过程稳定性_试算说明_20261007.txt》。此处是设计资料，不运行制造业务数据。</p></section>')
if f.get('spc_workspace'):
    status=next(v['status'] for v in f['surfaces'] if v['href']=='#spc-workspace')
    parts.append('<section id="spc-workspace"><h2>个人受控试验：定义、冻结与复核</h2><p>'+h(status)+'</p><p>操作与边界：《BI个人试验视角与快照说明_20261007.txt》。此处是离线设计资料。</p></section>')
if f.get('msa_trial'):
    status=next(v['status'] for v in f['surfaces'] if v['href']=='#msa')
    parts.append('<section id="msa-trial"><h2>测量系统：交叉采样与变异分解</h2><p>'+h(status)+'</p><p>采样定义：《BI测量系统交叉采样说明_20261007.txt》。这是离线设计资料，不作真实MSA资格判定。</p></section>')
if f.get('model_cards'):
    cards=f['model_cards']
    parts.append(section('model-cards-design','分析模型：业务口径、定义版本与当前结果',table(['口径卡要素','定义与呈现'],[[k,cards[k]] for k in ['objects','definitions','presentation','privacy','time','boundaries']])+'<p>'+h(cards['state'])+'</p><p>操作说明：《BI个人模型口径卡说明_20261007.txt》。此处为离线设计资料。</p>'))
if f.get('crew_schedule_trial'):
    crew=f['crew_schedule_trial']
    parts.append(section('crew-schedule-design','资源与人员：联立约束怎样在BI中阅读',table(['定义项','设计与边界'],[[k,crew[k]] for k in ['definition','measures','method','visuals','boundary']])+'<p>'+h(crew['state'])+'</p><p>完整说明：《BI资源人员联立试排说明_20261007.txt》。这是离线设计资料。</p>'))
output=ROOT/'outputs/BI需求与呈现方案.html'
if f.get('topic_page_composition'):
    c=f['topic_page_composition']
    parts.append(section('topic-page-composition','个人专题页面：阅读编排、版本和导航','<p>'+h(c['state'])+'</p>'+table(['内容','定义与边界'],[[k,c[k]] for k in ['definition','layout','navigation','versions','permission','boundary']])+'<p>完整说明：《BI个人专题页面编排说明_20261007.txt》。</p>'))
if f.get('oee_trial'):
    c=f['oee_trial']
    parts.append(section('oee-design','班次效率：配置口径、损失时间与采集缺口','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','formula','mixed','time','zero','visuals','sources','permission','boundary']])+'<p>方法参考：'+ ' · '.join('<a href="'+h(url)+'">OEE计算与因素</a>' for url in c['references'])+'</p>'))
if f.get('joint_blocker_reading'):
    c=f['joint_blocker_reading']
    parts.append(section('joint-blocker-design','首阻断关联：去重范围与任务核查','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','measures','time','presentation','boundary']])))
if f.get('joint_material_evidence'):
    c=f['joint_material_evidence']
    parts.append(section('joint-material-design','逐物料核对：需求、供给与原序预留','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','measures','time','presentation','boundary']])))
if f.get('workbench_trial_favorites'):
    c=f['workbench_trial_favorites']
    parts.append(section('trial-favorites-design','方案收藏：保存明确的方案与阅读方式','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','presentation','boundary']])))
if f.get('joint_occupancy_comparison'):
    c=f['joint_occupancy_comparison']
    parts.append(section('occupancy-design','人机占用对照：同一对象并排核查安排','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','measures','presentation','boundary']])))
if f.get('joint_batch_material_comparison'):
    c=f['joint_batch_material_comparison']
    parts.append(section('batch-material-design','批次获料对照：总量相同也要核对获配对象','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','measures','presentation','boundary']])))
if f.get('joint_schedule_trial'):
    c=f['joint_schedule_trial']
    parts.append(section('joint-schedule-design','物料、人机联立：从批次交期追到预留依据','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','demand','supply','method','presentation','measures','boundary']])))
if f.get('order_baseline_trial'):
    c=f['order_baseline_trial']
    parts.append(section('order-baseline-design','订单与BOM基线：覆盖缺口、双交期和版本差异','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','arithmetic','coverage','time','presentation','boundary']])))
if f.get('object_hub'):
    c=f['object_hub']
    parts.append(section('object-hub-design','统一对象检索：身份、来源与明确引用','<p>'+h(c['state'])+'</p>'+table(['内容','定义与边界'],[[k,c[k]] for k in ['definition','presentation','boundary']])))
if f.get('topic_journey'):
    c=f['topic_journey']
    parts.append(section('topic-journey-design','跨专题探索：范围、日期角色与返回','<p>'+h(c['state'])+'</p>'+table(['内容','定义与边界'],[[k,c[k]] for k in ['definition','presentation','boundary']])))
if f.get('first_piece_evidence'):
    c=f['first_piece_evidence']
    parts.append(section('first-piece-design','首件证据：实测与计量依据同屏核对','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','evidence','presentation','boundary']])))
if f.get('launch_review'):
    c=f['launch_review']
    parts.append(section('launch-review-design','投产条件：从排得进到开工依据核对','<p>'+h(c['state'])+'</p>'+table(['内容','定义与呈现'],[[k,c[k]] for k in ['definition','time','capacity','evidence','presentation','boundary']])))
document='<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BI需求与呈现方案</title><style>'+style+'</style></head><body><main>'+''.join(parts)+'</main><script>'+script+'</script></body></html>'
document=document.replace('href="#spc"','href="#spc-trial"').replace('href="#msa"','href="#msa-trial"').replace('href="#model-cards"','href="#model-cards-design"').replace('href="#crew-schedule"','href="#crew-schedule-design"').replace('href="#topic-pages"','href="#topic-page-composition"')
document=document.replace('href="#objects"','href="#object-hub-design"')
document=document.replace('href="#oee"','href="#oee-design"')
document=document.replace('href="#joint-schedule"','href="#joint-schedule-design"')
document=document.replace('href="#order-baselines"','href="#order-baseline-design"')
document=document.replace('href="#first-piece"','href="#first-piece-design"')
document=document.replace('href="#launch-review"','href="#launch-review-design"')
output.write_text(document)
print(output)

# Readable fallback for environments that cannot open an HTML preview.
text_lines=[f'电机制造企业 BI 需求、定义与呈现方案 v{d["version"]}',
    f'{len(d["domains"])}个领域 / {count}项候选需求 / {len(d["metrics"])}项指标口径 / {len(d["page_blueprints"])}个页面蓝图',
    d['notice'],'',f['bi_definition_short'],'',
    f'阅读顺序：BI定义与分析模板 → 呈现方式 → {count}项需求及领域数据契约 → 指标口径 → 页面蓝图 → 角色工作台 → 跨部门场景与建设顺序。',
    '本文件为同一设计目录的离线文字版，可用文本编辑器直接打开；无需本地网页服务。',
    '', 'BI与业务系统的职责']
for row in f['product_boundaries']:
    text_lines.append('｜'.join(row))
text_lines.extend(['','BI可配置对象与编码（示例，并非批量改号）'])
v9_sections=[('六类BI定义对象','definition_objects_v9'),('指标定义的十项契约','metric_definition_v9'),('九种呈现形态','presentation_plan_v9'),('一页BI的分层结构','page_pattern_v9'),('自定义配置与发布','config_contract_v9'),('专项适用性评审','conditional_review_v9'),('首期四页的决策与数据','mvp_decisions_v9')]
for title,key in v9_sections:
    if key in f:
        text_lines.extend(['',title])
        text_lines.extend('｜'.join(row) for row in f[key])
if f.get('execution_design'):
    text_lines.extend(['','实施设计补充：建设分类与页面内容优先级'])
    text_lines.extend(execution_text(d))
text_lines.extend('｜'.join(row) for row in f['configurable_objects'])
text_lines.extend('｜'.join(row) for row in f['coding_rules'])
text_lines.extend(['','展示内容与交互规范',f['content_design_note'],'','16种展示组件'])
text_lines.extend('｜'.join(row) for row in f['component_contracts'])
text_lines.extend(['','15种数据状态'])
text_lines.extend('｜'.join([v['name'],v['label'],v['render'],v['boundary']]) for v in f['presentation_states'])
text_lines.extend(['','15类筛选控件'])
text_lines.extend('｜'.join([v['label'],v['rule']]) for v in f['filter_library'])
text_lines.extend(['','电机制造的8组分析维度字典'])
text_lines.extend('｜'.join(row) for row in f['factory_dimension_library'])
text_lines.extend(['','12条数字呈现规则'])
text_lines.extend('｜'.join(row) for row in f['number_display_rules'])
text_lines.extend(['','一张BI页面的10项定义'])
text_lines.extend('｜'.join(row) for row in f['page_definition_fields'])
text_lines.extend(['','14种分析模型选型（设计，不代表已实现全部计算）'])
for m in f['model_library']:
    text_lines.extend([m['id']+' · '+m['name'],'问题：'+m['question'],
        '粒度：'+m['grain'],'呈现：'+m['visual'],'下钻：'+m['drill'],
        '边界：'+m['guardrail'],'候选指标：'+' / '.join(m['metric_ids']),
        '示例需求：'+m['example_need_id'],'采集门槛：'+m['collection_gate'],''])
text_lines.extend(['','14条按问题选图的规则'])
text_lines.extend('｜'.join(row) for row in f['chart_selection'])
text_lines.extend(['','完整性检查的8个方向'])
text_lines.extend('｜'.join(row) for row in f['completeness_axes'])
text_lines.extend(['','适合当前电机工厂的特别规则'])
text_lines.extend('｜'.join(row) for row in f['factory_specific_rules'])
text_lines.extend(['',f['scope_note'],'设计草稿与正式配置的边界：'+f['studio_notice'],'仍需确认：'+' / '.join(f['studio_pending'])])
text_lines.extend(['','每份分析必须定义的12件事'])
for title,definition,example,boundary in f['definition_contract']:
    text_lines.extend([title+'：'+definition,'例子：'+example,'边界：'+boundary,''])
text_lines.append('呈现方式')
for p in f['presentation_choices']:
    text_lines.extend([f'【{p["name"]}】{p["reader"]}',p['question'],
        '内容：'+p['density'],'图形：'+p['visual'],'明细：'+p['detail'],
        '动作：'+p['action'],'边界：'+p['avoid'],'手机：'+p['mobile'],''])
contracts={c['code']:c for c in f['domain_data_contracts']}
for dom in d['domains']:
    c=contracts[dom['code']]
    text_lines.extend(['='*45,f'{dom["code"]} · {dom["name"]} · {len(dom["items"])}项',
        '领域关联键：'+c['key'],'最少字段：'+c['fields'],'时间：'+c['clock'],
        '采集起步：'+c['approach'],'真实数据状态：'+c['source_status'],''])
    for i in dom['items']:
        text_lines.append(i['id']+' · '+i['need'])
        for key,label in [('definition','业务定义'),('owner','责任岗位'),('action','处理动作'),
            ('view','建议呈现'),('source','建议来源'),('grain','对象粒度'),('frequency','查看频率'),
            ('dimensions','分析维度'),('applicability','适用条件'),('prerequisite','数据前提'),
            ('priority','候选阶段'),('implementation','模拟状态'),('gap','待补内容'),('acceptance','验收')]:
            text_lines.append(label+'：'+i[key])
        text_lines.extend(['候选展示维度：'+' / '.join(i['display_design']['dimensions']),'维度启用边界：'+i['display_design']['scope_note'],'对象与证据：'+i['display_design']['object_and_evidence'],'页面蓝图：'+' / '.join(i['page_ids']),''])
        if i.get('presentation_contract'):
            contract=i['presentation_contract']
            for key,label in [('question','展示问题'),('compare_gate','可比条件'),('context_binding','交互上下文'),('detail_contract','对象明细契约'),('mobile_task','手机任务'),('permissions','读取与导出权限'),('export_contract','导出一致性'),('action_boundary','处理边界')]:
                text_lines.append(label+'：'+contract[key])
        if i.get('delivery_proposal'):
            proposal=i['delivery_proposal']
            text_lines.extend(['建议建设包：'+proposal['package_id']+' '+proposal['package_name'],'建议进入条件：'+proposal['entry_gate'],'建议试点范围：'+proposal['first_scope'],'部门决定 / 节奏：'+proposal['decision_context']+' / '+proposal['review_cadence'],'维护责任待确认：'+proposal['maintainer'],'分类边界：'+proposal['review_state'],''])
text_lines.extend(['='*45, '指标口径建议 · '+str(len(d['metrics']))+'项',
    '下列为候选定义，须由业务责任人审定。缺失不当作0；分母为零不显示0%；比例汇总后相除。'])
for m in d['metrics']:
    text_lines.append(m['id']+' · '+m['name'])
    for key,label in [('formula','计算'),('grain','粒度'),('clock','时间口径'),
        ('source','来源'),('owner','责任'),('refresh','更新'),('pitfalls','边界'),
        ('status','定义状态'),('implementation','实施状态'),('contract_note','口径契约')]:
        if m.get(key):text_lines.append(label+'：'+m[key])
    text_lines.append('')
text_lines.extend(['='*45,'页面蓝图 · '+str(len(d['page_blueprints']))+'页'])
for p in d['page_blueprints']:
    text_lines.append(p['id']+' · '+p['name'])
    for key,label in [('reader','使用者'),('question','决策问题'),('visual','解释图'),
        ('detail','对象清单'),('drill','下钻路径'),('decision','处理动作'),
        ('gate','启用条件'),('status','实施状态')]:
        text_lines.append(label+'：'+p[key])
    for key,label in [('cards','主卡'),('domains','领域'),('metrics','指标')]:
        text_lines.append(label+'：'+' / '.join(p[key]))
    text_lines.extend('布局 '+title+'：'+content for title,content in p['layout'])
    spec=p['display_spec']; filters={x['id']:x for x in f['filter_library']}
    text_lines.extend(['候选筛选：'+' / '.join(filters[i]['label'] for i in spec['filters']),'时间含义：'+spec['time_semantics'],'对象字段：'+' / '.join(spec['detail_columns']),'默认顺序：'+spec['default_sort'],'手机用途：'+spec['mobile'],'筛选边界：'+spec['filter_rule'],'权限：'+spec['privacy']])
    text_lines.extend('交互：'+x for x in spec['interaction'])
    text_lines.append('')
text_lines.extend(['='*45,'角色工作台'])
for r in d['roles']:
    text_lines.append('【'+r['role']+'】')
    for key,label in [('question','问题'),('content','内容'),('surface','呈现'),
        ('drill','下钻'),('cadence','节奏'),('action','行动')]:
        text_lines.append(label+'：'+r[key])
    text_lines.append('')
text_lines.extend(['='*45,'六条跨部门对象路径'])
text_lines.extend('｜'.join(row) for row in f['scenario_navigation'])
text_lines.extend(['','适合低预算、少IT人员的建设顺序'])
text_lines.extend('｜'.join(row) for row in f['delivery_waves'])
text_lines.extend(['','上线评审检查'])
text_lines.extend('｜'.join(row) for row in f['review_gates'])
text_lines.extend(['','设计来源：'+d['design_basis']['context'],'适用边界：'+d['design_basis']['limits']])
(ROOT/f'outputs/BI完整{count}项需求清单.txt').write_text('\n'.join(text_lines)+'\n')

# Plain-text companion remains usable when a local browser cannot be opened.
brief=['电机制造企业 BI 展示内容与定义总览',f'设计版本 v{d["version"]}；{len(d["domains"])}个领域、{count}项候选需求、{len(d["metrics"])}项指标口径、{len(d["page_blueprints"])}个页面蓝图。',
       '候选目录尽量覆盖全流程；适用范围需由工厂确认，后续新业务仍可扩展。这些数量不表示生产实施完成率。',
       '', '一、BI的定义', f['definition'],f['factory_focus'],'',
       '二、构成BI的六层']
brief.extend(' → '.join(row) for row in f['bi_layers'])
brief.extend(['','三、全流程需求领域'])
for dom in d['domains']:
    owner=dom.get('owner') or ' / '.join(dict.fromkeys(i['owner'] for i in dom['items']))
    brief.extend([f'{dom["code"]}｜{dom["name"]}｜{len(dom["items"])}项｜责任：{owner}',
                  '  '+'；'.join(i['id']+' '+i['need'] for i in dom['items'])])
brief.extend(['','四、怎样呈现，而不是只堆指标卡'])
for x in f['presentation_choices']:
    brief.extend([x['name']+'｜读者：'+x['reader'],'  要回答：'+x['question'],'  主内容：'+' / '.join(x['cards']),'  呈现：'+x['visual'],'  下钻与动作：'+x['detail']+'；'+x['action'],'  使用边界：'+x['avoid']])
brief.extend(['','五、每项分析定义必须明确'])
brief.extend('｜'.join(row) for row in f['page_definition_fields'])
brief.extend(['','六、制造企业的可比性与数据边界'])
brief.extend('｜'.join(row) for row in f['factory_specific_rules'])
brief.extend(['特性分析：先核对必检覆盖，再看单一物料、特性、单位和规范版本的实测分布。复查次数不增加原检验批次；逐样本超限数、原批次结论及库存批准分别显示。',
              '材质证明：按到货单去重，证明号登记、原件归档、身份及内容一致、签章核验和质量批准分别呈现；供方声明与本厂实测分开，缺资料或需授权不判作材料不合格。',
              '状态表达：实测零、尚无数据、漏项、资料错误、仅部分覆盖、未来记录和权限受限分别显示；未知不补成零，未批准不显示已可用。',
              '', '七、适合低预算、少IT的建设顺序'])
brief.extend('｜'.join(row) for row in f['delivery_waves'])
brief.extend(['','八、当前实例与验证范围',
              '采购库存 → 来料特性与样本：支持原检验队列、六类互斥特性状态、单规范直方分布、逐批中位/实测范围、逐样本矩阵、登记历史、Excel来源及完整CSV接口。',
              '采购库存 → 到货材质证明：按到货单展示身份核对、原件完整性与权限、供方声明对照、当前错误或撤销、关联历史和原IQC；133份模拟原件中132份已归档，一份作为缺归档样例。',
              '原件协作 → 指定账号只读授权：归档人核对指定文件、接收账号及期限后确认；接收人只能读取获授权原件，撤销、到期和岗位变化后停止后续读取。材质证明共用该权限规则，主库未自动授予权限；相关界面和实际浏览器下载尚未实测。',
              '所有当前业务数据、证明文件和特性限值均为合成演示；未连接U8/MES。来料特性及材质证明已完成数据、服务端及代码检查，新增页面的浏览器渲染、手机布局和实际下载尚未实测，材质证明上传交互也未实测。',
              f'详细公式、来源、粒度、候选维度、前提、责任、动作、验收及实施缺口，见同目录《BI完整{count}项需求清单.txt》。'])
for title,key in v9_sections:
    if key in f:
        brief.extend(['',title])
        brief.extend('｜'.join(row) for row in f[key])
if f.get('execution_design'):
    brief.extend(['','实施设计补充：382项需求、26领域和17页均有建设与使用设计'])
    brief.extend(p['id']+' '+p['name']+'｜'+str(p['candidate_count'])+'项｜'+p['gate'] for p in f['execution_design']['packages'])
    brief.extend(['分类是建议，未作真实就绪、工期或工作量评审。','部门决策、节奏、试点字段，17页主结果/解释/护栏以及完整建设包索引见《BI建设分层与页面内容_实施补充.txt》。'])
(ROOT/'outputs/BI展示内容与定义总览.txt').write_text('\n'.join(brief)+'\n')

if d['version']>=9:
    concept=[f'电机制造企业：BI定义与呈现构思 v{d["version"]}',
       '适用现状：用友U8、momo MES待上线；约900台/日，全流程自制，小批量定制；Excel、纸质及设备文件分散；预算与IT人力有限。',
       '这是候选设计，未核验真实接口、字段、企业限值或审批规则；当前系统演示数据为合成资料。',
       '',f['definition'],'',f'全景范围：26个领域、{count}项候选需求、63项指标建议、17页蓝图。',f['scope_note'],
       '', '建设取舍：先按真实业务判断适用性，再确认来源、身份、口径和维护责任；先补关键证据，不先追求所有图形。']
    for title,key in v9_sections:
        concept.extend(['',title]);concept.extend('｜'.join(row) for row in f[key])
    concept.extend(['','十七个页面的主问题'])
    concept.extend(p['id']+' '+p['name']+'｜'+p['reader']+'｜'+p['question']+'｜处理：'+p['decision'] for p in d['page_blueprints'])
    concept.extend(['','怎样定义一项指标：以交付为例（建议评审结构，不修改现有计算）',
      '编码与版本：稳定编码关联批准版本；原承诺、现承诺、发运履约、签收履约分别确认用途。',
      '粒度：交付计划行；无分批计划时才使用订单行。选择订单期、承诺到期队列或发运期须明确，不能混用。',
      '分母：明确截止时已到期的有效计划行、取消排除依据及未知承诺；日期承诺当日是否仍可履约由业务规则确认。',
      '分子：同一分母中按所选承诺版本按期足量完成的行；部分发运和分批允差按批准规则处理。',
      '比较：客户、可比配置、批量与承诺版本；比例汇总分子分母后相除，零分母显示无有效样本。',
      '呈现：结果比例及分子分母 → 延期分布与未交队列 → 具体订单 → 工单/检测/发运证据 → 协调与复查。',
      '', '怎样组织创新体验',
      '同一订单视角：销售、计划、质量、仓库各看自己的阻断，但下钻到相同业务身份；不另造各部门的订单编号。',
      '对象作为入口：输入订单、工单、批次或SN即可进入履历；已确认关系、候选关系和未知关系分别展示。',
      '解释优先：显示当前范围、分母、排除、未知和数据更新时间，说明为何不能比较或为何数字改变。',
      '分析定义工作坊：先选业务问题、粒度和模型，再选图形；生成待评审草稿，试算后再发布。',
      '复盘双视角：保留当时已知结果与后来更正事实，能解释历史数字变化；保存筛选不冒充冻结结果。',
      '情景沙盘：同一基线比较拼批、插单、备料或班次方案，假设与实际分开，约束未知时不声称可执行。',
      '', '小批量定制必须守住的规则'])
    concept.extend('｜'.join(row) for row in f['factory_specific_rules'])
    concept.extend(['','如何判断上线是否有用',
      '抽取实际订单与SN，核对汇总、对象、来源和导出同范围；验证缺失、更正、权限、零分母及无数据。',
      '先实测找单、追溯、统计与异常复核耗时，再比较上线后耗时；页面点击与模拟数量不是改善收益。',
      '每项需求有业务责任人、来源责任人和维护接续人；少IT人员应优先可维护的模块，避免无人维护的定制。',
      '',f'完整逐项内容见《BI完整{count}项需求清单.txt》；网页不便打开时可直接读取TXT。'])
    if f.get('execution_design'):
        concept.extend(['','实施设计补充']);concept.extend(execution_text(d))
    (ROOT/f'outputs/BI定义与呈现构思_v{d["version"]}.txt').write_text('\n'.join(concept)+'\n')

if f.get('execution_design'):
    execution_companion='\n'.join(execution_text(d,include_index=True))+'\n'
    (ROOT/'outputs/BI建设分层与页面内容_实施补充.txt').write_text(execution_companion)
    # The application recovery contract already includes all text files in docs.
    (ROOT/'docs/BI内容与实施设计说明.txt').write_text(execution_companion)

# A single-page companion uses the identical overview renderer; no server/assets.
overview_data=json.dumps(d,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
overview_js=(ROOT/'static/catalog_planning.js').read_text().replace('export function ','function ')
overview_js+='\nconst overviewCatalog='+overview_data+';\n'
overview_js+=r'''const overviewEsc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const overviewTable=(headers,rows)=>'<div class="scroll"><table><thead><tr>'+headers.map(h=>'<th>'+overviewEsc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
renderBiDecisionDesign(document.querySelector('#one-page'),overviewCatalog,{esc:overviewEsc,table:overviewTable});'''
overview_style=style+'main{padding:24px;max-width:1250px}.bi-workbench{display:none}.bi-overview{margin:0}.bi-caption{margin-bottom:0}'
(ROOT/'outputs/BI一页概览.html').write_text('<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>电机企业BI一页概览</title><style>'+overview_style+'</style></head><body><main id="one-page"></main><script>'+overview_js+'</script></body></html>')

if f.get('presentation_design'):
    companion='\n'.join(presentation_text(d))+'\n'
    (ROOT/'outputs/BI展示内容与交互设计_完善版.txt').write_text(companion)
    (ROOT/'docs/BI展示内容与交互设计说明.txt').write_text(companion)
    quick='\n'.join(reader_guide_text(d))+'\n'
    (ROOT/'outputs/BI定义与呈现_快速阅读版.txt').write_text(quick)
    (ROOT/'docs/BI定义与呈现_快速阅读版.txt').write_text(quick)
    partial=sum(i['implementation']=='模拟部分覆盖' for dom in d['domains'] for i in dom['items'])
    guide=[f'电机制造企业 BI 设计 v{d["version"]} 阅读说明',
        '展示补充版本：'+f['presentation_design']['revision'],'',
        '先读《BI定义与呈现_快速阅读版.txt》：工厂BI定位、五个首期问题、两项结果与一项护栏、26领域索引和页面选择。',
        '展开读《BI展示内容与交互设计_完善版.txt》：BI定义、8类配置对象、12种呈现、17页任务、12条跨部门路径、26领域比较规则、条件需求及全部382项索引。',
        '逐项评审读《BI完整382项需求清单.txt》：完整需求定义、来源、粒度、责任、前提、动作、验收、缺口和展示交互契约；附63项指标建议及17页蓝图。',
        '建设安排读《BI建设分层与页面内容_实施补充.txt》：建议分包、进入条件、维护责任、试点起步和每页结果/解释/护栏。',
        '《BI展示内容与定义总览.txt》《BI定义与呈现构思_v9.txt》保留总体框架。','',
        '《BI需求与呈现方案.html》和《BI一页概览.html》内含数据、脚本与样式，无须本地应用服务；网页不能打开时直接读取TXT。',
        '《BI需求与定义数据_v9.json》保留需求、指标、页面关系和新增展示契约；适合后续评审与程序使用。','',
        f'当前为26领域382项候选、63项指标建议、17页蓝图；{partial}项模拟部分覆盖、{count-partial}项待建设。',
        '设计完善保留原需求、指标和页面定义及覆盖状态；校准原件功能仅更新两项需求与四页的已验证模拟状态。第31份模拟Excel按正常导入另增524条来源，旧事实、模型、目标和指标发布保留。',
        '候选数量不是完成率；需求库不能穷尽未来业务，条件项须确认适用性后进入。',
        '约900台/日、U8、MES待上线及全流程自制来自用户；momo产品及接口未确认。',
        '业务记录、原件和限值全部为合成演示；真实系统、规则和审批尚待核实。','',
        '结构、引用、幂等、完整文本覆盖、脚本语法及原字段/数据库保留检查结果见 data/bi_presentation_validation.json 与 data/bi_v9_validation.json。',
        '本轮已有BI设计草稿的8项服务端测试通过。新增浏览器渲染、手机布局、实际筛选和下载尚未实测，不提供本轮浏览器验收截图。',
        'ZIP为设计资料包，不是应用恢复备份。',
    ]
    (ROOT/f'outputs/BI方案阅读说明_v{d["version"]}.txt').write_text('\n'.join(guide)+'\n')
if f.get('model_result_reading'):
    import shutil
    shutil.copyfile(ROOT/'docs/BI模型结果阅读与来源说明.txt',ROOT/'outputs/BI模型结果阅读与来源说明_20261007.txt')
    shutil.copyfile(ROOT/'docs/BI模型当前结果导出说明.txt',ROOT/'outputs/BI模型当前结果导出说明_20261007.txt')

if f.get('method_workshop'):
    depth=workshop_text(d)
    (ROOT/'outputs/BI分析方法与页面预演_20261007.txt').write_text(depth)
    (ROOT/'docs/BI分析方法与页面预演说明.txt').write_text(depth)
    addition='\n'+method_reading_note()+'\n'
    for name in (f'outputs/BI方案阅读说明_v{d["version"]}.txt',):
        path=ROOT/name
        path.write_text(path.read_text()+addition)
if f.get('model_cards'):
    import shutil
    shutil.copyfile(ROOT/'docs/BI个人模型口径卡说明.txt',ROOT/'outputs/BI个人模型口径卡说明_20261007.txt')
    guide=['BI方案阅读说明 · 当前个人模型口径卡增量（2026-10-07）','',
        '先读《BI定义与呈现_快速阅读版.txt》：从业务问题到统一口径、分析方式、页面、证据和复查。',
        '再读《BI完整382项需求清单.txt》：26领域的全部候选内容、来源粒度、责任、前提及验收。',
        '选页面读《BI展示内容与交互设计_完善版.txt》：17页首屏任务、筛选、下钻与空状态。',
        '选方法读《BI分析方法与页面预演_20261007.txt》：18类方法及适用门槛。',
        '个人模型看《BI个人模型口径卡说明_20261007.txt》：编码、业务说明、实际定义、版本、专题入口和当前结果的区别。','',
        f'当前仍为63项建议指标、{sum(n["implementation"]=="模拟部分覆盖" for g in d["domains"] for n in g["items"])}项模拟部分覆盖及{sum(n["implementation"]=="待建设" for g in d["domains"] for n in g["items"])}项待建设；不是全部功能完成。',
        '网页不能打开时直接读TXT；离线HTML内含目录、脚本和样式，无须本地应用服务。',
        '设计ZIP不含数据库/凭据，不是应用恢复包；应用备份另有完整校验包。',
        '新增检查证据：data/model_cards_design_validation.json、data/model_cards_release.json、data/model_cards_phase_release.json。',
        '业务资料均为合成数据，真实U8/MES未接入；浏览器、手机及实际下载尚未验收。']
    (ROOT/f'outputs/BI方案阅读说明_v{d["version"]}.txt').write_text('\n'.join(guide)+'\n')
