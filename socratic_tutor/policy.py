"""Socratic Tutor — hint-gating policy.

核心不变量（与 DESIGN.md §3 对应）：

    I1  在给出完整解答（L5）之前，必须至少尝试过一次提示。
    I2  每次学生回合最多升一级，不允许跳级（除非学生显式索要答案）。
    I3  学生显式索要答案时，最多连续两次才放行 L5。
    I4  升级必须由「同一层级连续失败 N 次」触发，不能由模型自行判断"该给答案了"。
    I5  任何 L4/L5 的产生只要发生在学生走完 L1/L2 之前，都必须计入 over_help。

本模块只负责策略：此刻允许说什么、不允许说什么。它不调用任何模型，
因此可以用纯状态机做单元测试 —— 这是把"模型幻觉"和"教学策略错误"
分开排查的前提。

术语
----
L1..L5      : hint ladder 的五级，见 Level 枚举。
misconception: 误解分类器输出，见 Misconception。
over_help   : 在学生没有先经历低强度提示的情况下，直接给出方法或答案。
              这是本项目最关心的一类失败 —— 它让系统退化成答案机。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

# ---------------------------------------------------------------- constants

CONSECUTIVE_FAILURES_TO_ESCALATE = 2  # 同层级连续失败次数阈值
MIN_HINTS_BEFORE_SOLUTION = 1  # I1：给答案前至少 1 次提示
DIRECT_REQUEST_LIMIT = 2  # I3：连续直要两次才放行完整解答
OVER_HELP_LEVEL = 4  # 达到此级别，且学生尚未在提示下动过手，即记为 over_help


class Level(IntEnum):
    """Hints 的强度梯度。数值越大，泄露的信息越多。"""

    L1_METACOGNITIVE = 1  # "你这一步用到了什么假设？" —— 不给方向
    L2_POINT = 2  # 指出出错的步骤，不解释原因
    L3_NAME_ERROR = 3  # 说出错误类型（符号/单位/概念），不给正确做法
    L4_METHOD = 4  # 给出方法，不含本题数值
    L5_SOLUTION = 5  # 完整解答 + 复盘


@dataclass(frozen=True)
class Misconception:
    """误解分类器的一次判定。confidence 低于阈值时策略应降级为 L2。"""

    taxonomy_id: str
    confidence: float
    evidence_span: str


@dataclass
class Turn:
    """一次决策的产出，直接用于渲染给学生的消息与写日志。"""

    level: Optional[Level]
    reason: str
    over_help: bool = False
    is_release: bool = False


@dataclass
class SessionState:
    """一次答疑会话的全部可变状态。可 JSON 序列化落库。"""

    failures_at_level: int = 0
    max_level_given: int = 0
    hints_given: int = 0
    guided_attempts: int = 0  # 学生在有提示的情况下真正作答的次数
    direct_requests: int = 0
    over_help_count: int = 0
    history: list[dict] = field(default_factory=list)

    def record(self, turn: Turn) -> None:
        if turn.level is not None:
            self.hints_given += 1
            self.max_level_given = max(self.max_level_given, int(turn.level))
        if turn.over_help:
            self.over_help_count += 1
        self.history.append(
            {
                "level": int(turn.level) if turn.level else None,
                "reason": turn.reason,
                "over_help": turn.over_help,
                "is_release": turn.is_release,
            }
        )

    @property
    def over_help_rate_num(self) -> int:
        """over_help_rate 的分子：被 over_help 的回合数。"""
        return self.over_help_count

    @property
    def over_help_rate_denom(self) -> int:
        """分母：全部非 release 提示回合数。"""
        return sum(1 for h in self.history if h["level"] is not None)

    @property
    def over_help_rate(self) -> float:
        d = self.over_help_rate_denom
        return self.over_help_count / d if d else 0.0


def _gate_solution(state: SessionState) -> bool:
    """I1 的守卫：是否已经具备给完整解答的资格。"""
    return state.hints_given >= MIN_HINTS_BEFORE_SOLUTION


def _emit(state: SessionState, turn: Turn) -> Turn:
    """统一出口：每次决策必须落账，避免调用方漏记导致指标失真。"""
    state.record(turn)
    return turn


def _classify_over_help(state: SessionState, level: Level) -> bool:
    """I5：给出方法或答案时，学生此前是否真的在提示下尝试过。

    判据不是"发过几条提示"，而是"学生有没有在提示之后动过手" ——
    学生拿到一条 L1 就立刻说"直接告诉我答案"，仍然属于 over_help：
    这正是我们要测的"答案机化"路径，不能因为中间发过一条提示就不计。
    """
    return int(level) >= OVER_HELP_LEVEL and state.guided_attempts == 0


def next_turn(
    state: SessionState,
    *,
    student_solved: bool,
    direct_request: bool = False,
    misconception: Optional[Misconception] = None,
    min_confidence: float = 0.55,
) -> Turn:
    """决定这一回合系统可以做什么。

    参数
    ----
    student_solved : 学生这一步是否已正确。True 时直接 release，不再追问。
    direct_request : 学生是否显式要求直接给答案（"告诉我答案"）。
    misconception  : 分类器输出；confidence 不足时不用于选层级，只做日志。
    min_confidence : 低于此值视为判不准，降级到 L2（指出位置），不指名错误类型。
    """
    # --- 已解决：结束本次追问，交给下一题 -----------------------------
    if student_solved:
        return _emit(state, Turn(level=None, reason="solved_by_student", is_release=True))

    # --- 学生显式索要答案 -------------------------------------------
    if direct_request:
        state.direct_requests += 1
        if state.direct_requests >= DIRECT_REQUEST_LIMIT:
            level = Level.L5_SOLUTION
            return _emit(
                state,
                Turn(
                    level=level,
                    reason="explicit_request_x2",
                    over_help=_classify_over_help(state, level),
                ),
            )
        # 第一次索要：降级为方法提示（L4），并明确告知还会再问一次
        level = Level.L4_METHOD
        return _emit(
            state,
            Turn(
                level=level,
                reason="explicit_request_x1_downgraded",
                over_help=_classify_over_help(state, level),
            ),
        )

    state.direct_requests = 0  # 非索要回合打断连击计数

    # --- 首次介入：先问，不给方向 -----------------------------------
    if state.hints_given == 0:
        state.failures_at_level = 0
        return _emit(state, Turn(level=Level.L1_METACOGNITIVE, reason="first_contact"))

    # --- 是否该升级 --------------------------------------------------
    can_escalate = state.failures_at_level >= CONSECUTIVE_FAILURES_TO_ESCALATE

    if not can_escalate:
        # 停在当前层级：重复同级提示，措辞可变，信息量不变
        current = Level(max(state.max_level_given, 1))
        return _emit(state, Turn(level=current, reason="same_level_retry"))

    # 升一级（I2：一次只升一级）
    target = min(state.max_level_given + 1, int(Level.L5_SOLUTION))

    # 分类器判不准时，不指名错误类型，退回 L2
    if (
        misconception is not None
        and misconception.confidence < min_confidence
        and target >= int(Level.L3_NAME_ERROR)
    ):
        target = int(Level.L2_POINT)

    # I1：没有走过提示就直接到 L5，一律判为策略故障，降回 L4
    if target == int(Level.L5_SOLUTION) and not _gate_solution(state):
        target = int(Level.L4_METHOD)

    state.failures_at_level = 0
    level = Level(target)
    return _emit(
        state,
        Turn(
            level=level,
            reason="escalated_within_ladder",
            over_help=_classify_over_help(state, level),
        ),
    )


def on_student_failure(state: SessionState) -> None:
    """学生这一步仍然错误时调用；负责累计升级所需的失败次数。"""
    state.failures_at_level += 1
    state.guided_attempts += 1


def on_student_progress(state: SessionState) -> None:
    """学生部分正确（推进了一步但未解出）：清零连败，但不降级。"""
    state.failures_at_level = 0
    state.guided_attempts += 1


def render(turn: Turn, misconception: Optional[Misconception] = None) -> str:
    """把策略产出渲染成提示语骨架。真实实现里由模型在约束下填充。"""
    if turn.is_release:
        return "对，就这样。说说你怎么确认这一步是对的？"
    if turn.level is None:
        return ""
    if turn.level == Level.L1_METACOGNITIVE:
        return "先别算下一步。你刚才这一步，用了什么前提？"
    if turn.level == Level.L2_POINT:
        return "问题在第二行到第三行之间。再看一遍那一步。"
    if turn.level == Level.L3_NAME_ERROR:
        name = misconception.taxonomy_id if misconception else "这一类错误"
        return f"不是算错，是这里属于「{name}」。这个类型你之前也碰到过。"
    if turn.level == Level.L4_METHOD:
        return "换个做法：先把两边化成同一种单位，再比较。具体数值你来。"
    return (
        "完整写一遍，然后我们回看：第一步做了什么、哪一步开始偏的。"
        "复盘比答案重要。"
    )
