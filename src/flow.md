# chat_app.py Flowchart (Box Diagram Style)

## 1. App Startup

┌───────────────┐
│   Start       │
└──────┬────────┘
       │
       v
┌──────────────────────────────┐
│ Load environment variables   │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Configure Azure Monitor      │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Initialize FastAPI app       │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Load prompt files            │
└──────┬───────────────────────┘
       v
┌───────────────────────────────┐
│ Create handoff and LLM clients│
└──────┬────────────────────────┘
       v
┌──────────────────────────────┐
│ Define endpoints             │
└──────────────────────────────┘

---

## 2. HTTP Endpoints

┌────────────┐      ┌───────────────────────┐
│  GET /     │───→  │ Return chat.html      │
└────────────┘      └───────────────────────┘

┌──────────────┐    ┌────────────────────────────┐
│  GET /health │──→ │ Return health status JSON  │
└──────────────┘    └────────────────────────────┘

---

## 3. WebSocket Endpoint (/ws)

┌──────────────────────────────┐
│ WebSocket Connect            │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Create agent threads         │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Initialize session variables │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Run customer loyalty task    │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Main Loop: Wait for message  │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Parse incoming message       │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Update persistent image/cart │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Append to raw_io_history     │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Parse conversation history   │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Format chat history          │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Call handoff agent           │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Handoff reply                │
└──────┬───────────────────────┘
       v
┌──────────────────────────────────────────────┐
│ Is content filter error?                     │
├───────────────┬───────────────┬──────────────┤
│ Yes           │               │ No           │
│               v               v              │
│      Send error to user   Check for 'cart'?  │
└───────────────┬───────────────┬──────────────┘
                │               │
                v               v
        ┌──────────────────────────────┐
        │ 'cart' in message?           │
        └──────┬───────────────┬───────┘
               │ Yes           │ No
               v               v
   [Run cart update &      [Select agent]
    cora fallback]             │
        │                     v
   [Merge results]   ┌──────────────────────────────┐
        │            │ Agent selected?              │
   [Update cart]     └──────┬───────────────┬───────┘
        │                   │ Yes           │ No
   [Send response]          v               v
        │            [Run agent logic]   [Send error]
   [Send loyalty            │
    response if             v
    available]        [Send agent response]
        │
        v
     [Loop]

---

## 4. Agent Logic (after selection)

┌──────────────────────────────┐
│ interior_designer           │
└──────┬───────────────────────┘
       v
┌──────────────────────────────┐
│ Image/Video?                 │
└──────┬───────────────┬───────┘
       │ Yes           │ No
       v               v
[Get description/      [Product recommendations]
 summary]                   │
       │                   v
[Product recommendations]   [Fallback LLM]
       │                   │
[Fallback LLM]              v
       │             [Send response]
[Send response]

┌──────────────────────────────┐
│ interior_designer_create_image │
└──────┬───────────────────────┘
       v
[Get image description]
       │
[Product recommendations]
       │
[AgentProcessor stream]
       │
[Send response]

┌──────────────┐
│ cora         │
└──────┬───────┘
       v
[Cora fallback LLM]
       │
[Send response]

┌──────────────────────────────┐
│ Other agent                  │
└──────┬───────────────────────┘
       v
[AgentProcessor stream]
       │
[Send response]

---

## 5. Error Handling

┌──────────────┐
│ Any error    │
└──────┬───────┘
       v
[Send error message to user]

---

## 6. WebSocket Disconnect

┌────────────────────┐
│ WebSocketDisconnect│
└──────┬─────────────┘
       v
     [End]

---

**Note:**
- All major steps are boxed, with arrows showing flow.
- Decision points are shown as diamond boxes ("Is ...?").
- Agent logic is branched based on agent_name.
- Error handling and session state updates are included.
