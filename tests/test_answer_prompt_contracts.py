from retail_analytics_agent.brand_identity import (
    EVIDENCE_ANSWER_SYSTEM_PROMPT,
    FINAL_ANSWER_SYSTEM_PROMPT,
    GENERAL_AGENT_SYSTEM_PROMPT,
    REFUND_RATE_CALIBER_RULE,
    UNTRUSTED_EVIDENCE_RULE,
)


def test_evidence_answer_prompt_carries_refund_rate_caliber_rule() -> None:
    assert REFUND_RATE_CALIBER_RULE in EVIDENCE_ANSWER_SYSTEM_PROMPT
    assert UNTRUSTED_EVIDENCE_RULE in EVIDENCE_ANSWER_SYSTEM_PROMPT
    # 口径约束必须明确正分母与禁止事项，防止"退款笔数/总订单数"冒充退款率。
    assert "已支付去重订单数 ÷ 同范围已支付去重订单总数" in REFUND_RATE_CALIBER_RULE
    assert "不能充当分母" in REFUND_RATE_CALIBER_RULE
    assert "禁止在回答中给出任何退款率百分比" in REFUND_RATE_CALIBER_RULE


def test_other_system_prompts_do_not_inherit_refund_caliber_rule() -> None:
    # 口径约束只针对带数据证据的协作/知识回答层；通用与最终回答层保持原语义。
    assert REFUND_RATE_CALIBER_RULE not in GENERAL_AGENT_SYSTEM_PROMPT
    assert REFUND_RATE_CALIBER_RULE not in FINAL_ANSWER_SYSTEM_PROMPT
    assert UNTRUSTED_EVIDENCE_RULE in GENERAL_AGENT_SYSTEM_PROMPT
    assert UNTRUSTED_EVIDENCE_RULE in FINAL_ANSWER_SYSTEM_PROMPT
