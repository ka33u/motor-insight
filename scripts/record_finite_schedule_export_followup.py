import json,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOTE='2026-10-07 试排暂停状态导出补充：JSON保留全部7表假设输入；CSV在暂停原因后保留全部输入任务、份号、数量、每台工时和Excel行，明确排程/完成/等待/负载未计算。六岗位原生HTTP复查24份正常及暂停文件响应，117项受影响检查再通过；主库仍保持6,006新增事实与4条导入/模板审计，试排没有实际派工。浏览器、手机和实际下载仍未验收。'
def main():
 h=json.loads((ROOT/'data/finite_schedule_http_v2.json').read_text());assert h['success'] and h['result_exports']==24;assert '\nOK\n' in (ROOT/'data/finite_schedule_related_tests_v2.log').read_text()
 for name in ('README.md','docs/BUILD_PLAN.md'):
  p=ROOT/name;s=p.read_text();head,rest=s.split('\n',1);assert NOTE not in s;p.write_text(head+'\n\n'+NOTE+'\n'+rest)
 p=ROOT/'outputs/BI平台本轮完成记录_20261007.txt';p.write_text(p.read_text()+'\n'+NOTE+'\n')
 shutil.copy2(ROOT/'docs/BI有限资源试排说明.txt',ROOT/'outputs/BI有限资源试排说明_20261007.txt')
 phase=json.loads((ROOT/'data/finite_schedule_phase.json').read_text());assert hashlib.sha256((ROOT/'data/platform.sqlite3').read_bytes()).hexdigest()==phase['main_database_sha256'];phase.update(related_tests_after_export_refinement=117,native_http_exports=24,paused_inputs_preserved=True)
 (ROOT/'data/finite_schedule_phase.json').write_text(json.dumps(phase,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(success=True,paused_inputs_preserved=True,main_unchanged=True)))
if __name__=='__main__':main()
