"""V14 pure channel context functions, extracted without controller imports."""
import re
from typing import Any
from .canonical import first_result
SystemStageError = ValueError

CHANNEL_GENERATION_SPEC_SECTION_ORDER = (
    "GLOBAL",
    "TITLE",
    "COVER",
    "DESCRIPTION",
    "HASHTAG",
    "COMMUNITY",
    "PLAYLIST",
)
CHANNEL_GENERATION_SPEC_SECTION_PATTERN = re.compile(
    r"^## \[(GLOBAL|TITLE|COVER|DESCRIPTION|HASHTAG|COMMUNITY|PLAYLIST)\][ \t]*$",
    re.MULTILINE,
)
CHANNEL_SNAPSHOT_SOURCE_PATTERN = re.compile(r"^## 来源：", re.MULTILINE)


def channel_generation_spec_sections(snapshot: str) -> dict[str, str]:
    """Parse the one channel execution spec embedded in a frozen snapshot."""
    matches = list(CHANNEL_GENERATION_SPEC_SECTION_PATTERN.finditer(snapshot))
    names = [match.group(1) for match in matches]
    for name in CHANNEL_GENERATION_SPEC_SECTION_ORDER:
        count = names.count(name)
        if count == 0:
            raise SystemStageError(f"preflight_channel_generation_spec_section_missing:{name}")
        if count > 1:
            raise SystemStageError(f"preflight_channel_generation_spec_section_duplicate:{name}")
    if tuple(names) != CHANNEL_GENERATION_SPEC_SECTION_ORDER:
        raise SystemStageError("preflight_channel_generation_spec_section_order_invalid")

    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(snapshot)
        if index + 1 == len(matches):
            next_source = CHANNEL_SNAPSHOT_SOURCE_PATTERN.search(snapshot, match.end())
            if next_source:
                end = next_source.start()
        sections[match.group(1)] = snapshot[match.start():end].rstrip() + "\n"
    return sections


def title_channel_context(snapshot: str) -> str:
    sections = channel_generation_spec_sections(snapshot)
    return sections["GLOBAL"].rstrip() + "\n\n" + sections["TITLE"].rstrip() + "\n"



THEME_PROFILES = {
    "萌宝家庭": {
        "audience_promise": "children, parent-child identity, family recognition, protection, warmth, and reunion",
        "required_plot_signals": ("孩子", "萌宝", "宝宝", "双宝", "双胞胎", "儿童", "小孩", "男孩", "女孩", "幼儿", "亲子"),
        "required_output_signals": ("孩子", "萌宝", "宝宝", "双宝", "双胞胎", "儿童", "小孩", "男孩", "女孩", "幼儿", "亲子"),
    },
    "豪门婚恋": {
        "audience_promise": "wealthy-family romance, marriage pressure, heir identity, relationship choice, and emotional reversal",
        "required_plot_signals": ("豪门", "总裁", "继承", "财阀", "集团", "董事长", "少爷", "千金", "婚姻", "结婚", "离婚", "复婚"),
        "required_output_signals": ("豪门", "总裁", "继承", "财阀", "集团", "董事长", "少爷", "千金", "婚姻", "结婚", "离婚", "复婚"),
    },
    "复仇逆袭": {
        "audience_promise": "betrayal, humiliation, comeback, counterattack, exposed lies, and regained agency",
        "required_plot_signals": ("复仇", "逆袭", "背叛", "陷害", "羞辱", "反击", "重生", "报复", "翻身"),
        "required_output_signals": ("复仇", "逆袭", "背叛", "陷害", "羞辱", "反击", "重生", "报复", "翻身"),
    },
    "甜宠": {
        "audience_promise": "mutual attraction, affectionate protection, romantic trust, and a warm relationship payoff",
        "required_plot_signals": ("甜宠", "心动", "恋爱", "相爱", "告白", "暗恋", "宠爱", "情侣"),
        "required_output_signals": ("甜宠", "心动", "恋爱", "相爱", "告白", "暗恋", "宠爱", "情侣"),
    },
}


def channel_theme_contract(item: dict[str, Any], plot_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build the shared channel-semantic contract used by every creative stage."""
    nickname = str(item.get("nickname") or "").strip()
    parts = [part.strip() for part in nickname.split("-") if part.strip()]
    direction = str(item.get("direction") or (parts[-1] if parts else "")).strip()
    gender = str(item.get("gender") or (parts[-2] if len(parts) >= 2 else "")).strip()
    profile = THEME_PROFILES.get(direction, {})
    plot_result = first_result(plot_payload or {})
    plot_fields = plot_result.get("plot_fields") if isinstance(plot_result.get("plot_fields"), dict) else {}
    plot_text = "\n".join(
        str(plot_fields.get(key) or "")
        for key in ("内容概述", "剧情档案", "剧情套路", "核心人设")
    )
    def positively_present(term: str) -> bool:
        start = 0
        while True:
            index = plot_text.find(term, start)
            if index < 0:
                return False
            prefix = plot_text[max(0, index - 10):index]
            if not re.search(r"(?:没有|并无|不存在|未出现|不是|不含|无)[^，。；：]{0,6}$", prefix):
                return True
            start = index + len(term)

    found = [term for term in profile.get("required_plot_signals", ()) if positively_present(term)]
    return {
        "channel_direction": direction,
        "channel_gender": gender,
        "audience_promise": str(profile.get("audience_promise") or direction),
        "plot_supported": bool(found),
        "plot_support_signals": found[:12],
        "required_output_signals": list(profile.get("required_output_signals", ())),
        "truth_rule": "use_only_verified_plot_facts_and_never_invent_theme_evidence",
        "same_channel_rule": "theme_consistent_creative_distinct",
        "cross_channel_rule": "channel_direction_must_change_packaging_angle",
    }
