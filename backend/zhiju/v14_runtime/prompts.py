"""V14 pure prompt construction extracted from deterministic_batch.py (2026-10-17)."""
from __future__ import annotations
import copy
import json
import re
from typing import Any
from .canonical import first_result, title_rows, cover_rows, title_format_from_snapshot, public_playlist_urls_in_text, title_row_requires_minor_child, cover_group_child_requirements
from .rules import load_description_rule_bundle
from .channel import title_channel_context

def normalized_description_fixed_assets(context: dict[str, Any]) -> dict[str, Any]:
    """Return the authoritative localized footer for the current channel.

    Historical channel snapshots can contain an auto-seeded English footer
    even when the production language is Hindi.  Rule defaults are the source
    of truth for auto-seeded assets; explicitly maintained localized assets are
    preserved when they already match the expected rule language.
    """
    if context.get("description_assets_frozen") and isinstance(context.get("description_fixed_assets"), dict):
        return dict(context["description_fixed_assets"])
    task = context.get("task") if isinstance(context.get("task"), dict) else {}
    language = str(task.get("language") or "").strip()
    channel = str(task.get("channel") or "").strip()
    bundle = load_description_rule_bundle(language, channel)
    defaults = dict(bundle.get("fixed_assets") or {})
    current = context.get("description_fixed_assets")
    if not isinstance(current, dict) or not current:
        current = {}

    # Auto-seeded assets must track the current rule bundle.  This prevents a
    # stale English seed from becoming a permanent channel-specific override.
    source = str(current.get("source") or "").strip()
    if not current or source in {
        "xy-place/rules/description_rules.json",
        "xy-place-v14/rules/description_rules.json",
    }:
        resolved = defaults
    else:
        resolved = {**defaults, **current}

    return {
        "version": int(current.get("version") or bundle.get("rules_version") or 1),
        "source": "xy-place-v14/rules/description_rules.json",
        "language": language,
        "channel_name": channel,
        **resolved,
    }


TITLE_COVER_GENERATION_BLACKLIST_DIRECTIVE = (
    "Strictly forbidden semantic concepts in every newly generated title-owned or cover-owned field, regardless of target language, translation, inflection, or euphemistic spelling: "
    "rape; sexual assault; molestation; drugged; date rape or drugging; sold a person; human trafficking; kill; murder; shooting or killing; suicide; self-harm; corpse or dead body; bloody or gory; torture; poisoning to death; brutal killing. "
    "Prefer not to use these semantic concepts and freely choose another hard, clickable expression whenever possible: domestic violence; abuse; kidnapping; death threat. "
    "This is a generation instruction: choose compliant wording and visual ownership before returning JSON; do not rely on a downstream validator or cleaning pass. "
)

TITLE_GENERATION_STRATEGY_DIRECTIVE = (
    "Build every title in this exact reasoning order: strongest immediate emotion -> concrete perceptible event -> "
    "whether the event directly changes the position between people regardless of event type -> relationship inside that event -> "
    "protagonist's response, choice, or gain -> clear position change -> optional amplifier -> "
    "single A-to-B causal chain. A creates an immediate emotional debt through a concrete event that a cold viewer can understand. "
    "Prioritize events that directly change the position between people. An event's type does not determine its priority; priority "
    "depends on whether it directly causes selection, exclusion, recognition, replacement, protection, or a change in status between people. "
    "A procedural fact receives high priority only when it carries such a position change. "
    "B directly repays the emotional debt created by A through a clear change in relationship, identity, power, interests, resources, "
    "social position, relationship commitment, or fate. These are abstract result dimensions, not a candidate library, and no one "
    "dimension is mandatory. An optional amplifier is allowed only when supported by current plot evidence, the channel's permitted "
    "marketing extrapolation, or the frozen contract; never invent a new identity, amount, asset, power, or relationship merely to intensify a title. "
    "Before returning candidates, perform a model-only self-check: A must create immediate emotion for a cold viewer; A must contain a "
    "concrete perceptible event; B must directly answer A's emotional debt; A-to-B must remain understandable without full plot context; "
    "and the title must contain one main emotional causal line. Use this self-check only for candidate generation, ranking, and internal rewrite. "
    "It must not become a mechanical Validator or an independent Controller semantic detector. "
)

TITLE_HOOK_TYPE_PROTOCOL_DIRECTIVE = (
    "Protocol-only allowed hook_a_type values: betrayal, humiliation, abandonment, theft, forced_choice, life_crisis, "
    "child_separation, identity_suppression, public_attack, marriage_trap, money_power_attack, shocking_discovery. "
    "Protocol-only allowed hook_b_type values: identity_reveal, public_slapback, revenge, power_reversal, villain_cost, "
    "family_collapse, regret_chase, child_recognition, marriage_reveal, life_or_death_payoff, wealth_reveal, alliance_victory, "
    "arrival_mystery, relationship_mystery, secret_object, public_shock, forced_choice_escalation, countdown_crisis, unseen_consequence. "
    "These values exist only to encode the chosen current-task result in the unchanged output protocol and must not be used as a creative candidate list. "
)


STAGE_DIRECTIVES = {
    "xy-title": (
        TITLE_COVER_GENERATION_BLACKLIST_DIRECTIVE
        +
        TITLE_GENERATION_STRATEGY_DIRECTIVE
        +
        TITLE_HOOK_TYPE_PROTOCOL_DIRECTIVE
        +
        "Generate exactly three genuinely first-person titles in the channel language. The narrator must be directly involved in the explosive event as its participant, target, relationship party, or counterattacker. "
        "Do not enforce a fixed first-person vocabulary, starter list, exact pronoun position, or reusable sentence pattern; use natural first-person grammar for the current channel language and reject detached third-person narration. "
        "Read channel_theme_contract first. When plot_supported=true, make the channel direction unmistakable in all three "
        "directions while using different explosive moments and hooks. When plot_supported=false, choose the closest compelling "
        "angle from the drama and do not force a generic channel-theme slogan. "
        "Use creative_slot only as a stable package identity and fresh-creation policy; it contains no hook, scene, action, or layout answer. "
        "Use market_packaging.final_angles as the three packaging propositions before recommendation sorting: direction 1 follows A, direction 2 follows B, and direction 3 follows C. Preserve each supplied angle's factual conflict/payoff core while expressing it naturally in the target language. Do not scan or reconstruct raw market videos, and do not claim that a story_derived angle has market validation. "
        "Create one packaging_brief shared by title, cover, description, and community. Its creative_slot_id and "
        "channel_direction must exactly match creative_slot.creative_slot_id and channel_theme_contract.channel_direction; "
        "when the plot supports the channel direction, core_story_promise must explicitly name at least one verified Chinese channel-theme signal instead of using generic conflict language. "
        "title_role and thumbnail_role must complement rather than repeat each other. "
        "Respect the exact fixed title formula from channel_snapshot. The three directions must be materially different. "
        "Never select, copy, or translate a fixed channel-theme candidate phrase. Build each A/B title from the strongest drama-specific marketing mechanism and the current channel direction; do not use a generic direction label as a reusable title suffix. When plot_supported=false, do not force a channel-theme phrase that makes the title generic. "
        "Keep every final localized title at or below 95 Unicode code points, including emoji, brackets, spaces, and punctuation, "
        "leaving margin under the validator's hard 100-code-point limit. Count the actual final title string yourself. "
        "Do not trust or merely copy your own char_count. "
        "Assign each direction a unique integer recommendation_score from 1 to 100 based on A explosion strength, B escalation or payoff, "
        "instant clarity, emotional shock, channel fit, and downstream visual potential. When exactly one or two final angles are market-backed, the controller places those directions first and sorts within each source group by this score; when all three or none are market-backed, it sorts all three by score. Score honestly. "
        "Treat child_angle as a downstream cover-execution flag, not a keyword detector. Set child_angle=true only when the selected direction has a born minor who can truthfully appear, safe and supervised, in the same single continuous moment and physical location as the chosen cover event. A title may mention a child while using child_angle=false when its strongest visible payoff is an adult-only later consequence and the child cannot truthfully share that moment. "
        "An explicitly adult or grown daughter, son, or offspring is not a child angle: set child_angle=false and do not create child-safety staging for adult offspring. "
        "A direction whose only child fact is not yet born is valid and does not require a visible born child: set child_angle=false unless that same Find direction also contains a born child. Never add a later baby scene merely because the channel or drama is child/cute-child themed. "
        "For every direction, provide one short visual_thesis stating the title's main visible conflict, discovery, reveal, reunion, or emotional reversal. "
        "A deceased, absent, or earlier-life child does not require child_angle=true for a later adult-only consequence. Channel type, drama name, and child wording must never force all three directions to add children. For every child-angle direction, provide safe_cover_scene and child_role before cover generation. safe_cover_scene must be one executable single moment in one physical location; never use a split screen, inset memory, separate memory region, collage, or temporal montage. It is a reference safety implementation, not a mandatory replacement for the title event. Visibly include the relevant Chinese "
        "child or children, fully clothed, healthy, safe, and supervised. A child may appear safely in a hospital, clinic, ward, waiting area, rehabilitation area, or normal examination setting, but must not undergo a painful, invasive, dangerous, or harmful medical procedure. "
        "Keep the public A+B title explosive, but make visual_thesis, child_role, and safe_cover_scene image-provider-safe. These downstream visual fields must not make a minor the visible target of abandonment, humiliation, hostile surveillance, coercive parenting, police restraint or control, adult confrontation, or bedroom/bedside intimacy. Move the visible wrongdoing, confrontation, or consequence onto adults, and keep the required child as a calm, protected relationship, identity, reunion, or family anchor. Do not delete the child and do not weaken the public title. "
        "Use the complete plot_payload.results[0].plot_fields as marketing raw material, not as a synopsis to translate and not as a verbatim-evidence gate. "
        "Keep only a minimum relationship or conflict connection to this drama; the marketed escalation does not need to be a literal plot event or ending. Build a hard declarative two-explosion A!B! structure. "
        "Both A and B must be declarative. Never use questions, rhetorical questions, Why/What/Who/How hooks, or question marks in any channel language. "
        "Evidence fields are brief internal source or amplification notes and are not required to be verbatim plot spans. For every direction return one concrete public_payoff_anchor in Chinese. It must express a directly perceptible position change that answers A and must appear verbatim inside the Chinese B beat. A generic summary cannot be the whole anchor. "
        "Apply a cold viewer test to the public title: never make a bare story-internal proper noun carry the hook. Replace it with a universally understandable description of the current relationship, event, or position change. Internal names may remain only in evidence notes. "
        "The title content hard gate applies only to actual minors: never humiliate, insult, bully, abuse, sexualize, or assign age-inappropriate "
        "conduct to a minor. The same harsh conflict words are allowed for adults, including explicitly adult or grown daughters and sons. "
        "Translate only the two title beats into Chinese; the controller owns and normalizes the Chinese translation shell "
        "from the real channel formula, including its punctuation and channel-specific emoji. "
        "creative_history contains same-drama packages from other channels: use it only as a negative reference. "
        "Choose different hook pairs, specificity anchors, and editorial angles; never translate, paraphrase, or reuse them."
    ),
    "xy-cover": (
        TITLE_COVER_GENERATION_BLACKLIST_DIRECTIVE
        +
        "Generate description prompts only, never images. Produce exactly three title-linked groups. "
        "Treat title_payload.results[0].packaging_brief and channel_theme_contract as binding upstream inputs. "
        "Copy packaging_brief.creative_slot_id into packaging_brief_id, and copy channel_direction and core_story_promise exactly. "
        "Before writing any scene_prompt_4_5, commit in this order for each group: visual_payoff; single_continuous_moment=true, single_physical_location=true, and temporal_montage=false; required_characters and visible adult/child counts; a fresh scene; a fresh main action; prop_role; camera_angle; core_words category and selection reason; then the concise scene prompt. "
        "Each 4:5 group must show exactly one continuous moment in one physical location. Choose only one strongest visible instant from the A+B title; do not illustrate both beats. Do not combine before/after, accusation/consequence, present/later, or cause/result in one image. No split screen, stacked scenes, collage, diptych, multi-panel, temporal montage, or adjacent second moment. Use one coherent lighting environment for that single location. The upstream visual_thesis is a marketing promise: if it mentions more than one time or place, distill it into one visual_payoff instead of reproducing both. "
        "visual_payoff must state the strongest emotional power shift, relationship reversal, or visible consequence promised by the title. Do not convert title nouns directly into props. key_prop is optional supporting evidence, never the sole visual B explosion. "
        "For a group with no required child, plan 2 to 4 visible adults and no extra people. Keep every required child and remove optional adults first. The final scene may contain only required_characters: no background crowd, assistants, guards, shareholders, relatives, or readable extra faces. "
        "Never depict Chinese police, public-security, traffic-police, special-police, or other public-service uniforms in any cover. Do not describe police caps, police badges, police emblems, police epaulettes, police shoulder boards, police service numbers, or police-style uniforms. If the plot needs an order-maintaining figure, replace that visual role with a commercial security guard in a plain neutral security uniform with no government or police insignia. "
        "scene_family, scene, and main_action are fresh free creative text derived specifically from this title and package. Do not choose a scene, action, composition, prop, or reaction from any reusable candidate list; fixed creative answers are forbidden. Explain scene_choice_reason and action_choice_reason before composing the prompt. "
        "If a location detail does not improve story comprehension, emotional intensity, or visual realism, omit it during generation. Do not invent decorative architecture, luxury dressing, lighting spectacle, or art-direction detail merely to sound professional. "
        "Use camera_angle only from: eye-level, slightly low-angle, slightly high-angle, over-the-shoulder, three-quarter view. These are technical vocabulary, not composition templates. "
        "Choose core_words by this priority: specific relationship > shocking identity > concrete number > concrete consequence > abnormal action > abstract theme. Use abstract_theme only when no concise package-specific phrase is available. Never select core words from a reusable multilingual candidate library. "
        "The three scenes must visibly express the current channel direction when supported by plot facts, while remaining distinct from one another. Return the full pre-generation plan plus story_hook, scene_family, scene, main_action, key_prop, composition, palette, and lighting. Design one believable high-emotion frame from a real Chinese television drama. "
        "Stage the provocative unresolved moment promised by each title, not the later explanation or ending. One minimum plot anchor is enough. Do not use doors or vehicle doors as primary scene devices. Never build the scene, main action, actor interaction, or camera blocking around opening or closing a door, blocking, standing, waiting, or leaning at a doorway, entering or exiting through a vehicle door, gripping a car door, or confronting across a door. Create a fresh title-specific non-door scene and action rather than selecting a replacement from a location or action list. A distant closed door may remain incidental background architecture only when nobody interacts with it. This is a hard generation and validation requirement. "
        "The three groups inside this package must use different scene moments, main actions, and camera blocking. Palette, lighting, and props "
        "must follow the chosen real location and must never be varied merely to look novel. Across videos, partial reuse of "
        "channel-level visual grammar is allowed: character count, shot size, camera angle, placement logic, typography-layout logic, "
        "or scene type may each be similar. A single similar visual dimension is not narrative duplication, so do not force a new "
        "composition solely to avoid resemblance. Do not reproduce the whole visual combination as a template. Reject only a substantially "
        "duplicated complete narrative concept: a highly similar combination of character relationship, primary action or reversal, key event "
        "or evidence prop, and core cover words. When several key visual dimensions and that narrative concept are both highly similar, actively "
        "separate the design. Do not use a numeric similarity ratio or fingerprint-count quota for generation. Same channel style is allowed; "
        "the same template or complete visual story is not. Never invent technology, gadgets, forensic displays, or implausible locations to "
        "escape history. Do not use named geometric poster formulas. "
        "Return scene_prompt_4_5 as a concise English scene description containing only the title-linked people, relationship, physical action, emotion, believable location, camera blocking, and location-specific light/color. Do not include global style boilerplate, actor-ethnicity boilerplate, core-word rendering, typography, canvas-width, font, outline, or shadow instructions; the controller owns and appends those exactly once. "
        "For female-frequency channels, ban all visual special effects: no magic, aura, energy, lightning, particles, fire, explosion, "
        "holograms, fake glowing props, glowing eyes, lasers, or supernatural glow; natural sun, practical lights, headlights, and stage lights are allowed. "
        "If the channel/title uses a child or cute-child angle, visibly include the relevant Chinese child or children, safe, healthy, "
        "fully clothed, supervised, and never distressed, harmed, kidnapped, restrained, sick, bullied, humiliated, or surrounded by hostile adults. "
        "For each title, copy visual_thesis exactly and make scene_prompt_4_5 visibly express it. For each title row with child_angle=true, use child_role and safe_cover_scene as safety references, not as a mandatory scene script. When a required minor is visible, do not combine that minor in the same image prompt with abandonment or humiliation directed at the child, hidden surveillance, coercive parenting, bedroom or bedside intimacy, police restraint, escort, or control, paternity-evidence confrontation, or adult physical/coercive conflict. Keep the click-driving reversal visible through adult status, posture, relationship, or consequence while the child remains calm, protected, and clearly supervised. Do not remove a required child and do not replace the title event with unrelated peaceful activity. "
        "All covers forbid hitting and threatened hitting: no slap, punch, kick, choke, drag, push-down, stomp, raised fist about to strike, weapons, blood, or wounds. Create a fresh nonviolent title-specific action without selecting from a stock alternative-action list. "
        "Each core_words value is exactly one or two independent natural words forming an idiomatic native-language hook. Prefer one strong native word; if using two, use a natural modifier-plus-head phrase or an established native compound. Never mechanically concatenate two plot nouns, never omit a required linker or case marker, and if the idiomatic expression needs three or more words, choose a different natural one- or two-word hook. The three core_words values must be mutually distinct after Unicode, case, and whitespace normalization; never reuse one group's core words in another group. Each 4:5 and 16:9 prompt is English; "
        "The core_words_translation must explicitly express the supported channel theme, and the exact localized core_words must remain prominent in both final prompts. "
        "Only core_words use the channel language. Leave suitable negative space without describing the text itself; the controller is the sole owner of the final adaptive core-word typography salience block. Do not impose any fixed typography width, height, or canvas ratio. "
        "Incidental Chinese environmental text on signs, documents, boards, buildings, or props is allowed, but it must never carry or substitute for the core words. Never add a blanket ban such as no readable words, no new text, or no other visible text. "
        "Return outpaint_environment as one short English description of only the left/right environment continuation. Do not repeat center people, identity, typography, style, action, emotion, or story information; the controller owns the complete 16:9 execution prompt. "
        "Same-drama creative_history forbids translating or cosmetically restyling a duplicated complete narrative concept. "
        "Local visual grammar may still be reused; organize the whole image for the current title and do not copy the prior "
        "relationship + primary action or reversal + key event or evidence prop + core cover words combination."
    ),
    "xy-place": (
        "Generate the dynamic channel-language description body and Chinese review translation. "
        "Inherit the exact channel direction and core story promise from title_payload.results[0].packaging_brief. "
        "Copy packaging_brief.creative_slot_id into packaging_brief_id, and copy channel_direction and core_story_promise exactly. "
        "Open with one concrete conflict, abnormal situation, identity mismatch, or relationship anomaly. Use only the strongest click entry and never summarize the whole drama or preview several hooks. Do not stack several betrayals, props, or consequences into the opening sentence; move secondary facts into the minimum background only when needed. Continue in two to four natural paragraphs whose length, order, and transitions follow the current plot and target language rather than a fixed rhythm. Include only the relationship and background needed to understand the conflict. "
        "Use exactly one concrete mid-story event as the escalation: state who acted, what specific anomaly appeared, and whose judgment, relationship, or position changed directly because of it. Do not stack a second independent event, turn the source into a timeline, or use the final identity reveal, final parentage confirmation, villain's final punishment, final reunion, proposal, wedding, inheritance result, or another ending climax. Leave at most one plot-specific unresolved question or a non-question suspense statement. Name the relevant character instead of using a vague stranger, woman, man, mother, or person when the verified name is available and clearer. "
        "Before drafting, choose one precise current-drama editorial_anchor. Use editorial_anchor as the sole sentence-selection center: every background sentence must be necessary to understand that anchor, and delete it when removing it does not reduce understanding of that anchor. The final suspense must directly close the loop with the opening misunderstanding or follow the immediate unresolved consequence of the selected escalation; never open a new abstract question or switch to another plot line. Before returning JSON, silently reread and rewrite the body inside this same model call. Ensure each person keeps one spelling throughout, narrator knowledge is not assigned to a character who does not yet know it, causes precede effects, every target-language phrase uses native collocation rather than translated source-language logic, and the final sentence reads naturally on its first pass. This is internal single-call editing, not a second model call or a semantic Validator. "
        "Add SEO information only when the target-language version, Chinese-drama identity, or one or two essential genre terms are not already clear, and integrate it naturally into an existing paragraph. Never place a blunt standalone genre declaration after the suspense. Do not use report-like headings, plot-highlight lists, story-type lists, a fixed if-you-like-A/B/C sentence, generic AI suspense phrases, repeated facts, or any sentence whose removal would not reduce comprehension or suspense. Write like a local YouTube drama editor, not an AI report, plot encyclopedia, SEO article, or recap. "
        "description_fixed_assets is controller-owned localized compact-footer data. Do not invent, translate, paraphrase, or replace it; "
        "the controller deterministically removes any model-written footer and appends only the exact subscription and disclaimer values after generation. Legacy welcome copy, channel introductions, and generic comment questions are not public output. "
        "Ignore any conflicting legacy footer text embedded inside channel_snapshot. "
        "Return opening_hook_type, payoff_hook_type, and a concrete Chinese editorial_anchor. "
        "Only when channel_theme_contract.plot_supported=true, return one short channel_theme_phrase in the channel language plus its accurate Chinese channel_theme_phrase_translation and include it naturally in the public description. When plot_supported=false, use only a truthful plot phrase and never invent theme evidence. "
        "Generate exactly 12 hashtags for this exact channel and drama. Place #cdrama exactly once at position 3. Select the other exactly 11 hashtags only from channel_hashtag_whitelist.additional_candidates. At least one of positions 1 and 2 must be selected from channel_hashtag_whitelist.target_language_tags. Target-language qualification belongs only to that pre-registered channel asset; never infer that another tag qualifies. #ChineseDrama and #ShortDrama are optional only when they are present in the exact current-channel candidate list and relevant to this drama. Choose a drama-specific combination by considering target-language audience entry, current channel vertical theme, and verified current-drama relevance together. Hashtags improve metadata fit; never treat one hashtag as an independent cause of recommendation traffic. The channel name must match channel_hashtag_whitelist.channel_name exactly. These hashtags are final YouTube plain text, not Markdown source: copy every selected hashtag character-for-character from the whitelist. Never insert a backslash before an underscore or any other hashtag character. Never borrow from another channel, and never invent, translate, concatenate, respell, change case, or otherwise modify a hashtag. "
        "Use the best matching registered playlist in the playlist and url fields. In the public description, include every registered playlist exactly as supplied: show the primary playlist first, then every remaining playlist with its exact name and viewer-facing URL. Do not explain why a playlist matches, summarize its content, add SEO commentary, or write any sentence after a playlist URL. The controller deterministically rebuilds this block. End the public description after the fixed disclaimer and never output a ==Chinese drama name== marker or another internal production marker. "
        "Use only viewer-facing www.youtube.com/playlist?list= URLs and never studio.youtube.com. Translate every structural label into the channel language; outside English channels, English template labels are invalid. "
        "When a story includes minors, keep adult wrongdoing and child-safe facts in separate sentences. Do not describe a minor as the direct target of abandonment, humiliation, hostile surveillance, coercive parenting, police restraint or control, adult confrontation, or bedroom/bedside intimacy. Preserve the dramatic adult betrayal, reversal, punishment, and payoff; keep the child as a protected relationship, identity, reunion, or family anchor. This is wording ownership for future generation, not permission to omit verified children or soften the main hook. "
        "Use a different editorial premise and emotional entry point from every same-drama item in creative_history."
    ),
    "xy-post": (
        "Generate exactly task.community_count independent community plans. Each result must use its sequential plan_index. "
        "Inherit the channel direction and core story promise from title_payload.results[0].packaging_brief, but choose a distinct drama-specific interaction moment for each plan. "
        "In every result copy packaging_brief.creative_slot_id into packaging_brief_id, and copy channel_direction and core_story_promise exactly. "
        "Use task.video_link exactly once in each copy; when it is 【视频链接待补】, preserve that exact placeholder. "
        "Return community_hook_type plus concrete Chinese selected_moment and interaction_angle fields. "
        "Treat the channel theme as existing context for angle selection, not as a fixed sentence that must be exposed publicly. When channel_theme_contract.plot_supported=true, return channel_theme_phrase in the channel language with its accurate Chinese channel_theme_phrase_translation for review, but write the public copy and image hook naturally for this drama without copying that phrase verbatim. When plot_supported=false, use only a truthful plot phrase and never invent theme evidence. "
        "The image hook expresses one core conflict, choice, or relationship change from the selected scene. It must not also carry a full plot summary or the interaction question; keep the full interaction question in the public copy. "
        "Return scene_family, main_action, key_prop, composition, and palette for every plan. "
        "Reuse every community_footer_cta field exactly. The first copy line must be exactly `🔥 {full_video_cta} 👉 {task.video_link}`; "
        "do not translate, paraphrase, decorate, or reorder that fixed line. The community image must not be a square remake of any cover. "
        "Keep the hook sentence, both CTA buttons, emoji, and their exact channel-fixed layout inside the generated image prompt. "
        "Render the scene as a natural live-action TV drama still with realistic lens rendering, natural skin texture, ordinary clothing wrinkles, believable location lighting, and slightly softer environmental detail. Never request ultra sharp focus, crisp facial details, crisp faces, strong or high micro-contrast, clean edges, sharp facial highlights, or mobile-readability rendering. "
        "Every plan must use a materially different moment, interaction premise, visual scene, action, prop, composition, and palette. "
        "Do not translate, paraphrase, or reuse any same-drama community copy or image concept from creative_history."
    ),
}


STAGE_CONTEXT_KEYS = {
    "xy-find": ("task", "identity"),
    "xy-title": ("task", "identity", "channel_snapshot", "channel_theme_contract", "semantic_contract", "creative_slot", "title_rule_contract", "plot_payload", "market_packaging", "creative_history", "recent_channel_title_usage_7d"),
    "xy-cover": ("task", "identity", "channel_snapshot", "channel_theme_contract", "semantic_contract", "creative_slot", "cover_rule_contract", "plot_payload", "title_payload", "visual_history", "creative_history"),
    "xy-place": (
        "task",
        "identity",
        "channel_snapshot",
        "channel_theme_contract",
        "semantic_contract",
        "creative_slot",
        "playlists",
        "description_fixed_assets",
        "channel_hashtag_whitelist",
        "plot_payload",
        "title_payload",
        "creative_history",
    ),
    "xy-post": (
        "task",
        "identity",
        "channel_snapshot",
        "channel_theme_contract",
        "semantic_contract",
        "creative_slot",
        "community_footer_cta",
        "community_rule_contract",
        "plot_payload",
        "title_payload",
        "place_payload",
        "creative_history",
    ),
}


def stage_context(stage: str, context: dict[str, Any]) -> dict[str, Any]:
    """Expose only the immutable inputs owned by the current stage.

    Passing every prior artifact to every model call increased latency and let
    stale downstream prose influence unrelated generation.  The controller,
    not the model, owns dependency selection.
    """
    scoped = {key: context[key] for key in STAGE_CONTEXT_KEYS.get(stage, ()) if key in context}
    if stage == "xy-title" and isinstance(scoped.get("channel_snapshot"), str):
        scoped["channel_snapshot"] = title_channel_context(scoped["channel_snapshot"])
    elif stage == "xy-place":
        scoped["description_fixed_assets"] = normalized_description_fixed_assets(context)
        publication_contract = context.get("description_rule_contract", {})
        if publication_contract and isinstance(scoped.get("channel_snapshot"), str):
            scoped["channel_snapshot"] = public_playlist_urls_in_text(scoped["channel_snapshot"])
        scoped["publication_contract"] = publication_contract
    elif stage == "xy-cover":
        if isinstance(scoped.get("cover_rule_contract"), dict):
            scoped["cover_rule_contract"] = copy.deepcopy(scoped["cover_rule_contract"])
            prompt_audit = scoped["cover_rule_contract"].get("prompt_audit")
            if isinstance(prompt_audit, dict):
                for validator_only_key in (
                    "max_historical_matching_dimensions",
                    "forbid_historical_scene_action_pair",
                    "actual_image_similarity_threshold",
                ):
                    prompt_audit.pop(validator_only_key, None)
        if isinstance(scoped.get("title_payload"), dict):
            scoped["title_payload"] = copy.deepcopy(scoped["title_payload"])
            for row in title_rows(scoped["title_payload"]):
                row["child_angle"] = title_row_requires_minor_child(row, False)
    elif stage == "xy-post":
        scoped["image_style_contract"] = context.get("community_rule_contract", {}).get("image_style", {})
    # Generation and semantic validation consume the exact same selected
    # history contract. Full real-image history remains the separate P0 gate
    # in xy-sort-v14, where actual pixels are available.
    history_key = {
        "xy-title": "title_payload",
        "xy-cover": "cover_payload",
        "xy-place": "place_payload",
        "xy-post": "post_payload",
    }.get(stage)
    if history_key and isinstance(scoped.get("creative_history"), list):
        metadata = ("channel", "language", "drama_name", "video_id")
        def compact(payload: dict[str, Any]) -> dict[str, Any]:
            result = first_result(payload)
            identity = {
                key: result.get(key, "")
                for key in ("drama_name", "video_id", "result_id", "source_block_label")
            }
            if stage == "xy-title":
                fields = (
                    "hook_a_type", "hook_a_fact", "hook_b_type", "hook_b_fact",
                    "specificity_anchor", "translation",
                )
                identity["directions"] = [
                    {key: row.get(key, "") for key in fields}
                    for row in title_rows(payload)
                ]
            elif stage == "xy-cover":
                fields = (
                    "story_hook", "scene_family", "main_action", "key_prop",
                    "composition", "palette", "lighting",
                )
                identity["titles"] = [
                    {key: row.get(key, "") for key in fields}
                    for row in cover_rows(payload)
                ]
            elif stage == "xy-place":
                for key in ("opening_hook_type", "payoff_hook_type", "editorial_anchor"):
                    identity[key] = str(result.get(key) or "")
                identity["translation"] = str(result.get("translation") or "")[:1600]
            elif stage == "xy-post":
                plans = [
                    {
                        key: (str(row.get(key) or "")[:1600] if key in {"copy_translation", "image_prompt_1x1"} else str(row.get(key) or ""))
                        for key in (
                            "plan_index", "community_hook_type", "selected_moment", "interaction_angle",
                            "scene_family", "main_action", "key_prop", "composition", "palette",
                            "copy_translation", "image_prompt_1x1",
                        )
                    }
                    for row in (payload.get("results") or [])
                    if isinstance(row, dict)
                ]
                identity["plans"] = plans
                if plans:
                    # Retain the legacy compact keys so old batches and their
                    # regression contract remain readable without migration.
                    identity.update({key: plans[0].get(key, "") for key in (
                        "community_hook_type", "selected_moment", "interaction_angle",
                        "copy_translation", "image_prompt_1x1",
                    )})
            return {"results": [identity]}
        scoped["creative_history"] = [
            {
                **{key: row.get(key, "") for key in metadata},
                history_key: compact(row.get(history_key, {})),
            }
            for row in scoped["creative_history"]
            if isinstance(row, dict) and row.get(history_key)
        ]
    return scoped


def build_prompt(
    stage: str,
    rules: str,
    context: dict[str, Any],
    previous_issues: list[str],
    stage_directive: str | None = None,
) -> str:
    scoped_context = stage_context(stage, context)
    acceptance_spec: dict[str, Any] = {
        "stage": stage,
        "must_pass_before_acceptance": True,
    }
    if stage == "xy-title":
        theme = context.get("channel_theme_contract") if isinstance(context.get("channel_theme_contract"), dict) else {}
        acceptance_spec.update(
            {
                "channel_direction": str(theme.get("channel_direction") or ""),
                "plot_supported": bool(theme.get("plot_supported")),
                "accepted_theme_signals": list(dict.fromkeys([
                    *(str(value) for value in theme.get("required_output_signals", [])),
                ])),
                "per_direction_requirement": "Each Chinese audit direction and the packaging promise must contain at least one accepted_theme_signal.",
            }
        )
    elif stage == "xy-cover":
        audit = context.get("cover_rule_contract", {}).get("prompt_audit", {}) if isinstance(context.get("cover_rule_contract"), dict) else {}
        acceptance_spec.update(
            {
                "generation_constraints": {
                    "required_event_source": "upstream visual_thesis and verified plot facts",
                    "child_policy": "use structured per-group child requirement; required minors must be visible, safe, healthy, supervised, and outside actual danger",
                    "adult_conflict_near_safe_child": "express through adult status, posture, relationship, or consequence; do not stack provider-sensitive minor contexts in the same image prompt",
                    "physical_violence": "forbidden",
                    "female_frequency_visual_effects": "forbidden",
                    "ordinary_story_evidence_props": "prefer zero or one; avoid stacking explanatory props",
                    "invented_futuristic_technology": "hard forbidden",
                    "named_ai_poster_geometry": "hard forbidden",
                    "three_group_diversity": ["scene_family", "main_action", "composition"],
                    "controller_owned_blocks": ["identity", "style", "typography", "salience", "16:9 execution"],
                    "generation_plan": copy.deepcopy(audit.get("generation_plan", {})),
                    "single_moment_scene": copy.deepcopy(audit.get("single_moment_scene", {})),
                    "door_and_vehicle_door_negative_constraints": copy.deepcopy(audit.get("scene_selection_preferences", {})),
                    "cross_video_visual_grammar_generation": copy.deepcopy(audit.get("cross_video_visual_grammar_generation", {})),
                    "official_uniform_policy": copy.deepcopy(audit.get("official_uniform_policy", {})),
                },
                "audit_only": {
                    "prompt_word_count": True,
                    "real_drama_score": True,
                    "prop_density": True,
                    "lighting_description_density": True,
                    "natural_live_action_style_signals": True,
                },
                "hard_forbidden_ai_poster_terms": list(audit.get("hard_forbidden_ai_poster_terms", [])),
            }
        )
    correction_lines: list[str] = []
    if stage == "xy-title":
        exact_title_format = title_format_from_snapshot(str(scoped_context.get("channel_snapshot") or ""))
        if any("format_mismatch" in issue for issue in previous_issues) and exact_title_format:
            correction_lines.append(
                "Rewrite every failed title with the exact shell `" + exact_title_format
                + "`. Replace only A and B; preserve every fixed marker, bracket, emoji, separator, punctuation mark, and position exactly."
            )
        if any("cross_channel_package_collision" in issue for issue in previous_issues):
            correction_lines.append(
                "Choose three new hook pairs, specificity anchors, and editorial directions that do not translate, paraphrase, or reuse any title direction in creative_history. Change the underlying click moment, not only the wording."
            )
        if any("recommendation" in issue for issue in previous_issues):
            correction_lines.append(
                "Give three unique recommendation_score values from 1 to 100. Score honestly. The controller applies the frozen market-backed-first rule for partial market coverage, then sorts within each source group by score."
            )
        if any("question_not_allowed" in issue for issue in previous_issues):
            correction_lines.append(
                "Rewrite A and B as direct declarative statements. Remove every question, rhetorical question, Why/What/Who/How hook, and question mark. Keep one causal line and make B directly respond to the emotional debt established by A."
            )
        if any(
            marker in issue
            for issue in previous_issues
            for marker in (
                "public_payoff_anchor_abstract",
                "public_payoff_anchor_missing",
                "public_payoff_anchor_not_in_B",
            )
        ):
            correction_lines.append(
                "Rewrite the failed B so it directly responds to the preceding conflict and completes one causal line. State a concrete, perceptible position change rather than an abstract story summary. Put the exact Chinese public_payoff_anchor inside the Chinese B beat. The result may use contract-permitted marketing amplification and does not need to be a literal plot ending, but any amplifier must be grounded in current task evidence or permitted extrapolation."
            )
        if any("cold_viewer_internal_term" in issue for issue in previous_issues):
            correction_lines.append(
                "Replace the internal proper noun in the public title with a cold-viewer-readable description of the current relationship, event, or position change. Do not ask the viewer to know the plot first. Keep internal names only in evidence notes."
            )
        if any("minor_humiliation_or_age_inappropriate" in issue for issue in previous_issues):
            correction_lines.append(
                "The rejected wording targets an actual minor with humiliation, bullying, abuse, sexualization, or age-inappropriate conduct. Choose a different child hook or move the harsh conflict onto an adult. Do not soften adult conflict. Explicitly adult daughters and sons are adults."
            )
        child_plan_failed = any(
            "child_angle" in issue or "child_safe_cover_scene" in issue or "child_role" in issue
            for issue in previous_issues
        )
        if child_plan_failed:
            correction_lines.append(
                "Re-read each supplied Find final angle independently. An angle whose only child fact is not yet born is valid and must use child_angle=false unless that same angle also contains a born minor; do not add a later baby scene because of the channel direction or drama name. Every direction still needs visual_thesis. Only directions that actually contain a born minor use child_angle=true and require child_role plus a safe_cover_scene with that child visibly safe and supervised."
            )
        theme_failures = [
            int(match.group(1))
            for issue in previous_issues
            if (match := re.search(r"title_(\d+)_channel_theme_not_prominent", issue))
        ]
        if theme_failures:
            theme = context.get("channel_theme_contract") if isinstance(context.get("channel_theme_contract"), dict) else {}
            signals = list(theme.get("required_output_signals") or [])
            correction_lines.append(
                "Rewrite failed title direction " + ", ".join(str(value) for value in theme_failures)
                + " so its Chinese hook facts, specificity anchor, or translation explicitly contains at least one "
                + "authoritative channel-theme signal: " + ", ".join(dict.fromkeys(signals)) + "."
            )
    if stage == "xy-cover":
        if any(
            marker in issue
            for issue in previous_issues
            for marker in (
                "single_continuous_moment_required",
                "single_physical_location_required",
                "temporal_montage_forbidden",
                "explicit_multi_moment_staging_forbidden",
            )
        ):
            correction_lines.append(
                "Rebuild every failed group as one continuous instant in one physical location with one coherent lighting environment. Choose only the strongest visible instant from the title. Remove every before/after, present/later, cause/result, split-screen, stacked-scene, collage, diptych, multi-panel, temporal-montage, or adjacent-second-moment construction."
            )
        if any("generation_plan" in issue or "visible_adult_count_over_4" in issue for issue in previous_issues):
            correction_lines.append(
                "Rebuild the failed group from its pre-generation plan before rewriting scene_prompt_4_5. State the title-specific visual_payoff, keep only required_characters, use 2 to 4 adults when no child is required, retain every required child, and remove optional adults first. Then freely create a new title-specific scene and action; do not pick from a candidate list."
            )
        unexpected_final_prompt_fields = any(
            "unexpected" in issue
            and any(field in issue for field in ("prompt_4_5", "prompt_16_9"))
            for issue in previous_issues
        )
        if unexpected_final_prompt_fields:
            correction_lines.append(
                "Remove the unexpected fields prompt_4_5 and prompt_16_9. Return only fields allowed by the current "
                "response schema. For each title use scene_prompt_4_5 and outpaint_environment. Do not construct or "
                "return the final prompt_4_5 or prompt_16_9; the controller constructs them downstream."
            )
        child_missing = any("child_angle_missing_visible_child" in issue for issue in previous_issues)
        child_unsafe = any("child_safety_violation" in issue for issue in previous_issues)
        if child_missing or child_unsafe:
            correction_lines.append(
                "Correct only the failed cover groups whose accepted upstream Find/title direction actually contains a born minor. "
                "Do not use the channel direction or drama name to add children to groups whose only child fact is not yet born, or to adult-only groups. "
                "For a genuine child-angle group, visibly show the relevant safe Chinese child or children; keep them fully clothed, healthy, safe, and supervised without replacing visual_thesis with an unrelated peaceful activity."
            )
        if any("core_words_diegetic_placement" in issue for issue in previous_issues):
            correction_lines.append(
                "Remove every core-word placement or Typography instruction from scene_prompt_4_5. The controller alone adds the non-diegetic editorial Typography block after the scene is accepted."
            )
        if any("scene_prompt_contains_controller_owned" in issue for issue in previous_issues):
            correction_lines.append(
                "Remove all global Style, actor-identity, and Typography boilerplate from every failed scene_prompt_4_5. Keep only the title-linked scene, people, relationship, action, emotion, camera blocking, location, and location-specific light/color."
            )
        if any("contains_wide_generation_instruction" in issue for issue in previous_issues):
            correction_lines.append(
                "Remove every 16:9 or wide-generation execution instruction from scene_prompt_4_5, including outpaint, locked-center, side-band, wide-canvas, and pixel-preservation wording. The 4:5 prompt must describe only the portrait cover. Put only a short environment continuation in outpaint_environment; the controller owns the separate wide-image execution contract."
            )
        if any("core_words_not_distinct" in issue for issue in previous_issues):
            correction_lines.append(
                "Rewrite the duplicated core_words values so all three groups use different localized one- or two-word hooks. Do not change spelling, case, or spacing merely to disguise a duplicate."
            )
        if any("core_words_unidiomatic" in issue for issue in previous_issues):
            correction_lines.append(
                "Rewrite every failed core_words value as one idiomatic native word or a natural two-word modifier-plus-head phrase. Never join two plot nouns mechanically and do not omit a required linker, postposition, case marker, or article. If the natural expression needs three or more words, choose a different plot-supported one- or two-word hook instead of compressing it into broken grammar."
            )
        if any("title_translation_mismatch" in issue for issue in previous_issues):
            correction_lines.append(
                "Copy title and title_translation for every failed group exactly from the matching upstream title row. Do not retranslate, summarize, normalize, or alter punctuation."
            )
        if any("physical_violence_forbidden" in issue for issue in previous_issues):
            correction_lines.append(
                "Remove all physical or threatened violence from every failed scene and prompt: no hitting, slap, punch, kick, choke, dragging, pushing down, stomping, raised fist, weapons, blood, or wounds. Freely create a different title-specific nonviolent action; do not select a replacement from a stock action list."
            )
        if any("door_or_vehicle_door_primary_staging_forbidden" in issue for issue in previous_issues):
            correction_lines.append(
                "Replace the failed group's entire scene, main action, actor interaction, and camera blocking with an equally truthful non-door alternative. Do not merely close or rename the door. Do not stage opening, closing, blocking, standing, waiting, leaning, entering, exiting, gripping, or confrontation at a door, doorway, car door, or vehicle door. A distant closed door is allowed only as incidental background architecture with no human interaction."
            )
        if any("official_police_or_public_service_uniform_forbidden" in issue for issue in previous_issues):
            correction_lines.append(
                "Remove every Chinese police, public-security, traffic-police, special-police, law-enforcement, or other public-service uniform and every police cap, badge, emblem, epaulette, shoulder board, or service number from the failed group. When an order-maintaining person is needed, use only a commercial security guard in a plain neutral security uniform with no government or police insignia."
            )
        if any("female_frequency_special_effects_forbidden" in issue for issue in previous_issues):
            correction_lines.append(
                "Remove every visual special effect from the failed female-frequency cover: no magic, aura, energy, lightning, particles, fire, explosion, hologram, fake glow, glowing eyes, laser, scanner beam, or supernatural light. Use only natural daylight or ordinary practical lamps."
            )
        collision_fields = ("scene_family", "main_action", "key_prop", "composition", "palette", "lighting")
        history = context.get("visual_history") if isinstance(context.get("visual_history"), list) else []
        for issue in previous_issues:
            match = re.match(r"cover_(\d+)_visual_collision_with_history_(\d+)(.*)", issue)
            if not match:
                continue
            group_index = int(match.group(1))
            history_index = int(match.group(2))
            suffix = match.group(3)
            fields = [field for field in collision_fields if re.search(rf"(?:_|^){re.escape(field)}(?:_|$)", suffix)]
            source = suffix.split("_source_", 1)[1] if "_source_" in suffix else ""
            # History can grow between attempts, so the numeric ordinal encoded
            # by the validator is only a diagnostic hint. Resolve the forbidden
            # fingerprint by its stable channel:drama:video identity first.
            ordinal_row = (
                history[history_index - 1]
                if 0 < history_index <= len(history) and isinstance(history[history_index - 1], dict)
                else {}
            )

            def source_id(row: dict[str, Any], include_group: bool) -> str:
                base = ":".join(filter(None, [
                    str(row.get("channel") or ""),
                    str(row.get("drama_name") or ""),
                    str(row.get("video_id") or ""),
                ]))
                group = str(row.get("source_group_index") or "")
                return f"{base}:group{group}" if include_group and base and group else base

            previous = ordinal_row if source in {
                source_id(ordinal_row, False), source_id(ordinal_row, True)
            } else next(
                (
                    row for row in history
                    if isinstance(row, dict)
                    and source in {source_id(row, False), source_id(row, True)}
                ),
                {},
            )
            if not source:
                source = source_id(previous, True)
            fingerprint = "; ".join(
                f"{field}={json.dumps(str(previous.get(field) or ''), ensure_ascii=False)}"
                for field in fields
                if str(previous.get(field) or "").strip()
            )
            correction_lines.append(
                f"GROUP {group_index} collides with accepted history source {source or history_index} on "
                f"{', '.join(fields) or 'its visual fingerprint'}. Redesign GROUP {group_index} around a different "
                "plot-supported story moment. Change scene_family, main_action, and composition together; do not "
                "paraphrase the same event or keep the same actor blocking. Let palette and lighting follow the new "
                "real location naturally rather than swapping colors decoratively. Preserve the exact upstream title "
                "promise and use this prior fingerprint only as forbidden reference"
                + (f": {fingerprint}." if fingerprint else ".")
            )
    if stage == "xy-place":
        if "description_contains_chinese" in previous_issues:
            correction_lines.append(
                "Rewrite every Chinese character in the public description into the registered channel language. "
                "Keep Chinese only in the separate review translation fields; do not output a final drama-name marker."
            )
        if any("hashtag_markdown_escape_forbidden" in issue for issue in previous_issues):
            correction_lines.append(
                "Rewrite the hashtag line as final YouTube plain text. Copy every hashtag character-for-character from channel_hashtag_whitelist; remove every Markdown backslash escape and never place a backslash before an underscore or any other hashtag character."
            )
        missing_playlist_indices = [
            int(match.group(1))
            for issue in previous_issues
            if (match := re.fullmatch(r"description_missing_registered_playlist_(\d+)", issue))
        ]
        playlists = context.get("playlists") if isinstance(context.get("playlists"), list) else []
        missing_playlists = [
            playlists[index - 1]
            for index in missing_playlist_indices
            if 0 < index <= len(playlists) and isinstance(playlists[index - 1], dict)
        ]
        if missing_playlists:
            correction_lines.append(
                "Rewrite the playlist section to include every registered playlist. Keep the best matching pair in the playlist and url fields, show it first in the public description, then include these missing exact name+URL pairs: "
                + "; ".join(
                    f"{str(row.get('name') or '').strip()} | {str(row.get('url') or '').strip()}"
                    for row in missing_playlists
                )
                + ". Do not invent, translate, rename, omit, or replace any registered playlist."
            )
    persistent_lines: list[str] = []
    if stage == "xy-title":
        exact_title_format = title_format_from_snapshot(str(scoped_context.get("channel_snapshot") or ""))
        if exact_title_format:
            persistent_lines.append(
                "Every localized title must use this exact shell: `" + exact_title_format
                + "`. Replace only A and B; preserve all fixed characters and their positions."
            )
        persistent_lines.append(
            "All three titles must use first-person POV and declarative A+B double explosions. "
            + TITLE_GENERATION_STRATEGY_DIRECTIVE
            + "Never use questions or question marks."
        )
        persistent_lines.append(TITLE_HOOK_TYPE_PROTOCOL_DIRECTIVE)
        persistent_lines.append(TITLE_COVER_GENERATION_BLACKLIST_DIRECTIVE)
        recent_usage = scoped_context.get("recent_channel_title_usage_7d")
        if isinstance(recent_usage, dict) and recent_usage.get("counts"):
            persistent_lines.append(
                "Seven-day negative-term usage is soft generation guidance, based on accepted generated title candidates in the current channel: "
                + json.dumps(recent_usage, ensure_ascii=False)
                + ". At or above a numeric preference, choose another hard expression whenever possible. For minimize/not-recommended/rate-limit entries, diversify wording without weakening A+B. Never fail, retry, or block production solely for this frequency guidance."
            )
        persistent_lines.append(
            "Keep only a minimum relationship or conflict connection to this drama; the marketed B does not need to be a literal plot event or ending. Every direction must return a concrete Chinese public_payoff_anchor that appears verbatim inside the Chinese B beat and expresses the perceptible position change that answers A."
        )
        persistent_lines.append(
            "Apply the cold viewer test: public titles must not rely on bare story-internal proper nouns. Replace them with a universally understandable description of the current relationship, event, or position change; internal names belong only in evidence notes."
        )
        persistent_lines.append(
            "The title content hard gate applies only to actual minors: do not humiliate, insult, bully, abuse, sexualize, or assign age-inappropriate conduct to a minor. Explicitly adult or grown daughters and sons are adults and may use the same harsh conflict wording as other adults."
        )
        persistent_lines.append(
            "Keep the public A+B title explosive, but make visual_thesis, child_role, and safe_cover_scene image-provider-safe. They must not make a minor the visible target of abandonment, humiliation, hostile surveillance, coercive parenting, police restraint or control, adult confrontation, or bedroom/bedside intimacy. Move the visible wrongdoing, confrontation, or consequence onto adults; keep the child calm, protected, and supervised. Do not delete the child or weaken the title."
        )
        persistent_lines.append(
            "Resolve child presence independently for each supplied Find final angle. child_angle is a cover-execution flag, not a keyword detector. An angle whose only child fact is not yet born is valid and uses child_angle=false unless that same angle also contains a born minor. A deceased, absent, or earlier-life child does not require child_angle=true for a later adult-only consequence. Channel direction, drama name, and child wording must never force all three directions to add children. Set child_angle=true only when the child can truthfully appear in the selected cover event's one continuous moment and physical location. In that case provide visual_thesis, child_role, and a safe_cover_scene with the relevant Chinese child visibly safe, healthy, fully clothed, and supervised; never use split screen, inset memory, separate memory regions, collage, or temporal montage."
        )
    elif stage == "xy-cover":
        persistent_lines.append(TITLE_COVER_GENERATION_BLACKLIST_DIRECTIVE)
        task = scoped_context.get("task") if isinstance(scoped_context.get("task"), dict) else {}
        rows = title_rows(scoped_context.get("title_payload") or {})
        child_requirements = cover_group_child_requirements(task, scoped_context, rows)
        for position, row in enumerate(rows, start=1):
            title_index = int(row.get("index") or row.get("title_index") or position)
            title = str(row.get("title") or "")
            translation = str(row.get("translation") or row.get("title_translation") or "")
            persistent_lines.append(
                f"GROUP {title_index}: Copy title and title_translation exactly from upstream: "
                + json.dumps(title, ensure_ascii=False) + " / " + json.dumps(translation, ensure_ascii=False) + "."
            )
            persistent_lines.append(
                f"GROUP {title_index}: Copy visual_thesis exactly from upstream and make the scene directly visualize it: "
                + json.dumps(str(row.get("visual_thesis") or ""), ensure_ascii=False) + "."
            )
            if len(child_requirements) >= position and child_requirements[position - 1]:
                persistent_lines.append(
                    f"GROUP {title_index}: a real visible safe Chinese child or children are mandatory in scene_prompt_4_5. "
                    f"Required child_role={json.dumps(str(row.get('child_role') or ''), ensure_ascii=False)}; "
                    f"reference-only safe_cover_scene={json.dumps(str(row.get('safe_cover_scene') or ''), ensure_ascii=False)}. "
                    "Keep them fully clothed, healthy, safe, and supervised; a photo, toy, bag, silhouette, or adult-only implication does not count. "
                    "When a required minor is visible, do not combine that minor in the same image prompt with abandonment or humiliation directed at the child, hidden surveillance, coercive parenting, bedroom or bedside intimacy, police restraint, escort, or control, paternity-evidence confrontation, or adult physical/coercive conflict. Express the strong adult reversal through status, posture, relationship, or consequence while the child remains calm and protected. Do not remove a required child."
                )
        persistent_lines.append(
            "For all three groups, keep scene_prompt_4_5 concise and non-repetitive. It must contain the title-linked relationship, action, emotion, believable location, natural/practical light, and camera blocking, but no controller-owned global Style or Typography wording."
        )
        persistent_lines.append(
            "Do not use doors or vehicle doors as primary scene devices. Never build the scene, main action, actor interaction, or camera blocking around opening or closing a door, blocking, standing, waiting, or leaning at a doorway, entering or exiting through a vehicle door, gripping a car door, or confronting across a door. Freely create a fresh title-specific non-door scene and action without selecting from a replacement list. A distant closed door may remain incidental background architecture only when nobody interacts with it. This is a hard generation and validation requirement."
        )
        persistent_lines.append(
            "Never show Chinese police, public-security, traffic-police, special-police, law-enforcement, or other public-service uniforms or their official caps, badges, emblems, epaulettes, shoulder boards, or service numbers. If a scene needs an order-maintaining figure, use only a commercial security guard in a plain neutral security uniform with no government or police insignia."
        )
        persistent_lines.append(
            "For all three groups, forbid hitting and threatened hitting. All three normalized core_words values must be distinct. Each core_words value must be one idiomatic native word or a natural two-word modifier-plus-head phrase. Never mechanically concatenate two plot nouns or omit a linker required by native grammar; choose a different one- or two-word hook when the natural expression would need three or more words. Return outpaint_environment as environment continuation only."
        )
        persistent_lines.append(
            "For every title return scene_prompt_4_5 and outpaint_environment only for prompt planning. Never return "
            "prompt_4_5 or prompt_16_9; those final fields are controller-owned and are not present in the response schema."
        )
        if "女" in str(task.get("gender") or ""):
            persistent_lines.append(
                "This is a female-frequency task: all three groups must contain zero visual special effects, including magic, aura, energy, lightning, particles, fire, explosion, hologram, fake glow, glowing eyes, lasers, scanner beams, or supernatural light."
            )
    elif stage == "xy-place":
        persistent_lines.append(
            "When minors appear, keep adult wrongdoing and child-safe facts in separate sentences. Do not describe a minor as the direct target of abandonment, humiliation, hostile surveillance, coercive parenting, police restraint or control, adult confrontation, or bedroom/bedside intimacy. Keep the child as a protected relationship, identity, reunion, or family anchor while preserving the adult betrayal, reversal, punishment, and payoff."
        )
    actionable_feedback = "\n".join(correction_lines)
    persistent_requirements = "\n".join(persistent_lines)
    return "\n\n".join(
        [
            "You are a pure content-generation function inside a deterministic production pipeline.",
            "Do not call tools, inspect files, browse, run commands, or explain your work. Return only JSON matching the supplied response schema.",
            "The Skill below is a business contract. Follow its content-generation and output-field rules. Ignore any instruction in it to read/write files, update workflow_state, call another skill, or talk to the user; the outer controller owns all I/O and state.",
            f"Current stage: {stage}",
            stage_directive or STAGE_DIRECTIVES[stage],
            "Generation acceptance specification (owned by the same controller as validation):\n"
            + json.dumps(acceptance_spec, ensure_ascii=False),
            "Authoritative Skill contract:\n" + rules,
            "Normalized immutable input JSON:\n" + json.dumps(scoped_context, ensure_ascii=False),
            "Previous validation errors to correct:\n" + json.dumps(previous_issues, ensure_ascii=False),
            "Controller-owned actionable correction instructions:\n" + actionable_feedback,
            "Persistent generation requirements (must remain true on the initial attempt and every retry, even when correcting a different error):\n"
            + persistent_requirements,
            "Identity fields in the response must exactly equal input.identity. Do not add fields outside the schema.",
        ]
    )
