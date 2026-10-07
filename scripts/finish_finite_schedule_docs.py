"""Current increment handoff; preserve the prior completion note and history."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOTE='2026-10-07 有限资源试排：第36份合成Excel经正常预览与提交新增6,006事实：6独立方案、36批次、1,188任务、1,417依赖、2,374候选、961可用窗口、24不可用段。新增 #finite-schedule，前段批量、装配起逐台，按应完成或批次优先级作资源尾部试排，换型占用资源；甘特、完整批次交期、全部工序及等待/根阻断、资源负载、直接与全方案Excel依据、完整CSV/JSON均已提供。6情形区分可排、晚于交期、窗口不足、候选缺失、环路与重叠；异常不补零。39算法/接口、19纯呈现及全套2,322检查通过；六岗位原生HTTP核对1,154条方案来源和198任务，完整结果响应12份。主库220,529事实、50批次、125原始契约、52表；原214,523事实、118契约、52模型/21专题/33目标、旧快照、2个人口径卡及原模板v1至v4载荷保留；交付v8不变。454旧物理来源和31保护模块字节不变，仅2文件追加新契约和校验分支；模板正常升级v5/rev10。BI仍为26域382需求/63建议口径/17蓝图/18方法，F-05/F-06仅升级模拟部分覆盖，总116部分/266待建设。资源、工时、交期与未来窗口均独立模拟，人员/物料/模具未联立，无最优性证明或实际派工。浏览器、手机、实际下载与真实U8/MES连接仍未验收，全平台目标继续。说明 docs/BI有限资源试排说明.txt；保留证据 data/finite_schedule_release.json，恢复证据另行记录。以下为历史增量。'
def main():
 for n in ('finite_schedule_release.json','finite_schedule_http.json','finite_schedule_design.json','finite_schedule_presentation.json'):assert json.loads((ROOT/'data'/n).read_text())['success']
 assert '\nOK\n' in (ROOT/'data/finite_schedule_full_tests.log').read_text() and '\nOK\n' in (ROOT/'data/finite_schedule_related_tests.log').read_text()
 for name in ('README.md','docs/BUILD_PLAN.md'):
  p=ROOT/name;s=p.read_text();head,rest=s.split('\n',1);assert NOTE not in s;p.write_text(head+'\n\n'+NOTE+'\n'+rest)
 note=ROOT/'outputs/BI平台本轮完成记录_20261007.txt';before=ROOT/'data/backups/finite-schedule-before-completion-note';before.mkdir();shutil.copy2(note,before/note.name)
 note.write_text('本轮完成：有限资源试排（独立合成演练）\n\n'+NOTE+'\n\n阅读资料：BI有限资源试排说明_20261007.txt、BI定义与呈现_快速阅读版.txt、BI完整382项需求清单.txt。\n本机入口 http://127.0.0.1:8765/#finite-schedule\n网页暂不能打开时可直接读TXT和模拟输入Excel；应用恢复包与设计资料包分别提供。\n')
 # Public, non-sensitive reproducible presentation fixtures travel with recovery.
 for n in ('001_due','005_due'):shutil.copy2(ROOT/f'data/finite_schedule_board_{n}.json',ROOT/f'tests/fixtures/finite_schedule_board_{n}.json')
 proof=dict(success=True,phase='finite_resource_trial',main_database_sha256=hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest(),synthetic=True,full_tests=2322,targeted_tests=39,pure_presentation_checks=19,related_checks=True,browser_acceptance=False,mobile_acceptance=False,actual_download_acceptance=False,whole_platform_complete=False,restore_verified=False)
 (ROOT/'data/finite_schedule_phase.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n');print(json.dumps(proof))
if __name__=='__main__':main()
