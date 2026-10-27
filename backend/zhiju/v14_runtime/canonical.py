#!/usr/bin/env python3
"""Canonical machine contracts for the Xiaoyu deterministic workflow.

AI responses are JSON only.  Markdown is rendered from accepted JSON and is
never parsed back into machine state.
"""

from __future__ import annotations

import copy
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


from .rules import load_community_rule_bundle, load_cover_rule_bundle, load_description_rule_bundle


STAGE_FILES = {
    "xy-find": ("01_搜索资料.json", "01_搜索资料.md"),
    "xy-title": ("04_标题方案.json", "04_标题方案.md"),
    "xy-cover": ("04_封面提示词.json", "04_封面提示词.md"),
    "xy-place": ("place_result.json", "place_result.md"),
    "xy-post": ("06_社群方案.json", "06_社群方案.md"),
}


STRING = {"type": "string"}
INTEGER = {"type": "integer"}


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or list(properties),
        "additionalProperties": False,
    }


IDENTITY_PROPERTIES = {
    "search_result_index": INTEGER,
    "source_block_label": STRING,
    "result_id": STRING,
    "video_id": STRING,
    "drama_name": STRING,
}


TITLE_DIRECTION_SCHEMA = _object(
    {
        "index": INTEGER,
        "recommendation_score": INTEGER,
        "direction": STRING,
        "hook_a_type": STRING,
        "hook_a_fact": STRING,
        "hook_a_evidence": STRING,
        "hook_b_type": STRING,
        "hook_b_fact": STRING,
        "hook_b_evidence": STRING,
        "specificity_anchor": STRING,
        "public_payoff_anchor": STRING,
        "visual_thesis": STRING,
        "child_angle": {"type": "boolean"},
        "safe_cover_scene": STRING,
        "child_role": STRING,
        "title": STRING,
        "translation": STRING,
        "char_count": INTEGER,
    }
)


PACKAGING_BRIEF_SCHEMA = _object(
    {
        "creative_slot_id": STRING,
        "channel_direction": STRING,
        "core_story_promise": STRING,
        "audience_emotion": STRING,
        "information_gap": STRING,
        "title_role": STRING,
        "thumbnail_role": STRING,
        "truth_constraints": STRING,
        "avoid_repetition": STRING,
    }
)

PACKAGING_BRIEF_ACK_PROPERTIES = {
    "packaging_brief_id": STRING,
    "channel_direction": STRING,
    "core_story_promise": STRING,
}


SCHEMAS: dict[str, dict[str, Any]] = {
    "xy-title": _object(
        {
            "section": {"type": "string", "enum": ["titles"]},
            "results": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": _object(
                    {
                        **IDENTITY_PROPERTIES,
                        "packaging_brief": PACKAGING_BRIEF_SCHEMA,
                        "directions": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": TITLE_DIRECTION_SCHEMA,
                        },
                        "direct_titles": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": STRING,
                        },
                    }
                ),
            },
        }
    ),
    "xy-cover": _object(
        {
            "section": {"type": "string", "enum": ["covers"]},
            "results": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": _object(
                    {
                        **IDENTITY_PROPERTIES,
                        **PACKAGING_BRIEF_ACK_PROPERTIES,
                        "titles": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 3,
                            "items": _object(
                                {
                                    "title_index": INTEGER,
                                    "title": STRING,
                                    "title_translation": STRING,
                                    "core_words": STRING,
                                    "core_words_translation": STRING,
                                    "visual_thesis": STRING,
                                    "visual_payoff": STRING,
                                    "single_continuous_moment": {"type": "boolean"},
                                    "single_physical_location": {"type": "boolean"},
                                    "temporal_montage": {"type": "boolean"},
                                    "required_characters": {
                                        "type": "array",
                                        "minItems": 1,
                                        "maxItems": 12,
                                        "items": STRING,
                                    },
                                    "visible_adult_count": INTEGER,
                                    "visible_child_count": INTEGER,
                                    "removed_optional_characters": STRING,
                                    "scene_choice_reason": STRING,
                                    "action_choice_reason": STRING,
                                    "prop_role": {"type": "string", "enum": ["none", "supporting"]},
                                    "camera_angle": {
                                        "type": "string",
                                        "enum": [
                                            "eye-level",
                                            "slightly low-angle",
                                            "slightly high-angle",
                                            "over-the-shoulder",
                                            "three-quarter view",
                                        ],
                                    },
                                    "core_words_category": {
                                        "type": "string",
                                        "enum": [
                                            "specific_relationship",
                                            "shocking_identity",
                                            "concrete_number",
                                            "concrete_consequence",
                                            "abnormal_action",
                                            "abstract_theme",
                                        ],
                                    },
                                    "core_words_selection_reason": STRING,
                                    "story_hook": STRING,
                                    "scene_family": STRING,
                                    "scene": STRING,
                                    "main_action": STRING,
                                    "key_prop": STRING,
                                    "composition": STRING,
                                    "palette": STRING,
                                    "lighting": STRING,
                                    "scene_prompt_4_5": STRING,
                                    "outpaint_environment": STRING,
                                }
                            ),
                        },
                    }
                ),
            },
        }
    ),
    "xy-place": _object(
        {
            "section": {"type": "string", "enum": ["placement"]},
            "results": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": _object(
                    {
                        **IDENTITY_PROPERTIES,
                        **PACKAGING_BRIEF_ACK_PROPERTIES,
                        "opening_hook_type": STRING,
                        "payoff_hook_type": STRING,
                        "editorial_anchor": STRING,
                        "channel_theme_phrase": STRING,
                        "channel_theme_phrase_translation": STRING,
                        "playlist": STRING,
                        "url": STRING,
                        "description": STRING,
                        "translation": STRING,
                    }
                ),
            },
        }
    ),
    "xy-post": _object(
        {
            "section": {"type": "string", "enum": ["community"]},
            "results": {
                "type": "array",
                "minItems": 1,
                "maxItems": 32,
                "items": _object(
                    {
                        **IDENTITY_PROPERTIES,
                        **PACKAGING_BRIEF_ACK_PROPERTIES,
                        "plan_index": INTEGER,
                        "community_hook_type": STRING,
                        "selected_moment": STRING,
                        "interaction_angle": STRING,
                        "scene_family": STRING,
                        "main_action": STRING,
                        "key_prop": STRING,
                        "composition": STRING,
                        "palette": STRING,
                        "channel_theme_phrase": STRING,
                        "channel_theme_phrase_translation": STRING,
                        "image_prompt_1x1": STRING,
                        "copy": STRING,
                        "copy_translation": STRING,
                    }
                ),
            },
        }
    ),
}


LEGACY_POST_SCHEMA = _object(
    {
        "section": {"type": "string", "enum": ["community"]},
        "results": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1,
            "items": _object(
                {
                    **IDENTITY_PROPERTIES,
                    "community_hook_type": STRING,
                    "selected_moment": STRING,
                    "interaction_angle": STRING,
                    "image_prompt_1x1": STRING,
                    "copy": STRING,
                    "copy_translation": STRING,
                }
            ),
        },
    }
)


def schema_for(stage: str, item: dict[str, Any] | None = None) -> dict[str, Any]:
    """Choose a complete strict schema for the exact batch version/count."""
    item = item or {}
    if stage == "xy-title" and int(item.get("workflow_contract_version") or 1) < 2:
        schema = copy.deepcopy(SCHEMAS[stage])
        result_schema = schema["properties"]["results"]["items"]
        result_schema["properties"].pop("packaging_brief", None)
        result_schema["required"] = list(result_schema["properties"])
        return schema
    if stage in {"xy-cover", "xy-place"} and int(item.get("workflow_contract_version") or 1) < 2:
        schema = copy.deepcopy(SCHEMAS[stage])
        result_schema = schema["properties"]["results"]["items"]
        for key in PACKAGING_BRIEF_ACK_PROPERTIES:
            result_schema["properties"].pop(key, None)
        if stage == "xy-place":
            result_schema["properties"].pop("channel_theme_phrase", None)
            result_schema["properties"].pop("channel_theme_phrase_translation", None)
        result_schema["required"] = list(result_schema["properties"])
        return schema
    if stage != "xy-post":
        return SCHEMAS[stage]
    is_multi_v2 = int(item.get("community_output_version") or 0) >= 2 or "community_count" in item
    if not is_multi_v2:
        return LEGACY_POST_SCHEMA
    count = int(item.get("community_count", 1 if item.get("need_community") else 0) or 0)
    schema = copy.deepcopy(SCHEMAS["xy-post"])
    if int(item.get("workflow_contract_version") or 1) < 2:
        result_schema = schema["properties"]["results"]["items"]
        for key in PACKAGING_BRIEF_ACK_PROPERTIES:
            result_schema["properties"].pop(key, None)
        result_schema["properties"].pop("channel_theme_phrase", None)
        result_schema["properties"].pop("channel_theme_phrase_translation", None)
        result_schema["required"] = list(result_schema["properties"])
    schema["properties"]["results"]["minItems"] = count
    schema["properties"]["results"]["maxItems"] = count
    return schema


def first_result(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results")
    return results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else {}


def title_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = first_result(payload)
    rows = result.get("directions")
    return rows if isinstance(rows, list) else []


def title_length_issues(
    title: str,
    index: int,
    title_rule_contract: dict[str, Any] | None = None,
) -> list[str]:
    maximum = int((title_rule_contract or {}).get("max_visible_characters", 100))
    return [] if len(str(title or "")) <= maximum else [f"title_{index}_over_{maximum}_chars"]


def cover_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = first_result(payload)
    rows = result.get("titles")
    return rows if isinstance(rows, list) else []


COVER_STYLE_BLOCK = (
    "Natural live-action Chinese television drama still. Chinese actors, Chinese facial features, East Asian "
    "appearance. Realistic lens rendering, natural skin texture, ordinary clothing wrinkles, believable location "
    "lighting, natural shadows, accurate anatomy, expressive but believable acting, and slightly softer "
    "environmental detail. Avoid plastic beauty-filter rendering and obvious CGI aesthetics."
)
COVER_IDENTITY_MARKER = "Chinese actors, Chinese facial features, East Asian appearance"
COVER_STYLE_MARKER = "Natural live-action Chinese television drama still"
CORE_WORDS_TYPOGRAPHY_MARKER = "non-diegetic cover typography"
CORE_WORDS_SALIENCE_MARKER = "visually prominent, highly legible"


def visual_cast_contract(context: dict[str, Any] | None = None) -> dict[str, str]:
    """Use only the drama's original language, never its channel/dub language."""
    if str((context or {}).get("source_language") or "").strip().lower() == "en":
        return {
            "identity": "Western actors, European and North American facial features, Western appearance",
            "style": "Natural live-action Western television drama still",
            "community_face": "European and North American facial features",
            "community_cast": "Western short-drama",
        }
    return {
        "identity": COVER_IDENTITY_MARKER,
        "style": COVER_STYLE_MARKER,
        "community_face": "Chinese facial features",
        "community_cast": "Chinese short-drama",
    }


def cover_style_block(context: dict[str, Any] | None = None) -> str:
    cast = visual_cast_contract(context)
    return COVER_STYLE_BLOCK.replace(COVER_STYLE_MARKER, cast["style"]).replace(COVER_IDENTITY_MARKER, cast["identity"])


def core_words_typography_clause(
    core_words: str,
    cover_rule_contract: dict[str, Any] | None = None,
) -> str:
    core = str(core_words or "").strip()
    if not core:
        return ""
    return (
        f'Render exact core words "{core}" as bold high-contrast non-diegetic cover typography fully inside the '
        "centered 1728x2160 4:5 image area. Make them visually prominent, highly legible, and immediately recognizable "
        "on mobile. Adapt font size, line breaks, color contrast, outline, shadow, optional backing, and placement to "
        "language, word length, negative space, background, and actors; use no fixed width, height, font size, or canvas "
        "ratio. Prominent does not mean largest possible: faces and event remain primary. Never cover faces, critical "
        "hands, story objects, or logos; never place text on "
        "physical surfaces or props."
    )


def canonical_outpaint_prompt(environment: str) -> str:
    continuation = str(environment or "").strip()
    return " ".join(
        part for part in (
            "Image-to-image environmental outpainting only. Use the approved 1728x2160 4:5 image as the immutable "
            "centered source inside a final 3840x2160 canvas. Preserve the entire center pixel-for-pixel, including "
            "all people, faces, hands, expressions, props, typography, lighting, color, sharpness, shadows, and "
            "composition. Keep the approved core-word typography entirely inside that locked center; do not resize, "
            "move, restyle, recolor, re-outline, re-shadow, or reflow it. Apply a side-only outpaint mask and generate "
            "only the 1056px left and 1056px right side bands. "
            "After outpainting, composite the approved 4:5 source pixels back over the full center area pixel-for-pixel. Continue the existing environment "
            "naturally with matching perspective, materials, lighting direction, color temperature, and depth. Do not "
            "add new people, body fragments, typography, story information, evidence, or new focal objects. "
            "Do not run this as standalone text-to-image. Environmental extension only. Never reconstruct or reinterpret the locked center.",
            continuation,
        )
        if part
    )


def cover_prompt_structure_issues(row: dict[str, Any], index: int, context: dict[str, Any] | None = None) -> list[str]:
    """Detect assembly ownership violations without rewriting creative prose."""
    issues: list[str] = []
    scene = str(row.get("scene_prompt_4_5") or "")
    scene_lower = scene.lower()
    cast = visual_cast_contract(context)
    controller_markers = {
        "typography": CORE_WORDS_TYPOGRAPHY_MARKER,
        "salience": CORE_WORDS_SALIENCE_MARKER,
        "style": cast["style"].lower(),
        "identity": cast["identity"].lower(),
    }
    for label, marker in controller_markers.items():
        if marker.lower() in scene_lower:
            issues.append(f"cover_{index}_scene_prompt_contains_controller_owned_{label}")
    if re.search(r"\b(?:50\s*[-–—]\s*75%|character height at least|thick contrasting outline|compact hard shadow)\b", scene, re.I):
        issues.append(f"cover_{index}_scene_prompt_contains_controller_owned_typography")

    wide_contract = load_cover_rule_bundle().get("prompt_audit", {}).get("wide_generation_execution", {})
    wide_markers = tuple(
        str(term).casefold()
        for term in wide_contract.get("forbidden_in_4_5_prompt_terms", ())
        if str(term).strip()
    )
    if any(marker in scene.casefold() for marker in wide_markers):
        issues.append(f"cover_{index}_scene_prompt_contains_wide_generation_instruction")

    final_prompt = str(row.get("prompt_4_5") or "")
    if any(marker in final_prompt.casefold() for marker in wide_markers):
        issues.append(f"cover_{index}_final_prompt_contains_wide_generation_instruction")
    for label, marker in controller_markers.items():
        count = final_prompt.lower().count(marker.lower())
        if count != 1:
            issues.append(f"cover_{index}_final_prompt_{label}_block_count_{count}")
    if "Controlled shock; asymmetrical blocking." in final_prompt:
        issues.append(f"cover_{index}_final_prompt_context_free_creative_suffix")
    return list(dict.fromkeys(issues))


def has_diegetic_core_word_placement(prompt: str, core_words: str) -> bool:
    """Detect when the requested core words are made part of a physical object."""
    core = str(core_words or "").strip().casefold()
    if not core:
        return False
    text = str(prompt or "").casefold().replace("\n", " ")
    # Ignore explicit prohibitions such as the controller-owned "never printed"
    # clause; only positive placement instructions are violations.
    positive = re.sub(r"\b(?:never|must not|do not|not)\b[^.;]*", " ", text)
    start = 0
    physical_placement = re.compile(
        r"\b(?:place|placed|position|positioned|set|painted|printed|written|engraved|projected|reflected|displayed|attached)\b"
        r"[^.;]{0,120}\b(?:wall|door|paper|document|folder|book|screen|clothing|shirt|sign|prop|foliage)\b"
    )
    while True:
        index = positive.find(core, start)
        if index < 0:
            return False
        sentence_start = max(positive.rfind(".", 0, index), positive.rfind(";", 0, index)) + 1
        sentence_end_candidates = [pos for pos in (positive.find(".", index), positive.find(";", index)) if pos >= 0]
        sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(positive)
        if physical_placement.search(positive[sentence_start:sentence_end]):
            return True
        start = index + len(core)


STYLE_SIGNAL_PATTERNS = {
    "live-action": r"\blive-action\b",
    "natural skin texture": r"\bnatural(?:\s+\w+){0,2}\s+skin texture\b",
    "clothing wrinkles": r"\b(?:ordinary\s+)?(?:clothing|fabric) wrinkles\b",
    "realistic lens rendering": r"\b(?:realistic lens rendering|photograph(?:ed|y|ic)?|\d{2,3}mm photography feel)\b",
    "believable lighting": r"\b(?:believable lighting|realistic[^.;]{0,40}lighting|authentic location lighting)\b",
    "softer environmental detail": r"\b(?:slightly\s+)?softer (?:environmental|background) detail\b",
}


def image_prompt_style_issues(
    prompt: str,
    prefix: str,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    """Validate natural live-action rendering without removing overlay text."""
    if contract is None:
        if str(prefix).startswith("post_"):
            contract = load_community_rule_bundle().get("image_style", {})
        else:
            contract = load_cover_rule_bundle().get("prompt_audit", {}).get("image_style", {})
    if not contract:
        return []
    lower = str(prompt or "").lower()
    issues: list[str] = []
    forbidden = [
        str(term).lower()
        for term in contract.get("forbidden_overprocessed_terms", [])
        if str(term).strip()
    ]
    if any(term in lower for term in forbidden):
        issues.append(f"{prefix}_overprocessed_advertising_style")
    required = [str(signal) for signal in contract.get("required_natural_signals", [])]
    matched = sum(
        bool(re.search(STYLE_SIGNAL_PATTERNS.get(signal, re.escape(signal)), lower, re.I))
        for signal in required
    )
    minimum = int(contract.get("minimum_required_natural_signals", 0) or 0)
    if matched < minimum:
        issues.append(f"{prefix}_natural_live_action_style_incomplete")
    return issues


AI_POSTER_FORBIDDEN_TERMS = (
    "holographic display",
    "holographic interface",
    "hologram",
    "futuristic interface",
    "futuristic scanner",
    "transparent evidence canister",
    "forensic timeline rail",
    "uv projection",
    "glowing dna",
    "illuminated dna",
    "memory carousel",
    "magnetic false back",
    "glowing tracker",
    "glowing route",
    "account frozen rejection tray",
    "lightning-bolt composition",
    "threshold-hourglass composition",
    "bridge-and-crescent composition",
    "sweeping-anchor composition",
    "unfolding-fan composition",
    "rail-switch composition",
    "crossed-chute composition",
    "descending-hand chain composition",
    "shield-and-split composition",
)

COVER_PROP_PATTERNS = {
    "phone": r"\b(?:smartphone|mobile phone|cell phone|phone screen)\b",
    "document": r"\b(?:printed medical report|medical report|contract|certificate|appointment letter|shareholder file)\b",
    "identity_card": r"\b(?:id card|identity card|passport)\b",
    "jewelry": r"\b(?:wedding ring|engagement ring|locket|bracelet|necklace)\b",
    "money": r"\b(?:briefcase of money|cash|bank card)\b",
    "test_result": r"\b(?:dna report|paternity report|test result)\b",
    "recording": r"\b(?:audio recorder|voice recorder|security recording)\b",
    "key": r"\b(?:house key|car key|keycard)\b",
}


def _cover_positive_text(prompt: str) -> str:
    """Remove negative clauses before auditing risky visual inventions.

    The shared safety tail deliberately names forbidden objects (for example
    ``no holograms``).  Those words must not be mistaken for a positive scene
    instruction.
    """
    text = str(prompt or "").lower().replace("\n", " ")
    return re.sub(r"\b(?:no|without|avoid|do not add|never add)\b[^.;]*", " ", text)


def _cover_word_count(prompt: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", str(prompt or ""), flags=re.UNICODE))


def _cover_story_props(prompt: str) -> list[str]:
    positive = _cover_positive_text(prompt)
    return [name for name, pattern in COVER_PROP_PATTERNS.items() if re.search(pattern, positive, re.I)]


def audit_cover_prompt(
    prompt: str, hard_forbidden_terms: list[str] | tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Score a prompt as a believable drama still rather than an AI poster."""
    positive = _cover_positive_text(prompt)
    forbidden_source = hard_forbidden_terms or AI_POSTER_FORBIDDEN_TERMS
    forbidden = [str(term) for term in forbidden_source if str(term).lower() in positive]
    props = _cover_story_props(prompt)

    # V14 R4 separates genuinely forbidden invented poster devices/geometries
    # from quality observations.  Prompt length, prop density, and decorative
    # wording remain useful evidence, but they must never become creative
    # rejection thresholds through an accumulated score.
    quality_observations: list[str] = []
    if len(props) > 2:
        quality_observations.append("prop_density")
    if len(re.findall(r"\b(?:glow|glowing|luminous|neon|illuminated)\w*\b", positive)) > 2:
        quality_observations.append("excessive_lighting_description")
    ai_risk = 7 if forbidden else 0

    score = 0
    if re.search(r"\b(?:wife|husband|mother|father|daughter|son|sister|brother|fianc[eé]|rival|couple)\b", positive):
        score += 2
    if re.search(r"\b(?:shock|panic|grief|fear|anger|betray|relief|controlled|stunned|tear|emotion)\w*\b", positive):
        score += 2
    if re.search(r"\b(?:holds?|turns?|reaches?|steps?|opens?|closes?|pulls?|pushes?|kneels?|embraces?|hands?)\b", positive):
        score += 2
    if re.search(r"\b(?:apartment|garage|office|home|kitchen|street|courtyard|restaurant|hotel|school|wedding|station|shop)\b", positive):
        score += 2
    if len(props) <= 1:
        score += 2
    if re.search(r"\b(?:natural|daylight|window light|location lighting|practical light|overcast|sunset|morning light)\b", positive):
        score += 2
    if re.search(r"\b(?:overlap|overlapping|behind|beside|foreground|shoulder)\w*\b", positive):
        score += 1
    if "asymmetrical" in positive or "off-center" in positive:
        score += 1

    return {
        "word_count": _cover_word_count(prompt),
        "ai_poster_risk": ai_risk,
        "real_drama_score": score,
        "forbidden_terms": forbidden,
        "story_evidence_props": props,
        "quality_observations": quality_observations,
    }


def cover_prompt_quality_issues(
    prompt: str,
    index: int,
    cover_rule_contract: dict[str, Any] | None = None,
) -> list[str]:
    rules = cover_rule_contract if isinstance(cover_rule_contract, dict) else load_cover_rule_bundle()
    contract = rules.get("prompt_audit", {})
    configured = contract.get("hard_forbidden_ai_poster_terms", AI_POSTER_FORBIDDEN_TERMS)
    audit = audit_cover_prompt(prompt, configured)
    issues: list[str] = []
    if audit["forbidden_terms"]:
        issues.append(f"cover_{index}_ai_poster_hard_forbidden")
    return issues


def cover_prompt_quality_observations(
    prompt: str,
    index: int,
    cover_rule_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return non-blocking quality evidence for a final cover prompt."""
    rules = cover_rule_contract if isinstance(cover_rule_contract, dict) else load_cover_rule_bundle()
    contract = rules.get("prompt_audit", {})
    configured = contract.get("hard_forbidden_ai_poster_terms", AI_POSTER_FORBIDDEN_TERMS)
    audit = audit_cover_prompt(prompt, configured)
    audit_score_reference = int(contract.get("minimum_real_drama_score_audit", 10))
    observations = [f"cover_{index}_{value}" for value in audit["quality_observations"]]
    observations.extend(image_prompt_style_issues(prompt, f"cover_{index}", contract.get("image_style", {})))
    if audit["real_drama_score"] < audit_score_reference:
        observations.append(f"cover_{index}_real_drama_score_below_{audit_score_reference}")
    return {
        **audit,
        "title_index": index,
        "hard_forbidden": bool(audit["forbidden_terms"]),
        "observations": list(dict.fromkeys(observations)),
    }


FEMALE_SPECIAL_EFFECT_RE = re.compile(
    r"\b(?:magic(?:al)?|aura|energy(?:\s+(?:beam|field|wave))?|lightning|particles?|fire|flames?|"
    r"explosions?|holograms?|laser(?:s|\s+beam)?|glowing\s+(?:eyes?|props?|object)|"
    r"supernatural\s+glow|spell(?:s|casting)?)\b",
    re.I,
)
PHYSICAL_VIOLENCE_RE = re.compile(
    r"\b(?:about\s+to\s+(?:slap|punch|kick|hit|strike)|raises?\s+(?:his|her|a)\s+fist\s+to\s+"
    r"(?:punch|hit|strike)|slaps?|punch(?:es|ing)?|hits?|strikes?|kicks?|chok(?:e|es|ing)|strangl(?:e|es|ing)|"
    r"dragg(?:ed|ing)|push(?:es|ing)?\s+(?:him|her|them)\s+(?:down|to\s+the\s+(?:ground|floor))|"
    r"stomps?|beating|weapons?|knife|gun|blood(?![\s-]+type\b)|wounds?)\b",
    re.I,
)
VISIBLE_CHILD_RE = re.compile(
    r"\b(?:child|children|kid|kids|baby|babies|toddler|boy|girl|daughter|son|twins?|triplets?|"
    r"five-year-old|six-year-old|seven-year-old)\b|儿童|孩子|小孩|宝宝|萌宝|男孩|女孩|女儿|儿子|双胞胎|三胞胎",
    re.I,
)
CHILD_UNSAFE_RE = re.compile(
    r"\b(?:crying|frightened|terrified|panicked|injured|wounded|sick|ill|unconscious|"
    r"kidnapped|tied|threatened|bullied|humiliated|abused|helpless|endangered|"
    r"(?:painful|invasive|dangerous|harmful)\s+(?:medical\s+)?(?:procedure|treatment|operation)|"
    r"surrounded\s+by\s+angry\s+adults?|adult\s+mob)\b|哭泣|惊恐|受伤|生病|昏迷|绑架|"
    r"(?:痛苦|侵入性|危险|有害)(?:的)?医疗(?:操作|治疗)|"
    r"束缚|捆绑|威胁|霸凌|羞辱|虐待|无助|陷入危险",
    re.I,
)
CHILD_RESTRAINT_RE = re.compile(
    r"\b(?:restrained(?:\s+[a-z-]+){0,2}\s+(?:child|children|kid|kids|baby|babies|boy|girl|daughter|son)|"
    r"(?:child|children|kid|kids|baby|babies|boy|girl|daughter|son)\s+(?:is|are|was|were|being)?\s*restrained)\b|"
    r"(?:被束缚|受束缚|遭束缚)(?:的)?(?:儿童|孩子|小孩|宝宝|男孩|女孩|女儿|儿子)|"
    r"(?:儿童|孩子|小孩|宝宝|男孩|女孩|女儿|儿子)(?:被|正被)?束缚",
    re.I,
)
CHILD_ANGLE_RE = re.compile(
    r"\b(?:child|children|kid|kids|baby|babies|daughter|son|twins?|triplets?)\b|萌宝|孩子|小孩|宝宝|婴儿|女婴|男婴|女儿|儿子|双宝|双胞胎|三胞胎|三宝|四宝|五宝|六宝",
    re.I,
)
ADULT_OFFSPRING_RE = re.compile(
    r"\b(?:adult|grown|fully[- ]grown)\s+(?:daughter|daughters|son|sons|children|offspring)\b|"
    r"成年(?:的)?(?:女儿|儿子|子女|孩子)|(?:女儿|儿子|子女|孩子)(?:均为|都是|已经是)?成年人",
    re.I,
)
MINOR_SPECIFIC_RE = re.compile(
    r"\b(?:child|children|kid|kids|baby|babies|toddler|little\s+(?:boy|girl)|twins?|triplets?)\b|"
    r"萌宝|宝宝|婴儿|女婴|男婴|儿童|小孩|幼儿|男孩|女孩|双宝|双胞胎|三胞胎|三宝|四宝|五宝|六宝",
    re.I,
)

CHILD_SAFE_NEGATION_RE = re.compile(
    r"(?:无|没有|不含|不存在)(?:任何)?(?:威胁|危险|冲突|霸凌|羞辱|虐待)|"
    r"不受(?:任何)?威胁|"
    r"\b(?:no|without)\s+(?:any\s+)?(?:threats?|danger|conflict|bullying|humiliation|abuse)\b|"
    r"\bnot\s+(?:threatened|endangered|bullied|humiliated|abused)\b|"
    r"\b(?:entirely|physically|clearly)\s+separate(?:d)?\s+from\s+(?:this\s+|the\s+)?"
    r"(?:adult\s+)?(?:hospital|clinic|medical\s+(?:scene|setting|danger)|conflict|confrontation|standoff)\b",
    re.I,
)


def _positive_child_risk_text(value: str) -> str:
    """Remove only explicit safety negations before detecting actual child risk."""
    return CHILD_SAFE_NEGATION_RE.sub(" ", str(value or ""))


EXPLICIT_MINOR_RE = re.compile(
    r"\b(?:child|children|kid|kids|baby|babies|toddler|twins?|triplets?|"
    r"(?:five|six|seven|eight|nine|ten|eleven|twelve|\d+)[- ]year[- ]old|little\s+(?:boy|girl))\b|"
    r"儿童|孩子|小孩|宝宝|婴儿|女婴|男婴|萌宝|幼儿|男孩|女孩|双胞胎|三胞胎|双宝|三宝|四宝|五宝|六宝",
    re.I,
)
AMBIGUOUS_OFFSPRING_RE = re.compile(r"\b(?:daughter|daughters|son|sons|girl|girls|boy|boys)\b|女儿|儿子", re.I)
ADULT_PERSON_REPLACEMENT = " adult-person "
def _without_explicit_adult_offspring(value: str) -> str:
    """Remove explicitly adult offspring before minor-presence/safety checks."""
    return ADULT_OFFSPRING_RE.sub(ADULT_PERSON_REPLACEMENT, str(value or ""))


def _contains_visible_minor(value: str, child_required: bool) -> bool:
    text = _without_explicit_adult_offspring(value)
    if EXPLICIT_MINOR_RE.search(text):
        return True
    return bool(child_required and AMBIGUOUS_OFFSPRING_RE.search(text))


def _minor_subject_pattern(child_required: bool) -> str:
    explicit = (
        r"(?:child|children|kid|kids|baby|babies|toddler|twins?|triplets?|"
        r"(?:five|six|seven|eight|nine|ten|eleven|twelve|\d+)[- ]year[- ]old|little\s+(?:boy|girl))"
    )
    if child_required:
        return explicit + r"|daughter|daughters|son|sons|girl|girls|boy|boys"
    return explicit


def _child_risk_is_direct(clause: str, child_required: bool) -> bool:
    """Return true only when a risk state/action is grammatically tied to a minor.

    This deliberately favors precision over same-sentence co-occurrence. Adult
    emotion beside a safe child is valid cover drama and must not be rejected.
    """
    text = _positive_child_risk_text(_without_explicit_adult_offspring(clause))
    if not _contains_visible_minor(text, child_required):
        return False
    minor = _minor_subject_pattern(child_required)
    risk = r"(?:crying|frightened|terrified|panicked|injured|wounded|sick|ill|unconscious|kidnapped|tied|threatened|bullied|humiliated|abused|helpless|endangered)"
    direct_patterns = (
        rf"\b(?:{minor})\b\s*(?:(?:who\s+)?(?:is|are|was|were|looks?|appears?|remains?|seems?|becomes?)\s+)?(?:visibly\s+|clearly\s+|obviously\s+)?{risk}\b",
        rf"\b{risk}\s+(?:(?:young|little|healthy|Chinese|East Asian)\s+){{0,3}}(?:{minor})\b",
        rf"\b(?:kidnap(?:s|ped|ping)?|tie[sd]?|threaten(?:s|ed|ing)?|bull(?:y|ies|ied|ying)|humiliat(?:e|es|ed|ing)|abus(?:e|es|ed|ing)|restrain(?:s|ed|ing)?)\b[^.;]{{0,50}}\b(?:{minor})\b",
        rf"\b(?:{minor})\b[^.;]{{0,50}}\b(?:kidnap(?:s|ped|ping)?|tie[sd]?|threaten(?:s|ed|ing)?|bull(?:y|ies|ied|ying)|humiliat(?:e|es|ed|ing)|abus(?:e|es|ed|ing)|restrain(?:s|ed|ing)?)\b",
    )
    if any(re.search(pattern, text, re.I) for pattern in direct_patterns):
        return True
    if re.search(r"(?:儿童|孩子|小孩|宝宝|萌宝|幼儿|男孩|女孩|双胞胎|双宝|女儿|儿子)(?:正在|显得|看起来|处于|被|受到)?(?:哭泣|惊恐|受伤|生病|昏迷|绑架|束缚|捆绑|威胁|霸凌|羞辱|虐待|无助|陷入危险)", text):
        return True
    if re.search(r"(?:绑架|束缚|捆绑|威胁|霸凌|羞辱|虐待)(?:了|着|这些|那些|一名|两名|三名)?(?:儿童|孩子|小孩|宝宝|萌宝|幼儿|男孩|女孩|双胞胎|双宝|女儿|儿子)", text):
        return True
    if re.search(
        rf"\b(?:{minor})\b[^.;]{{0,80}}\b(?:painful|invasive|dangerous|harmful)\s+(?:medical\s+)?(?:procedure|treatment|operation)\b",
        text,
        re.I,
    ):
        return True
    if re.search(rf"\b(?:{minor})\b[^.;]{{0,60}}\b(?:surrounded\s+by\s+angry\s+adults?|adult\s+mob)\b", text, re.I):
        return True
    return False


def _sentence_windows_with_children(prompt: str, child_required: bool = False) -> list[str]:
    """Return local clauses containing a structured or explicit minor."""
    clauses = [part.strip() for part in re.split(r"(?<=[.!?;])\s+|\n+", str(prompt or "")) if part.strip()]
    return [clause for clause in clauses if _contains_visible_minor(clause, child_required)]


def title_child_cover_safety_issues(index: int, row: dict[str, Any]) -> list[str]:
    """Require a feasible child-safe visual plan before cover generation."""
    if not bool(row.get("child_angle")):
        return []
    issues: list[str] = []
    scene = str(row.get("safe_cover_scene") or "").strip()
    role = str(row.get("child_role") or "").strip()
    if not scene:
        issues.append(f"title_{index}_child_safe_cover_scene_missing")
    if not role:
        issues.append(f"title_{index}_child_role_missing")
    local_child_text = " ".join(value for value in (scene, role) if value)
    if local_child_text and any(
        _child_risk_is_direct(window, True)
        for window in _sentence_windows_with_children(local_child_text, True)
    ):
        issues.append(f"title_{index}_child_safe_cover_scene_unsafe")
    if local_child_text and not _contains_visible_minor(local_child_text, True):
        issues.append(f"title_{index}_child_safe_cover_scene_missing_visible_child")
    return issues


def title_row_requires_minor_child(row: dict[str, Any], global_child_required: bool = False) -> bool:
    """Use the model's Find-grounded direction flag; do not reinterpret copy."""
    return bool(row.get("child_angle"))


def title_direction_child_policy_issues(
    index: int, row: dict[str, Any], global_child_required: bool
) -> list[str]:
    """Unify title and cover child policy for the exact same task."""
    required = title_row_requires_minor_child(row, global_child_required)
    issues: list[str] = []
    marketing_values = [
        str(row.get(key) or "")
        for key in ("title", "hook_a_fact", "hook_b_fact", "specificity_anchor")
    ]
    if any(minor_title_humiliation_or_age_inappropriate(value) for value in marketing_values):
        issues.append(f"title_{index}_minor_humiliation_or_age_inappropriate")
    if required and not bool(row.get("child_angle")):
        issues.append(f"title_{index}_child_angle_flag_missing")
    if required:
        safety_row = dict(row)
        safety_row["child_angle"] = True
        issues.extend(title_child_cover_safety_issues(index, safety_row))
    return issues


def minor_title_humiliation_or_age_inappropriate(value: str) -> bool:
    """Apply the title content gate only when the affected person is a minor.

    Illness, separation, DNA, custody, and other dramatic child hooks are not
    rejected here.  Explicitly adult daughters/sons are adults and may use the
    same harsh conflict language as any other adult character.
    """
    text = _without_explicit_adult_offspring(value)
    clauses = [part.strip() for part in re.split(r"[.!?;。！？；,，]+", text) if part.strip()]
    minor_en = (
        r"(?:child|children|kid|kids|baby|babies|toddler|twins?|triplets?|little\s+(?:boy|girl)|"
        r"(?:five|six|seven|eight|nine|ten|eleven|twelve|\d+)[- ]year[- ]old|daughter|son)"
    )
    forbidden_en = r"(?:humiliat(?:e|es|ed|ing)|insult(?:s|ed|ing)?|bull(?:y|ies|ied|ying)|abus(?:e|es|ed|ing)|sexualiz(?:e|es|ed|ing))"
    minor_zh = r"(?:未成年|儿童|孩子|小孩|宝宝|萌宝|幼儿|男孩|女孩|双胞胎|三胞胎|双宝|女儿|儿子)"
    forbidden_zh = r"(?:羞辱|侮辱|欺辱|欺负|霸凌|虐待|性化)"
    adult_role_en = r"(?:bride|groom|wife|husband|lover|mistress|pregnant)"
    adult_role_zh = r"(?:新娘|新郎|妻子|丈夫|情人|恋人|怀孕)"
    for clause in clauses:
        if re.search(rf"\b{minor_en}\b.{{0,45}}\b{forbidden_en}\b", clause, re.I):
            return True
        if re.search(rf"\b{forbidden_en}\b.{{0,45}}\b{minor_en}\b", clause, re.I):
            return True
        if re.search(
            rf"\b{minor_en}\b.{{0,18}}\b(?:is|are|was|were|become|becomes|became|made|forced|as)\b.{{0,12}}\b{adult_role_en}\b",
            clause,
            re.I,
        ):
            return True
        if re.search(rf"\b(?:force|forces|forced|make|makes|made)\b.{{0,18}}\b{minor_en}\b.{{0,12}}\b{adult_role_en}\b", clause, re.I):
            return True
        if re.search(rf"{minor_zh}.{{0,18}}{forbidden_zh}|{forbidden_zh}.{{0,18}}{minor_zh}", clause):
            return True
        if re.search(rf"{minor_zh}.{{0,8}}(?:被迫|被逼|成为|当上|充当|嫁给|怀孕).{{0,6}}{adult_role_zh}", clause):
            return True
        if re.search(rf"(?:逼|强迫|迫使|让).{{0,8}}{minor_zh}.{{0,8}}(?:成为|当上|充当|嫁给|怀孕).{{0,6}}{adult_role_zh}", clause):
            return True
    return False


def global_child_plan_required(item: dict[str, Any], context: dict[str, Any]) -> bool:
    """Never let a channel label override Find's per-direction story angle.

    Visible-child requirements are resolved independently for each accepted
    title direction.  A cute-child channel or drama name is packaging context,
    not evidence that every Find angle contains a born child.
    """
    return False


def cover_group_child_requirements(
    item: dict[str, Any], context: dict[str, Any], titles: list[dict[str, Any]]
) -> list[bool]:
    """Return the exact child-presence requirement for each cover group.

    The requirement stays scoped to each upstream Find/title direction.  A
    channel theme must never leak a child requirement into a pregnancy-only or
    adult-only angle.
    """
    global_required = global_child_plan_required(item, context)
    return [
        title_row_requires_minor_child(row, global_required)
        for row in titles
    ]


def _market_direction_source_types(context: dict[str, Any] | None) -> dict[int, str]:
    market = context.get("market_packaging") if isinstance(context, dict) else {}
    final_angles_value = market.get("final_angles") if isinstance(market, dict) else []
    final_angles = final_angles_value if isinstance(final_angles_value, list) else []
    return {
        index: str(angle.get("source_type") or "")
        for index, angle in enumerate(final_angles, 1)
        if isinstance(angle, dict)
    }


def _has_partial_market_coverage(context: dict[str, Any] | None, row_count: int) -> bool:
    source_type_by_index = _market_direction_source_types(context)
    market_backed_count = sum(
        source_type in {"external_market_verified", "internal_performance"}
        for source_type in source_type_by_index.values()
    )
    return 0 < market_backed_count < row_count


def normalize_title_recommendation_order(
    payload: dict[str, Any], context: dict[str, Any] | None = None
) -> None:
    """Put partial market-verified coverage first, then order by score."""
    result = first_result(payload)
    rows = result.get("directions") if isinstance(result.get("directions"), list) else []
    source_type_by_index = _market_direction_source_types(context)
    market_backed_indexes = {
        index
        for index, source_type in source_type_by_index.items()
        if source_type in {"external_market_verified", "internal_performance"}
    }
    partial_market_coverage = _has_partial_market_coverage(context, len(rows))

    def ranking_key(row: dict[str, Any]) -> tuple[int, int]:
        original_index = int(row.get("index") or 0)
        market_priority = int(partial_market_coverage and original_index in market_backed_indexes)
        return market_priority, int(row.get("recommendation_score") or 0)

    rows.sort(key=ranking_key, reverse=True)
    for index, row in enumerate(rows, 1):
        row["index"] = index
    result["directions"] = rows
    result["direct_titles"] = [str(row.get("title") or "") for row in rows]


def cover_policy_issues(
    prompt: str, index: int, female_frequency: bool, child_required: bool
) -> list[str]:
    """Hard prompt policy that cannot be traded away for click-through."""
    positive = _cover_positive_text(prompt)
    issues: list[str] = []
    if female_frequency and FEMALE_SPECIAL_EFFECT_RE.search(positive):
        issues.append(f"cover_{index}_female_frequency_special_effects_forbidden")
    if PHYSICAL_VIOLENCE_RE.search(positive):
        issues.append(f"cover_{index}_physical_violence_forbidden")
    if child_required and not _contains_visible_minor(positive, True):
        issues.append(f"cover_{index}_child_angle_missing_visible_child")
    child_windows = _sentence_windows_with_children(positive, child_required)
    if any(
        _child_risk_is_direct(window, child_required)
        or CHILD_RESTRAINT_RE.search(_positive_child_risk_text(_without_explicit_adult_offspring(window)))
        for window in child_windows
    ):
        issues.append(f"cover_{index}_child_safety_violation")
    return issues


def cover_generation_plan_issues(
    row: dict[str, Any],
    index: int,
    child_required: bool,
    cover_rule_contract: dict[str, Any] | None,
) -> list[str]:
    """Check only objective plan invariants frozen into the active contract.

    Scene/action quality stays model-owned. Legacy frozen contracts do not gain
    these fields or gates after the fact.
    """
    contract = cover_rule_contract if isinstance(cover_rule_contract, dict) else {}
    audit = contract.get("prompt_audit") if isinstance(contract.get("prompt_audit"), dict) else contract
    plan = audit.get("generation_plan") if isinstance(audit.get("generation_plan"), dict) else {}
    if not plan.get("required"):
        return []

    issues: list[str] = []
    text_fields = (
        "visual_payoff",
        "removed_optional_characters",
        "scene_choice_reason",
        "action_choice_reason",
        "core_words_selection_reason",
    )
    for field in text_fields:
        if not str(row.get(field) or "").strip():
            issues.append(f"cover_{index}_generation_plan_{field}_missing")
    characters = row.get("required_characters")
    if not isinstance(characters, list) or not any(str(value).strip() for value in characters):
        issues.append(f"cover_{index}_generation_plan_required_characters_missing")

    adult_count = row.get("visible_adult_count")
    child_count = row.get("visible_child_count")
    if isinstance(adult_count, bool) or not isinstance(adult_count, int) or adult_count < 0:
        issues.append(f"cover_{index}_generation_plan_visible_adult_count_invalid")
    if isinstance(child_count, bool) or not isinstance(child_count, int) or child_count < 0:
        issues.append(f"cover_{index}_generation_plan_visible_child_count_invalid")
    hard_max = int(plan.get("non_child_visible_adult_hard_max") or 4)
    if not child_required and isinstance(adult_count, int) and not isinstance(adult_count, bool) and adult_count > hard_max:
        issues.append(f"cover_{index}_non_child_visible_adult_count_over_{hard_max}")
    if child_required and isinstance(child_count, int) and not isinstance(child_count, bool) and child_count < 1:
        issues.append(f"cover_{index}_required_child_count_missing")
    return issues


def cover_single_moment_issues(
    row: dict[str, Any], index: int, cover_rule_contract: dict[str, Any] | None
) -> list[str]:
    """Reject explicit multi-time or multi-location staging for new contracts."""
    contract = cover_rule_contract if isinstance(cover_rule_contract, dict) else {}
    audit = contract.get("prompt_audit") if isinstance(contract.get("prompt_audit"), dict) else contract
    policy = audit.get("single_moment_scene") if isinstance(audit.get("single_moment_scene"), dict) else {}
    if not policy.get("required"):
        return []
    issues: list[str] = []
    if row.get("single_continuous_moment") is not True:
        issues.append(f"cover_{index}_single_continuous_moment_required")
    if row.get("single_physical_location") is not True:
        issues.append(f"cover_{index}_single_physical_location_required")
    if row.get("temporal_montage") is not False:
        issues.append(f"cover_{index}_temporal_montage_forbidden")
    scene_text = " ".join(
        str(row.get(key) or "")
        for key in ("scene_family", "scene", "main_action", "composition", "lighting", "scene_prompt_4_5")
    ).casefold()
    patterns = policy.get("forbidden_explicit_patterns")
    if isinstance(patterns, list) and any(str(pattern).casefold() in scene_text for pattern in patterns):
        issues.append(f"cover_{index}_explicit_multi_moment_staging_forbidden")
    return issues


def cover_primary_door_device_issues(
    row: dict[str, Any], index: int, cover_contract: dict[str, Any] | None
) -> list[str]:
    """Reject door/vehicle-door staging while allowing incidental architecture."""
    contract = cover_contract if isinstance(cover_contract, dict) else {}
    audit = contract.get("prompt_audit") if isinstance(contract.get("prompt_audit"), dict) else contract
    policy = audit.get("scene_selection_preferences") if isinstance(audit.get("scene_selection_preferences"), dict) else {}
    if policy.get("enforcement") != "hard_generation_and_validation":
        return []
    patterns = policy.get("hard_forbidden_primary_staging_patterns")
    if not isinstance(patterns, list):
        return []
    # Inspect only model-owned scene fields. The controller-owned typography
    # block legitimately says that text must not be placed on a door and must
    # never be mistaken for story staging.
    scene_text = " ".join(
        str(row.get(key) or "")
        for key in (
            "story_hook",
            "scene_family",
            "scene",
            "main_action",
            "composition",
            "scene_prompt_4_5",
        )
    )
    for pattern in patterns:
        if re.search(str(pattern), scene_text, re.I):
            return [f"cover_{index}_door_or_vehicle_door_primary_staging_forbidden"]
    return []


def cover_official_uniform_issues(
    row: dict[str, Any], index: int, cover_contract: dict[str, Any] | None
) -> list[str]:
    """Reject explicit Chinese police/public-service uniforms in visual fields.

    Plain commercial security staff remain allowed.  Negated phrases such as
    ``no government or police insignia`` are stripped before matching so the
    approved replacement wording cannot reject itself.
    """
    contract = cover_contract if isinstance(cover_contract, dict) else {}
    audit = contract.get("prompt_audit") if isinstance(contract.get("prompt_audit"), dict) else contract
    policy = audit.get("official_uniform_policy") if isinstance(audit.get("official_uniform_policy"), dict) else {}
    if policy.get("enforcement") != "hard_generation_and_validation":
        return []
    patterns = policy.get("forbidden_visual_patterns")
    if not isinstance(patterns, list):
        return []
    required_characters = row.get("required_characters")
    character_text = " ".join(str(value or "") for value in required_characters) if isinstance(required_characters, list) else ""
    visual_text = " ".join(
        [
            character_text,
            *(
                str(row.get(key) or "")
                for key in (
                    "visual_payoff",
                    "scene_family",
                    "scene",
                    "main_action",
                    "composition",
                    "scene_prompt_4_5",
                    "outpaint_environment",
                )
            ),
        ]
    )
    positive = _cover_positive_text(visual_text)
    if any(re.search(str(pattern), positive, re.I) for pattern in patterns):
        return [f"cover_{index}_official_police_or_public_service_uniform_forbidden"]
    return []


def localized_core_words_issues(
    core_words: str,
    language: str,
    index: int,
    cover_contract: dict[str, Any] | None,
) -> list[str]:
    """Reject configured grammatical classes of unidiomatic core phrases.

    This gate never rewrites output. It detects mechanical plot-noun joining,
    omitted linkers, and configured semantic-class clashes so the generator
    must produce a new idiomatic one- or two-word phrase.
    """
    contract = cover_contract if isinstance(cover_contract, dict) else {}
    audit = contract.get("prompt_audit") if isinstance(contract.get("prompt_audit"), dict) else contract
    policy = audit.get("localized_core_words") if isinstance(audit.get("localized_core_words"), dict) else {}
    if not bool(policy.get("require_idiomatic_native_phrase")):
        return []
    tokens = [
        unicodedata.normalize("NFKC", token)
        for token in re.split(r"\s+", str(core_words or "").strip())
        if token
    ]
    if len(tokens) != 2:
        return []
    aliases = {"印地语": "印地", "Hindi": "印地", "hindi": "印地"}
    language_key = aliases.get(str(language or "").strip(), str(language or "").strip())
    language_rules = policy.get("language_rules") if isinstance(policy.get("language_rules"), dict) else {}
    rules = language_rules.get(language_key) if isinstance(language_rules.get(language_key), dict) else {}
    if not rules:
        return []
    modifier, head = tokens
    if (
        modifier in {str(value) for value in rules.get("role_noun_modifiers", [])}
        and head in {str(value) for value in rules.get("relational_heads", [])}
    ):
        return [f"cover_{index}_core_words_unidiomatic_missing_linker"]
    if (
        modifier in {str(value) for value in rules.get("measure_modifiers", [])}
        and head in {str(value) for value in rules.get("evidence_heads", [])}
    ):
        return [f"cover_{index}_core_words_unidiomatic_measure_compound"]
    if (
        modifier in {str(value) for value in rules.get("literal_impairment_modifiers", [])}
        and head in {str(value) for value in rules.get("abstract_truth_heads", [])}
    ):
        return [f"cover_{index}_core_words_unidiomatic_semantic_pair"]
    return []


def _cover_task_policy(context: dict[str, Any], item: dict[str, Any], titles: list[dict[str, Any]]) -> tuple[bool, bool]:
    task = context.get("task") if isinstance(context.get("task"), dict) else {}
    identity_core = " ".join(
        str(value or "") for value in (
            task.get("channel"), task.get("nickname"), item.get("channel"), item.get("nickname"),
            task.get("drama_name"), item.get("drama_name"),
        )
    )
    female_text = identity_core + " " + str(context.get("channel_snapshot") or "")
    child_relevant_rows = []
    for row in titles:
        if title_row_requires_minor_child(row):
            child_relevant_rows.append(row)
    marketing_text = identity_core + " " + " ".join(
        str(row.get(key) or "") for row in child_relevant_rows for key in (
            "hook_a_fact", "hook_b_fact", "specificity_anchor"
        )
    )
    return "女频" in female_text, bool(CHILD_ANGLE_RE.search(marketing_text))


def has_blanket_background_text_ban(prompt: str) -> bool:
    """Reject model-authored bans on incidental environmental text.

    Only the visible cover core words are language-constrained.  Chinese text
    that naturally belongs to a Chinese location (signage, documents, boards)
    is allowed and must not be turned into a generic no-text requirement.
    """
    lower = str(prompt or "").lower()
    patterns = (
        r"without\s+readable\s+(?:words|text)",
        r"no\s+(?:new\s+)?(?:people,\s*)?(?:children,\s*)?text(?:,|\.|\s|$)",
        r"no\s+(?:other\s+)?visible\s+text(?:,|\.|\s|$)",
        r"add\s+no\s+new[^.]{0,80}\btext\b",
    )
    return any(re.search(pattern, lower) for pattern in patterns)


def normalize_cover_prompt_contract(
    payload: dict[str, Any],
    cover_rule_contract: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Assemble controller-owned style, typography, and outpaint blocks once."""
    rules = cover_rule_contract if isinstance(cover_rule_contract, dict) else load_cover_rule_bundle()
    for row in cover_rows(payload):
        scene_prompt = str(row.get("scene_prompt_4_5") or "").strip()
        row["scene_prompt_4_5"] = scene_prompt
        core = str(row.get("core_words") or "").strip()
        row["prompt_4_5"] = " ".join(
            part for part in (
                scene_prompt,
                cover_style_block(context),
                core_words_typography_clause(core, rules),
            )
            if part
        ).strip()
        environment = str(row.get("outpaint_environment") or "").strip()
        row["outpaint_environment"] = environment
        row["prompt_16_9"] = canonical_outpaint_prompt(environment)


def community_opening_cta_issues(copy: str, expected_link: str, footer: dict[str, Any] | None) -> list[str]:
    """Keep the channel's viewer CTA fixed while leaving the story body creative."""
    fixed = str((footer or {}).get("full_video_cta") or "").strip()
    if not fixed:
        return []
    first_line = next((line.strip() for line in str(copy or "").splitlines() if line.strip()), "")
    expected = f"🔥 {fixed} 👉 {expected_link}"
    return [] if first_line == expected else ["copy_full_video_cta_mismatch"]


CHANNEL_THEME_TERMS = {
    "萌宝家庭": ("孩子", "萌宝", "宝宝", "双宝", "双胞胎", "儿童", "小孩", "男孩", "女孩", "幼儿", "亲子"),
    "豪门婚恋": ("豪门", "总裁", "继承", "财阀", "集团", "董事长", "少爷", "千金", "婚姻", "结婚", "离婚", "复婚"),
    "复仇逆袭": ("复仇", "逆袭", "背叛", "陷害", "羞辱", "反击", "重生", "报复", "翻身"),
    "甜宠": ("甜宠", "心动", "恋爱", "相爱", "告白", "暗恋", "宠爱", "情侣"),
}


def packaging_brief_alignment_issues(
    prefix: str,
    result: dict[str, Any],
    brief: dict[str, Any],
) -> list[str]:
    expected = {
        "packaging_brief_id": str(brief.get("creative_slot_id") or "").strip(),
        "channel_direction": str(brief.get("channel_direction") or "").strip(),
        "core_story_promise": str(brief.get("core_story_promise") or "").strip(),
    }
    issues = []
    for key, value in expected.items():
        if not value or str(result.get(key) or "").strip() != value:
            issues.append(f"{prefix}_packaging_brief_{key}_mismatch")
    return issues


def channel_theme_alignment_issues(
    stage: str,
    payload: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    """Apply legacy theme gates only; current V14 leaves theme meaning to generation."""
    theme = context.get("channel_theme_contract") if isinstance(context.get("channel_theme_contract"), dict) else {}
    if not theme.get("plot_supported"):
        return []
    semantic = context.get("semantic_contract") if isinstance(context.get("semantic_contract"), dict) else {}
    if (
        int(semantic.get("version") or 0) >= 11
        and semantic.get("fixed_localized_title_candidates") is False
    ):
        # Current V14 uses the channel theme as generation context, not as a
        # literal-keyword contract.  A deterministic validator cannot decide
        # whether target-language copy expresses that theme by searching a few
        # Chinese audit fields, so theme meaning stays with the content model.
        # Objective packaging-brief, schema, asset, and publication checks are
        # enforced by their dedicated validators.
        return []
    direction = str(theme.get("channel_direction") or "").strip()
    configured_terms = theme.get("required_output_signals")
    base_terms = tuple(str(value) for value in configured_terms) if isinstance(configured_terms, list) else CHANNEL_THEME_TERMS.get(direction, ())
    terms = tuple(dict.fromkeys(base_terms))
    if not terms:
        return []
    if stage == "xy-title":
        rows = title_rows(payload)
        groups = [
            " ".join(str(row.get(key) or "") for key in ("hook_a_fact", "hook_b_fact", "specificity_anchor", "translation"))
            for row in rows
        ]
    elif stage == "xy-cover":
        rows = cover_rows(payload)
        groups = [
            " ".join(str(row.get(key) or "") for key in ("story_hook", "scene", "main_action", "core_words_translation"))
            for row in rows
        ]
    elif stage == "xy-place":
        result = first_result(payload)
        rows = [result]
        groups = [str(result.get("editorial_anchor") or "")]
    elif stage == "xy-post":
        rows = [row for row in (payload.get("results") or []) if isinstance(row, dict)]
        groups = [
            " ".join(str(row.get(key) or "") for key in ("selected_moment", "interaction_angle"))
            for row in rows
        ]
    else:
        return []
    missing = [index for index, text in enumerate(groups, 1) if not any(term in text for term in terms)]
    prefix = stage.removeprefix("xy-")
    issues = [f"{prefix}_{index}_channel_theme_not_prominent" for index in missing]
    if groups and len(missing) == len(groups):
        issues.insert(0, f"{prefix}_channel_theme_not_prominent")

    localized_fields_present = any("channel_theme_phrase" in row for row in rows)
    if int(semantic.get("version") or 0) < 6 and not localized_fields_present:
        return issues

    if stage == "xy-title":
        brief = first_result(payload).get("packaging_brief")
        promise = str((brief or {}).get("core_story_promise") or "") if isinstance(brief, dict) else ""
        if not any(term in promise for term in terms):
            issues.append("packaging_brief_core_story_promise_not_channel_theme")

    for index, row in enumerate(rows, 1):
        if stage == "xy-title":
            # V14 titles are built from each drama's strongest plot-supported
            # hook. They must never copy or validate against a fixed localized
            # channel-theme phrase list.
            continue
        elif stage == "xy-cover":
            # Core words are the click hook, not a surrogate channel-theme label.
            # Cover theme fit is already checked against story_hook/scene/action;
            # forcing core words to be a theme noun makes thumbnails generic.
            continue
        elif stage == "xy-place":
            phrase = str(row.get("channel_theme_phrase") or "").strip()
            publication = str(row.get("description") or "")
            issue_prefix = "place"
        else:
            phrase = str(row.get("channel_theme_phrase") or "").strip()
            copy_text = str(row.get("copy") or "")
            prompt_text = str(row.get("image_prompt_1x1") or "")
            publication = " ".join((copy_text, prompt_text))
            issue_prefix = f"post_{index}"
        if not phrase:
            issues.append(f"{issue_prefix}_localized_theme_phrase_missing")
            continue
        if stage != "xy-post" and phrase.casefold() not in publication.casefold():
            issues.append(f"{issue_prefix}_localized_theme_phrase_missing_from_publication")
    return issues


def normalize_identity(payload: dict[str, Any], item: dict[str, Any]) -> None:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return
    video_id = str(item.get("video_id") or "").strip()
    for result in results:
        if isinstance(result, dict):
            result.update(
                {
                    "search_result_index": 1,
                    "source_block_label": "搜索资料1",
                    "result_id": f"{video_id}_1" if video_id else f"{item.get('slot', '')}_1",
                    "video_id": video_id,
                    "drama_name": str(item.get("drama_name") or "").strip(),
                }
            )


def normalize_place_fixed_footer(
    payload: dict[str, Any], context: dict[str, Any], item: dict[str, Any]
) -> None:
    """Publish a deterministic playlist block and the compact frozen V14 footer."""
    assets = context.get("description_fixed_assets")
    if not isinstance(assets, dict) or not assets:
        return
    required = [
        str(assets.get("subscribe_line") or "").strip(),
        *[str(value or "").strip() for value in assets.get("disclaimer_lines") or []],
    ]
    if any(not value for value in required):
        raise ValueError("description_fixed_assets_incomplete")
    footer = "\n".join([
        required[0],
        "",
        *required[1:],
    ])
    playlists = context.get("playlists") if isinstance(context.get("playlists"), list) else []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return
    for result in results:
        if not isinstance(result, dict):
            continue
        description = str(result.get("description") or "").strip()
        description = re.sub(r"(?m)^\s*==.+?==\s*$", "", description).strip()
        footer_start = re.search(r"(?m)^\s*[💖🔔💬⚠️]", description)
        if footer_start:
            description = description[:footer_start.start()].rstrip()
        description = description.replace("[[V14_FIXED_FOOTER]]", "").rstrip()

        playlist_start = re.search(r"(?m)^\s*👇", description)
        if playlist_start and playlists:
            before_playlists = description[:playlist_start.start()].rstrip()
            playlist_text = description[playlist_start.start():]
            primary_label_match = re.search(r"(?m)^\s*👇.*$", playlist_text)
            more_label_match = re.search(r"(?m)^\s*📌.*$", playlist_text)
            primary_name = str(result.get("playlist") or "").strip()
            primary_url = public_playlist_url(str(result.get("url") or "").strip())
            normalized_playlists = [
                {
                    "name": str(row.get("name") or "").strip(),
                    "url": public_playlist_url(str(row.get("url") or "").strip()),
                }
                for row in playlists
                if isinstance(row, dict)
            ]
            primary = next(
                (
                    row for row in normalized_playlists
                    if row["name"] == primary_name and row["url"] == primary_url
                ),
                None,
            )
            if primary and primary_label_match:
                remaining = [row for row in normalized_playlists if row is not primary]
                playlist_lines = [
                    primary_label_match.group(0).strip(),
                    f"{primary['name']} 👉",
                    primary["url"],
                ]
                if remaining and more_label_match:
                    playlist_lines.extend(["", more_label_match.group(0).strip(), ""])
                    for index, row in enumerate(remaining, 1):
                        if index > 1:
                            playlist_lines.append("")
                        playlist_lines.extend([
                            f"{index}. {row['name']} 👉",
                            row["url"],
                        ])
                description = "\n\n".join(
                    part for part in (before_playlists, "\n".join(playlist_lines)) if part
                )
        result["description"] = "\n\n".join(
            part for part in (description, footer) if part
        )


def title_format_from_snapshot(snapshot: str) -> str:
    patterns = [
        r"固定标题格式：\s*`([^`]+)`",
        r"标题格式：\s*`?([^`\n]+)`?",
    ]
    for pattern in patterns:
        match = re.search(pattern, snapshot)
        if match and "A" in match.group(1) and "B" in match.group(1):
            return match.group(1).strip()
    return ""


def _title_template_parts(template: str) -> tuple[str, str, str] | None:
    """Split the final A/B placeholders without mistaking letters in labels.

    Some real channel labels contain the Latin letter A (for example TAMAMI),
    so splitting on the first ``A`` is not safe.  The placeholder A is the last
    A before the placeholder B in the fixed channel template.
    """
    match = re.match(r"^(.*)A(.*?)B(.*)$", template, flags=re.DOTALL)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def chinese_title_translation_template(snapshot: str) -> str:
    """Mirror the real channel title template for the Chinese review title."""
    template = title_format_from_snapshot(snapshot)
    if not template:
        return ""
    # The completion marker is language content, while punctuation, layout and
    # the channel-specific emoji remain exactly those of the real channel.
    return re.sub(r"【[^】]*】", "【完结】", template, count=1)


def _extract_template_values(value: str, template: str) -> tuple[str, str] | None:
    parts = _title_template_parts(template)
    if not parts:
        return None
    prefix, middle, suffix = parts
    match = re.match(
        rf"^{re.escape(prefix)}(.+?){re.escape(middle)}(.+?){re.escape(suffix)}$",
        value.strip(),
        flags=re.DOTALL,
    )
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def normalize_title_translation_format(payload: dict[str, Any], context: dict[str, Any]) -> None:
    """Let AI translate content while the controller owns the title shell."""
    snapshot = str(context.get("channel_snapshot") or "")
    target = chinese_title_translation_template(snapshot)
    parts = _title_template_parts(target)
    if not target or not parts:
        return
    prefix, middle, suffix = parts
    for row in title_rows(payload):
        value = str(row.get("translation") or "").strip()
        if not value:
            continue
        beats = _extract_template_values(value, target)
        if not beats:
            # Remove any model-supplied localized completion shell.  The
            # controller will rebuild it from the real channel template.
            body = re.sub(r"^\s*[^\w一-鿿]*【[^】]*】\s*", "", value, count=1)
            marker = re.sub(r"[!！\s]", "", middle)
            if marker and marker in body:
                left, right = body.split(marker, 1)
                beats = (left.strip(" !！"), right.strip(" !！"))
            else:
                split = re.split(r"[!！;；]", body, maxsplit=1)
                if len(split) != 2:
                    # Chinese review translations occasionally return the two
                    # clear title beats separated by a single ASCII space.
                    # The controller still owns and rebuilds the real channel
                    # shell; whitespace is only a last-resort beat boundary.
                    split = re.split(r"\s+", body, maxsplit=1)
                if len(split) == 2:
                    beats = (split[0].strip(), split[1].strip(" !！;；"))
        if beats and all(beats):
            row["translation"] = f"{prefix}{beats[0]}{middle}{beats[1]}{suffix}"


def public_playlist_url(url: str) -> str:
    value = str(url or "").strip()
    match = re.fullmatch(
        r"https?://studio\.youtube\.com/playlist/([A-Za-z0-9_-]+)(?:/videos)?/?",
        value,
        re.I,
    )
    if not match:
        return value
    return f"https://www.youtube.com/playlist?list={match.group(1)}"


def public_playlist_urls_in_text(text: str) -> str:
    return re.sub(
        r"https?://studio\.youtube\.com/playlist/[A-Za-z0-9_-]+(?:/videos)?/?",
        lambda match: public_playlist_url(match.group(0)),
        str(text or ""),
        flags=re.I,
    )


def playlists_from_snapshot(snapshot: str) -> list[dict[str, str]]:
    playlists: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in snapshot.splitlines():
        if "播放列表" not in line and "playlist" not in line.lower():
            continue
        line = re.sub(r"^.*?播放列表\s*[：:]\s*", "", line).strip()
        line = re.sub(r"^[\s>*-]*注册表允许路由\s*[：:]\s*", "", line).strip()
        for part in re.split(r"[；;]", line):
            for match in re.finditer(r"(?:播放列表：\s*)?(.+?)\s*\|\s*(https?://\S+)", part):
                name = match.group(1).strip(" -`\"'")
                raw_url = match.group(2).rstrip(".,;，；`\"')]}>")
                url = public_playlist_url(raw_url)
                if url not in seen:
                    seen.add(url)
                    playlists.append({"name": name, "url": url})
    return playlists


def place_publication_issues(
    result: dict[str, Any],
    language: str,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    if contract == {}:
        return []
    if contract is None:
        contract = load_description_rule_bundle(language, "").get("contract", {})
    issues: list[str] = []
    url = str(result.get("url") or "")
    description = str(result.get("description") or "")
    empty_playlist_url = r"https?://www\.youtube\.com/playlist\?list=(?![A-Za-z0-9_-])"
    if re.search(empty_playlist_url, url, flags=re.I):
        issues.append("playlist_url_missing_id")
    if re.search(empty_playlist_url, description, flags=re.I):
        issues.append("description_playlist_url_missing_id")
    chinese_check_exempt_languages = {
        str(value).strip().casefold()
        for value in contract.get("chinese_character_check_exempt_languages", [])
    }
    if (
        (
            contract.get("forbid_chinese_characters_in_public_description")
            or contract.get("forbid_chinese_characters_outside_final_marker")
        )
        and str(language or "").strip().casefold() not in chinese_check_exempt_languages
    ):
        public_lines = description.splitlines()
        public_body_lines = [
            line
            for line in public_lines
            if not (
                line.strip().startswith("#")
                and all(token.startswith("#") for token in line.split())
            )
        ]
        if re.search(r"[\u3400-\u9fff]", "\n".join(public_body_lines)):
            issues.append("description_contains_chinese")
    if re.search(r"(?m)^\s*==.+?==\s*$", description):
        issues.append("description_contains_internal_marker")
    if contract.get("forbid_studio_youtube_urls", True):
        if "studio.youtube.com" in url.lower():
            issues.append("playlist_studio_url_forbidden")
        if "studio.youtube.com" in description.lower():
            issues.append("description_studio_url_forbidden")
    normalized_language = str(language or "").strip().lower()
    if normalized_language not in {"英语", "英文", "english"}:
        labels = contract.get("english_template_labels_forbidden_outside_english", [])
        if any(str(label).lower() in description.lower() for label in labels):
            issues.append("description_foreign_template_label_forbidden")
    return issues


DEFAULT_MANDATORY_DESCRIPTION_HASHTAGS = ("#cdrama",)


def mandatory_description_hashtags(contract: dict[str, Any] | None = None) -> tuple[str, ...]:
    contract = contract or {}
    configured = contract.get("mandatory_hashtags")
    if isinstance(configured, list):
        values = tuple(str(value).strip() for value in configured if str(value).strip())
        if values:
            return values
    legacy = str(contract.get("mandatory_hashtag") or "").strip()
    if legacy:
        return (legacy,)
    return DEFAULT_MANDATORY_DESCRIPTION_HASHTAGS


def description_hashtag_present(description: str, hashtag: str) -> bool:
    return bool(re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(hashtag)}(?![A-Za-z0-9_])",
        description,
        flags=re.I,
    ))


def description_hashtag_tokens(description: str) -> list[str]:
    trailing = ".,;:!?，。！？、؛؛)]}》】〉”’\"'"
    return [match.rstrip(trailing) for match in re.findall(r"#[^\s#]+", description) if match.rstrip(trailing)]


def channel_hashtag_whitelist_issues(
    description: str, context: dict[str, Any]
) -> list[str]:
    whitelist = context.get("channel_hashtag_whitelist")
    if not isinstance(whitelist, dict) or not whitelist:
        return []
    tokens = description_hashtag_tokens(description)
    expected_count = int(whitelist.get("selection_count") or 12)
    issues: list[str] = []
    description_contract = (
        context.get("description_rule_contract")
        if isinstance(context.get("description_rule_contract"), dict)
        else {}
    )
    if description_contract.get("hashtag_markdown_escape_forbidden"):
        for token in tokens:
            if "\\" in token:
                issues.append(f"description_hashtag_markdown_escape_forbidden:{token}")
    if len(tokens) != expected_count:
        issues.append(f"description_hashtag_count_mismatch:{len(tokens)}!={expected_count}")
    normalized = [unicodedata.normalize("NFKC", token).casefold() for token in tokens]
    if len(normalized) != len(set(normalized)):
        issues.append("description_hashtag_duplicate")
    mandatory = [str(tag) for tag in whitelist.get("mandatory_hashtags") or []]
    for hashtag in mandatory:
        if tokens.count(hashtag) != 1:
            issues.append(f"description_mandatory_hashtag_exact_once:{hashtag}")
    cdrama_position = int(description_contract.get("cdrama_position") or 0)
    if cdrama_position and (
        len(tokens) < cdrama_position or tokens[cdrama_position - 1] != "#cdrama"
    ):
        issues.append(f"description_cdrama_position_mismatch:{cdrama_position}")
    target_positions = description_contract.get(
        "target_language_tag_required_within_positions"
    )
    target_language_tags = {
        str(tag) for tag in whitelist.get("target_language_tags") or []
    }
    if isinstance(target_positions, list) and target_positions:
        positioned_tokens = [
            tokens[position - 1]
            for position in target_positions
            if isinstance(position, int) and 0 < position <= len(tokens)
        ]
        if not target_language_tags or not any(
            token in target_language_tags for token in positioned_tokens
        ):
            issues.append("description_target_language_hashtag_missing_from_lead_positions")
    allowed = {
        unicodedata.normalize("NFKC", str(tag))
        for tag in [*mandatory, *(whitelist.get("additional_candidates") or [])]
    }
    for token in tokens:
        if unicodedata.normalize("NFKC", token) not in allowed:
            issues.append(f"description_hashtag_not_in_channel_whitelist:{token}")
    return issues


def _validate_identity(payload: dict[str, Any], item: dict[str, Any]) -> list[str]:
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return ["results_missing"]
    issues = []
    for index, result in enumerate(results, 1):
        if not isinstance(result, dict):
            issues.append(f"result_{index}_must_be_object")
            continue
        if str(result.get("drama_name") or "").strip() != str(item.get("drama_name") or "").strip():
            issues.append(f"result_{index}_drama_name_mismatch")
        if str(result.get("video_id") or "").strip() != str(item.get("video_id") or "").strip():
            issues.append(f"result_{index}_video_id_mismatch")
    return issues


def _schema_issues(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Small deterministic validator for the schema subset used by this workflow."""
    issues: list[str] = []
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return [f"{path}_must_be_object"]
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                issues.append(f"{path}.{key}_required")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    issues.append(f"{path}.{key}_unexpected")
        for key, child_schema in properties.items():
            if key in value:
                issues.extend(_schema_issues(value[key], child_schema, f"{path}.{key}"))
        return issues
    if expected == "array":
        if not isinstance(value, list):
            return [f"{path}_must_be_array"]
        if len(value) < int(schema.get("minItems", 0)):
            issues.append(f"{path}_too_few_items")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            issues.append(f"{path}_too_many_items")
        child_schema = schema.get("items", {})
        for index, child in enumerate(value):
            issues.extend(_schema_issues(child, child_schema, f"{path}[{index}]"))
        return issues
    if expected == "string" and not isinstance(value, str):
        issues.append(f"{path}_must_be_string")
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        issues.append(f"{path}_must_be_integer")
    if "enum" in schema and value not in schema["enum"]:
        issues.append(f"{path}_not_in_enum")
    return issues


def _matches_title_format(title: str, template: str) -> bool:
    parts = _title_template_parts(template)
    if not parts:
        return True
    prefix, middle, suffix = parts
    pattern = rf"^{re.escape(prefix)}.+?{re.escape(middle)}.+?{re.escape(suffix)}$"
    return bool(re.match(pattern, title))


TITLE_A_TYPES = {
    "betrayal", "humiliation", "abandonment", "theft", "forced_choice",
    "life_crisis", "child_separation", "identity_suppression", "public_attack",
    "marriage_trap", "money_power_attack", "shocking_discovery",
}
TITLE_B_TYPES = {
    "identity_reveal", "public_slapback", "revenge", "power_reversal",
    "villain_cost", "family_collapse", "regret_chase", "child_recognition",
    "marriage_reveal", "life_or_death_payoff", "wealth_reveal", "alliance_victory",
    "arrival_mystery", "relationship_mystery", "secret_object", "public_shock",
    "forced_choice_escalation", "countdown_crisis", "unseen_consequence",
}
WEAK_B_ONLY_RE = re.compile(
    r"^(?:然后|后来|最终|于是|直到)?(?:他|她|他们|我们|家人|爸爸|妈妈|CEO)?"
    r"(?:知道|发现|揭开|说出|看见|明白|认出|回来|找到|相遇|团圆|在一起|爱上|求婚|没有抛下|接受)"
    r"(?:了|我|我们|真相|一切|彼此|回家|回来|身份|孩子|女儿|儿子)*[！!。.]?$"
)

ABSTRACT_PUBLIC_PAYOFF_RE = re.compile(
    r"^(?:我)?(?:会|要|开始|展开|终于|最终|彻底)?"
    r"(?:让|叫|使)?(?:他|她|他们|所有人|全家|整个家族|仇人|坏人)?(?:全部|全都|都)?"
    r"(?:付出代价|后悔|得到报应|受到惩罚|认输|复仇|反击|逆袭|翻身|夺回一切|拿回一切|真相大白)$"
)

INTERNAL_FAMILY_NAME_RE = re.compile(r"[\u3400-\u9fff]{1,4}氏(?:集团|家族|公司)?")
INTERNAL_QUOTED_NAME_RE = re.compile(r"《[^》]{2,20}》")
INTERNAL_NAMED_ASSET_RE = re.compile(r"^([\u3400-\u9fff]{2,6})(?:计划|项目|协议|行动|工程)$")
GENERIC_PUBLIC_ASSET_PREFIXES = {
    "离婚", "婚前", "婚后", "收购", "合作", "保密", "股权", "遗产", "继承",
    "亲子", "复仇", "反击", "投资", "融资", "百亿", "千亿", "亿元", "豪门",
}

TITLE_QUESTION_RE = re.compile(
    r"[?？]|为什么|为何|怎么会|究竟(?:是|有|谁|什么|为何|为什么)|到底(?:是|有|谁|什么|为何|为什么)",
    re.I,
)


def title_question_issues(index: int, *values: str) -> list[str]:
    """AB titles are declarative double explosions, never question hooks."""
    return (
        [f"title_{index}_question_not_allowed"]
        if any(TITLE_QUESTION_RE.search(str(value or "")) for value in values)
        else []
    )


def title_marketing_issues(
    index: int,
    evidence_a: str,
    evidence_b: str,
    hook_a: str,
    hook_b: str,
    plot_source_text: str,
) -> list[str]:
    """Validate declarative A+B strength without policing reveals or endings."""
    issues: list[str] = []
    if len(_normalized_evidence(hook_a)) < 6:
        issues.append(f"title_{index}_hook_a_too_weak")
    if len(_normalized_evidence(hook_b)) < 6:
        issues.append(f"title_{index}_hook_b_too_weak")
    issues.extend(title_question_issues(index, hook_a, hook_b))
    return issues


def _plot_internal_title_terms(plot_source_text: str) -> set[str]:
    """Extract only obvious story-internal names; universal public concepts stay allowed."""
    terms = set(INTERNAL_FAMILY_NAME_RE.findall(plot_source_text))
    terms.update(INTERNAL_QUOTED_NAME_RE.findall(plot_source_text))
    return terms


def _public_anchor_is_internal_named_asset(anchor: str) -> bool:
    match = INTERNAL_NAMED_ASSET_RE.fullmatch(str(anchor or "").strip())
    return bool(match and match.group(1) not in GENERIC_PUBLIC_ASSET_PREFIXES)


def title_public_clarity_issues(
    index: int,
    public_payoff_anchor: str,
    translation: str,
    translation_template: str,
    plot_source_text: str,
) -> list[str]:
    """Require a concrete public B promise and reject story-internal naming."""
    issues: list[str] = []
    anchor = str(public_payoff_anchor or "").strip()
    normalized_anchor = _normalized_evidence(anchor)
    if len(normalized_anchor) < 2:
        issues.append(f"title_{index}_public_payoff_anchor_missing")
    elif ABSTRACT_PUBLIC_PAYOFF_RE.fullmatch(normalized_anchor):
        issues.append(f"title_{index}_public_payoff_anchor_abstract")

    internal_terms = _plot_internal_title_terms(plot_source_text)
    if _public_anchor_is_internal_named_asset(anchor) or any(term and term in anchor for term in internal_terms):
        issues.append(f"title_{index}_cold_viewer_internal_term")
    return issues


def _normalized_evidence(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE).lower()


def _text_similarity(left: str, right: str) -> float:
    """Return a language-agnostic near-copy score for creative QA.

    Channel-language text is compared through its Chinese review fields where
    available.  English visual blueprints are compared directly.  This is not
    used for plot facts; it only guards authored marketing concepts.
    """
    a = _normalized_evidence(left)
    b = _normalized_evidence(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _history_result(entry: dict[str, Any], key: str) -> dict[str, Any]:
    payload = entry.get(key)
    return first_result(payload) if isinstance(payload, dict) else {}


def _history_results(entry: dict[str, Any], key: str) -> list[dict[str, Any]]:
    payload = entry.get(key)
    rows = payload.get("results") if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def creative_collision_issues(
    stage: str, payload: dict[str, Any], context: dict[str, Any]
) -> list[str]:
    """Reject reuse of a same-drama operating concept across channels."""
    current = first_result(payload)
    history = context.get("creative_history")
    if not current or not isinstance(history, list):
        return []

    for entry in history:
        if not isinstance(entry, dict):
            continue
        if stage == "xy-title":
            previous = _history_result(entry, "title_payload")
            current_rows = current.get("directions") if isinstance(current.get("directions"), list) else []
            previous_rows = previous.get("directions") if isinstance(previous.get("directions"), list) else []
            for row in current_rows:
                for old in previous_rows:
                    same_types = (
                        str(row.get("hook_a_type") or "") == str(old.get("hook_a_type") or "")
                        and str(row.get("hook_b_type") or "") == str(old.get("hook_b_type") or "")
                    )
                    same_copy = _text_similarity(
                        str(row.get("title") or ""), str(old.get("title") or "")
                    ) >= 0.72
                    same_anchor = _text_similarity(
                        str(row.get("specificity_anchor") or ""), str(old.get("specificity_anchor") or "")
                    ) >= 0.50
                    if same_copy or (same_types and same_anchor):
                        return ["title_cross_channel_package_collision"]

        elif stage == "xy-cover":
            previous = _history_result(entry, "cover_payload")
            current_rows = current.get("titles") if isinstance(current.get("titles"), list) else []
            previous_rows = previous.get("titles") if isinstance(previous.get("titles"), list) else []
            fields = (
                "story_hook", "scene_family", "main_action", "key_prop",
                "composition", "palette", "lighting",
            )
            for row in current_rows:
                for old in previous_rows:
                    close_fields = {
                        key for key in fields
                        if _text_similarity(str(row.get(key) or ""), str(old.get(key) or "")) >= 0.48
                    }
                    scene_action = {"scene_family", "main_action"}.issubset(close_fields)
                    narrative_and_blocking = (
                        "composition" in close_fields
                        and ("scene_family" in close_fields or "main_action" in close_fields)
                    )
                    prompt_copy = _text_similarity(
                        str(row.get("prompt_4_5") or ""), str(old.get("prompt_4_5") or "")
                    ) >= 0.70
                    if scene_action or narrative_and_blocking or prompt_copy:
                        return ["cover_cross_channel_package_collision"]

        elif stage == "xy-place":
            previous = _history_result(entry, "place_payload")
            same_signature = (
                str(current.get("opening_hook_type") or "")
                and str(current.get("opening_hook_type") or "") == str(previous.get("opening_hook_type") or "")
                and str(current.get("payoff_hook_type") or "") == str(previous.get("payoff_hook_type") or "")
                and _text_similarity(
                    str(current.get("editorial_anchor") or ""), str(previous.get("editorial_anchor") or "")
                ) >= 0.30
            )
            if _text_similarity(
                str(current.get("description") or ""), str(previous.get("description") or "")
            ) >= 0.70 or same_signature:
                return ["place_cross_channel_package_collision"]

        elif stage == "xy-post":
            current_rows = [row for row in (payload.get("results") or []) if isinstance(row, dict)]
            previous_rows = _history_results(entry, "post_payload")
            for current_plan in current_rows:
                for previous in previous_rows:
                    same_signature = (
                        str(current_plan.get("community_hook_type") or "")
                        and str(current_plan.get("community_hook_type") or "") == str(previous.get("community_hook_type") or "")
                        and _text_similarity(str(current_plan.get("selected_moment") or ""), str(previous.get("selected_moment") or "")) >= 0.35
                        and _text_similarity(str(current_plan.get("interaction_angle") or ""), str(previous.get("interaction_angle") or "")) >= 0.30
                    )
                    copy_collision = _text_similarity(str(current_plan.get("copy") or ""), str(previous.get("copy") or "")) >= 0.62
                    image_collision = _text_similarity(str(current_plan.get("image_prompt_1x1") or ""), str(previous.get("image_prompt_1x1") or "")) >= 0.68
                    if copy_collision or image_collision or same_signature:
                        return ["post_cross_channel_package_collision"]
    return []


def visual_history_collision_issues(
    current_rows: list[dict[str, Any]], history: list[dict[str, Any]]
) -> list[str]:
    """Reject semantic reuse of any accepted V2 visual blueprint.

    Historical fields are AI-authored phrases, so exact normalized equality is
    not sufficient: small wording changes can describe the same thumbnail.
    Return the first precise collision so the cover retry can redesign it.
    """
    fields = ("scene_family", "main_action", "key_prop", "composition", "palette", "lighting")
    thresholds = {
        "scene_family": 0.48,
        "main_action": 0.48,
        "key_prop": 0.48,
        "composition": 0.48,
        "palette": 0.48,
        "lighting": 0.48,
    }
    for current_index, current in enumerate(current_rows, 1):
        if not isinstance(current, dict):
            continue
        for history_index, previous in enumerate(history, 1):
            if not isinstance(previous, dict):
                continue
            close = [
                key for key in fields
                if _text_similarity(str(current.get(key) or ""), str(previous.get(key) or ""))
                >= thresholds[key]
            ]
            scene_action = {"scene_family", "main_action"}.issubset(close)
            narrative_and_blocking = (
                "composition" in close
                and ("scene_family" in close or "main_action" in close)
            )
            # Props, palette, and lighting are supporting metadata.  They may
            # recur naturally and cannot reject a genuinely different story
            # moment by themselves.
            if scene_action or narrative_and_blocking:
                identity = ":".join(
                    filter(None, [
                        str(previous.get("channel") or ""),
                        str(previous.get("drama_name") or ""),
                        str(previous.get("video_id") or ""),
                    ])
                ) or "unknown"
                source_group = str(previous.get("source_group_index") or "").strip()
                if source_group:
                    identity += f":group{source_group}"
                return [
                    f"cover_{current_index}_visual_collision_with_history_{history_index}"
                    f"_fields_{'_'.join(close)}_source_{identity}"
                ]
    return []


def _plot_source_text(context: dict[str, Any]) -> str:
    payload = context.get("plot_payload") if isinstance(context.get("plot_payload"), dict) else {}
    result = first_result(payload)
    fields = result.get("plot_fields") if isinstance(result.get("plot_fields"), dict) else {}
    return "\n".join(str(fields.get(key) or "") for key in ("内容概述", "剧情档案", "剧情套路", "核心人设"))


def _numeric_grounding_issues(index: int, evidence: str, localized_title: str) -> list[str]:
    """Catch the frequent Chinese 亿 -> billion tenfold mistranslation."""
    issues: list[str] = []
    for match in re.finditer(r"(?<!\d)(\d+(?:\.\d+)?)\s*亿", evidence):
        chinese_hundred_millions = float(match.group(1))
        expected_billions = chinese_hundred_millions / 10.0
        wrong_token = f"{chinese_hundred_millions:g}"
        expected_token = (f"{expected_billions:.6f}").rstrip("0").rstrip(".")
        # In a localized title containing a billion-unit word, retaining the
        # raw 亿 count is a tenfold error unless both numbers are identical.
        if expected_token != wrong_token and re.search(r"(?:billions?|миллиард(?:а|ов)?|bilh(?:ão|ões)|milyar|miliar|mil millones)", localized_title, re.I):
            numbers = re.findall(r"(?<!\d)\d+(?:[.,]\d+)?", localized_title)
            normalized = {number.replace(",", ".") for number in numbers}
            if wrong_token in normalized and expected_token not in normalized:
                issues.append(f"title_{index}_numeric_unit_mistranslation_{wrong_token}yi_is_{expected_token}billion")
    return issues


def validate_title(payload: dict[str, Any], item: dict[str, Any], context: dict[str, Any]) -> list[str]:
    issues = _validate_identity(payload, item)
    if int(item.get("workflow_contract_version") or 1) >= 2:
        brief = first_result(payload).get("packaging_brief")
        theme = context.get("channel_theme_contract") if isinstance(context.get("channel_theme_contract"), dict) else {}
        if not isinstance(brief, dict):
            issues.append("packaging_brief_missing")
        else:
            expected_slot = str((context.get("creative_slot") or {}).get("creative_slot_id") or "").strip()
            if expected_slot and str(brief.get("creative_slot_id") or "").strip() != expected_slot:
                issues.append("packaging_brief_creative_slot_id_mismatch")
            expected_direction = str(theme.get("channel_direction") or "").strip()
            if expected_direction and str(brief.get("channel_direction") or "").strip() != expected_direction:
                issues.append("packaging_brief_channel_direction_mismatch")
            for key in (
                "creative_slot_id", "core_story_promise", "audience_emotion", "information_gap", "title_role",
                "thumbnail_role", "truth_constraints", "avoid_repetition",
            ):
                if len(_normalized_evidence(str(brief.get(key) or ""))) < 4:
                    issues.append(f"packaging_brief_{key}_too_weak")
    rows = title_rows(payload)
    title_contract = context.get("title_rule_contract") if isinstance(context.get("title_rule_contract"), dict) else {}
    required_count = int(title_contract.get("required_direction_count", 3))
    if len(rows) != required_count:
        return issues + [f"title_count={len(rows)}_expected={required_count}"]
    template = title_format_from_snapshot(str(context.get("channel_snapshot") or ""))
    translation_template = chinese_title_translation_template(str(context.get("channel_snapshot") or ""))
    raw_plot_text = _plot_source_text(context)
    plot_text = _normalized_evidence(raw_plot_text)
    task = context.get("task") if isinstance(context.get("task"), dict) else {}
    global_child_required = global_child_plan_required(item, context)
    titles = []
    recommendation_scores: list[int] = []
    a_types: list[str] = []
    b_types: list[str] = []
    anchors: list[str] = []
    for expected, row in enumerate(rows, 1):
        title = str(row.get("title") or "").strip()
        titles.append(title)
        if int(row.get("index") or 0) != expected:
            issues.append(f"title_{expected}_index_mismatch")
        if not title:
            issues.append(f"title_{expected}_blank")
        else:
            issues.extend(title_length_issues(title, expected, title_contract))
        if title and not _matches_title_format(title, template):
            issues.append(f"title_{expected}_format_mismatch")
        translation = str(row.get("translation") or "").strip()
        issues.extend(title_question_issues(expected, title))
        hook_a_type = str(row.get("hook_a_type") or "").strip()
        hook_b_type = str(row.get("hook_b_type") or "").strip()
        hook_a = str(row.get("hook_a_fact") or "").strip()
        hook_b = str(row.get("hook_b_fact") or "").strip()
        evidence_a = str(row.get("hook_a_evidence") or "").strip()
        evidence_b = str(row.get("hook_b_evidence") or "").strip()
        anchor = str(row.get("specificity_anchor") or "").strip()
        public_payoff_anchor = str(row.get("public_payoff_anchor") or "").strip()
        visual_thesis = str(row.get("visual_thesis") or "").strip()
        if len(_normalized_evidence(visual_thesis)) < 8:
            issues.append(f"title_{expected}_visual_thesis_too_weak")
        recommendation_score = int(row.get("recommendation_score") or 0)
        recommendation_scores.append(recommendation_score)
        if not 1 <= recommendation_score <= 100:
            issues.append(f"title_{expected}_recommendation_score_out_of_range")
        issues.extend(title_direction_child_policy_issues(expected, row, global_child_required))
        a_types.append(hook_a_type)
        b_types.append(hook_b_type)
        anchors.append(_normalized_evidence(anchor))
        if hook_a_type not in TITLE_A_TYPES:
            issues.append(f"title_{expected}_invalid_hook_a_type")
        if hook_b_type not in TITLE_B_TYPES:
            issues.append(f"title_{expected}_invalid_hook_b_type")
        if len(_normalized_evidence(anchor)) < 2:
            issues.append(f"title_{expected}_specificity_anchor_missing")
        issues.extend(title_marketing_issues(expected, evidence_a, evidence_b, hook_a, hook_b, plot_text))
        if bool(title_contract.get("require_public_payoff_anchor")):
            issues.extend(title_public_clarity_issues(
                expected,
                public_payoff_anchor,
                translation,
                translation_template,
                raw_plot_text,
            ))
        issues.extend(_numeric_grounding_issues(expected, evidence_a + " " + evidence_b, title))
        row["char_count"] = len(title)
    if len(set(titles)) != 3:
        issues.append("titles_not_unique")
    if len(set(recommendation_scores)) != 3:
        issues.append("title_recommendation_scores_not_unique")
    if (
        recommendation_scores
        and not _has_partial_market_coverage(context, len(rows))
        and recommendation_scores[0] != max(recommendation_scores)
    ):
        issues.append("title_strongest_recommendation_not_first")
    if len(set(a_types)) < 2:
        issues.append("title_A_hook_types_not_diverse")
    if len(set(b_types)) < 2:
        issues.append("title_B_payoff_types_not_diverse")
    if len({value for value in anchors if value}) != 3:
        issues.append("title_specificity_anchors_not_unique")
    result = first_result(payload)
    supplied_direct = result.get("direct_titles")
    if supplied_direct != titles:
        issues.append("direct_titles_mismatch")
    result["direct_titles"] = titles
    return issues


def validate_cover(payload: dict[str, Any], item: dict[str, Any], context: dict[str, Any]) -> list[str]:
    issues = _validate_identity(payload, item)
    rows = cover_rows(payload)
    title_payload = context.get("title_payload") if isinstance(context.get("title_payload"), dict) else {}
    titles = title_rows(title_payload)
    if int(item.get("workflow_contract_version") or 1) >= 2:
        brief = first_result(title_payload).get("packaging_brief")
        issues.extend(packaging_brief_alignment_issues(
            "cover", first_result(payload), brief if isinstance(brief, dict) else {}
        ))
    if len(rows) != 3:
        return issues + [f"cover_count={len(rows)}_expected=3"]
    required_face = visual_cast_contract(context)["identity"].split(", ")
    fingerprint_keys = ("scene_family", "main_action", "key_prop", "composition", "palette", "lighting")
    fingerprints: list[dict[str, str]] = []
    core_word_keys: list[str] = []
    female_frequency, _ = _cover_task_policy(context, item, titles)
    child_requirements = cover_group_child_requirements(item, context, titles)
    cover_contract = (
        context.get("cover_rule_contract")
        if isinstance(context.get("cover_rule_contract"), dict)
        else load_cover_rule_bundle()
    )
    for expected, row in enumerate(rows, 1):
        if int(row.get("title_index") or 0) != expected:
            issues.append(f"cover_{expected}_index_mismatch")
        expected_title = str((titles[expected - 1] if len(titles) >= expected else {}).get("title") or "").strip()
        expected_visual_thesis = str((titles[expected - 1] if len(titles) >= expected else {}).get("visual_thesis") or "").strip()
        if str(row.get("title") or "").strip() != expected_title:
            issues.append(f"cover_{expected}_title_mismatch")
        if str(row.get("visual_thesis") or "").strip() != expected_visual_thesis:
            issues.append(f"cover_{expected}_visual_thesis_mismatch")
        core = str(row.get("core_words") or "").strip()
        core_word_keys.append(
            " ".join(unicodedata.normalize("NFKC", core).casefold().split())
        )
        # Core words are authored in the channel language.  Counting Unicode
        # ``\w`` runs is incorrect for scripts such as Bengali because vowel
        # signs and other combining marks split one visible word into several
        # regex runs.  The business rule is one or two independent words, and
        # those words are separated by whitespace in the generated cover text.
        tokens = [token for token in re.split(r"\s+", core) if token]
        if len(tokens) not in {1, 2}:
            issues.append(f"cover_{expected}_core_words_must_be_1_or_2")
        issues.extend(localized_core_words_issues(
            core,
            str(item.get("language") or context.get("task", {}).get("language") or ""),
            expected,
            cover_contract,
        ))
        fingerprint = {key: _normalized_evidence(str(row.get(key) or "")) for key in fingerprint_keys}
        fingerprints.append(fingerprint)
        for key, value in fingerprint.items():
            if len(value) < 3:
                issues.append(f"cover_{expected}_{key}_missing")
        if len(_normalized_evidence(str(row.get("story_hook") or ""))) < 8:
            issues.append(f"cover_{expected}_story_hook_too_weak")
        prompt_4_5 = str(row.get("prompt_4_5") or "").strip()
        if not prompt_4_5:
            issues.append(f"cover_{expected}_prompt_4_5_blank")
        for phrase in required_face:
            if phrase not in prompt_4_5:
                issues.append(f"cover_{expected}_prompt_4_5_missing_{phrase.replace(' ', '_')}")
        if core and core not in prompt_4_5:
            issues.append(f"cover_{expected}_prompt_4_5_missing_exact_core_words")
        if core and has_diegetic_core_word_placement(prompt_4_5, core):
            issues.append(f"cover_{expected}_prompt_4_5_core_words_diegetic_placement")
        wide_prompt = str(row.get("prompt_16_9") or "").strip()
        if not wide_prompt:
            issues.append(f"cover_{expected}_prompt_16_9_blank")
        if core and CORE_WORDS_TYPOGRAPHY_MARKER not in str(row.get("prompt_4_5") or "").lower():
            issues.append(f"cover_{expected}_prompt_4_5_core_words_not_non_diegetic_typography")
        if core and CORE_WORDS_SALIENCE_MARKER not in str(row.get("prompt_4_5") or "").lower():
            issues.append(f"cover_{expected}_prompt_4_5_core_words_not_visually_salient")
        issues.extend(cover_prompt_structure_issues(row, expected, context))
        issues.extend(cover_prompt_quality_issues(prompt_4_5, expected, cover_contract))
        issues.extend(cover_primary_door_device_issues(row, expected, cover_contract))
        issues.extend(cover_official_uniform_issues(row, expected, cover_contract))
        child_required = child_requirements[expected - 1] if len(child_requirements) >= expected else False
        issues.extend(cover_generation_plan_issues(row, expected, child_required, cover_contract))
        issues.extend(cover_single_moment_issues(row, expected, cover_contract))
        issues.extend(cover_policy_issues(prompt_4_5, expected, female_frequency, child_required))
        wide = str(row.get("prompt_16_9") or "").lower()
        if not any(word in wide for word in ("outpaint", "expand", "extend")):
            issues.append(f"cover_{expected}_16_9_not_expansion_prompt")
        for required_wide_phrase in ("pixel-for-pixel", "left and 1056px right side bands", "environmental extension only"):
            if required_wide_phrase not in wide:
                issues.append(f"cover_{expected}_16_9_execution_contract_missing")
        for key in ("prompt_4_5", "prompt_16_9"):
            if has_blanket_background_text_ban(str(row.get(key) or "")):
                issues.append(f"cover_{expected}_{key}_blanket_background_text_ban")
    if bool(
        cover_contract.get("prompt_audit", {}).get(
            "core_words_unique_across_three_groups", False
        )
    ) and len(core_word_keys) == 3 and len(set(core_word_keys)) != 3:
        issues.append("cover_current_drama_core_words_not_distinct")
    # Scene moment, physical action, and camera blocking must differ.  Props,
    # palette, and lighting are metadata for history checks, not novelty quotas:
    # forcing all six to differ was the source of invented gadgets and colors.
    for key in ("scene_family", "main_action", "composition"):
        values = [row[key] for row in fingerprints]
        if len(set(values)) != 3:
            issues.append(f"cover_current_drama_{key}_not_distinct")
    history = context.get("visual_history") if isinstance(context.get("visual_history"), list) else []
    for current_index, current in enumerate(fingerprints, 1):
        for history_index, previous in enumerate(history, 1):
            if not isinstance(previous, dict):
                continue
            prior = {key: _normalized_evidence(str(previous.get(key) or "")) for key in fingerprint_keys}
            same = [key for key in fingerprint_keys if current.get(key) and current.get(key) == prior.get(key)]
            scene_action = {"scene_family", "main_action"}.issubset(same)
            narrative_and_blocking = (
                "composition" in same
                and ("scene_family" in same or "main_action" in same)
            )
            if scene_action or narrative_and_blocking:
                issues.append(
                    f"cover_{current_index}_visual_collision_with_history_{history_index}_same_{'_'.join(same)}"
                )
                break
    if not issues:
        issues.extend(visual_history_collision_issues(rows, history))
    return issues


def validate_place(payload: dict[str, Any], item: dict[str, Any], context: dict[str, Any]) -> list[str]:
    issues = _validate_identity(payload, item)
    result = first_result(payload)
    if int(item.get("workflow_contract_version") or 1) >= 2:
        title_payload = context.get("title_payload") if isinstance(context.get("title_payload"), dict) else {}
        brief = first_result(title_payload).get("packaging_brief")
        issues.extend(packaging_brief_alignment_issues(
            "place", result, brief if isinstance(brief, dict) else {}
        ))
    signature_values = (
        str(result.get("opening_hook_type") or "").strip(),
        str(result.get("payoff_hook_type") or "").strip(),
        str(result.get("editorial_anchor") or "").strip(),
    )
    if not all(signature_values):
        issues.append("place_creative_signature_blank")
    else:
        if signature_values[0] not in TITLE_A_TYPES:
            issues.append("place_opening_hook_type_invalid")
        if signature_values[1] not in TITLE_B_TYPES:
            issues.append("place_payoff_hook_type_invalid")
        if len(_normalized_evidence(signature_values[2])) < 6:
            issues.append("place_editorial_anchor_too_weak")
    for key in ("playlist", "url", "description"):
        if not str(result.get(key) or "").strip():
            issues.append(f"place_{key}_blank")
    playlists = context.get("playlists") if isinstance(context.get("playlists"), list) else []
    if playlists:
        pair = (str(result.get("playlist") or "").strip(), str(result.get("url") or "").strip())
        allowed = {(str(row.get("name") or "").strip(), str(row.get("url") or "").strip()) for row in playlists}
        if pair not in allowed:
            issues.append("playlist_not_in_channel_snapshot")
        description = str(result.get("description") or "")
        for playlist_index, row in enumerate(playlists, 1):
            name = str(row.get("name") or "").strip()
            url = str(row.get("url") or "").strip()
            if not name or not url or name not in description or url not in description:
                issues.append(f"description_missing_registered_playlist_{playlist_index}")
    description = str(result.get("description") or "")
    description_contract = (
        context.get("description_rule_contract")
        if isinstance(context.get("description_rule_contract"), dict)
        else None
    )
    for mandatory_hashtag in mandatory_description_hashtags(description_contract):
        if description_hashtag_present(description, mandatory_hashtag):
            continue
        issue_suffix = re.sub(r"[^a-z0-9]+", "", mandatory_hashtag.lower())
        issues.append(f"description_missing_{issue_suffix}")
    issues.extend(channel_hashtag_whitelist_issues(description, context))
    issues.extend(place_publication_issues(
        result,
        str(item.get("language") or context.get("task", {}).get("language") or ""),
        description_contract,
    ))
    fixed_assets = context.get("description_fixed_assets")
    if isinstance(fixed_assets, dict) and fixed_assets:
        fixed_values = [
            fixed_assets.get("subscribe_line"),
            *list(fixed_assets.get("disclaimer_lines") or []),
        ]
        for index, value in enumerate(fixed_values, 1):
            if str(value or "").strip() and str(value).strip() not in description:
                issues.append(f"description_missing_fixed_asset_{index}")
    return issues


def validate_post(payload: dict[str, Any], item: dict[str, Any], context: dict[str, Any]) -> list[str]:
    issues = _validate_identity(payload, item)
    results = payload.get("results") if isinstance(payload, dict) else []
    is_multi_v2 = int(item.get("community_output_version") or 0) >= 2 or "community_count" in item
    expected_count = int(item.get("community_count", 1) or 0) if is_multi_v2 else 1
    if len(results) != expected_count:
        issues.append(f"post_count={len(results)}_expected={expected_count}")
    expected_link = "【视频链接待补】" if str(item.get("video_id") or "").startswith("pending_") else f"https://youtu.be/{item.get('video_id', '')}"
    fingerprints = []
    footer = context.get("community_footer_cta")
    title_payload = context.get("title_payload") if isinstance(context.get("title_payload"), dict) else {}
    brief = first_result(title_payload).get("packaging_brief")
    for expected_index, result in enumerate(results, 1):
        prefix = f"post_{expected_index}"
        if int(item.get("workflow_contract_version") or 1) >= 2:
            issues.extend(packaging_brief_alignment_issues(
                prefix, result, brief if isinstance(brief, dict) else {}
            ))
        if is_multi_v2 and int(result.get("plan_index") or 0) != expected_index:
            issues.append(f"{prefix}_plan_index_mismatch")
        signature_values = tuple(
            str(result.get(key) or "").strip()
            for key in ("community_hook_type", "selected_moment", "interaction_angle")
        )
        if not all(signature_values):
            issues.append(f"{prefix}_creative_signature_blank")
        else:
            if len(_normalized_evidence(signature_values[1])) < 6:
                issues.append(f"{prefix}_selected_moment_too_weak")
            if len(_normalized_evidence(signature_values[2])) < 6:
                issues.append(f"{prefix}_interaction_angle_too_weak")
        prompt = str(result.get("image_prompt_1x1") or "").strip()
        copy = str(result.get("copy") or "").strip()
        if not prompt:
            issues.append(f"{prefix}_image_prompt_blank")
        style_contract = context.get("community_rule_contract")
        if isinstance(style_contract, dict) and style_contract.get("image_style"):
            issues.extend(image_prompt_style_issues(prompt, prefix, style_contract["image_style"]))
        cast = visual_cast_contract(context)
        for phrase in (cast["community_face"], cast["community_cast"]):
            if phrase not in prompt:
                issues.append(f"{prefix}_prompt_missing_{phrase.replace(' ', '_')}")
        if not copy:
            issues.append(f"{prefix}_copy_blank")
        if copy.count(expected_link) != 1:
            issues.append(f"{prefix}_copy_requires_exactly_one_video_link")
        if re.search(r"\[[^\]]+\]\(https?://", copy):
            issues.append(f"{prefix}_copy_markdown_link_forbidden")
        copy_without_placeholder = copy.replace("【视频链接待补】", "")
        if re.search(r"[\u3400-\u9fff]", copy_without_placeholder):
            issues.append(f"{prefix}_copy_contains_chinese")
        for emoji in ("🔥", "👉", "🤔", "👇", "🔔", "🙏"):
            if emoji not in copy:
                issues.append(f"{prefix}_copy_missing_{emoji}")
        if len([line for line in copy.splitlines() if line.strip()]) < 8:
            issues.append(f"{prefix}_copy_too_short")
        if isinstance(footer, dict) and footer:
            subscribe = str(footer.get("subscribe_cta") or "").strip()
            share = str(footer.get("share_cta") or "").strip()
            layout = str(footer.get("layout_style") or "").strip()
            for label, value in (("subscribe", subscribe), ("share", share)):
                if value and value not in copy:
                    issues.append(f"{prefix}_copy_missing_fixed_{label}_cta")
                if value and value not in prompt:
                    issues.append(f"{prefix}_prompt_missing_fixed_{label}_cta")
            if layout and layout not in prompt:
                issues.append(f"{prefix}_prompt_missing_fixed_layout_style")
            issues.extend(
                f"{prefix}_{issue}"
                for issue in community_opening_cta_issues(copy, expected_link, footer)
            )
        if is_multi_v2:
            for key in ("scene_family", "main_action", "key_prop", "composition", "palette"):
                if not str(result.get(key) or "").strip():
                    issues.append(f"{prefix}_{key}_blank")
        fingerprints.append(tuple(_normalized_evidence(str(result.get(key) or "")) for key in (
            "selected_moment", "interaction_angle", "scene_family", "main_action", "key_prop", "composition", "palette"
        )))
    if not is_multi_v2 and results and not all(str(results[0].get(key) or "").strip() for key in ("community_hook_type", "selected_moment", "interaction_angle")):
        issues.append("post_creative_signature_blank")
    for left in range(len(results) if is_multi_v2 else 0):
        for right in range(left + 1, len(results)):
            close_fields = sum(
                _normalized_evidence(str(results[left].get(key) or ""))
                == _normalized_evidence(str(results[right].get(key) or ""))
                for key in ("selected_moment", "interaction_angle", "scene_family", "main_action", "key_prop", "composition", "palette")
            )
            copy_close = _text_similarity(str(results[left].get("copy") or ""), str(results[right].get("copy") or "")) >= 0.62
            image_close = _text_similarity(str(results[left].get("image_prompt_1x1") or ""), str(results[right].get("image_prompt_1x1") or "")) >= 0.68
            if close_fields >= 3 or (close_fields >= 2 and (copy_close or image_close)):
                issues.append(f"post_internal_plan_collision_{left + 1}_{right + 1}")
    return issues


VALIDATORS = {
    "xy-title": validate_title,
    "xy-cover": validate_cover,
    "xy-place": validate_place,
    "xy-post": validate_post,
}


def validate_model_output_schema(
    stage: str,
    payload: dict[str, Any],
    item: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    """Validate the model-owned response before controller normalization.

    Controller normalization may intentionally add canonical output fields that
    are forbidden in the model response schema.  Those fields must never be
    sent back through this model-boundary validator.
    """
    frozen_schema = context.get("output_schema") if isinstance(context.get("output_schema"), dict) else None
    schema = frozen_schema or (schema_for(stage, item) if stage in SCHEMAS else None)
    return _schema_issues(payload, schema) if schema else []


def validate_payload(
    stage: str,
    payload: dict[str, Any],
    item: dict[str, Any],
    context: dict[str, Any],
    *,
    validate_schema: bool = True,
) -> list[str]:
    validator = VALIDATORS.get(stage)
    issues = validate_model_output_schema(stage, payload, item, context) if validate_schema else []
    if issues:
        return issues
    issues = validator(payload, item, context) if validator else []
    if int(item.get("workflow_contract_version") or 1) >= 2:
        issues.extend(channel_theme_alignment_issues(stage, payload, context))
    if not issues:
        issues.extend(creative_collision_issues(stage, payload, context))
    return issues


def render_find(payload: dict[str, Any]) -> str:
    result = first_result(payload)
    fields = result.get("plot_fields") if isinstance(result.get("plot_fields"), dict) else {}
    parts = []
    for key in ("内容概述", "剧情档案", "剧情套路", "核心人设"):
        value = str(fields.get(key) or "").strip()
        if value:
            parts.append(f"【{key}】\n{value}")
    return (
        "# 搜索资料\n\n"
        f"剧名：{result.get('drama_name', '')}\n"
        f"- 别名：{result.get('alias', '')}\n\n"
        "## 剧情\n"
        + "\n\n".join(parts)
        + "\n"
    )


def render_title(payload: dict[str, Any]) -> str:
    result = first_result(payload)
    lines = [
        "# 标题方案",
        "",
        "搜索资料1：",
        f"source_block_label：{result.get('source_block_label', '')}",
        f"video_id：{result.get('video_id', '')}",
        f"id：{result.get('result_id', '')}",
        f"剧名：{result.get('drama_name', '')}",
        "",
    ]
    for row in title_rows(payload):
        index = row.get("index", "")
        lines.extend(
            [
                f"方向{index}：{row.get('direction', '')}",
                f"标题{index}：{row.get('title', '')}",
                f"翻译：{row.get('translation', '')}",
                f"Visual Thesis：{row.get('visual_thesis', '')}",
                f"字符数：{row.get('char_count', '')}",
                "",
            ]
        )
    lines.extend(["复制数据：", *[str(row.get("title") or "") for row in title_rows(payload)], ""])
    return "\n".join(lines)


def render_cover(payload: dict[str, Any]) -> str:
    result = first_result(payload)
    lines = [
        f"剧名1：{result.get('drama_name', '')}",
        f"source_block_label：{result.get('source_block_label', '')}",
        f"video_id：{result.get('video_id', '')}",
        f"id：{result.get('result_id', '')}",
        "",
    ]
    for row in cover_rows(payload):
        index = row.get("title_index", "")
        lines.extend(
            [
                f"标题{index}：{row.get('title', '')}",
                f"标题翻译：{row.get('title_translation', '')}",
                f"核心词：{row.get('core_words', '')}",
                f"核心词翻译：{row.get('core_words_translation', '')}",
                f"Visual Thesis：{row.get('visual_thesis', '')}",
                "4:5场景底稿：",
                str(row.get("scene_prompt_4_5") or ""),
                "4:5封面：",
                str(row.get("prompt_4_5") or ""),
                "16:9封面：",
                str(row.get("prompt_16_9") or ""),
                "",
            ]
        )
    return "\n".join(lines)


def render_place(payload: dict[str, Any]) -> str:
    result = first_result(payload)
    return "\n".join(
        [
            "# 播放列表",
            "",
            f"source_block_label：{result.get('source_block_label', '')}",
            f"video_id：{result.get('video_id', '')}",
            f"id：{result.get('result_id', '')}",
            f"剧名：{result.get('drama_name', '')}",
            f"播放列表：{result.get('playlist', '')}",
            f"地址：{result.get('url', '')}",
            "说明：",
            str(result.get("description") or ""),
            "翻译：",
            str(result.get("translation") or ""),
            "",
        ]
    )


def render_post(payload: dict[str, Any]) -> str:
    lines = ["# 社群", ""]
    for index, result in enumerate(payload.get("results") or [], 1):
        lines.extend([
            f"## 社群方案{index}", "",
            f"剧名{index}：{result.get('drama_name', '')}",
            f"source_block_label：{result.get('source_block_label', '')}",
            f"video_id：{result.get('video_id', '')}",
            f"id：{result.get('result_id', '')}", "",
            "社群图 1：1：", str(result.get("image_prompt_1x1") or ""), "",
            "社群文案：", str(result.get("copy") or ""), "",
            "社群文案翻译：", str(result.get("copy_translation") or ""), "",
        ])
    return "\n".join(lines)


RENDERERS = {
    "xy-find": render_find,
    "xy-title": render_title,
    "xy-cover": render_cover,
    "xy-place": render_place,
    "xy-post": render_post,
}


def write_stage_outputs(package: Path, stage: str, payload: dict[str, Any]) -> tuple[Path, Path]:
    json_name, markdown_name = STAGE_FILES[stage]
    json_path = package / json_name
    markdown_path = package / markdown_name
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(RENDERERS[stage](payload), encoding="utf-8")
    return json_path, markdown_path
