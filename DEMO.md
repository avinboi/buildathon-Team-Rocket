# Underpass demo video (2-3 minutes)

Recorded, not live: retake any shot. Suggested shots:
1. Website https://avinboi.github.io/buildathon-Team-Rocket/ (5 s scroll): "one install, works in any agent".
2. Problem voice-over (below).
3. `underpass list coach.mastersunion.org | more`: 239 tools from one login.
4. The race (below), Underpass finishing first.
5. In Claude Code: "Use Underpass: add a note titled 'Demo day'..." -> preview -> "yes" -> verified -> "delete it".
6. Hard part + close.


## Before going on stage (T-10 min)
```bash
cd C:\Workspaces\buildathon-Team-Rocket
uv run underpass check coach.mastersunion.org      # all read tools green? if many FAIL with 401: uv run underpass login coach.mastersunion.org
claude mcp list                                     # 'coach' shows Connected
```
Open 2 terminals side by side (big font) + one Claude Code window.

## 0:00 Problem (20s)
> "Most software we use every day (college portals, company tools, vendor dashboards) has no API and no MCP.
> So the only way an AI agent can use it is a browser agent: screenshots and clicks. That's slow, expensive and brittle.
> But every modern website already HAS a full API: its own front end calls it for every page and every button. It's just hidden.
> Underpass finds that hidden API and turns it into tools for your agent."

## 0:20 One command (20s)
```bash
uv run underpass list coach.mastersunion.org
```
> "I ran `underpass add coach.mastersunion.org`, logged in once and clicked around for 2 minutes. Underpass explored the rest
> on its own, read the site's JavaScript, and Claude designed **239 tools: 171 reads and 68 actions**. I never clicked
> those actions: Underpass found them in the site's own code."

## 0:40 The race (45s)
```bash
uv run python demo/race.py coach.mastersunion.org "For each of my courses, what's my attendance %, and how many more classes can I miss while staying at or above 75%?"
```
> "Same question, same model. Left: a browser agent. Right: the same agent with Underpass."

Measured (18 Nov, same question, same model):

| | Browser agent | Underpass |
|---|---|---|
| Time | 102.6 s | **23.8 s** (4.3x faster) |
| Tool calls | 18 | **3** |
| Answer | correct | correct |

## 1:25 Do something, safely, and prove it (45s)
In Claude Code:
> "Add a note on Coach titled 'Demo day' saying 'Revise Neuroscience before Friday'."

- Agent calls `create_student_note` -> Underpass returns a **preview** of the exact request, agent asks me -> I approve.
- Created in ~0.4 s, then Underpass **automatically verifies** with `list_student_notes`: the note is there.
- Then: "Delete that note." -> preview -> approve -> verified gone.

> "Reads are instant; actions always show an exact preview, need my approval, and come back with proof."

## 2:10 The hard part (30s)
> "Making this work on ANY site without per-site code:
> - It learns each site's own HTTP helper functions from the calls it saw, then finds every action in the code (Coach: 3 actions clicked -> 50 found).
> - It templates IDs, reuses my login (bearer/cookie/headers), never exposes login/password calls.
> - It trims answers for agents: attendance went from 690 KB to 35 KB, without losing a single course.
> - Same tool works on Hacker News search and crates.io with zero changes."

## 2:40 Close
> "Underpass: any website you can log into becomes something your AI can use. Runs locally, your login never leaves your machine,
> and the agent only gets your permissions."

## If something breaks
- Login expired -> `uv run underpass login coach.mastersunion.org` (10 s), or show the backup video.
- Wi-Fi down -> backup video.
- Public-site fallback: `uv run underpass call hn.algolia.com search_hn_stories query=claude`
