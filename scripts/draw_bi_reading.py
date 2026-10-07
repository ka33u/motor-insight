"""Render the conceptual BI reading map; no synthetic business metrics."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
FONT='/System/Library/Fonts/Supplemental/Arial Unicode.ttf'
def main():
 d=json.loads((ROOT/'data/bi_design.json').read_text());b=d['framework']['decision_reading']
 image=Image.new('RGB',(1800,1240),'#f6f8fa');draw=ImageDraw.Draw(image)
 fonts={n:ImageFont.truetype(FONT,n) for n in (20,23,26,30,42)}
 def text(x,y,value,size=23,color='#172b3a'):draw.text((x,y),value,font=fonts[size],fill=color)
 def wrap(x,y,value,width,size=23,color='#172b3a',spacing=9):
  line='';rows=[]
  for c in value:
   if draw.textlength(line+c,font=fonts[size])>width:rows.append(line);line=c
   else:line+=c
  if line:rows.append(line)
  for row in rows:text(x,y,row,size,color);y+=size+spacing
  return y
 text(55,34,'MotorInsight · 电机智造 BI 全景',42)
 text(55,99,'把分散记录变成统一口径、业务判断、对象证据与效果复查',26,'#466276')
 text(55,164,'定义关系：通用能力集中维护，页面围绕岗位任务组织',26)
 names=[('来源事实','系统 · Excel · 设备原件'),('业务模型','身份 · 粒度 · 有效关系'),('指标口径','公式 · 日期 · 单位 · 版本'),('分析模型','比较 · 分解 · 追溯 · 试算'),('专题页面','结果 · 解释 · 异常对象'),('处理复查','依据 · 责任 · 措施 · 结果')]
 for i,(name,note) in enumerate(names):
  x=55+i*282;draw.rounded_rectangle((x,213,x+263,331),radius=10,fill='#e7f0f4')
  text(x+15,228,name,30);wrap(x+15,278,note,235,20)
  if i<5:text(x+265,246,'→',26,'#466276')
 text(55,369,'展示内容：六类决定覆盖全部 26 个业务领域',26)
 domain_map={v['code']:v for v in d['domains']}
 for i,g in enumerate(b['lenses']):
  x=55+i%3*566;y=420+i//3*173
  draw.line((x,y,x+525,y),fill='#5b8091',width=3)
  text(x,y+12,g['name'],30)
  wrap(x,y+58,' · '.join(domain_map[c]['name'] for c in g['domains']),515,23)
 text(55,809,'页面结构：从数字进入对象，从对象追到证据',26)
 labels=[('范围','期间 / 截止 / 来源'),('结果','1—3个主要判断'),('解释','趋势 / 结构 / 条件'),('对象','订单 / 批次 / SN'),('证据','版本 / 明细 / 原件'),('复查','责任 / 期限 / 结果')]
 for i,(name,note) in enumerate(labels):
  x=55+i*282;draw.rectangle((x,855,x+263,949),fill='#e9efec')
  text(x+15,863,name,30);text(x+15,910,note,20)
 text(55,990,'低预算首期：先做四页，跑通一条真实业务证据链',26)
 for i,name in enumerate(['P02 订单交付','P05 质量与试验','P06 单台履历','P15 数据可信度']):
  text(55+i*425,1044,name,30)
 count=sum(len(v['items']) for v in d['domains'])
 text(55,1120,f'{count}项候选需求 · {len(d["metrics"])}项指标建议 · {len(d["page_blueprints"])}页蓝图；按业务价值、数据与维护能力分期启用',23,'#466276')
 text(55,1164,'设计建议 / 合成演示；不代表真实ERP或MES已接入。完整编号和定义见阅读指南及需求清单。',20,'#466276')
 path=ROOT/'outputs/BI决策与展示_总览.png';image.save(path);print(path)

if __name__=='__main__':main()
