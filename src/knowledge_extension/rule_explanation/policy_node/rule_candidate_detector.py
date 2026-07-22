from .rule_scoring import score_rule_candidate


def detect_rule_candidates(df):
    """
    输入：
        semantic chunk dataframe

    输出：
        增加规则识别字段后的 dataframe
    """

    result_rows = []

    for _, row in df.iterrows():

        full_context_text = str(
            row.get("full_context_text", "")
        )

        level = str(
            row.get("level", "")
        )

        result = score_rule_candidate(
            text=full_context_text,
            level=level,
        )

        result_rows.append({
            **row.to_dict(),

            "rule_score": result["rule_score"],

            "candidate_level": result["candidate_level"],

            "is_rule_candidate": result["is_rule_candidate"],

            "candidate_types": ",".join(
                result["candidate_types"]
            ),

            "matched_keywords": ",".join(
                result["matched_keywords"]
            ),

            "matched_patterns": ",".join(
                result["matched_patterns"]
            ),

            "negative_keywords": ",".join(
                result["negative_keywords"]
            ),
        })

    return result_rows