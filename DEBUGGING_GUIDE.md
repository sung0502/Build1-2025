# TimeBuddy Debugging Guide

## 🔍 Understanding Bot Flow

### When are specialized bots called?

```
USER INPUT
    ↓
┌───────────────────────────────────────────┐
│ 1. ROUTER (brain/router.py)              │
│    ├─ Keyword matching (confidence calc) │
│    └─ If confidence < 0.7 → LLM call    │
└───────────────────────────────────────────┘
    ↓
ROUTE DECISION (e.g., "PLAN_CREATE")
    ↓
┌───────────────────────────────────────────┐
│ 2. BOT SELECTION (app.py:392-404)        │
│    ├─ PLAN_CREATE → CreateBot.run()      │
│    ├─ PLAN_EDIT → EditBot.run()          │
│    ├─ PLAN_CHECK → CheckBot.run()        │
│    └─ OTHER → OtherBot.run()             │
└───────────────────────────────────────────┘
    ↓
BOT PROCESSES REQUEST
    ↓
RETURNS ENVELOPE (with results)
```

---

## 🤖 When is the LLM (Model) Actually Called?

The LLM is called in **specific situations**:

### 1. Router LLM Call (brain/router.py:120-156)
**When**: Only when keyword confidence is < 0.7
**Purpose**: Classify unclear user intent
**Method**: `llm.classify_json()`
**Location**: core/llm.py:71-132

### 2. Bot LLM Calls (varies by bot)
- **CreateBot**: NO LLM CALL (uses rule-based parsing only!)
- **EditBot**: May call LLM for task matching
- **CheckBot**: May call LLM for formatting responses
- **OtherBot**: Calls LLM for general questions

---

## 📊 How to Check if Model is Being Called

### Method 1: Check Terminal/Console Logs

When you run `streamlit run app.py`, you'll see logs like:

```
============================================================
🧭 ROUTER.route() called with: 'Add meeting tomorrow at 2pm'
   📝 Keyword decision: PLAN_CREATE (confidence: 0.89)
   ✅ High confidence - using keyword decision: PLAN_CREATE
   🎯 FINAL DECISION: PLAN_CREATE (confidence: 0.89)
============================================================
🤖 Calling bot for stage: PLAN_CREATE
   → CreateBot.run()
   ✅ Bot completed - returned envelope
```

**If LLM is called**, you'll see:
```
============================================================
🧭 ROUTER.route() called with: 'Show me stuff'
   📝 Keyword decision: PLAN_CHECK (confidence: 0.40)
   ⚠️ Low confidence - calling LLM for tie-breaking...
🔍 LLM.classify_json() CALLED
   Model: gemini-flash-lite-latest
   Prompt: Classify this user message into ONE of these categories:...
   ✅ Parsed JSON: {'stage': 'PLAN_CHECK', 'confidence': 0.85}
   🎯 FINAL DECISION: PLAN_CHECK (confidence: 0.85)
============================================================
🤖 Calling bot for stage: PLAN_CHECK
   → CheckBot.run()
```

---

### Method 2: Add Streamlit Debug Display

Add this to `app.py` (after line 302, before main layout):

```python
# DEBUG: Show routing info
if st.session_state.get('DEBUG_MODE', False):
    with st.expander("🐛 Debug Info", expanded=True):
        st.write(f"Last route decision: {st.session_state.get('last_route', 'None')}")
        st.write(f"Awaiting confirmation: {st.session_state.awaiting_confirmation}")
        st.write(f"Chat history length: {len(st.session_state.chat_history)}")
```

Then add this in app.py after route_decision (line 388):

```python
# Store for debugging
st.session_state.last_route = f"{route_decision.stage} (conf: {route_decision.confidence:.2f})"
```

Enable by running:
```python
# In Python console or add to app.py temporarily
st.session_state.DEBUG_MODE = True
```

---

## 🔬 Testing Different Scenarios

### Scenario 1: High Confidence Keyword (NO LLM call)
**Input**: "Add team meeting tomorrow at 2pm"
**Expected**:
- Router uses keyword matching
- Confidence > 0.7
- CreateBot called directly
- **NO LLM API call**

**Logs**:
```
📝 Keyword decision: PLAN_CREATE (confidence: 0.89)
✅ High confidence - using keyword decision: PLAN_CREATE
```

---

### Scenario 2: Low Confidence (LLM call for routing)
**Input**: "What do I have?"
**Expected**:
- Router uses keyword matching
- Confidence < 0.7
- **LLM called for tie-breaking**
- CheckBot called

**Logs**:
```
📝 Keyword decision: PLAN_CHECK (confidence: 0.40)
⚠️ Low confidence - calling LLM for tie-breaking...
🔍 LLM.classify_json() CALLED
```

---

### Scenario 3: Bot Calls LLM
**Input**: (varies by bot)
**Expected**:
- Bot needs LLM for processing
- **LLM.generate() called**

**Logs**:
```
🤖 LLM.generate() CALLED
   Model: gemini-flash-lite-latest
   Prompt: ...
   Response: ...
```

---

## 🛠️ Debugging Checklist

When debugging, check:

1. ✅ **Is the router being called?**
   - Look for: `🧭 ROUTER.route() called`

2. ✅ **What's the confidence level?**
   - Look for: `📝 Keyword decision: XXX (confidence: 0.XX)`
   - < 0.7 = LLM will be called

3. ✅ **Is LLM being called?**
   - Look for: `🔍 LLM.classify_json() CALLED` or `🤖 LLM.generate() CALLED`

4. ✅ **Which bot is handling the request?**
   - Look for: `→ CreateBot.run()` / `→ EditBot.run()` / etc.

5. ✅ **Did the bot complete?**
   - Look for: `✅ Bot completed - returned envelope`

---

## 🐛 Common Issues

### Issue: No logs appearing
**Solution**: Check your terminal/console where you ran `streamlit run app.py`

### Issue: Model not being called when expected
**Reason**: Keyword confidence is high (> 0.7)
**Solution**: This is normal and saves API costs!

### Issue: Model called too often
**Reason**: Unclear user input leads to low keyword confidence
**Solution**: Check if keywords in router.py:70-97 need updating

---

## 📝 Log Output Examples

### Full Example Log (with LLM call):

```
============================================================
🧭 ROUTER.route() called with: 'idk what to do'
   📝 Keyword decision: OTHER (confidence: 0.25)
   ⚠️ Low confidence - calling LLM for tie-breaking...
🔍 LLM.classify_json() CALLED
   Model: gemini-flash-lite-latest
   Prompt: Classify this user message into ONE of these categories:
- PLAN_CREATE: User wants...
   ✅ Parsed JSON: {'stage': 'OTHER', 'confidence': 0.9}
   🎯 FINAL DECISION: OTHER (confidence: 0.90)
============================================================
🤖 Calling bot for stage: OTHER
   → OtherBot.run()
🤖 LLM.generate() CALLED
   Model: gemini-flash-lite-latest
   Prompt: User said: "idk what to do"...
   Response: I can help you...
   ✅ Bot completed - returned envelope
```

---

## 💡 Tips

1. **Check logs first** - Terminal output shows everything
2. **Keyword routing is preferred** - Saves API costs, faster
3. **Low confidence is OK** - LLM tie-breaker improves accuracy
4. **CreateBot doesn't call LLM** - Uses rule-based parsing (fast!)

---

## 🔗 Code References

- Router: `brain/router.py:38-74`
- Bot selection: `app.py:390-404`
- LLM wrapper: `core/llm.py:31-132`
- CreateBot: `brain/bots/plan_create.py:34-86`

---

Generated: 2025-10-21
