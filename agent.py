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
from support import mock_backend

MAX_TOOL_CALLS = 8  # Larkspur's own build capped the loop here; then a human takes over.

TONE_ADDENDUM = ""                       # ✏️ Build 4, step 4.1, intelligence goal
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
        "name": "fare_rules",
        "description": (
            "Explain Larkspur's policies from the handbook regarding topics like refunds, "
            "care entitlements, fare families, and what chat automation cannot do. Use this "
            "when a customer asks about the policy rules themselves, not what they specifically "
            "qualify for. Returns the relevant policy section from the handbook with the rules "
            "and explanation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The policy topic the customer is asking about (e.g., 'refund policy', 'hotel coverage', 'fare families')"}
            },
            "required": ["query"],
        },
    }
]

SECTION_7 = [
    "refunds", "fare-difference collection", "hotel approval", "other-airline rebooking",
    "group bookings of 10 or more", "unaccompanied minors",
    "itineraries with partner-operated flights", "pets in cabin",
    "medical requests on a new flight", "baggage tracing", "cancelling the whole trip",
]


def what_automation_will_not_do(request: str) -> Dict[str, Any]:
    return {
        "handbook_section": 7,
        "request": request,
        "not_allowed_for_the_assistant": SECTION_7,
        "next_step": (
            "If the request matches anything on this list, do not perform it: call "
            "escalate_to_human. Otherwise continue as normal."
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


LOCAL_TOOLS: Dict[str, Any] = {          # ✏️ Build 2, step 2.1: the functions behind them
    "what_automation_will_not_do": what_automation_will_not_do,
    "hold_time_left": hold_time_left,
}


def fare_rules(query: str) -> str:
    """Look up fare rules from the handbook based on a customer query."""
    import os

    file_path = os.path.join(os.path.dirname(__file__), "data", "americas", "fare_rules_excerpt.md")

    try:
        with open(file_path) as f:
            content = f.read()
    except FileNotFoundError:
        return "Error: fare_rules_excerpt.md not found."

    query_lower = query.lower()

    # Map keywords to section numbers
    section_mappings = [
        (["refund", "cancellation", "divert", "delay"], 5),
        (["hotel", "meal", "care", "entitlement"], 6),
        (["chat", "automation", "cannot", "guardrail", "what"], 7),
        (["fare", "family", "class", "basic", "main", "first"], 4),
    ]

    # Find which section matches
    matched_section = None
    for keywords, section_num in section_mappings:
        if any(keyword in query_lower for keyword in keywords):
            matched_section = section_num
            break

    if matched_section is None:
        return "I couldn't identify which policy section answers your question. Try asking about refunds, meals/hotels, fare families, or what chat cannot do."

    # Extract the section from the content
    section_start = f"### {matched_section}."
    section_end = f"### {matched_section + 1}." if matched_section < 7 else None

    try:
        start_idx = content.find(section_start)
        if start_idx == -1:
            return f"Section {matched_section} not found in handbook."

        if section_end:
            end_idx = content.find(section_end, start_idx)
            section_text = content[start_idx:end_idx].strip()
        else:
            section_text = content[start_idx:].strip()

        return section_text
    except Exception as e:
        return f"Error extracting section: {str(e)}"


# Add all tools to LOCAL_TOOLS
LOCAL_TOOLS["fare_rules"] = fare_rules


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
    return build_tools() + EXTRA_TOOLS


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
                "again."
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
