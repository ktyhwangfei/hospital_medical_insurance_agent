# -*- coding: utf-8 -*-
"""Issue #33 E2E: broad 路由/拒答机制实测
case1: 上海在职职工门诊报销比例 -> 异地拒答（含"不适用/未收录"）
case2: 在职职工三级医院门诊 2万以下报销比例 -> 结构化引用（rule_id/文号）
case3: 住院费用怎么报销 -> 住院范围外拒答
case4: 2023已废止年度 -> 版本/时间拒答
"""
import sys, os, time, json
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:3160/policy-qa"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(OUT, exist_ok=True)

CASES = [
    ("case1_shanghai_region", "上海在职职工门诊报销比例",
     ["不适用", "未收录"], "异地拒答"),
    ("case2_structured_ratio", "在职职工三级医院门诊 2万以下报销比例",
     None, "结构化引用"),  # 期望非拒答 + 证据
    ("case3_inpatient_scope", "住院费用怎么报销",
     ["住院范围", "暂未收录", "未收录"], "住院范围外拒答"),
    ("case4_time_version", "2023年已废止的门诊报销政策是什么",
     ["未收录该年度", "现行政策未收录", "未收录该年度或版本"], "版本/时间拒答"),
]

def main():
    results = {}
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width':1440,'height':900})
        pg.goto(BASE, timeout=30000)
        pg.wait_for_timeout(3000)
        pg.screenshot(path=os.path.join(OUT, "00_initial.png"))
        # fresh session
        pg.fill('textarea', '@新会话')
        pg.click('button:has-text("发送")')
        pg.wait_for_timeout(2000)
        for name, q, expect_terms, desc in CASES:
            log = []
            try:
                pg.fill('textarea', q)
                pg.click('button:has-text("发送")')
                # wait user message bubble + response settle
                pg.wait_for_timeout(40000)
                body = pg.eval_on_selector('body', 'e => e.innerText')
                pg.screenshot(path=os.path.join(OUT, f"{name}.png"))
                with open(os.path.join(OUT, f"{name}.body.txt"), "w", encoding="utf-8") as f:
                    f.write(body)
                ok = False
                if expect_terms:
                    hits = [t for t in expect_terms if t in body]
                    ok = len(hits) > 0
                    log.append(f"assert refuse terms={expect_terms} hits={hits} => {ok}")
                else:
                    # structured: should have 政策依据/引用块 and NOT refusal message
                    refuse_sigs = ["不适用", "未收录", "无法回答"]
                    refused = any(s in body for s in refuse_sigs)
                    has_evidence = ("政策依据" in body or "引用" in body or "依据" in body)
                    ok = (not refused) and has_evidence
                    log.append(f"assert structured: refused={refused} has_evidence={has_evidence} => {ok}")
                results[name] = {"ok": ok, "desc": desc, "log": log}
                print(f"[{name}] {'PASS' if ok else 'FAIL'} :: {' | '.join(log)}")
            except Exception as e:
                results[name] = {"ok": False, "desc": desc, "log": [f"EXC: {e}"]}
                print(f"[{name}] FAIL :: EXC: {e}")
            # fresh session between cases
            try:
                pg.fill('textarea', '@新会话')
                pg.click('button:has-text("发送")')
                pg.wait_for_timeout(1500)
            except Exception:
                pass
        b.close()

    summary_path = os.path.join(OUT, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    all_ok = all(r["ok"] for r in results.values())
    print("=" * 50)
    print("SUMMARY:", "ALL GREEN" if all_ok else "SOME FAIL", "->", summary_path)
    sys.exit(0 if all_ok else 1)

if __name__ == "__main__":
    main()

# ── case2 补充：后端结构化证据断言（rule_id/文号，设计契约：公开 citations 不含内部血缘）──
def verify_structured_evidence():
    """路由层直查：结构化证据必须携带 rule_id / policy_version / policy_id 溯源链。"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    from src.runtime.api.policy_qa_routes import _router_structured_retrieve
    from src.runtime.policy_qa.broad_query_router import route_broad_question
    d = route_broad_question(
        "在职职工三级医院门诊 2万以下报销比例",
        structured_retrieve=_router_structured_retrieve,
    )
    ev = d.evidence
    assert d.route == "structured" and ev, "router 未返回结构化证据"
    with_rule = sum(1 for e in ev if getattr(e, "rule_id", ""))
    with_ver = sum(1 for e in ev if getattr(e, "policy_version", ""))
    ok = len(ev) > 0 and with_rule == len(ev) and with_ver == len(ev)
    log = (
        f"route={d.route} landing={d.landing} evidence={len(ev)} "
        f"rule_id_full={with_rule}/{len(ev)} policy_version_full={with_ver}/{len(ev)} "
        f"sample_rule_id={ev[0].rule_id if ev else '-'} "
        f"sample_version={ev[0].policy_version if ev else '-'}"
    )
    with open(os.path.join(OUT, "case2_structured_evidence.txt"), "w", encoding="utf-8") as f:
        f.write(log + "\n")
        for e in ev[:5]:
            f.write(f"  rule_id={e.rule_id} version={e.policy_version} type={e.rule_type} src={e.source_text[:40]}\n")
    print(f"[case2_evidence] {'PASS' if ok else 'FAIL'} :: {log}")
    return ok

if __name__ == "__main__":
    ui_ok = main()
    ev_ok = verify_structured_evidence()
    sys.exit(0 if (ui_ok and ev_ok) else 1)
