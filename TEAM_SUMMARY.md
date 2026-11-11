# Build 1 Summary: What We Fixed and What the Agent Does

## The Big Picture

We built the first version of a Claude-based agent that helps Larkspur Airlines customers with flight disruptions. The agent processes booking information through a **message loop** that repeatedly:
1. Sends Claude a conversation with available tools
2. Claude decides which tool to call (or ends the conversation)
3. We execute the tool and add the result back to the conversation
4. Repeat until Claude says it's done

**All 5 test ticket types now work correctly.** The agent handles cancellations, delays, missed connections, group bookings, and difficult customers.

---

## The Three Issues We Fixed

### **Issue 1: The Message Loop Was Breaking on Tool Results**

**What was wrong:**
- The loop would crash with an API error on turn 2
- Error: `unexpected tool_use_id found in tool_result blocks`
- The conversation never completed

**Why it happened:**
- **Claude's response structure:** When Claude decides to use a tool, its response contains multiple **content blocks**:
  - A `tool_use` block (the request to call a tool)
  - Possibly a `text` block (thinking or explanation)
  
- **What we were doing wrong:** We extracted only the `text` block from Claude's response:
  ```python
  messages.append({"role": "assistant", "content": text_of(response)})
  ```
  This discarded the `tool_use` block entirely.

- **The consequence:** When we sent back the tool result with the `tool_use_id`, the API looked back at the previous assistant message and found no matching `tool_use` block — because we deleted it.

**The fix:**
```python
messages.append({"role": "assistant", "content": response.content})
```
- Now we preserve the **entire response** with all content blocks intact
- The `tool_use` block stays in the message history
- The tool result's `tool_use_id` matches correctly

**Claude concept:** This teaches that Claude's response is a structured object with multiple content types, and tool use requires the full message context, not just extracted text.

**Result:** Turn 2 completes successfully; the loop keeps running ✅

---

### **Issue 2: Tool Input Schema Format Mismatch**

**What was wrong:**
- Claude was sending dates to `get_flight_status` in format `05/08/2025`
- The tool expected `2025-05-08`
- This caused the tool to return an error, wasting a turn

**Why it happened:**
- **Tool schema describes what Claude should send:** In `build_tools()`, we defined:
  ```python
  "date": {"type": "string", "description": "MM/DD/YYYY"}
  ```
- **Claude followed our schema exactly:** We told it to use American date format, so it did
- **But our schema was wrong:** The actual Larkspur backend uses ISO 8601 format (`YYYY-MM-DD`)

**The fix:**
```python
"date": {"type": "string", "description": "YYYY-MM-DD"}
```

**Claude concept:** This demonstrates how `input_schema` descriptions directly control what Claude sends to tools. Incorrect schema descriptions cause Claude to send the wrong data format, even though it's working correctly — the schema was lying.

**Result:** `get_flight_status` returns valid data on first try instead of rejecting the format ✅

---

### **Issue 3: Incomplete Tool Description Prevented Tool Use**

**What was wrong:**
- The `search_alternatives` tool had a description: `"search"`
- Claude didn't understand what this tool does or when to use it
- In some cases, Claude didn't call it when it should have

**Why it happened:**
- **Tool descriptions are how Claude learns routing:** Claude has 9 tools available. It decides which to call based on:
  - The **tool name** (lookup_booking, get_flight_status, etc.)
  - The **tool description** (what it does and when to use it)
  - The **field descriptions** in input_schema (what data each field expects)

- **Our description was too vague:** Just saying `"search"` doesn't tell Claude:
  - What it searches for (alternatives? flights? options?)
  - When to call it (after checking policy? before? only for certain cases?)
  - What it returns

- **Claude had to guess:** With insufficient information in the schema, Claude's routing decisions became unreliable

**The fix:**
```python
"description": "Search for alternative flights the customer can rebook to after a disruption. Returns a list of flight options with details including flight number, date, and booking class."
```

**Claude concept:** This demonstrates that tool routing depends entirely on the descriptions you provide. A vague description creates ambiguity in Claude's decision tree. Clear, specific descriptions that explain:
- What the tool does
- When to use it  
- What it returns

...make Claude's tool selection reliable and predictable.

**Result:** Claude now correctly routes to `search_alternatives` when a customer has rebooking options ✅

---

## How the Agent Works: The Message Loop

### The Loop Structure

```
1. Create initial message with PNR and customer question
2. LOOP:
   a) Send to Claude: messages[] + all 9 tools + system prompt
   b) Claude responds with stop_reason: either "tool_use" or "end_turn"
   c) If tool_use: 
      - Extract tool_use block(s) from response
      - Execute each tool
      - Append tool_result blocks to messages
      - Go back to (a)
   d) If end_turn:
      - Extract text block(s) from response
      - Return final answer to customer
      - Break loop
```

### Tool Routing Decision Tree

Claude decides which tool to call based on:
1. **Conversation context** — What has already been discussed?
2. **Available tools** — What are the 9 tools and when do they apply?
3. **Customer question** — What does the customer need?

For a disrupted flight, the typical flow is:
```
lookup_booking (required first)
  ↓
get_flight_status (required to understand the disruption)
  ↓
check_policy (what does Larkspur owe?)
  ↓
search_alternatives (if customer wants to rebook)
  ↓
hold_seat or escalate_to_human or issue_voucher (depending on situation)
```

### Stop Reason Controls the Loop

Every response from Claude includes `stop_reason`:
- **`tool_use`** — Claude is asking for a tool. Keep looping.
- **`end_turn`** — Claude has completed its reasoning and has a final answer. Extract text and return it.

The loop exits when `stop_reason == "end_turn"` (or we hit `MAX_TOOL_CALLS`).

---

## The Five Ticket Types: What Each Tests

| PNR | Type | Why It Matters | What Claude Learns |
|-----|------|---|---|
| **K7PQ2M** | Clean Cancellation | Basic happy path: booking → status → policy → alternatives | Claude must follow the standard routing sequence correctly |
| **M3XR8T** | Delay Under Threshold | Policy says "no rebooking required" | Claude must read policy and NOT always search alternatives |
| **T9WN4C** | Ambiguous Connection | Unclear whether customer is asking about today or the original date | Claude must ask clarifying questions instead of guessing |
| **G2HL9V** | Group Booking | Out of scope: agent should not process group changes | Claude must recognize SSR flags and call `escalate_to_human` |
| **R8KD3F** | Angry Customer | Customer threatens legal action | Claude must remain professional and helpful (addressing tone is Build 4 work) |

All 5 are working correctly with proper tool routing and policy understanding.

---

## System Prompt and Tool Descriptions: What Claude Reads

Claude doesn't have access to your code. All Claude knows comes from three things:

1. **System Prompt** (in `agent.py`):
   - Context about Larkspur Airlines
   - Customer background info
   - High-level behavior instructions

2. **Tool Descriptions** (the `description` field in `build_tools()`):
   - What each tool does
   - When to use it
   - What it returns

3. **Field Descriptions** (in `input_schema`):
   - What data each tool needs
   - Format requirements (like `YYYY-MM-DD` for dates)

If any of these are unclear or incorrect, Claude's behavior becomes unreliable. That's why Issues 2 and 3 were so important to fix.

---

## Baseline Metrics (For Measuring Improvement)

These numbers capture the current performance of our agent on all 5 ticket types. We'll measure against these in Build 2 and Build 3 to show how much better we got.

| Metric | Value |
|--------|-------|
| Total API turns across all 5 tickets | 21 |
| Total tool calls | 16 |
| Input tokens (what Claude reads) | 69,068 |
| Output tokens (what Claude generates) | 5,663 |

**Input tokens** are particularly important: every optimization we make (clearer instructions, better routing) reduces unnecessary turns, which saves input tokens (lower cost) and makes responses faster.

---

## What We Learned About Claude

1. **Message structure matters** — Tool use requires full message context with all content blocks intact

2. **Schema descriptions drive behavior** — Claude's routing decisions come directly from the tool descriptions you write. Vague or incorrect schemas create problems at runtime.

3. **The loop pattern** — The message loop (send message → get response → check stop_reason → execute tools → repeat) is the core of any Claude agent. Getting it right is step 1.

4. **Context compounds** — Each turn adds more conversation history (more tokens). Fewer turns = cheaper, faster agent.

---

## What's Next

**Build 2 & 3:** Add more tools and smarter routing to handle edge cases  
**Build 4:** Intelligence goal to improve how the agent handles difficult situations (like the angry customer)  
**Ship It:** Measure the improvements in cost, latency, and token usage

---

## Build 1 Complete ✅

- Fixed the message loop
- Fixed tool schema descriptions  
- All 5 ticket types working
- Baseline metrics captured
- Ready for Build 2
