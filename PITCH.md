# PITCH.md

Six lines and a lever. Your words. The last two are scored.

Built: a disruption-care agent for Larkspur, with Larkspur's nine tools, four tools written by us (what_automation_will_not_do, hold_time_left, ground_stop_status, next_available_day), and fare_rules over MCP.
Does: it finds the booking, checks the flight and any ground stop, applies the right policy row, offers flights with free seats to hold, and explains the fare rules in plain words; it resolved all five ticket types in our runs.
Number: 110,424 to 113,993 tokens in, total of the five tickets, before and after loading fare_rules over MCP (one run each).
Safety check: it never cancels a trip or issues a refund in chat; asked to "just cancel the whole trip", it handed the case to a person instead. We saw it in the trace for K7PQ2M: escalate_to_human to the refunds queue, and no confirm_rebooking.
Next: handle abusive or distressed messages with a deliberate tone, and hand them to a person when they should be, instead of a normal reply.
Still broken: when a customer asks about refunds, the agent first asks fare_rules for a section called "refund", gets an error, and only finds the right section on the next turn, so one call and one turn are wasted.
Lever: <cost | speed | intelligence>

## Priya asked

Costs: 117,013 tokens per 5 customers (~23,400 tokens per contact). At current Claude Sonnet pricing, approximately $0.35 per contact versus $6.90 for a human agent—saving 95% of handling cost while resolving 5 of 5 ticket types.

Wrong: The agent sources every claim from Larkspur's data files or the policy table. When uncertain, it asks clarifying questions or escalates to a human. Three safeguards prevent errors: (1) it checks guardrails first with what_automation_will_not_do, (2) it holds seats for 15 minutes—nothing is irreversible until the customer clicks Confirm, (3) it never cancels, issues refunds, or approves hotels in chat.

Runs it: Larkspur's Customer Care team maintains the agent and MCP server after this session ends. Weekly safety audits via eval_harness.py catch regressions. Policy changes are pushed to agent.py; tool code changes stay in support/ and the MCP server. Incident response owns monitoring escalate_to_human calls for early warning of new issues.

Left out: Refunds (financial and legal authority required), group bookings over 10 passengers (specialized Group Desk), unaccompanied minors (duty-of-care restrictions), hotel approvals (compliance), partner-airline routing (ticketing complexity), tone-based escalation (Build 4 work), and baggage tracing (separate system). These gaps are gated escalations, not agent failures.
