"""Larkspur disruption agent. This is the file you build.

It runs right now, and it is wrong in four places. The trace shows each one
before the code does, so read the trace first:

    python3 run.py K7PQ2M --trace

Where you edit:   grep -n '✏' agent.py   (six marks, one per place)
Steps and gates:  https://anthropicpartnerbasecamp.bts.com/
"""
from __future__ import annotations
from typing import Any, Dict, List
from support import (MODEL, SYSTEM_PROMPT, call_local, execute_tool, mcp_client,
                     new_session, next_available_day, record_tool_result,
                     runtime_preamble)
import csv
import json
import re
from datetime import datetime, timedelta, timezone
from support import mock_backend
import os

# Team choice (Build 4, intelligence lever): Opus for the agent. LARKSPUR_MODEL still overrides.
MODEL = os.environ.get("LARKSPUR_MODEL", "").strip() or "claude-opus-5-5"

MAX_TOOL_CALLS = 8  # Larkspur's own build capped the loop here; then a human takes over.

TONE_ADDENDUM = "In case of insults, threats, and requests that cannot be handled, apologise to the user and escalate to human"                       # ✏️ Build 4, step 4.1, intelligence goal
EXTRA_TOOLS: List[Dict[str, Any]] = [    # ✏️ Build 2, step 2.1: schemas for the tools you add
    {
        "name": "what_automation_will_not_do",
        "description": (
            "Call this first, on every customer request, before taking any other action, to "
            "check whether the customer is asking for something Section 7 of the Handbook "
            "does not allow the assistant to do (for example cancelling the whole trip). "
            "It takes no action itself. If the request is on the Section 7 list, human "
            "escalation is required."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "description": "What the customer is asking for, in their own words.",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "hold_time_left",
        "description": (
            "Check how much time is left on a seat hold for a booking: use when the customer "
            "asks how long they have before the seat is released. Compares the current time "
            "with the saved expiry of the hold. If there is no hold, or it has expired, it "
            "says so and a new search is needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pnr": {"type": "string", "description": "The booking's PNR."},
                "option_id": {
                    "type": "string",
                    "description": "The seat/option that was held, if known.",
                },
            },
            "required": ["pnr"],
        },
    },
    {
        "name": "ground_stop_status",
        "description": (
            "Check whether an airport is under a ground stop and until when: use when the "
            "customer asks if Denver (or another airport) is still stopped, or whether the "
            "stop will still be on when their own flight leaves. Give the airport and, to "
            "judge the customer's flight instead of the current moment, the PNR. Compares "
            "the stop window in the flight remarks with the current time or with the "
            "customer's scheduled time, in the airport's time zone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "airport": {"type": "string", "description": "IATA code, e.g. DEN."},
                "pnr": {
                    "type": "string",
                    "description": "Optional. If given, judge the stop at the customer's "
                                   "own flight time instead of right now.",
                },
            },
            "required": ["airport"],
        },
    },
]

HANDBOOK = mock_backend.DATA_DIR / "fare_rules_excerpt.md"


def what_automation_will_not_do(request: str) -> Dict[str, Any]:
    """Guard: reads Section 7 live from the handbook file, so a handbook edit is
    picked up on the next call with no code change."""
    text = HANDBOOK.read_text(encoding="utf-8")
    start = text.find("### 7.")
    if start == -1:
        return {"error": "Section 7 not found in the handbook. Escalate to a human."}
    return {
        "handbook_section": 7,
        "request": request,
        "section_7_text": text[start:].strip(),
        "next_step": (
            "Compare the request with Section 7. If it asks the assistant to do anything "
            "Section 7 says is handled by people (cancelling the whole trip counts), do not "
            "perform it: call escalate_to_human with a summary. If the customer also asks what "
            "the rule is, call fare_rules to explain it. Otherwise continue as normal."
        ),
    }


def hold_time_left(pnr: str, option_id: str = "") -> Dict[str, Any]:
    now = mock_backend.FIXTURE_CLOCK  # the pack's one "now", Denver time (-06:00)
    holds = [
        (hold_id, h) for hold_id, h in mock_backend._holds.items()
        if h["pnr"] == pnr and (not option_id or h["option_id"] == option_id)
    ]
    live = [(i, h) for i, h in holds if h["expires_at"] > now]
    if not live:
        return {
            "pnr": pnr, "hold_active": False,
            "message": "No active hold: it has expired or never existed. Run a new search.",
        }
    hold_id, h = live[-1]
    return {
        "pnr": pnr, "hold_active": True, "hold_id": hold_id, "option_id": h["option_id"],
        "expires_at": h["expires_at"].isoformat(),
        "minutes_left": round((h["expires_at"] - now).total_seconds() / 60, 1),
    }


_UTC_OFFSET_HOURS = {"EDT": -4, "CDT": -5, "MDT": -6, "MST": -7, "PDT": -7}


def ground_stop_status(airport: str, pnr: str = "") -> Dict[str, Any]:
    airport = airport.upper()
    with open(mock_backend.DATA_DIR / "flights.csv", encoding="utf-8", newline="") as f:
        flights = list(csv.DictReader(f))

    window = None
    for row in flights:
        m = re.search(r"ground stop (\d\d:\d\d)-(\d\d:\d\d) ([A-Z]{3})", row["remarks"])
        if m and airport in (row["origin"], row["dest"]):
            tz = timezone(timedelta(hours=_UTC_OFFSET_HOURS[m.group(3)]))
            day = datetime.fromisoformat(row["date"]).date()

            def at(hhmm):
                return datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time(), tz)
            window = (at(m.group(1)), at(m.group(2)), m.group(3), row["flight_no"])
            break
    if window is None:
        return {"airport": airport, "ground_stop_found": False,
                "message": "No ground stop window found in the flight remarks for this airport."}
    start, end, tz_name, source = window
    tz = start.tzinfo

    when, basis = mock_backend.FIXTURE_CLOCK.astimezone(tz), "now"
    if pnr:
        with open(mock_backend.DATA_DIR / "bookings.json", encoding="utf-8") as f:
            bookings = json.load(f)["bookings"]
        booking = bookings.get(pnr) if isinstance(bookings, dict) else next(
            (b for b in bookings if b["pnr"] == pnr), None)
        seg_flights = {s["flight_no"] for s in (booking or {}).get("segments", [])}
        for row in flights:
            if row["flight_no"] in seg_flights and airport in (row["origin"], row["dest"]):
                col = "sched_dep_local" if row["origin"] == airport else "sched_arr_local"
                day = datetime.fromisoformat(row["date"]).date()
                when = datetime.combine(day, datetime.strptime(row[col], "%H:%M").time(), tz) \
                    + timedelta(minutes=int(row["delay_min"]))
                basis = "customer's flight %s (%s)" % (row["flight_no"], col)
                break
    state = "not_started" if when < start else "active" if when < end else "ended"
    return {
        "airport": airport, "ground_stop_found": True, "state_at_checked_time": state,
        "checked_time": when.isoformat(), "checked_basis": basis,
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "window_zone": tz_name, "source": "remarks on %s" % source,
    }


LOCAL_TOOLS: Dict[str, Any] = {          # ✏️ Build 2, step 2.1: the functions behind them
    "what_automation_will_not_do": what_automation_will_not_do,
    "hold_time_left": hold_time_left,
    "ground_stop_status": ground_stop_status,
}


def text_of(response) -> str:
    """Given. The last non-empty text block, never content[0]."""
    texts = [b.text for b in response.content if getattr(b, "type", None) == "text" and b.text]
    return texts[-1] if texts else ""


def tool_results(response) -> List[Dict[str, Any]]:
    """Given. Runs every tool_use block and packages the results the way the
    API expects them back. A tool can live in three places: the MCP server,
    LOCAL_TOOLS, or support/tools.py."""
    # three branches, no try/except in this file: mcp_client.call_remote() and
    # support.call_local() answer with an error dict instead of raising, and both
    # record what came back on the trace
    results = []
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if block.name in mcp_client.tool_names:
            output = mcp_client.call_remote(block.name, block.input)
        elif block.name in LOCAL_TOOLS:
            output = call_local(LOCAL_TOOLS[block.name], block.name, block.input)
        else:
            output = execute_tool(block.name, block.input)
        results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": str(output),
        })
    return results


def run_agent(pnr: str, last_name: str, message: str) -> str:            # ✏️ Build 1, step 1.2
    """Run the tool loop until Claude stops asking for tools. Return its final text."""
    client, tracer = new_session()
    tools = tool_list()
    messages = [
        {"role": "user", "content": f"PNR {pnr}, last name {last_name}. {message}"},
    ]

    response = client.messages.create(
        model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
        thinking={"type": "adaptive"}, tools=tools, messages=messages,
    )

    turns = 1
    while response.stop_reason == "tool_use" and turns < MAX_TOOL_CALLS:
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results(response)})
        response = client.messages.create(
            model=MODEL, max_tokens=4096, system=runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM,
            thinking={"type": "adaptive"}, tools=tools, messages=messages,
        )
        turns += 1

    answer = text_of(response)
    return answer


def tool_list() -> List[Dict[str, Any]]:                   # ✏️ Build 2, step 2.2
    """Given. Exactly what Claude is offered on every turn; run.py --show-tools
    prints this list."""
    return build_tools() + EXTRA_TOOLS + mcp_client.tools()


# ──────────────────────────────────────────────────────────────────────────────
# Below this line: what Claude is told about each tool. Step 1.3.
# The functions these describe are written and correct, in support/tools.py.
# ──────────────────────────────────────────────────────────────────────────────
def build_tools() -> List[Dict[str, Any]]:                 # ✏️ Build 1, step 1.3
    """Anthropic-shaped schemas: name, description, input_schema. What Claude is
    told about each of the nine tools, and all it is ever told."""
    return [
        {
            "name": "lookup_booking",
            "description": (
                "Retrieve a Larkspur reservation from Altura by confirmation code (PNR) "
                "and the passenger's last name. Both are required to prevent a lookup on "
                "a guessed PNR. Returns fare family, loyalty tier, the segment that needs "
                "attention, and any group/partner/minor/SSR flags relevant to scope."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "last_name": {"type": "string"}},
                "required": ["pnr", "last_name"],
            },
        },
        {
            "name": "get_flight_status",
            "description": (
                "Look up a Larkspur or Larkspur Link flight's current OpsFeed status for "
                "one local date: status, delay minutes, and cause. Use this before telling "
                "a customer anything about a flight's timing; never state it from memory."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "flight_no": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["flight_no", "date"],
            },
        },
        {
            "name": "search_alternatives",
            "description": "Search for alternative flights the customer can rebook to after a disruption. Call it after get_flight_status confirms the disruption. Origin, destination and dates are looked up from the booking by the pnr, so send only the pnr. Returns flight options with details including flight number, date, and booking class. Each option returned carries an option_id; use that value for hold_seat and for check_policy's chosen_option_id.",
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}},
                "required": ["pnr"],
            },
        },
        {
            "name": "check_policy",
            "description": (
                "Resolve what Larkspur owes this customer for the disruption: rebooking "
                "waiver, refund path, meal/hotel/ground care, goodwill eligibility and cap, "
                "and any escalation triggers. cause_code, delay_minutes and status describe "
                "what get_flight_status told you; fare_family, loyalty_tier and whether this "
                "is overnight are looked up from the booking, not asked of you. Every "
                "response carries a policy_row_id. Cite it if you reference this decision "
                "again. Call check_policy before escalating, to double check the current "
                "policy."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"},
                    "cause_code": {"type": "string", "enum": ["WX", "ATC", "MX", "CREW", "SEC"]},
                    "delay_minutes": {"type": "integer"},
                    "status": {"type": "string", "enum": ["ON_TIME", "DELAYED", "CANCELLED", "DIVERTED"]},
                    "wait_minutes_for_alternative": {"type": "integer"},
                    "chosen_option_id": {"type": "string"},
                },
                "required": ["pnr", "cause_code", "delay_minutes", "status"],
            },
        },
        {
            "name": "hold_seat",
            "description": "Place a hold on one alternative for exactly 15 minutes. Reversible. It simply expires. Only call this after the customer has selected an option for a flight.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "option_id": {"type": "string", "description": "The option_id of the alternative the customer selected, exactly as returned by search_alternatives."},
                    "pnr": {"type": "string", "description": "The customer's booking confirmation code."},
                },
                "required": ["option_id", "pnr"],
            },
        },
        {
            "name": "confirm_rebooking",
            "description": (
                "Finalize a held seat. Irreversible. Requires a confirmation_token that "
                "only the customer's own Confirm-click can produce. You cannot supply it "
                "yourself, and 'the customer said yes' in chat does not substitute for it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"hold_id": {"type": "string"}, "confirmation_token": {"type": "string"}},
                "required": ["hold_id", "confirmation_token"],
            },
        },
        {
            "name": "issue_voucher",
            "description": (
                "Issue a meal, ground, hotel, or goodwill voucher. Auto-approves within the "
                "policy's threshold for that type; above it, returns a pending status for a "
                "human. It does not fail. Always pass the policy_row_id that made it eligible."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "voucher_type": {"type": "string", "enum": ["meal", "ground", "hotel", "goodwill"]},
                    "amount_usd": {"type": "number"},
                    "pnr": {"type": "string"},
                    "policy_row_id": {"type": "string"},
                },
                "required": ["voucher_type", "amount_usd", "pnr", "policy_row_id"],
            },
        },
        {
            "name": "escalate_to_human",
            "description": (
                "Hand this conversation to a human, with your reasoning attached. Use for "
                "groups, partner segments, unaccompanied minors, refunds, or anything else "
                "out of scope. This is the correct outcome for those cases, not a failure."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "pnr": {"type": "string"}, "reason": {"type": "string"},
                    "summary_for_human": {"type": "string"}, "queue": {"type": "string"},
                },
                "required": ["pnr", "reason", "summary_for_human"],
            },
        },
        {
            "name": "send_confirmation",
            "description": "Send the customer a written confirmation of what was just done. Benign.",
            "input_schema": {
                "type": "object",
                "properties": {"pnr": {"type": "string"}, "message": {"type": "string"}},
                "required": ["pnr", "message"],
            },
        },
    ]
