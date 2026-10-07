"""Excel contract for synthetic first-piece review versions."""
DATASET = 'first_piece_reviews'


def register(register):
    register(DATASET, '首件复核登记', '42_首件复核',
             'id:复核记录号:str;plan_id:首件应检计划:str:process_check_plans;version:复核版本:int;previous_id:上版复核:str?:first_piece_reviews;status:登记状态:str;basis_at:依据截止:datetime;check_id:依据检验记录:str?:process_checks;basis_hash:依据内容摘要:str;rule_hash:依据规则摘要:str;reviewed:复核时点:datetime;registered:登记时点:datetime;decision:登记结论:str;reviewer_id:复核工号:str:employees;reference:复核文件编号:str;note:结论或变更原因:str')
