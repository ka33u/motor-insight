"""Write a reviewable phase note; the active platform goal remains open."""
import shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOTE='2026-10-07 个人模型口径卡：新增个人唯一编码、业务问题、岗位、对象粒度/时间说明、解释边界和复查日期；绑定保存模型、指定指标/分组、数据集契约与规则版本，历史不可覆盖。定义依据变化时暂停当前数据分析；说明文字不改变实际筛选，不保留历史数值。自由分析可登记，专题仅显示本人同模型卡，管理员也不能读取他人卡。31项新增服务端检查、全套2,244项（264.675秒）、18项纯呈现检查与六岗位隔离原生HTTP通过。主库正常新增2张个人卡/2版本/2审计及2张操作表；原50表全部旧行、214523事实、454来源文件、27保护模块、52通用模型/21专题/33目标/旧快照、模板v4/rev8和交付v8保留。BI保持26域382候选/63建议口径/17蓝图/18方法，114模拟部分覆盖、268待建设。浏览器、手机和实际下载未验收；真实U8/MES、全局模型编码、跨部门口径审批与团队共享继续待建设。说明 [个人模型口径卡](docs/BI个人模型口径卡说明.txt)，当前来源保留证据 data/model_cards_release.json，完整恢复核对结果见 data/model_cards_restore_final.json。整体平台目标继续，以下为历史增量。'
def main():
 for name in ('README.md','docs/BUILD_PLAN.md'):
  p=ROOT/name;s=p.read_text();assert '2026-10-07 个人模型口径卡：' not in s;first,rest=s.split('\n',1);note=NOTE.replace('(docs/BI个人模型口径卡说明.txt)','(BI个人模型口径卡说明.txt)') if name.startswith('docs/') else NOTE;p.write_text(first+'\n\n'+note+'\n'+rest)
 p=ROOT/'outputs/BI平台本轮完成记录_20261007.txt';backup=ROOT/'data/backups/model-cards-before-completion-note';backup.mkdir();shutil.copy2(p,backup/p.name)
 p.write_text('本轮完成记录：BI定义与个人模型口径卡（2026-10-07）\n\n'+NOTE+'\n\n完整需求：《BI完整382项需求清单.txt》。先读《BI定义与呈现_快速阅读版.txt》，再按岗位选择页面与方法。\n应用入口：http://127.0.0.1:8765/#model-cards\n检查证据：data/model_cards_phase_release.json；正式恢复资料与校验以该证据内记录为准。\n')
 print('Current BI model-card phase documents written; overall goal remains active')
if __name__=='__main__':main()
