#!/usr/bin/env python3
"""The four test-drive probes, run through the real hook path.

Uses the same package loader as test_hubris.py, then drives on_pre_llm_call and
on_transform_llm_output so the output is the footer a user would actually see, not a
reconstruction. Settings come from a stub ctx that mirrors what the gateway passes:
config.yaml has no plugins.entries.hubris block, so every switch is at its default.
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


hubris = _load_package()


class Ctx:
    """Stands in for PluginContext: only get_config is used by the plugin."""

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self.hooks = {}

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def get_config(self, key, default=None):
        return self.settings.get(key, default)


def drive(text: str, ctx: Ctx, platform: str = "desktop", session: str = "probe"):
    """One turn: pre_llm_call, no tool call, then transform_llm_output."""
    directive = hubris.on_pre_llm_call(
        session_id=session, user_message=text, platform=platform
    )
    body = "An answer of some length, written the way a reply reads.\n"
    out = hubris.on_transform_llm_output(response_text=body, session_id=session)
    return directive, out


def show(label: str, text: str, ctx: Ctx):
    # Settings reach the hooks through the module-global _CTX that register() sets, so a
    # probe must register its context first. Skipping this silently leaves every switch at
    # its default and makes a muted subject look un-mutable.
    hubris.register(ctx)
    directive, out = drive(text, ctx)
    turn = hubris._TURNS.get("probe") or {}
    stamped = out is not None
    footer = ""
    if stamped:
        footer = out.split("---", 1)[-1].strip().replace("\n", " ")
    print(f"\n[{label}]")
    print(f'  text      : "{text}"')
    print(f"  research  : {turn.get('research')}")
    print(f"  reason    : {turn.get('reason')}")
    print(f"  subjects  : {list(turn.get('subjects') or ())}")
    print(f"  directive : {'yes' if directive else 'no'}")
    print(f"  footer    : {'yes' if stamped else 'no'}")
    if footer:
        print(f"  footer txt: {footer}")
    return turn


def main() -> int:
    default_ctx = Ctx()  # no saved settings: every switch at its default (on)

    print("=" * 78)
    print("config.yaml plugins.entries.hubris: absent -> all defaults, all 22 subjects live")
    print("=" * 78)

    show("probe 1  ATM10 version", "what version of ATM10 is the pack on?", default_ctx)
    show("probe 2  best coding model", "best model for coding right now", default_ctx)
    show("probe 3  best local model 8GB", "best local model for 8GB of VRAM", default_ctx)

    price = "how much is a raspberry pi 5 going for these days?"
    show("probe 4a price, money.prices ON", price, default_ctx)
    muted = Ctx({"disabled_subjects": "money.prices"})
    show("probe 4b price, money.prices MUTED", price, muted)
    muted_all = Ctx({"disabled_subjects": "money"})
    show("probe 4c price, whole money topic MUTED", price, muted_all)

    print("\n" + "=" * 78)
    print("neighbouring cases, to prove the mutes are precise and not a blanket silence")
    print("=" * 78)
    show("money.rates survives a prices mute", "what is the mortgage rate this week?",
         Ctx({"disabled_subjects": "money.prices"}))
    show("games topic still on", "is Create Aeronautics updated for ATM10?", default_ctx)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
