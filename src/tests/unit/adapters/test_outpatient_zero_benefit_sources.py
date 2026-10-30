"""原始待遇码始终读取，资格派生开关仅控制正向资格推导。"""
from src.adapters.data_supply.record_query_mappings import RecordQueryMapping
from src.tests.unit.adapters.test_outpatient_decomposition_queries import _build_direct, _trade_row_full


def test_zero_source_codes_are_read_with_derivation_disabled():
    snapshot, _ = _build_direct(_trade_row_full(
        p_official=0, p_officialcode='0', p_jclevel=0))
    assert snapshot.person.public_medical_flag == '0'
    assert snapshot.person.public_medical_treatment_code == '0'
    assert snapshot.person.military_disability_level_code == '0'
    assert snapshot.person.is_disabled_veteran is None
    assert snapshot.person.public_medical_eligible is None


def test_missing_source_codes_are_not_filled_with_zero():
    row = _trade_row_full()
    for key in ('p_official', 'p_officialcode', 'p_jclevel'):
        row.pop(key)
    snapshot, _ = _build_direct(row)
    assert snapshot.person.public_medical_flag is None
    assert snapshot.person.public_medical_treatment_code is None
    assert snapshot.person.military_disability_level_code is None


def test_source_codes_follow_custom_mapping_and_lowercase_row_keys():
    mapping = RecordQueryMapping(columns={
        'op_official': 'BenefitFlag', 'op_official_code': 'BenefitKind', 'op_jc_level': 'DisabilityLevel'})
    snapshot, _ = _build_direct(_trade_row_full(
        benefitflag='0', benefitkind='0', disabilitylevel='0'), mapping=mapping)
    assert snapshot.person.public_medical_flag == '0'
    assert snapshot.person.public_medical_treatment_code == '0'
    assert snapshot.person.military_disability_level_code == '0'
