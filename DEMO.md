# Underpass demo video (~2.5 minutes)

Recorded, not live: record shots separately, retake any shot, then join them (Clipchamp on Windows 11).

## Before recording (10 min)
1. Recorder: **Clipchamp** (built into Windows 11) -> screen + mic. `Win+Alt+R` also works but records one window only.
2. Terminal font ~20 (`Ctrl` + `+`), browser zoom 125%.
3. Close WhatsApp/email, turn on Focus Assist.
4. Warm up:
   ```
   cd C:\Workspaces\buildathon-Team-Rocket
   uv run underpass check coach.mastersunion.org
   ```
   Many FAIL lines mentioning login? Run `uv run underpass login coach.mastersunion.org` first.

## Shot 1: Hook (10 s), website
Open https://avinboi.github.io/buildathon-Team-Rocket/ and scroll slowly.
> "This is Underpass. It turns any website you can log into into tools your AI agent can use, through the site's own hidden API."

## Shot 2: Problem (20 s), website "Why" cards
> "Most software we use (college portals, company tools, dashboards) has no API, so agents can't use it. The only option today
> is a browser agent that takes screenshots and clicks: slow, and it breaks easily. But every modern website already has a full
> API: its own front end calls it for every page and button. It's just hidden. Underpass finds it."

## Shot 3: One login gives 239 tools (20 s), terminal
```
uv run underpass list coach.mastersunion.org
```
> "I connected my college portal, Coach. I only logged in. Underpass explored the site by itself, read its code, and built
> 239 tools: 171 to read data and 68 actions. I never clicked those actions. It found them in the site's own JavaScript."

## Shot 4: The race (45 s), the most important shot
```
uv run python demo/race.py coach.mastersunion.org "For each of my courses, what's my attendance %, and how many more classes can I miss while staying at or above 75%?"
```
> "Same question, same AI model. One agent uses a browser; the other uses Underpass."

When Underpass finishes: "Underpass answered in about 25 seconds with 3 calls. The browser agent is still clicking."
Let the browser finish and show the comparison table. Slow take? Run it again.

Measured 18 Nov: browser 102.6 s / 18 tool calls; Underpass 23.8 s / 3 tool calls; both correct.

## Shot 5: A real action, safely (40 s), new Claude Code session (`claude`)
Type: `Use Underpass to add a note on Coach titled "Demo day" saying "Revise Neuroscience before Friday"`
1. It shows a **preview** and asks: "Before anything changes, it shows exactly what it will do and asks me."
2. Type **yes**. It creates and verifies: "Then it checks the site to prove the note really exists."
3. (Optional) Show the note on Coach's notes board in the browser.
4. Type **now delete it** and approve.

## Shot 6: The hard part (25 s), website "How it works" or README
> "The hard part was making this work on any website without per-site code. Underpass learns each site's own internal
> functions from the calls it sees, then uses them to find every action hidden in the code. It reuses your login, never touches
> password or logout calls, and trims huge responses (690 KB down to 35 KB) without losing a single record. It worked unchanged on
> crates.io and Hacker News too."

## Shot 7: Close (15 s), website install section
> "One line to install, and it works in Claude Code, Codex, Cursor or any agent. Everything runs on your machine, and your login
> never leaves it. Underpass: any website becomes your agent's API."

## Tips
- Talk slowly; trim pauses later. Re-record only the shot that went wrong.
- Never show your password on screen.
- Finish by ~6:30.

## If something breaks
- Login expired: `uv run underpass login coach.mastersunion.org` (about 10 s).
- Public-site fallback: `uv run underpass call crates.io search_crates query=serde`
