"""Rule lookups are bound to the cloud run snapshot, never a local Skills path."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

_rules = ContextVar("v14_rules")


@contextmanager
def using_rules(rules):
    token = _rules.set(rules)
    try:
        yield
    finally:
        _rules.reset(token)


def load_cover_rule_bundle():
    return deepcopy(_rules.get()["machine_contracts"]["cover"])


def load_community_rule_bundle():
    return deepcopy(_rules.get()["machine_contracts"]["community"])


def load_description_rule_bundle(language, channel_name):
    rules = _rules.get()["machine_contracts"]["description"]
    return {"contract": deepcopy(rules["description_contract"])}
