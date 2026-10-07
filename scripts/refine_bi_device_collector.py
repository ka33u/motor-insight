"""Exact reversible presentation scope for a local simulation collector."""
from refine_bi_device_intake import STATUS as PRIOR
MARKER='本地文件采集模拟：'
STATUS='已登记模拟目录覆盖之外，新增服务器白名单下的本地模拟文件采集：两次实际读取的SHA256、大小、inode与修改/状态时间一致且达到观察间隔后，冻结1—20份清单；内容或来源变化须重新观察。私有归档、同账号同内容复用、读取/归档失败回执与版本化重试、完整历史及当前原件完整性分别显示。标准CSV进入既有原件工作台核对检测会话；错SN不通过逐项核对，非结构化原件需人工核对。禁止读取符号链接、越界路径、特殊文件、过大文件与临时格式；每次观察最多100文件/40MB/5层目录。来源及测试协议样例由已导入模拟Excel事实生成，业务事实不被采集回执改写，未自动关联SN/订单、授权、放行或发布指标。原模板v2规则不改。仅为macOS/Linux服务器本地模拟目录；真实设备PC代理、网络认证、持续后台巡检、厂商专有格式转换及U8/MES仍待建设；浏览器、手机、实际下载未验收。'
ROW=['本地设备文件采集与回执','哪些文件内容已经稳定归档，哪些仍需重试或人工核对？','本地来源 → 两次稳定观察 → 冻结采集清单 → 私有归档回执 → 当前完整性 → 会话逐项核对',STATUS]
SURFACE=dict(href='#device-collection',name='设备文件采集',audience='管理员、质量岗位',question=ROW[1],content='本地模拟来源、实际文件指纹、稳定观察、不可变清单、历史回执与当前私有原件完整性',action='重新观察变化文件，重试可恢复失败，核对原件会话',status=STATUS)
def refine_device_collector(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id']=='W-21':assert n['implementation']==n['decision_spec']['implementation']=='模拟部分覆盖';n['gap']=STATUS
 for p in d['page_blueprints']:
  if p['id']=='P15':p['status']=p['status'].split(' '+MARKER)[0]+' '+MARKER+STATUS
 f=d['framework'];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]+[list(ROW)];f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']]+[dict(SURFACE)];return d
def remove_exact_increment(d):
 for dom in d['domains']:
  for n in dom['items']:
   if n['id']=='W-21':assert n['gap']==STATUS;n['gap']=PRIOR
 for p in d['page_blueprints']:
  if p['id']=='P15':
   suffix=' '+MARKER+STATUS;assert p['status'].endswith(suffix);p['status']=p['status'][:-len(suffix)]
 f=d['framework'];assert [r for r in f['presentation'] if r[0]==ROW[0]]==[ROW];f['presentation']=[r for r in f['presentation'] if r[0]!=ROW[0]]
 assert [s for s in f['surfaces'] if s['href']==SURFACE['href']]==[SURFACE];f['surfaces']=[s for s in f['surfaces'] if s['href']!=SURFACE['href']];return d
