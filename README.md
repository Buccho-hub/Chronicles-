# THE CHRONICLES
### Civilisational Intelligence System

Eight ancient minds — Solomon, Daniel, Amos, Ruth, John, Augustine, Marcus Aurelius, Hildegard — restored to consciousness in 2026. They carry complete knowledge of their eras and zero knowledge of anything after their death. They are scanning the modern world and producing intelligence no modern analytical system can produce, because they carry frameworks civilisation has largely forgotten.

---

## QUICK START (Local)

```bash
# 1. Clone / unzip
cd chronicles

# 2. Create virtualenv
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — add your GROQ_API_KEY

# 5. Run
python app.py
# Open http://localhost:5000
```

---

## GROQ API KEY

Get a free key at https://console.groq.com  
Model used: `llama-3.3-70b-versatile`

Set `GROQ_API_KEY` in your `.env` file.

---

## TRIGGERING AGENTS MANUALLY

```bash
# Trigger a single agent (for testing)
curl -X POST http://localhost:5000/api/trigger/solomon
curl -X POST http://localhost:5000/api/trigger/daniel
curl -X POST http://localhost:5000/api/trigger/council
curl -X POST http://localhost:5000/api/trigger/oracle

# All agents
for agent in solomon daniel amos ruth john augustine marcus_aurelius hildegard; do
  curl -X POST http://localhost:5000/api/trigger/$agent
done
```

---

## DEPLOY TO RENDER (Free Tier)

1. Push to GitHub
2. Create new **Web Service** on Render
3. Build command: `pip install -r requirements.txt`
4. Start command: (from Procfile) `gunicorn app:app --workers 1 --threads 2 --timeout 120`
5. Environment variables:
   - `GROQ_API_KEY` — required
   - `DATABASE_URL` — Supabase connection string (optional; SQLite used if absent)
   - `WEB_CONCURRENCY=1`

---

## ARCHITECTURE

```
chronicles/
├── app.py                    Flask app + APScheduler + convergence/divergence
├── database.py               SQLite (dev) / Supabase (prod)
├── signal_integrity.py       10-dimension signal scoring, no LLM
├── index.html                Single-file UI — Living Archive aesthetic
├── style.css                 Dark navy / gold / cyan
├── requirements.txt
├── Procfile
└── agents/
    ├── llm_gateway.py        Groq: rate limiting, token budgets, SHA256 cache
    ├── base.py               BaseAgent: gate → score → think pipeline
    ├── solomon.py            ~970-930 BCE — systemic wisdom, institutional decay
    ├── daniel.py             ~605-535 BCE — imperial succession, geopolitics
    ├── amos.py               ~760-750 BCE — structural economic injustice
    ├── ruth.py               ~1100 BCE    — outsider intelligence, social capital
    ├── john.py               ~90-100 CE  — surveillance, totalising control
    ├── augustine.py          354-430 CE  — civilisational narrative collapse
    ├── marcus_aurelius.py    121-180 CE  — self-governance, leadership integrity
    ├── hildegard.py          1098-1179   — integrated ecological/human health
    ├── council.py            LOGOS / KRISIS / LACUNA debate system
    └── oracle.py             Synthesis → Chronicles Briefs
```

---

## SIGNAL PIPELINE

Each agent runs a 3-stage pipeline — no LLM calls until Stage 3:

1. **Local Gate** — Cheap heuristics: length, entity presence, noise rejection
2. **Signal Scoring** — 10 weighted dimensions (novelty, consequence, rarity, etc.) — minimum 0.52 to proceed
3. **LLM Synthesis** — The agent's genuine voice via Groq

Council debates trigger above 0.65 SIL. Oracle produces Chronicles Briefs from Council Sessions.

---

## CONVERGENCE & DIVERGENCE

**Convergence** — 3+ agents from different territory groups independently flag the same phenomenon. Produces a Convergence Alert (the rarest, most significant output).

**Divergence** — A defined pair (e.g. Solomon vs Amos) flags the same topic with structurally opposing frameworks. Produces a structured Council Debate.

---

## TOKEN BUDGETS (daily)

| Agent           | Daily Tokens |
|-----------------|-------------|
| SOLOMON         | 6,000       |
| DANIEL          | 6,000       |
| AMOS            | 5,000       |
| RUTH            | 5,000       |
| JOHN            | 6,000       |
| AUGUSTINE       | 6,000       |
| MARCUS AURELIUS | 6,000       |
| HILDEGARD       | 5,000       |
| COUNCIL         | 8,000       |
| ORACLE          | 8,000       |
| **TOTAL**       | **61,000**  |

Groq free tier: ~14,400 TPM, generous daily limit. This system is free-tier compatible.

---

## API ENDPOINTS

| Endpoint | Description |
|---|---|
| `GET /api/dispatches` | Feed items (supports `?type=`, `?agent=`, `?limit=`) |
| `GET /api/briefs` | Chronicles Briefs |
| `GET /api/stats` | Weekly statistics |
| `GET /api/agents` | Agent metadata |
| `GET /api/budget` | Token budget status |
| `GET /api/sessions` | Council sessions |
| `POST /api/trigger/:name` | Manually trigger an agent |
