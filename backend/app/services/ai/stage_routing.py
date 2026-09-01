"""确定性阶段路由 — 在 LLM 调用前决定阶段与工具白名单。

设计说明（为什么路由交给代码而不是模型）：
1. 流程控制是纯状态机问题：交给代码可单测、可回归（eval mock 模式全量覆盖路由分支）；
2. 模型的决策域被压缩到「阶段内选哪个工具」，跨阶段误调用由白名单拦截 +
   自省修正兜底，而不是靠模型自觉；
3. 短语表只覆盖用户「明确说出」的流程指令（"直接生成""重新做一个"），
   未命中时回落到画布状态与前端 conversation_stage 兜底（见 resolve_stage 分层）；
4. 演进路径：短语表是规则起步的正解而非妥协——如果未来自然语言变体
   超出短语覆盖，替换点只有本模块（如引入小模型意图分类器），路由协议
   （stage + allowed_tools）与下游全部不变。
"""

from .schemas import AgentStage
from .tools import TOOLS_BY_STAGE

# 显式指令短语表：key 为目标阶段，value 为触发该阶段的用户原话。
# 只做「用户显式说出的流程跳转」，不做意图猜测。
STAGE_OVERRIDE_PHRASES: dict[AgentStage, tuple[str, ...]] = {
    # 用户明确要求跳过确认直接生成
    "execute": ("直接生成", "立即生成", "不用确认", "确认，请生成", "确认生成", "开始生成"),
    # 用户在方案确认阶段要求回到方案设计
    "plan": ("修改方案", "调整方案", "换一个方案", "我想修改", "方案改成"),
    # 画布已有内容时，用户明确要求推倒重来
    "discover": ("新页面", "新海报", "全新", "重新生成", "重做", "替换画布", "重新设计"),
    # 画布已有内容时，用户对现有组件提出修改指令
    "edit": ("修改", "改成", "调整", "删除", "移动", "放大", "缩小", "加粗", "颜色", "换图", "替换文字"),
}

# 确认阶段的方案修改短语（requested_stage == confirm 时使用）
PLAN_REVISION_PHRASES = STAGE_OVERRIDE_PHRASES["plan"]


def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def resolve_stage(
    prompt: str,
    components: list[dict],
    requested_stage: str | None = None,
) -> AgentStage:
    """确定性规则决定阶段，按优先级分层：

    1. 显式生成指令 → execute（最高优先级，任何状态下生效）
    2. 确认阶段：方案修改短语 → plan，否则停留在 confirm
    3. 画布非空：重做短语 → discover；编辑短语或无明确指令 → edit
       （画布非空时默认 edit 是有意的：编辑是最高频操作，
       误入 discover 会浪费用户多轮选择）
    4. 前端透传的 conversation_stage（上一轮 agent 自己声明的 nextStage）
    5. 默认 discover（空画布冷启动）
    """
    text = "".join(prompt.strip().lower().split())

    if _contains_phrase(text, STAGE_OVERRIDE_PHRASES["execute"]):
        return "execute"

    if requested_stage == "confirm":
        if _contains_phrase(text, PLAN_REVISION_PHRASES):
            return "plan"
        return "confirm"

    if components:
        if _contains_phrase(text, STAGE_OVERRIDE_PHRASES["discover"]):
            return "discover"
        if requested_stage == "discover" and not _contains_phrase(text, STAGE_OVERRIDE_PHRASES["edit"]):
            return "discover"
        return "edit"

    if requested_stage in {"discover", "design", "plan", "execute"}:
        return requested_stage
    return "discover"


def next_stage_for_tool(tool_name: str, current_stage: AgentStage) -> AgentStage:
    """阶段状态机：工具调用成功后声明的下一阶段。

    propose_options 在 discover/design 两级选择间推进（方向 → 视觉），
    这是"新页面必须两轮选择"约束的实现位置。
    """
    if tool_name == "propose_options":
        return {"discover": "design", "design": "plan"}.get(current_stage, current_stage)
    if tool_name == "ask_question":
        return current_stage
    return {
        "confirm_plan": "confirm",
        "generate_page": "edit",
        "edit_page": "edit",
        "finish": "edit",
    }.get(tool_name, current_stage)
