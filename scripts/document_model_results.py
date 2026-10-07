from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
NOTE='2026-10-07 模型结果阅读：个人口径卡直接呈现业务范围、业务截止/日期角色/粒度与固定条件，整范围主度量及有效/缺失样本、六种原模型图形、分页分组与精确来源下钻。沿用既有计算与整范围重算，不相加/平均分组；来源凭据600秒绑定本人卡版本、全部资料、结果与权限，资料变化需重跑。19新增＋31既有检查、16纯呈现检查、全套2263项（269.086秒）通过；52既有模型演练50摘要可算、2按原单位条件暂停，六岗位原生HTTP核对全部150订单来源与精确分组、Excel行及陈旧凭据。主库52表、214523事实/49批次、2口径卡/2版本/794审计均不改；454原来源及31保护模块字节保留，发布交付v8与模板v4/rev8不改。382候选/63建议口径/17蓝图/18方法、114模拟部分覆盖/268待建设不变。浏览器、手机、实际键盘与下载仍未验收；说明 docs/BI模型结果阅读与来源说明.txt，当前证据 data/model_results_phase_release.json。整体目标继续，以下为历史增量。'
def main():
 for name in ('README.md','docs/BUILD_PLAN.md'):
  p=ROOT/name;s=p.read_text();assert '2026-10-07 模型结果阅读：' not in s;first,rest=s.split('\n',1);p.write_text(first+'\n\n'+NOTE+'\n'+rest)
 p=ROOT/'docs/BI个人模型口径卡说明.txt';s=p.read_text();assert '当前结果阅读补充' not in s;p.write_text(s+'\n当前结果阅读补充（2026-10-07）\n结果页已直接提供整范围指标、样本说明、图形、分组、固定条件及当前来源下钻，技术JSON收进展开区。操作和凭据失效规则详见《BI模型结果阅读与来源说明.txt》；此补充不改变历史卡定义或保存当时结果。\n')
 print('Result-reading documentation updated; goal remains active')
if __name__=='__main__':main()
