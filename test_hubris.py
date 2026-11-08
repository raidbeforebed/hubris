#!/usr/bin/env python3
"""Tests for hubris. Run: python3 test_hubris.py

No pytest, no fixtures, no network: the plugin is deterministic, so the test is a table.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_package():
    spec = importlib.util.spec_from_file_location(
        "hubris", HERE / "__init__.py", submodule_search_locations=[str(HERE)]
    )
    assert spec is not None and spec.loader is not None, "cannot load the plugin package"
    module = importlib.util.module_from_spec(spec)
    sys.modules["hubris"] = module
    spec.loader.exec_module(module)
    return module


sf = _load_package()
classifier = sys.modules["hubris.classifier"]

FAILS: list[str] = []


def check(name: str, condition: bool) -> None:
    print(f"{'ok  ' if condition else 'FAIL'} {name}")
    if not condition:
        FAILS.append(name)


# ---------------------------------------------------------------- classification table
# True = this turn turns on current external facts and deserves the directive.
CASES = [
    # the case that started the plugin
    ("I just need a checklist or where to start with the ATM Star", True),
    ("what is the best ATM10 star guide online right now?", True),
    ("Which All the Mods 10 modpack version is current right now?", True),
    ("Which mods do I need for the ATM star in ATM10?", True),
    # money, versions, availability, law, news
    ("how much does a 2TB NVMe cost today?", True),
    ("is there a D&D 5e boxed set available?", True),
    ("can you give me your ranking of the best AR's in the price range.", True),
    ("it's legal to hunt deer in louisiana with that rifle, correct?", True),
    ("in the recent elections in Hammond, LA who won the Mayor election?", True),
    ("Is Python 3.9 still supported?", True),
    # an explicit request to go and find something
    ("I need you to look up a jambalaya recipe for me.", True),
    ("Also research if there are any settings optimization which might improve it", True),
    ("compare draw.io and mermaid for this diagram", True),
    # never research: this installation, family, code, memory, local operation
    ("is hermes gateway running?", False),
    ("what is the SSH port of the PC?", False),
    ("Jackson is weak on integer exponents, what should we do?", False),
    ("fix the failing test in tools/approval.py", False),
    ("reply with exactly: NONE2", False),
    ("remember that I prefer short answers", False),
    ("add a /citecheck command to the plugin", False),
    # the everyday words that used to misfire
    ("So hold the clean button down now?", False),
    ("So can you connect and control the Roomba now", False),
    ("I'm still not sure if this is working.", False),
    ("are you still updating", False),
    ("Leave the schedule as is. But for today, once the battery is charged can you trigger it.", False),
    ("which is better for you", False),
    ("do what you think is best to fix it", False),
    ("Since you have access now what can you do or tell me about it", False),
    ("when you are researching prices for me, can you give me hyperlinks", False),
    # a bare acknowledgement is skipped; a substantive turn that starts with one is not
    ("ok", False),
    ("thanks", False),
    ("go ahead.", False),
    ("ok, let's flesh this out. we have the best at the $600 price range, give me the best at 800", True),
]

for text, want in CASES:
    got = classifier.classify(text).research
    check(f"classify {got!s:5s} {text[:56]}", got is want)


# ---------------------------------------------------------------- which tools count
TOOL_CASES = [
    ("web_search", True),
    ("web_extract", True),
    ("mcp__searxng__searxng_web_search", True),
    ("mcp__perplexica__perplexica_search", True),
    ("mcp__brave_search__brave_web_search", True),
    ("search_files", False),          # ripgrep over the disk is not the web
    ("session_search", False),        # the local session DB is not the web
    ("read_file", False),
    ("terminal", False),
]
for name, want in TOOL_CASES:
    check(f"counts_as_research {name} -> {want}", classifier.counts_as_research(name) is want)


# ---------------------------------------------------------------- hook behaviour
class FakeCtx:
    """Just the two members the plugin uses: settings and hook registration."""

    def __init__(self, **settings):
        self.settings = settings
        self.hooks: list[str] = []

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, fn):
        self.hooks.append(name)


def with_settings(**settings):
    """Install a fake context for one block; returns the previous context."""
    previous = sf._CTX
    sf._CTX = FakeCtx(**settings)
    return previous


def test_hooks() -> None:
    # research turn, no search -> directive in, footer out
    injected = sf.on_pre_llm_call(
        session_id="t1", user_message="what is the best ATM10 guide right now?", platform="cli"
    )
    check("directive injected for a research turn", bool(injected and "[hubris]" in injected["context"]))
    out = sf.on_transform_llm_output(response_text="Answer.", session_id="t1")
    check("footer appended when no search ran", bool(out and "no live web search ran" in out))
    check("footer names the plugin and says OBE", bool(out and "hubris" in out and "OBE" in out))
    check("footer is idempotent", sf.on_transform_llm_output(response_text=out, session_id="t1") is None)

    # research turn with a real web search -> no footer
    sf.on_pre_llm_call(session_id="t2", user_message="what is the current price of a 3080?")
    sf.on_post_tool_call(tool_name="web_search", session_id="t2", result="{}")
    check("no footer when a web search ran", sf.on_transform_llm_output(response_text="x", session_id="t2") is None)

    # MCP search tools count
    sf.on_pre_llm_call(session_id="t3", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="mcp__searxng__searxng_web_search", session_id="t3")
    check("MCP search counts as research", sf.on_transform_llm_output(response_text="x", session_id="t3") is None)

    # a local file search is NOT research: the footer must still fire
    sf.on_pre_llm_call(session_id="t3b", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="search_files", session_id="t3b")
    check(
        "a local file search does not silence the footer",
        sf.on_transform_llm_output(response_text="x", session_id="t3b") is not None,
    )

    # unrelated tool does not count
    sf.on_pre_llm_call(session_id="t4", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="read_file", session_id="t4")
    check("a file read is not a search", sf.on_transform_llm_output(response_text="x", session_id="t4") is not None)

    # the ledger is per session: a search in one session does not excuse another
    sf.on_pre_llm_call(session_id="t4b", user_message="latest ATM10 version?")
    sf.on_pre_llm_call(session_id="t4c", user_message="latest ATM10 version?")
    sf.on_post_tool_call(tool_name="web_search", session_id="t4b")
    check(
        "a search in another session does not silence this one",
        sf.on_transform_llm_output(response_text="x", session_id="t4c") is not None,
    )

    # local turn -> nothing at all
    check(
        "local turn gets no directive",
        sf.on_pre_llm_call(session_id="t5", user_message="is hermes gateway running?") is None,
    )
    check("local turn gets no footer", sf.on_transform_llm_output(response_text="yes", session_id="t5") is None)

    # multimodal turn: text parts only
    parts = [{"type": "text", "text": "what is the current price of a 1070 Ti?"}, {"type": "image_url"}]
    check(
        "multimodal text parts are read",
        bool(sf.on_pre_llm_call(session_id="t6", user_message=parts)),
    )

    # config can disable the plugin
    previous = with_settings(enabled=False)
    try:
        check(
            "config can disable the plugin",
            sf.on_pre_llm_call(session_id="t7", user_message="what is the best GPU right now?") is None,
        )
    finally:
        sf._CTX = previous

    # a quiet platform gets neither the directive nor the footer
    previous = with_settings(quiet_platforms=["discord_voice"])
    try:
        check(
            "quiet platform gets no directive",
            sf.on_pre_llm_call(
                session_id="t8", user_message="latest ATM10 version?", platform="discord_voice"
            ) is None,
        )
        check(
            "quiet platform gets no footer",
            sf.on_transform_llm_output(response_text="x", session_id="t8") is None,
        )
        check(
            "a platform not named as quiet still gets the directive",
            bool(sf.on_pre_llm_call(
                session_id="t9", user_message="latest ATM10 version?", platform="cli"
            )),
        )
    finally:
        sf._CTX = previous

    # a user phrase teaches a new domain without editing the classifier
    previous = with_settings(extra_trigger_phrases=["kubernetes"])
    try:
        check(
            "extra trigger phrase fires",
            classifier.classify("kubernetes pod stuck", extra_trigger_phrases=["kubernetes"]).research,
        )
        check(
            "settings reach the classifier through the hook",
            bool(sf.on_pre_llm_call(session_id="t10", user_message="kubernetes pod stuck")),
        )
    finally:
        sf._CTX = previous

    # a skip phrase wins over every built-in trigger
    check(
        "extra skip phrase wins over a trigger",
        not classifier.classify(
            "what is the best thesis topic", extra_skip_phrases=["thesis topic"]
        ).research,
    )


test_hooks()

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {FAILS}")
    raise SystemExit(1)
print("all checks passed")
