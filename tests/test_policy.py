"""策略状态机的可执行不变量测试。

不用 pytest，直接 `python3 tests/test_policy.py` 就能跑 ——
项目在写文档阶段不该引入依赖。

每个 test_* 对应 DESIGN.md §3 的一条不变量或 §6 的一条失效模式。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from socratic_tutor.policy import (  # noqa: E402
    CONSECUTIVE_FAILURES_TO_ESCALATE,
    DIRECT_REQUEST_LIMIT,
    Level,
    Misconception,
    SessionState,
    next_turn,
    on_student_failure,
)


def test_first_contact_is_never_an_answer():
    """I1：开场第一句不能是答案。"""
    s = SessionState()
    turn = next_turn(s, student_solved=False)
    assert turn.level == Level.L1_METACOGNITIVE, turn
    assert turn.over_help is False


def test_solution_blocked_without_prior_hint():
    """I1 + I3：第一次索要只给方法，不给完整解答。"""
    s = SessionState()
    turn = next_turn(s, student_solved=False, direct_request=True)
    assert turn.level == Level.L4_METHOD, turn
    # 但这是一次 over_help：学生没走 L1/L2 就拿到了方法级提示，必须记账
    assert turn.over_help is True


def test_second_direct_request_releases_l5_and_counts():
    """I3：连续两次索要才放行 L5，且两次都计 over_help。"""
    s = SessionState()
    next_turn(s, student_solved=False, direct_request=True)
    turn = next_turn(s, student_solved=False, direct_request=True)
    assert turn.level == Level.L5_SOLUTION, turn
    assert turn.over_help is True
    assert s.over_help_count == 2


def test_direct_request_counter_resets_on_real_work():
    """连击计数必须被真实作答打断，否则学生会攒两次"隔空"索要换答案。"""
    s = SessionState()
    next_turn(s, student_solved=False, direct_request=True)  # count=1
    next_turn(s, student_solved=False, direct_request=False)  # reset
    turn = next_turn(s, student_solved=False, direct_request=True)  # count=1 again
    assert turn.level == Level.L4_METHOD, f"不应二次索要即放行，实际 {turn.level}"


def test_escalates_one_level_at_a_time():
    """I2：失败次数未达阈值不升级；达到后一次只升一级。"""
    s = SessionState()
    next_turn(s, student_solved=False)  # L1
    assert s.max_level_given == 1

    on_student_failure(s)
    turn = next_turn(s, student_solved=False)
    assert turn.level == Level.L1_METACOGNITIVE, "单次失败不应升级"

    for _ in range(CONSECUTIVE_FAILURES_TO_ESCALATE):
        on_student_failure(s)
    turn = next_turn(s, student_solved=False)
    assert turn.level == Level.L2_POINT, f"应恰好升到 L2，实际 {turn.level}"


def test_low_confidence_misconception_degrades_to_l2():
    """§6.1：分类器判不准时不指名错误类型，宁可少说。"""
    s = SessionState(max_level_given=2, hints_given=2, failures_at_level=2)
    weak = Misconception(taxonomy_id="sign_error", confidence=0.31, evidence_span="x-2=5")
    turn = next_turn(s, student_solved=False, misconception=weak)
    assert turn.level == Level.L2_POINT, turn


def test_high_confidence_misconception_allows_l3():
    s = SessionState(max_level_given=2, hints_given=2, failures_at_level=2)
    strong = Misconception(taxonomy_id="sign_error", confidence=0.88, evidence_span="x-2=5")
    turn = next_turn(s, student_solved=False, misconception=strong)
    assert turn.level == Level.L3_NAME_ERROR, turn


def test_never_skips_l5_gate_via_ladder():
    """I1 的强化：阶梯一路升到底，也不得在无提示时直接 L5。"""
    s = SessionState()
    for _ in range(40):
        on_student_failure(s)
        turn = next_turn(s, student_solved=False, direct_request=False)
        if turn.level == Level.L5_SOLUTION:
            assert s.hints_given > 0, "ladder 不得绕过 I1"
    assert s.max_level_given >= 4, "足够多的失败应能升到方法级"


def test_ladder_to_l5_is_not_over_help():
    """正常阶梯即使升到 L5，学生一路都在动手，不计 over_help。"""
    s = SessionState()
    next_turn(s, student_solved=False)  # L1
    for _ in range(12):
        on_student_failure(s)
        next_turn(s, student_solved=False)
    assert s.max_level_given == Level.L5_SOLUTION, s.max_level_given
    assert s.over_help_count == 0, f"正常阶梯不应计 over_help，实际 {s.over_help_count}"


def test_solved_releases():
    s = SessionState(max_level_given=2, hints_given=2)
    turn = next_turn(s, student_solved=True)
    assert turn.is_release and turn.level is None


def test_over_help_rate_definition():
    """over_help_rate = over_help 回合数 / 全部提示回合数。"""
    s = SessionState()
    next_turn(s, student_solved=False)  # L1 正常
    assert s.over_help_rate == 0.0
    next_turn(s, student_solved=False, direct_request=True)  # L4 over_help
    assert s.over_help_rate_num == 1
    assert s.over_help_rate_denom == 2
    assert abs(s.over_help_rate - 0.5) < 1e-9


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
