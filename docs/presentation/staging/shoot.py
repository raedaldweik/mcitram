"""Photographs staged conversations in the real UI (mock_server must be up)."""
import os, sys
from playwright.sync_api import sync_playwright

SP = "/tmp/claude-0/-home-user/f62b4483-940b-5855-b24b-3d5ace82edc6/scratchpad"
URL = "http://127.0.0.1:8000"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

AGENT_PROC = "Procurement Integrity Analyst"
AGENT_COPILOT = "SAS Viya Copilot"
AGENT_VI = "Investigation Assistant"
AGENT_WEB = "Global Intelligence"


def pick_agent(pg, name):
    # open the target selector (header button showing the current agent)
    pg.locator("button", has_text="agent").first.click()
    pg.wait_for_timeout(300)
    pg.locator("button", has_text=name).last.click()
    pg.wait_for_timeout(300)


def ask(pg, question, wait_text, extra_ms=1200):
    pg.locator("textarea").fill(question)
    pg.keyboard.press("Enter")
    pg.wait_for_selector(f"text={wait_text}", timeout=60000)
    pg.wait_for_timeout(extra_ms)   # charts animate in


def new_chat(pg):
    pg.locator("button", has_text="New conversation").click()
    pg.wait_for_timeout(400)


def shot(pg, name):
    pg.screenshot(path=f"{SP}/{name}.png")
    print("shot:", name)


with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
    ctx = b.new_context(viewport={"width": 1440, "height": 900},
                        device_scale_factor=2, ignore_https_errors=True)
    pg = ctx.new_page()
    pg.goto(URL)
    pg.wait_for_selector("textarea", timeout=30000)
    pg.add_style_tag(content="* { caret-color: transparent !important; }")
    pg.wait_for_timeout(2500)   # let webfonts land

    fonts = pg.evaluate("document.fonts.check('13px Manrope') && document.fonts.check('13px \"IBM Plex Sans Arabic\"')")
    print("webfonts loaded:", fonts)

    # ── 0 · dropdown open ────────────────────────────────────────────
    pg.locator("button", has_text="agent").first.click()
    pg.wait_for_timeout(400)
    shot(pg, "shot_dropdown")

    # ── A · procurement ─────────────────────────────────────────────
    pg.locator("button", has_text=AGENT_PROC).last.click()
    pg.wait_for_timeout(300)
    ask(pg, "Who are our riskiest suppliers right now?",
        "Five suppliers need attention", 1600)
    shot(pg, "shot_procurement")

    # ── B · copilot + specialist ────────────────────────────────────
    new_chat(pg)
    pick_agent(pg, AGENT_COPILOT)
    ask(pg, "Profile the SUPPLIERS table and flag any data quality issues.",
        "model-ready after two fixes")
    shot(pg, "shot_copilot")
    # open the details / trace popup
    pg.locator("button[title*='Details view']").last.click()
    pg.wait_for_timeout(600)
    shot(pg, "shot_trace")
    n = pg.evaluate("""() => {
        const o = document.querySelectorAll("div[class*='z-[300]']");
        for (const d of o) { const b = d.querySelector('button'); if (b) b.click(); }
        return o.length;
    }""")
    print("overlays closed:", n)
    try:
        pg.wait_for_selector("div[class*='z-[300]']", state="detached",
                             timeout=4000)
    except Exception:
        print("popup still open — inner text:",
              pg.locator("div[class*='z-[300]']").first.inner_text()[:200])
        raise
    pg.wait_for_timeout(400)

    # ── C · dashboard in chat ───────────────────────────────────────
    ask(pg, "Show me the Procurement Integrity Dashboard and analyze it.",
        "three things stand out")
    pg.wait_for_selector("img[src*='/api/va/image/']", timeout=20000)
    pg.wait_for_timeout(900)
    shot(pg, "shot_dashboard")

    # ── D · investigator ────────────────────────────────────────────
    new_chat(pg)
    pick_agent(pg, AGENT_VI)
    ask(pg, "Good morning — what should I look at first today?",
        "Start with AL-2031", 1600)
    shot(pg, "shot_vi")

    # ── E · global intelligence ─────────────────────────────────────
    new_chat(pg)
    pick_agent(pg, AGENT_WEB)
    ask(pg, "What are other countries doing on AI-driven procurement oversight?",
        "Three models are emerging")
    shot(pg, "shot_web")

    # ── F · Arabic mode ─────────────────────────────────────────────
    new_chat(pg)
    pg.locator("button", has_text="عربي").first.click()
    pg.wait_for_timeout(800)
    pick_agent(pg, AGENT_PROC)
    pg.locator("textarea").fill("من هم الموردون الأعلى خطورة حالياً؟")
    pg.keyboard.press("Enter")
    pg.wait_for_selector("text=خمسة موردين", timeout=60000)
    pg.wait_for_timeout(1600)
    shot(pg, "shot_arabic")

    b.close()
print("ALL SHOTS DONE")
