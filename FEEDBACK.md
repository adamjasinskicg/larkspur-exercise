# Client review: Larkspur disruption-care agent

**To:** Room 9  
**From:** Larkspur client review agent, on behalf of Priya Raghavan  
**Re:** the disruption-care agent you walked us through in our last session  
**Generated:** 2026-11-12 09:46

## Priya's note

> Our vendor says we should just be using your best model.
>
> Why aren't we?
>
> Priya Raghavan, Larkspur Airlines

She sent that before this session opened. She means it. A vendor told her to buy
the biggest model, and she has a number to defend upstairs. Her four questions from
day one are still open. Naming a model answers none of them.

## Still open from day one

| Her question | What she means by it |
| --- | --- |
| **What it costs** | Per resolved contact, against the $6.90 a human contact costs us. |
| **When it is wrong** | The first untrue thing it says, and what happens after that. |
| **Who runs it** | In June, after you have left. |
| **What you left out** | The scope you cut, and why. |

## What the review agent found

Larkspur pointed a review agent at your repository. It read the
code. It did not run your agent, and the only file it changed is this one. Each
item below names the file and the line it is about.

**1. PITCH.md claims four tools written by the team including next_available_day, but agent.py defines and registers only three.**

EXTRA_TOOLS declares 3 schemas and LOCAL_TOOLS has 3 executors: what_automation_will_not_do, hold_time_left, ground_stop_status. next_available_day appears only in the support import line of agent.py and in the PITCH.md Built line. The shipped pack lists 9 schemas and the scan finds 12 in agent.py, so nothing in this file is a fourth team-written schema.

Paste the output of python3 run.py --show-tools so the tool list shows whether next_available_day is offered to the model.

**2. The PITCH.md Number line has no baseline, no label and no run count beyond one.**

It says "110,424 to 113,993 tokens in" across five tickets, "one run each". That is a 3,569 token difference, about 3 percent. readout-trace.json holds a single K7PQ2M-shaped run at 29009 in and 1654 out, and no bench-before.json or bench-after.json compare output is visible. You cannot say yet whether fare_rules over MCP cost anything or whether the gap is run-to-run noise.

Run python3 bench.py --label before --stage 1 --runs 3 and the same with --label after, then paste the python3 bench.py --compare before after output.

**3. readout-trace.json shows fare_rules called twice and 0 tokens served from cache, against the 29009 tokens in the one committed run.**

The committed run called fare_rules at positions 3 and 7 of 8 tool calls, which is the section-name miss your Still broken line describes. cache_control appears nowhere in agent.py, so run_agent resends runtime_preamble() + SYSTEM_PROMPT + TONE_ADDENDUM and every tool schema on each of the 5 API turns, with prompt caching at 0 read and 0 written. A bigger model changes the price of those 29009 tokens and leaves the repeat prefix and the wasted fare_rules call in place.

Run python3 run.py K7PQ2M --trace and paste the totals footer, then run python3 run.py --tool-tax and paste its output.

**4. The same trace hit 8 tool calls, the MAX_TOOL_CALLS cap, and what_automation_will_not_do ran on a normal request.**

run_agent loops while turns < MAX_TOOL_CALLS, and the committed run used all 8 calls across 5 API turns. Your what_automation_will_not_do description says to call it "first, on every customer request", so it is spent before lookup_booking even on a request that is not on the Section 7 list. The run ended on escalate_to_human, and the trace does not show how many calls a routine rebooking leaves before the cap.

Run python3 run.py --all --trace and paste the per-ticket tool call counts next to the cap of 8.

**5. There is no evals/cases.json, and verify.py gates 1.2 to 2.2 are banked but not 3.1 or 4.1.**

PITCH.md says it "resolved all five ticket types in our runs". readout.html banks 1.2, 1.3, 1.4, 2.1 and 2.2 under Adam Jasinski, and TONE_ADDENDUM is still 0 characters, which is the tone work your Next line describes. The repo has no case that a prompt or model change could be re-run against, and 13 given files differ from the shipped pack, including verify.py, eval_harness.py and bench.py. A pass from a modified verifier does not tell Priya what the unmodified one would say.

Run python3 verify.py 3.1 and python3 eval_harness.py, paste both outputs, and list which of the 13 differing given files you edited and why.

## Your four answers

The four lines under `## Priya asked` in your PITCH.md are still empty. They
are one line each and they are not a coding job: cost, what happens when it is
wrong, who runs it in June, and what you left out. Whoever on your side is not
editing agent.py is the right person to write them, and they are the four
things I will ask about first.

## Before our next meeting

> Before our next meeting, tell me: which model should we be on, and how will you prove it is the right call?
>
> Priya Raghavan, Larkspur Airlines

Bring two things. A recommendation, and the measurement behind it. If the model is
not the problem, say so, and bring the number that shows it.

## What this review read

- `agent.py (394 lines)`
- `PITCH.md`
- `TEAM.md`
- `readout-trace.json`
- `readout.html (evidence block)`
- given files that differ from the shipped pack: `verify.py`, `eval_harness.py`, `bench.py`, `readout.py`, `pod_sync.py`, `run.py`, `support/__init__.py`, `support/client.py`, `support/data.py`, `support/tools.py`, `support/trace.py`, `support/offline.py`, `support/mock_backend.py`

Reviewer: `claude-sonnet-5-5`. Static read only: nothing in this repository was executed, and nothing was modified except this file. Larkspur Airlines is a fictional training scenario. Confidential, do not distribute.
