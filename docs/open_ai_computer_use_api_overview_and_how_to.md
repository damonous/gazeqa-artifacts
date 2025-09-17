# OpenAI Computer Use (CUA) — overview and how‑to for autonomous web navigation

## 1) Executive summary
OpenAI’s Computer Use tool allows an AI agent to operate a real UI by perceiving screenshots and issuing mouse, keyboard, and system actions. You access it through the Responses API by enabling the built‑in **computer use** tool. The pattern is an iterative loop: see the screen, decide, act, repeat, with your code executing the actions and returning screenshots until the task completes.

Use it when you must drive GUI‑only systems with weak or missing APIs. Prefer native APIs when available for speed, cost, and determinism.

---

## 2) Core concepts
- **Tool‑augmented model**: You pair a reasoning model with the **computer use** tool inside the Responses API. The model plans steps and emits action calls.
- **Executor**: Your runtime that actually performs actions (click, type, scroll, drag), captures a screenshot, and returns it to the model.
- **Perception‑action loop**: 1) model asks for an action 2) executor performs it and returns a screenshot 3) model decides next action until done.
- **Action surface**: Typical actions to implement include `click`, `double_click`, `scroll`, `type`, `wait`, `move`, `keypress`, and `drag`.

---

## 3) Minimal kickoff with the Responses API
Below is a first call that enables the computer use tool. The response will contain tool calls that your executor must fulfill.

```javascript
import OpenAI from "openai";
const openai = new OpenAI();
const run = await openai.responses.create({
  model: "computer-use-preview",
  tools: [{ type: "computer_use_preview", display_width: 1280, display_height: 800, environment: "browser" }],
  truncation: "auto",
  input: "Open wikipedia.org, search for 'Cebu City', and read the first paragraph."
});
console.log(run.output);
```

### Control loop shape
Your app then iterates over returned tool calls, executes them, screenshots the result, and sends the screenshot back on the same run. Pseudocode:

```python
while tool_call := next_action():
  result = executor.execute(tool_call)
  screenshot = executor.screenshot()
  send_back(screenshot, result)
```

---

## 4) Quick start with the reference sample
A reference implementation shows the end‑to‑end loop with multiple execution backends (local Playwright browser, Dockerized desktop, or a hosted remote browser).

```bash
git clone https://github.com/openai/openai-cua-sample-app
cd openai-cua-sample-app
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python cli.py --computer local-playwright \
  --start-url https://wikipedia.org \
  --input "Search for Cebu City and summarize the first paragraph"
```

Options commonly provided by the sample:
- **local‑playwright** - fast feedback on a developer machine
- **docker‑desktop** - reproducible VM‑like desktop with a visible browser
- **remote browser** - use a hosted browser provider

---

## 5) Build your own executor
Whether browser‑only or full desktop, the responsibilities are similar.

1. **Initialize session**
   - Choose display size, environment type (browser vs desktop), and navigation policy.
2. **Map actions to an engine**
   - Browser: use Playwright or Puppeteer for `click`, `type`, `scroll`, `press`, `drag`.
   - Desktop: use VNC, Xvfb, OS‑level input automation, or a provider that exposes these primitives.
3. **Capture evidence**
   - Screenshot after each action. Persist images and logs for traceability.
4. **Return feedback**
   - Send the screenshot and any structured result back to the model on the same run.
5. **Stop conditions**
   - Max actions per run, timeouts, explicit “task completed,” or human confirmation gates.

### Suggested action interface
```ts
export type Action =
  | { kind: "click", x: number, y: number }
  | { kind: "double_click", x: number, y: number }
  | { kind: "move", x: number, y: number }
  | { kind: "scroll", dx: number, dy: number }
  | { kind: "type", text: string }
  | { kind: "keypress", keys: string[] }
  | { kind: "drag", path: Array<{x:number,y:number}> }
  | { kind: "wait", ms: number };
```

---

## 6) Autonomy patterns for real web apps
**Environments**
- Local Playwright for development
- Remote browsers or Dockerized desktops for isolation and scale

**Orchestration**
- Use the Agents SDK on top of Responses API tools to coordinate multi‑step tasks, handoffs, and retries. Add RAG and standard HTTP APIs as separate tools.

**Guardrails**
- Confirmation prompts before irreversible actions
- Restricted egress: allowlists or DNS filtering
- Max‑step and wall‑clock limits
- Credential hygiene: pre‑seed session storage where possible instead of typing passwords live
- Prompt‑injection awareness and content scanning policies

**Quality of life**
- StorageState bootstrap for logged‑in sessions
- Deterministic waits using page events before issuing the next action
- Structured traces with per‑step screenshots, DOM excerpts, and exit reasons

---

## 7) When to use CUA vs APIs
- **Use CUA** when the only viable interface is a GUI, the vendor lacks stable APIs, or workflows span multiple systems behind logins.
- **Use APIs** when they exist and are stable. They are faster, cheaper, and more reliable.
- **Hybrid** is common: use APIs for data and CUA for awkward UI gaps like admin panels, reports, and idiosyncratic flows.

---

## 8) Production checklist
- [ ] Executor implements the full action surface with screenshots on every step
- [ ] Network allowlist or DNS filter in place
- [ ] Credential handling policy and secrets redaction in logs
- [ ] Step limits, timeouts, and backoff
- [ ] Human‑in‑the‑loop for risky flows
- [ ] Tracing: per‑run timeline, actions, screenshots, DOM snippets, and errors
- [ ] Test harness with synthetic targets and fixtures
- [ ] Rollout plan, quotas, and alerting

---

## 9) Troubleshooting tips
- **Action does nothing**: verify viewport size and coordinates; ensure the element is in view and interactable.
- **Typing is ignored**: check active focus; fall back to click on the target input before typing; confirm keyboard layout.
- **Navigation stalls**: add deterministic wait conditions for network idle or specific selectors.
- **Logins break**: prefer cookie or storage bootstrap. If entering credentials, gate with user confirmation and mask logs.
- **Flaky flows**: record traces, raise wait thresholds, and add retries only where idempotent.

---

## 10) Appendix: Python executor sketch
A thin loop that reads actions, executes them via Playwright, screenshots, and responds.

```python
from playwright.sync_api import sync_playwright

class BrowserExecutor:
  def __init__(self):
    self.p = sync_playwright().start()
    self.browser = self.p.chromium.launch(headless=False)
    self.ctx = self.browser.new_context(viewport={"width":1280,"height":800})
    self.page = self.ctx.new_page()

  def click(self, x, y): self.page.mouse.click(x, y)
  def double_click(self, x, y): self.page.mouse.dblclick(x, y)
  def move(self, x, y): self.page.mouse.move(x, y)
  def scroll(self, dx, dy): self.page.mouse.wheel(dx, dy)
  def type(self, text): self.page.keyboard.type(text)
  def keypress(self, keys):
    for k in keys: self.page.keyboard.press(k)
  def drag(self, path):
    if not path: return
    self.page.mouse.move(path[0]["x"], path[0]["y"])
    self.page.mouse.down()
    for pt in path[1:]: self.page.mouse.move(pt["x"], pt["y"])
    self.page.mouse.up()
  def wait(self, ms): self.page.wait_for_timeout(ms)
  def screenshot(self): return self.page.screenshot(full_page=True)
```

---

## 11) Notes on security and compliance
- Keep a strict audit trail of actions, screenshots, and decisions.
- Never store credentials in prompts. Use short‑lived tokens, storage bootstrap, or encrypted credential vaults with explicit user consent.
- Respect robots and ToS. Obtain permission for any interactive automation against third‑party sites.

---

## 12) Quick recipe
1. Enable the **computer use** tool in a Responses API run.
2. Implement an executor that maps tool calls to Playwright or a desktop driver.
3. After each action, screenshot and feed it back.
4. Add guardrails, logs, and tests. Then scale behind a remote browser or Dockerized desktop.

