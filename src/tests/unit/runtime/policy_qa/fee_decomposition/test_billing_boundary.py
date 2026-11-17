"""收费边界解释（Issue #85）：诊疗/价格项目内涵的「不含/除外内容/另收/包含」。

验收要点：
- 解释必须对上费用行与目录内涵原文，对不上的不讲；
- 同一被解释行只产出一处解释（多来源合并引用）；
- 患者话术不出现 符合/不符合/违规/超收/加收；
- 药品目录备注（适应症）不参与；材料/诊疗目录才参与。
"""
from __future__ import annotations

from src.runtime.policy_qa.fee_decomposition import model_explanation as explanation
from src.runtime.policy_qa.fee_decomposition.billing_boundary import (
    build_billing_boundary_payload,
)
from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
from src.runtime.policy_qa.fee_decomposition.model_explanation import (
    QuestionTarget, build_model_input, render_evidence_answer, resolve_question_target)
from src.runtime.policy_qa.fee_decomposition.payment_condition_context import (
    PaymentConditionContext,
)
from src.runtime.policy_qa.public_contract import DecompositionUncertaintyView
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_model_explanation import _public_0408

BANNED = ("符合", "不符合", "违规", "超收", "加收")


def _ctx(bz: str | None, source: str = "诊疗目录", status: str = "unique") -> PaymentConditionContext:
    return PaymentConditionContext(bz=bz, catalog_source=source, catalog_status=status)


def _item(line_id: str, name: str, fee: str, *, item_type: str = "诊疗项目",
          ctx: PaymentConditionContext | None = None) -> FeeItemExplanation:
    return FeeItemExplanation(
        line_id=line_id, item_name=name, item_type=item_type,
        unit_price=fee, quantity="1.00", total_fee=fee,
        observed_in_scope=fee, observed_out_scope="0.00", observed_self_pay_2="0.00",
        calculated_in_scope=fee, calculated_out_scope="0.00", calculated_self_pay_2="0.00",
        status="calculated", verification_status="verified", explainable=True,
        division_method="full_in", payment_condition_context=ctx)


def _sample_a_items() -> list[FeeItemExplanation]:
    """样例 A 关键行（011100030X260417004975 的 8/10/14/15/16/17/26 行及代表检验行）。"""
    return [
        _item("1", "活检钳", "82.00", item_type="耗材"),
        _item("3", "消化道内镜活检术", "150.00", ctx=_ctx(
            "经皮肤造口（或经口或经肛门插入内镜），进行检查，于病变部位取活体组织，止血。"
            "不含消化内镜检查、病理学检查。此项为辅加操作项目。不同入路分别计价。")),
        _item("8", "电子胃镜检查", "410.00", ctx=_ctx(
            "润滑，消泡，插入电子胃镜，观察食管、胃、十二指肠球部及降部黏膜。"
            "出具报告。不含监护、实验室检验、活检。")),
        _item("9", "真空采血管", "1.49", item_type="耗材"),
        _item("10", "静脉采血", "6.00", ctx=_ctx(
            "核对医嘱及患者信息，评估患者，取适当体位，选择穿刺部位，皮肤消毒(直径大于5厘米)，"
            "用无菌采血针静脉穿刺并固定。除外内容：采血管。")),
        _item("11", "真空采血管", "1.27", item_type="耗材"),
        _item("12", "真空采血管", "1.27", item_type="耗材"),
        _item("14", "肛门直肠测压", "150.00", ctx=_ctx(
            "固定患者体位，经肛门插入测压导管（3个以上位点），测量肛门括约肌长度、压力。"
            "人工分析。出具报告。除外内容：导管、气囊。")),
        _item("15", "消化道动力监测", "40.00", ctx=_ctx("导管按实际消耗另收")),
        _item("16", "直肠测压导管", "850.00", item_type="耗材"),
        _item("17", "电子结肠镜检查", "460.00", ctx=_ctx(
            "将电子结肠镜自肛门插入，循腔至回盲部，观察全结肠黏膜。"
            "图文报告。不含监护、活检、病理学检查。")),
        _item("19", "总蛋白(TP)测定", "5.00", ctx=_ctx(
            "样本类型：血液、体液(不包括脑脊液)。样本采集、签收、处理，定标和质控，检测样本。")),
        _item("20", "白蛋白(Alb)测定", "5.00", ctx=_ctx("样本类型：血液。样本采集、签收、处理。")),
        _item("26", "丙型肝炎抗体(抗HCV)测定", "60.00", ctx=_ctx(
            "包含确认试验。样本类型：血液。样本采集、签收、处理，加免疫试剂，温育，检测，质控。")),
    ]


def _sample_b_items() -> list[FeeItemExplanation]:
    """样例 B 全部 3 行（011100030X260417003528）。"""
    return [
        _item("0", "内镜色素检查", "200.00", ctx=_ctx(
            "内镜下于病变部位喷洒染色药物或电子染色，以暴露病变部位黏膜及边界。"
            "图文报告。不含监护、内镜检查。除外内容：导管、导丝、引流管、套扎器（圈）、"
            "穿刺针、组织夹、细胞刷、异物钳、活检钳、一次性喷洒管。")),
        _item("1", "活检组织病理诊断", "150.00", ctx=_ctx(
            "由活检钳采集的各种组织、器官的标本，经过甲醛固定，由初检医师进行大体标本检查和取材。"
            "含上述技术过程中所产生的废液、废物的处理。"
            "不含除苏木素-伊红(HE)、巴氏染色以外的特殊染色及分子病理学诊断。"
            "以2个蜡块为基价，每增加1个蜡块加收不超过30元。")),
        _item("2", "圈套器（息肉勒除器）", "350.00", item_type="耗材"),
    ]


def _all_sentences(payload) -> list[str]:
    out = [line.sentence for line in payload.line_explanations]
    for source in payload.source_explanations:
        out.extend(source.sentences)
    return out


# ── 样例 A：匹配与去重 ─────────────────────────────────────────

def test_catheter_explained_once_with_two_citations():
    payload = build_billing_boundary_payload(_sample_a_items(), focus={10})
    lines = [line for line in payload.line_explanations if line.display_no == 10]
    assert len(lines) == 1
    link = lines[0]
    assert link.total_fee == "850.00"
    fragments = {citation.fragment for citation in link.citations}
    assert "导管按实际消耗另收" in fragments
    assert "除外内容：导管、气囊" in fragments
    assert {citation.display_no for citation in link.citations} == {8, 9}


def test_blood_tube_lines_each_explained_once():
    payload = build_billing_boundary_payload(_sample_a_items(), focus=None)
    by_target = {line.display_no: line for line in payload.line_explanations}
    for display_no, fee in ((4, "1.49"), (6, "1.27"), (7, "1.27")):
        assert display_no in by_target
        link = by_target[display_no]
        assert len(link.citations) == 1
        assert link.citations[0].display_no == 5
        assert link.citations[0].fragment == "除外内容：采血管"


def test_biopsy_matches_procedure_not_forceps_material():
    """「不含活检」解释活检术（诊疗），不误配耗材活检钳。"""
    payload = build_billing_boundary_payload(_sample_a_items(), focus=None)
    by_target = {line.display_no: line for line in payload.line_explanations}
    assert 1 not in by_target  # 活检钳不被「不含活检」误配
    assert 2 in by_target
    sources = {citation.display_no for citation in by_target[2].citations}
    assert sources == {3, 11}  # 胃镜与肠镜的「不含…活检…」


def test_lab_lines_explained_by_gastroscope_clue():
    payload = build_billing_boundary_payload(_sample_a_items(), focus=None)
    by_target = {line.display_no: line for line in payload.line_explanations}
    for display_no in (12, 13):
        assert display_no in by_target
        fragments = {citation.fragment for citation in by_target[display_no].citations}
        assert "不含监护、实验室检验、活检" in fragments


def test_hcv_included_confirmatory_test():
    payload = build_billing_boundary_payload(_sample_a_items(), focus={14})
    # 第14行自身也是检验项目（胃镜「不含实验室检验」的被解释行），回看链接允许存在；
    # 本用例验收的是「包含确认试验」的前看解释。
    sources = [source for source in payload.source_explanations if source.display_no == 14]
    assert len(sources) == 1
    text = "；".join(sources[0].sentences)
    assert "包含确认试验" in text
    assert "不再另收" in text or "不另收" in text


# ── 样例 B：圈套器 + 禁讲 ──────────────────────────────────────

def test_sample_b_snare_explained_by_endoscopy_clue():
    payload = build_billing_boundary_payload(_sample_b_items(), focus=None)
    by_target = {line.display_no: line for line in payload.line_explanations}
    assert set(by_target) == {3}
    link = by_target[3]
    assert link.total_fee == "350.00"
    assert len(link.citations) == 1
    assert link.citations[0].display_no == 1
    assert "套扎器（圈）" in link.citations[0].fragment


def test_sample_b_pathology_surcharge_never_in_patient_text():
    payload = build_billing_boundary_payload(_sample_b_items(), focus=None)
    text = "\n".join(_all_sentences(payload))
    assert "蜡块" not in text
    for word in BANNED:
        assert word not in text


def test_sample_b_no_unmatched_clue_is_spoken():
    """病理行无同单匹配行时不产生解释；色素检查「不含内镜检查」在 B 单无匹配也不讲。"""
    payload = build_billing_boundary_payload(_sample_b_items(), focus=None)
    assert all(line.display_no != 1 for line in payload.line_explanations)
    for source in payload.source_explanations:
        assert all("病理" not in sentence or "病理学检查" in sentence
                   for sentence in source.sentences)


# ── 通用纪律 ───────────────────────────────────────────────────

def test_drug_catalog_bz_never_participates():
    items = [
        _item("0", "注射用艾普拉唑钠", "52.60", item_type="药品", ctx=_ctx(
            "限消化性溃疡出血。支付标准不得高于63.00元", source="药品目录")),
        _item("1", "电子胃镜检查", "410.00", ctx=_ctx("出具报告。不含监护、实验室检验、活检。")),
    ]
    payload = build_billing_boundary_payload(items, focus=None)
    assert payload is None or _all_sentences(payload) == []


def test_non_unique_or_empty_catalog_skipped():
    items = [
        _item("0", "电子胃镜检查", "410.00",
              ctx=_ctx("出具报告。不含活检。", status="ambiguous")),
        _item("1", "消化道内镜活检术", "150.00"),
        _item("2", "无痛胃镜", "300.00", ctx=_ctx(None)),
    ]
    payload = build_billing_boundary_payload(items, focus=None)
    assert payload is None or _all_sentences(payload) == []


def test_included_clue_silent_when_same_bill_line_exists():
    """同单确有「确认试验」收费行时，不得讲「不再另收」。"""
    items = [
        _item("0", "丙型肝炎抗体(抗HCV)测定", "60.00", ctx=_ctx("包含确认试验。样本类型：血液。")),
        _item("1", "丙肝确认试验", "80.00"),
    ]
    payload = build_billing_boundary_payload(items, focus=None)
    text = "\n".join(_all_sentences(payload)) if payload else ""
    assert "不再另收" not in text and "不另收" not in text


def test_no_banned_words_in_any_sample_a_sentence():
    payload = build_billing_boundary_payload(_sample_a_items(), focus=None)
    text = "\n".join(_all_sentences(payload))
    for word in BANNED:
        assert word not in text


def test_focus_selects_only_relevant_explanations():
    payload = build_billing_boundary_payload(_sample_a_items(), focus={3})
    assert payload is not None
    # 第3行胃镜同时是活检术「不含消化内镜检查」的对上目标，回看链接合法存在。
    assert [line.display_no for line in payload.line_explanations] == [3]
    assert payload.line_explanations[0].citations[0].display_no == 2
    assert [source.display_no for source in payload.source_explanations] == [3]
    text = "；".join(payload.source_explanations[0].sentences)
    assert "不含监护、实验室检验、活检" in text
    # 只问胃镜时引用原文内涵，不把没问到的检验行开成清单。
    assert "测定" not in text
    assert "项，如" not in text
    assert payload.source_explanations[0].matches[0].targets == []
    assert "病理" not in text  # 对不上的不讲


def test_sentences_cite_line_and_fragment():
    payload = build_billing_boundary_payload(_sample_a_items(), focus={10})
    sentence = payload.line_explanations[0].sentence
    assert "第10行" in sentence and "直肠测压导管" in sentence and "850.00" in sentence
    assert "导管按实际消耗另收" in sentence
    assert "除外内容：导管、气囊" in sentence


# ── 接入费用解释链路（build_model_input / render_evidence_answer / explain_decomposition）──


def _public_with_items(items):
    public = _public_0408()
    return public.model_copy(update={"fee_items": items})


def _deterministic(monkeypatch):
    monkeypatch.setenv("FEE_EXPLANATION_MODE", "deterministic")


def test_line_question_delivers_backward_boundary(monkeypatch):
    _deterministic(monkeypatch)
    public = _public_with_items(_sample_a_items())
    result = explanation.explain_decomposition(public, "第10行直肠测压导管为什么单独收费")
    assert "850.00" in result.answer
    assert "导管按实际消耗另收" in result.answer
    assert "除外内容：导管、气囊" in result.answer
    for word in BANNED:
        assert word not in result.answer


def test_source_question_delivers_forward_boundary(monkeypatch):
    _deterministic(monkeypatch)
    public = _public_with_items(_sample_a_items())
    question = "第3行电子胃镜检查这项含什么"
    payload = build_model_input(public, question)
    assert payload.billed_items == []
    result = explanation.explain_decomposition(public, question)
    assert "不含监护、实验室检验、活检" in result.answer
    assert "活检术" in result.answer
    assert "电子胃镜检查" in result.answer
    # 只讲所问费用行和原文内涵，不列同单其余项目和汇总金额。
    assert "测定" not in result.answer
    assert "项，如" not in result.answer
    assert "本单其余各项金额如下" not in result.answer
    assert "费用总金额" not in result.answer
    # 样例A无病理行：不得点名病理行单独计费（引用原文片段中出现「病理学检查」属对得上）。
    assert "病理诊断" not in result.answer
    assert "病理" not in result.answer.replace("病理学检查」", "")


def test_billing_inventory_phrase_is_rejected_for_boundary_questions():
    """模型若补写汇总清单，事实校验要打回；汇总金额问题本身不受这条限制。"""
    public = _public_with_items(_sample_a_items())
    boundary = build_model_input(public, "电子胃镜检查这项含什么")
    rejected = explanation._billing_inventory_issues(
        "电子胃镜检查的目录内涵注明「不含监护、实验室检验、活检」。"
        "本单其余各项金额如下：费用总金额 410.00 元。", boundary)
    assert rejected
    summary = build_model_input(public, "费用总金额是多少")
    assert explanation._billing_inventory_issues("费用总金额 3435.00 元。", summary) == []


def test_hcv_question_says_confirmatory_test_included(monkeypatch):
    _deterministic(monkeypatch)
    public = _public_with_items(_sample_a_items())
    result = explanation.explain_decomposition(public, "第14行丙型肝炎抗体测定这项含什么")
    assert "包含确认试验" in result.answer
    assert "不再另收" in result.answer


def test_sample_b_window_output_mentions_snare_not_surcharge(monkeypatch):
    _deterministic(monkeypatch)
    public = _public_with_items(_sample_b_items())
    result = explanation.explain_decomposition(public, "第3行圈套器为什么单独收费")
    assert "350.00" in result.answer
    assert "套扎器（圈）" in result.answer
    assert "蜡块" not in result.answer
    for word in BANNED:
        assert word not in result.answer


def test_whole_settlement_loads_all_boundaries():
    public = _public_with_items(_sample_a_items())
    payload = build_model_input(public, "这张单为什么拆出这么多收费项目",
                                QuestionTarget(kind="whole_settlement"))
    assert payload.billing_boundaries is not None
    targets = {line.display_no for line in payload.billing_boundaries.line_explanations}
    assert {2, 4, 6, 7, 10, 12, 13, 14} <= targets or {2, 4, 6, 7, 10} <= targets
    sources = {source.display_no for source in payload.billing_boundaries.source_explanations}
    assert 14 in sources  # 抗HCV「包含确认试验」
    rendered = render_evidence_answer(payload)
    assert rendered is not None
    for word in BANNED:
        assert word not in rendered.body


def test_summary_field_question_skips_boundaries():
    public = _public_with_items(_sample_a_items())
    payload = build_model_input(public, "现金支付是多少")
    assert payload.billing_boundaries is None


_RETIRE_GAP = "缺少退休补充保险纳入起始日期，不默认已纳入。"


def _with_retire_gap(public):
    """整单里挂上退休补充缺纳入日期：内涵问题不得把它当成回答的一部分。"""
    fee_all = next(field for field in public.fields if field.field_code == "T_FeeAll")
    retire = fee_all.model_copy(update={
        "field_code": "T_BCPay", "label": "退休补充保险补助",
        "observed_amount": "383.22", "calculated_amount": None,
        "explainable": False, "calculation_refs": [], "explanation_reason": None,
    })
    fields = [field for field in public.fields if field.field_code != "T_BCPay"]
    fields.append(retire)
    return public.model_copy(update={
        "fields": fields,
        "uncertainties": [DecompositionUncertaintyView(
            code="SUPPLEMENT_ENROLL_DATE_MISSING", message=_RETIRE_GAP,
            id="u.rsup.enroll", affected_fields=["T_BCPay"])],
    })


def test_paren_lab_name_stays_on_its_billing_boundary(monkeypatch):
    """「总蛋白测定为什么还单独收费」：括号缩写不影响定位到总蛋白行。

    这是收费项目内涵解释，不展开其余汇总金额，也不把退休补充缺证带进尚待核实。
    """
    _deterministic(monkeypatch)
    public = _with_retire_gap(_public_with_items(_sample_a_items()))
    question = "总蛋白测定为什么还单独收费？"
    target = resolve_question_target(public, question)
    assert target.kind == "fee_line"
    assert public.fee_items[target.display_no - 1].item_name == "总蛋白(TP)测定"
    payload = build_model_input(public, question)
    assert payload.target_evidence == []
    assert [field.field_code for field in payload.decomposition.fields] == []
    assert payload.billing_boundaries is not None
    assert [line.display_no for line in payload.billing_boundaries.line_explanations] == [
        target.display_no]
    result = explanation.explain_decomposition(public, question)
    assert "总蛋白(TP)测定" in result.answer
    assert "不含监护、实验室检验、活检" in result.answer
    assert "费用总金额" not in result.answer
    assert "3435.00" not in result.answer
    assert "383.22" not in result.answer
    assert _RETIRE_GAP not in result.answer
    assert _RETIRE_GAP not in result.uncertainties


def test_spoken_colonoscopy_and_biopsy_stay_on_that_boundary(monkeypatch):
    """两字口语「肠镜」「活检」对上全名；活检术和活检钳都可以解释。

    不把胃镜算进来，也不展开整单其余金额和退休补充缺证。
    """
    _deterministic(monkeypatch)
    public = _with_retire_gap(_public_with_items(_sample_a_items()))
    question = "肠镜已经收了，活检为什么还要单收"
    target = resolve_question_target(public, question)
    assert target.kind == "multi_line"
    names = {public.fee_items[ref.display_no - 1].item_name for ref in target.lines}
    assert names == {"电子结肠镜检查", "消化道内镜活检术", "活检钳"}
    payload = build_model_input(public, question)
    # 模型资料里不能再有整单汇总金额和退休补充缺证，否则会写进正文和「尚待核实」。
    assert payload.target_evidence == []
    assert payload.decomposition.fields == []
    assert payload.decomposition.settlement_facts is None
    assert payload.decomposition.uncertainties == []
    model_blob = payload.model_dump_json()
    assert "费用总金额" not in model_blob
    assert "3435.00" not in model_blob
    assert "不默认已纳入" not in model_blob
    result = explanation.explain_decomposition(public, question)
    assert "电子结肠镜检查" in result.answer
    assert "消化道内镜活检术" in result.answer
    assert "不含监护、活检、病理学检查" in result.answer
    assert "电子胃镜检查" not in result.answer
    assert "活检钳" in result.answer
    assert "费用总金额" not in result.answer
    assert "3435.00" not in result.answer
    assert "蜡块" not in result.answer
    assert _RETIRE_GAP not in result.answer
    assert _RETIRE_GAP not in result.uncertainties
    for word in BANNED:
        assert word not in result.answer


def test_billing_scope_paraphrases_stay_on_the_named_line(monkeypatch):
    """收费项目内涵 / 为何还要单收是同一类，不因换一种说法就退回整单。"""
    _deterministic(monkeypatch)
    public = _with_retire_gap(_public_with_items(_sample_a_items()))

    protein = explanation.explain_decomposition(public, "总蛋白为什么还要单收")
    assert "总蛋白(TP)测定" in protein.answer
    assert "白蛋白" not in protein.answer
    assert "费用总金额" not in protein.answer
    assert "3435.00" not in protein.answer
    assert _RETIRE_GAP not in protein.uncertainties

    albumin = explanation.explain_decomposition(public, "白蛋白怎么还单独收")
    assert "白蛋白(Alb)测定" in albumin.answer
    assert "总蛋白" not in albumin.answer
    assert "3435.00" not in albumin.answer
    assert _RETIRE_GAP not in albumin.uncertainties

    tubes = explanation.explain_decomposition(public, "采血管为何还要单收")
    assert "真空采血管" in tubes.answer
    assert "除外内容：采血管" in tubes.answer
    assert "电子胃镜检查" not in tubes.answer
    assert "3435.00" not in tubes.answer
    assert _RETIRE_GAP not in tubes.uncertainties

    scope = explanation.explain_decomposition(public, "采血管这项的内涵是什么")
    assert "真空采血管" in scope.answer
    assert "除外内容：采血管" in scope.answer
    assert "费用总金额" not in scope.answer
    assert _RETIRE_GAP not in scope.uncertainties


def test_other_separate_charge_wording_drops_the_bill_summary(monkeypatch):
    """「另外收费」和「单独收费」是同一类，模型资料里同样不能有整单金额。"""
    _deterministic(monkeypatch)
    public = _with_retire_gap(_public_with_items(_sample_b_items()))
    question = "圈套器为什么另外收费"
    payload = build_model_input(public, question)
    assert payload.decomposition.settlement_facts is None
    assert payload.decomposition.uncertainties == []
    result = explanation.explain_decomposition(public, question)
    assert "圈套器" in result.answer
    assert "套扎器（圈）" in result.answer
    assert "3435.00" not in result.answer
    assert _RETIRE_GAP not in result.uncertainties


def test_summary_amount_question_is_not_a_billing_boundary_question():
    """问汇总金额为什么还要收，仍解释该金额，不改判成收费边界。"""
    public = _public_0408()
    target = resolve_question_target(public, "个人支付为什么还要收")
    assert target.kind == "summary_fields"


def test_forceps_full_name_does_not_pull_the_biopsy_procedure():
    """问句已经写出「活检钳」时，不因短称「活检」再牵连活检术。"""
    public = _public_with_items(_sample_a_items())
    target = resolve_question_target(public, "活检钳这笔多少钱")
    assert target.kind == "fee_line"
    assert public.fee_items[target.display_no - 1].item_name == "活检钳"


def test_unnamed_billing_boundary_question_skips_other_amounts(monkeypatch):
    """没点名项目、只问为什么还单独收费：只交付收费边界，不逐项解释整单金额。"""
    _deterministic(monkeypatch)
    public = _with_retire_gap(_public_with_items(_sample_a_items()))
    question = "这些化验为什么还单独收费？"
    payload = build_model_input(public, question)
    assert payload.target_evidence == []
    assert payload.billing_boundaries is not None
    result = explanation.explain_decomposition(public, question)
    assert "不含监护、实验室检验、活检" in result.answer
    assert "费用总金额" not in result.answer
    assert "3435.00" not in result.answer
    assert _RETIRE_GAP not in result.uncertainties


def test_enroll_date_gap_is_not_shown_even_for_whole_bill(monkeypatch):
    """整单问题仍解释汇总金额；退休补充纳入日期缺失不进正文，也不进尚待核实。"""
    _deterministic(monkeypatch)
    public = _with_retire_gap(_public_with_items(_sample_a_items()))
    result = explanation.explain_decomposition(public, "解释这笔结算")
    assert "费用总金额" in result.answer
    assert "3435.00" in result.answer
    assert _RETIRE_GAP not in result.answer
    assert _RETIRE_GAP not in result.uncertainties


def test_lab_item_names_not_mangled_by_sanitizer(monkeypatch):
    """全大写检验缩写（抗HCV/ALT 等）是项目名一部分，不得被内部编码消毒改写。"""
    _deterministic(monkeypatch)
    public = _public_with_items(_sample_a_items())
    result = explanation.explain_decomposition(public, "第14行丙型肝炎抗体测定这项含什么")
    assert "抗HCV" in result.answer
    assert "结算数据字段" not in result.answer
