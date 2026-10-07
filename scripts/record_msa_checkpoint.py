"""Append concise current documentation without rewriting historic entries."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOTE='2026-10-07 测量系统交叉采样：第35份合成Excel经正常导入新增11试验、141成员、930重复观测（1,082事实）。新增 #msa，包含完整性矩阵、试验/校准窗口、交互均值及全部读数、分开的方差与研究变异占比、公差占用、ANOVA/方差分量、逐点Excel来源与完整CSV；4完整试验可试算，7异常试验暂停，不删重复、不补缺测、不自动换单位。26算法＋22接口、21纯呈现、全套2,213及237相关检查通过，六岗位隔离原生HTTP验证来源/CSV/原件权限。主库214,523事实、49批次、118原始契约，共50表；原213,441事实、52模型/21专题/33目标/旧快照及2个人SPC视角2冻结结果保留。452旧物理来源、115旧契约、16原分析核心和其他9保护模块保留；只声明新增契约和新增制造校验分支。模板通过原模拟样例正常升级v4/rev8，v1/v2/v3载荷保留，交付v8不改。BI维持26域382需求/63建议口径/17蓝图/18方法，P-06定义改为独立试验粒度并仅标模拟部分覆盖：114部分、268待建设。浏览器/手机未验收，真实MSA资格与U8/MES未接入；完整平台目标继续。说明 docs/MSA_README.txt；来源保留证据 data/msa_release.json，恢复证据 data/msa_restore_final.json。以下为历史增量。'
def main():
 for name in ('README.md','docs/BUILD_PLAN.md'):
  p=ROOT/name;s=p.read_text();head,rest=s.split('\n',1);assert NOTE not in s;p.write_text(head+'\n\n'+NOTE+'\n'+rest)
if __name__=='__main__':main()
