# 🚀 Buildathon: Make Wednesdays Great Again

**Masters' Union · For AI Developers · Winner gets Rs. 25,000**

> **Every team must build in a fork of this repository.** Projects not built in a fork of this repo won't be judged.

| | |
|---|---|
| **Date** | Wednesday, 18 November 2026 |
| **Hacking** | **3:00 PM – 7:00 PM IST** (code freeze at 7:00 PM sharp) |
| **Venue** | CDS Audi, 8th floor |
| **Prize** | Rs. 25,000 to the winning team |
| **Register your fork** | 👉 **[https://forms.gle/ZJUYKwTYjsMsVB2b9](https://forms.gle/ZJUYKwTYjsMsVB2b9)** (**deadline 3:30 PM IST**) |
| **Final submission** | Your fork as it stands at **7:00 PM IST**. There's nothing else to submit. |

> 🤖 **Using an AI coding agent?** Point it at [`AGENTS.md`](AGENTS.md). It has the full event brief, tracks, judging and rules in a form agents can read directly. Claude Code loads it automatically through `CLAUDE.md`, and Codex reads `AGENTS.md` natively.

---

## 🎯 Pick one build track

| # | Track | Brief |
|---|---|---|
| **01** | **Build for the Physical World** | Make a real-world task easier, faster or more reliable. Show it in a realistic scenario. |
| **02** | **Build for AI Agents** | Find something an agent struggles with. Build the tool that fixes it, then demo the agent using it. |
| **03** | **Build in Your Area of Expertise** | Pick a field you know firsthand. Ship a working product that improves how people handle it today. |

## ⚖️ How you'll be judged (each criterion is ⅓ of your score)

| Criterion | The question judges ask |
|---|---|
| **Working product** | Does it do what you say it does? Show the core workflow in your demo. |
| **Problem insight** | Who faces this problem, and why does it happen? |
| **Depth of execution** | How well did you solve the hardest part of the build? |

---

## Why fork this repo?

Everyone starts from the same commit (the **genesis commit**) at the same time. Organizers can then check that:
- all code was written **during** the Buildathon and not brought in from an earlier project,
- teams commit steadily instead of pasting in one huge AI-generated dump at the end,
- every repo stays public and visible while you build.

The organizers track every fork automatically: commits, timing and activity. Read [RULES.md](RULES.md) before you write any code.

---

## ✅ Setup (about 5 minutes, do it at 3:00 PM)

**In short:** fork → register your fork in the form **by 3:30 PM** → build → push before 7:00 PM.

### 1. Fork this repo
Click **Fork** (top right). On the fork screen:
- **Owner:** one team member's personal account. Only **one fork per team**.
- **Repository name:** `buildathon-<team-name>`, for example `buildathon-byte-bandits`
- Click **Create fork**.

> ⚠️ Don't download a ZIP or copy the files into a new repo. **It has to be a real GitHub fork**, or the tracker can't see you.

### 2. Keep it public
Forks of a public repo are public. **Don't make it private, archive it, or delete it** until judging is over.

### 3. Add your teammates
In your fork: **Settings → Collaborators → Add people**. Add each teammate's GitHub account so their commits count toward the team.

### 4. Enable Actions
Open the **Actions** tab of your fork and click **"I understand my workflows, go ahead and enable them"**. This runs the automatic check on every push.

### 5. Make your registration commit (your first commit)
Fill in [`team.json`](team.json). `track` must be one of `physical-world`, `ai-agents` or `area-of-expertise`. Then:

```bash
git clone https://github.com/<your-username>/buildathon-<team-name>.git
cd buildathon-<team-name>
# edit team.json
git add team.json
git commit -m "register: <team name>"
git push
```

The **Hackathon check** in the Actions tab should go green ✅. If it's red, open the run to see what's wrong in `team.json`.

### 6. Register your fork (deadline: 3:30 PM IST)
👉 **[https://forms.gle/ZJUYKwTYjsMsVB2b9](https://forms.gle/ZJUYKwTYjsMsVB2b9)**

It's a 4-question Google Form: team name, fork link, track, team members. It connects your repo to the organizers' live tracker.

- Fill it in **once per team**, right after forking, and **no later than 3:30 PM IST**. **Teams that don't register can't be tracked.**
- Paste your **fork's** URL (`https://github.com/<you>/buildathon-<team-name>`), not this starter repo's.
- Need to change something? Use the **"Edit your response"** link on the confirmation page. Don't fill it in twice.
- **Final submission is automatic.** Whatever is pushed to your fork at 7:00 PM IST is what gets judged.

---

## 🛠 While you build (3:00 – 7:00 PM)

- Put your code anywhere in the repo (`app/`, `src/`, `frontend/`, `backend/`…). There's no required layout.
- **Commit early, commit often**, at least every 30 minutes of real work, with messages that say what changed.
- **Push regularly.** Commits you never push don't exist to the tracker.
- AI coding tools (Claude Code, Codex, Cursor, Copilot…) are **allowed and encouraged**. Keep `AGENTS.md` and `CLAUDE.md` in the repo; they keep your agent within the rules.
- Before 7:00 PM, replace the "Your project" section below with your project's README.

## 🧊 Code freeze: 7:00 PM IST

At 7:00 PM the tracker takes a snapshot of every fork. **Commits pushed after code freeze are ignored.** Judges look at your last commit before 7:00 PM.

## ❌ Things that get you flagged

- Rewriting history (`git push --force`, rebasing away the genesis commit, squashing everything into one commit)
- Commits dated before 3:00 PM
- One or two giant commits containing most of the project
- A repo that isn't a fork of this one, or that's private or deleted

See [RULES.md](RULES.md) for the full list.

---

## Your project

# Underpass

**Turn any website you can log into into a CLI and an MCP server, so your AI agent can do anything you can do there.**

- **Team:** Team Rocket (Avin Dev, solo)
- **Track:** Build for AI Agents (`ai-agents`)

### Problem
**Who:** anyone who wants an AI agent to work inside a website that has no public API or MCP server: a student's college portal,
an employee's internal company software, a small vendor dashboard. That's most of the software people actually use at work.

**Why it happens:** agents can only act through tools. Most websites never ship an API or MCP for end users, so today the agent's
only option is a browser agent that screenshots and clicks. That takes 30-60 seconds per task, breaks when the layout changes,
and re-reasons every click. But every modern site already has a full private JSON API: its own front end calls it for every page
and every button. That API is invisible to the agent.

**Insight:** record that hidden API once while the user is logged in, map everything the site can show and do, and generate typed
tools from it. The agent then reads and acts in ~1 second per call with structured data, using exactly the user's own permissions.

### What we built
One command turns a website into tools for your agent:

```bash
underpass add coach.mastersunion.org
```

1. **Record** (`record`): a browser opens; you log in and use the site. Underpass captures every API request the front end
   makes: reads, actions (POST/PUT/PATCH/DELETE with their bodies), GraphQL calls and classic form posts. Then it explores the
   rest of the site on its own with your saved login (skipping logout/delete links).
2. **Map** (`analyze`): groups calls into endpoint templates (`/term/{term_id}/attendance`), keeps real example values,
   flattens response shapes, detects how the site authenticates (bearer token / cookies / custom headers, plus token expiry),
   and **scans the site's own JavaScript for endpoints nobody clicked**. Passwords/OTPs are redacted; login/logout/telemetry
   calls never become tools.
3. **Generate** (`generate`): Claude designs the tool list: names, plain-English descriptions, which params an agent should
   vary vs. fixed defaults, which response fields matter, and for every action, a read tool that verifies it worked.
4. **Serve** (`serve`): a generic MCP server exposes the tools to Claude Code / Claude Desktop / Cursor. `add` registers it
   automatically. `call` and `list` use the same engine from the terminal.

**Safety model:** read tools run directly. Action tools never send anything without `confirm=true`: the first call returns an
exact preview of the request so the agent can ask the user; after an approved action, Underpass calls the verify tool and
returns proof. Everything runs locally; the login never leaves your machine; the agent only gets your own permissions.

**Agent-friendly responses:** only the useful fields, HTML stripped, empty values dropped, long lists cut to fit
(with a note telling the agent how to page).

### The hardest part
Making it work on *any* site without per-site code: inferring endpoint templates and which IDs are "always mine" vs. "the agent
picks", reusing the login across bearer-token, cookie and custom-header sites, discovering actions the user never clicked
(JavaScript scan), and letting an agent take real actions safely (preview -> approval -> execute -> verify).

### How to run it
**Anyone can install it** (Windows/macOS/Linux; needs [uv](https://docs.astral.sh/uv/) and [Claude Code](https://claude.com/claude-code) logged in):
```bash
uv tool install git+https://github.com/avinboi/buildathon-Team-Rocket
underpass add <website>          # a browser opens: log in, click around, close it. The browser downloads itself on first run.
```
Then open Claude Code and ask anything about that site. Other commands:
```bash
underpass list <site>              # see the generated tools
underpass check <site>             # test every read tool live
underpass call <site> <tool> k=v   # call one from the terminal (--yes to approve an action)
underpass login <site>             # if the saved login expires
```
From a clone instead: `uv sync`, then prefix commands with `uv run`.

Race demo (browser agent vs. Underpass on the same question):
```bash
uv run python demo/race.py <site> "<question>"
```

### Results (measured 18 Nov 2026 on a real student account at coach.mastersunion.org)
- **811 API calls recorded -> 89 endpoints mapped -> 132 tools (83 read, 49 actions).**
- **50 actions discovered from the site's JavaScript** that were never clicked: Underpass learned the site's own HTTP helpers
  from observed calls (8 helpers) and applied them to every API path in the code.
- `underpass check`: 60 read tools verified live, median **~0.6 s** per call.
- Action loop verified live: `create_student_note` preview -> approve -> created (432 ms) -> auto-verified via
  `list_student_notes` -> `delete_student_note` -> verified gone.
- Race, same question and model ("attendance % per course and how many more classes can I miss?"):
  browser agent **102.6 s / 18 tool calls**, Underpass **23.8 s / 3 tool calls**. Both correct.
- Response trimming: attendance 690 KB -> 35 KB with every course kept.
- Also works unchanged on public sites: hn.algolia.com (3 tools) and crates.io (8 tools).

### Demo
See [DEMO.md](DEMO.md) for the 2-3 minute script.
