# Underpass demo video (~2.5 min)

Recorded, not live. Record shot by shot, redo anything, join in Clipchamp. Talk like you're explaining it to a friend.

## Before recording (10 min)
1. Recorder: **Clipchamp** (built into Windows 11): screen + mic. `Win+Alt+R` works too (one window only).
2. Terminal font ~20 (`Ctrl` + `+`), browser zoom 125%. Notifications off.
3. Warm up:
   ```
   cd C:\Workspaces\buildathon-Team-Rocket
   uv run underpass check coach.mastersunion.org
   ```
   Lots of FAIL lines about login? Run `uv run underpass login coach.mastersunion.org` first.

---

## Shot 1: Hook (15 s), on the website
Open https://avinboi.github.io/buildathon-Team-Rocket/ and scroll slowly.

> "So this is Underpass. Basically, give it any website you can log into, and it turns that website into an MCP
> (a set of tools) your AI agent can actually use. Claude Code, Codex, Cursor, whatever you use."

## Shot 2: Why this matters (30 s), still on the website
> "Think about why companies bother making MCPs and APIs for agents at all. It's because just telling your agent
> 'go open the website and do it' is terrible. It takes screenshots, reads the page, clicks, waits, reads again...
> it's slow, it burns a ton of tokens, and it breaks the moment a button moves.
>
> An MCP is way more efficient: the agent just asks for the data and gets it. The problem is that most websites
> never make one. My college portal doesn't have one. Your company's internal tools probably don't either.
>
> But here's the thing: every modern website already has an API hidden inside it. The page itself uses it to load
> everything you see. Underpass finds that hidden API and turns it into an MCP for you."

## Shot 3: Coach is complicated, and it still took minutes (30 s), terminal
```
uv run underpass list coach.mastersunion.org
```
Scroll a bit while you talk.

> "I tried it on Coach, which is our college's portal, and it's honestly a really complicated website: attendance,
> assignments, timetable, grades, mentors, fees, events, polls, forms, notes... It talks to five different backend
> servers, and one attendance page alone pulls almost 700 KB of data.
>
> All I did was log in. That's it. Underpass explored the whole site on its own, read the site's code, and in a
> couple of minutes it built a full MCP: 239 tools. 171 to read stuff and 68 actions. And I never clicked a single
> one of those actions myself. It found them by reading the site's JavaScript."

## Shot 4: The race (45 s), the money shot
```
uv run python demo/race.py coach.mastersunion.org "For each of my courses, what's my attendance %, and how many more classes can I miss while staying at or above 75%?"
```
> "Let's actually compare. Same question, same AI model. One agent uses the browser like a normal browser agent,
> the other one uses Underpass."

When Underpass finishes:
> "Underpass is done in about 25 seconds, 3 tool calls. The browser agent is still clicking around."

When the table shows:
> "Browser agent: about 100 seconds, 18 steps, over 500,000 tokens. Underpass: 24 seconds, 3 calls, around 130,000
> tokens. So 4x faster and 4x fewer tokens, for the same answer."

(If a take is slow, just run it again. Measured on 18 Nov: browser 102.6 s / 18 calls / 521k tokens;
Underpass 23.8 s / 3 calls / 132k tokens; both answers correct.)

## Shot 5: It can do things too, safely (40 s), new Claude Code session (`claude`)
Type: `Use Underpass to add a note on Coach titled "Demo day" saying "Revise Neuroscience before Friday"`

> "And it's not just reading. It can actually do stuff on the site."

When the preview shows:
> "But before it changes anything, it shows me exactly what it's going to send and asks me first."

Type **yes**:
> "Done, and it checks the site again to prove the note really exists."

(Optional: flip to Coach in the browser and show the note.) Then type **now delete it** and approve.

## Shot 6: The hard part (25 s), website "How it works"
> "The hardest part was making this work on any website without writing custom code for each one. Underpass watches
> how the site calls its own API, learns the site's internal helper functions, and then uses that to find every
> action hidden in the code. It reuses your login safely, never touches password or logout stuff, and trims huge
> responses (700 KB down to 35 KB) without losing anything. And the same thing worked on crates.io and Hacker News
> with zero changes."

## Shot 7: Close (15 s), website install section
> "It's one line to install, and it plugs into any agent. Everything runs on your own laptop, and your login never
> leaves it. So yeah: any website, turned into your agent's API. That's Underpass."

---

## Checklist: what judges need to hear
- **Problem insight:** who has it (anyone whose tools have no API/MCP) and why (browser agents are slow, expensive,
  brittle; sites never ship MCPs) -> Shots 2-3
- **Working product:** real tools on a real, complicated site, real race, real action -> Shots 3-5
- **Depth of execution:** finds actions in the code, any site, safe actions, trimming -> Shot 6

## Tips
- Talk slowly; cut pauses later. Redo only the shot that went wrong.
- Never show your password on screen.
- Done by ~6:30.

## If something breaks
- Login expired: `uv run underpass login coach.mastersunion.org`
- Public-site backup: `uv run underpass call crates.io search_crates query=serde`
