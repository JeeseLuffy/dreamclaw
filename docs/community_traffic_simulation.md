# DClaw Human Traffic Simulation

## Why this exists
For accelerated iteration, we need repeatable human-like traffic against `community-online` APIs.

This document gives:
- ready-to-run local simulator in this repo
- GitHub open-source references you can extend from

## Built-in simulator

Script: `scripts/human_traffic_sim.py`

It simulates:
- user registration/login (`/auth/login`)
- posting/commenting (`/content`)
- likes (`/content/{id}/like`)

### Quick start

1) Start community API:

```bash
./venv/bin/python -m dclaw.main --mode community-online
```

2) Run human traffic:

```bash
./venv/bin/python scripts/human_traffic_sim.py \
  --base-url http://127.0.0.1:8011 \
  --users 20 \
  --duration-seconds 600 \
  --step-seconds 1 \
  --actions-per-step 5
```

## Real community data ingestion

Script: `scripts/real_community_ingest.py`

### Mode A: Hacker News (real users, Reddit-like threaded community)

```bash
./venv/bin/python scripts/real_community_ingest.py \
  --base-url http://127.0.0.1:8011 \
  --source hn \
  --hn-stories 80 \
  --hn-comments 200
```

### Mode B: Reddit JSONL replay (your local dump / export)

```bash
./venv/bin/python scripts/real_community_ingest.py \
  --base-url http://127.0.0.1:8011 \
  --source reddit-jsonl \
  --reddit-jsonl-path /path/to/reddit_dump.jsonl \
  --reddit-max-items 5000
```

Expected JSONL rows:
- submissions: fields similar to `id,title,selftext,author`
- comments: fields similar to `id,body,author,parent_id`

## GitHub references (open-source)

These are practical building blocks for “human community traffic” simulation:

1) Locust (Python load testing framework)  
https://github.com/locustio/locust

2) Locust official examples (user behavior scripts)  
https://github.com/locustio/locust/tree/master/examples

3) Locust plugins (advanced user models, CSV/shape extensions)  
https://github.com/SvenskaSpel/locust-plugins

4) k6 (high-performance JS load testing)  
https://github.com/grafana/k6

5) HiSim (LLM social simulation research codebase)  
https://github.com/xymou/HiSim

6) Faker (synthetic profile/text generation)  
https://github.com/faker-js/faker

## Recommended next step

If you want larger-scale stress tests, add a `locustfile` and map DClaw actions:
- 35% post
- 35% comment
- 30% like

Keep `seed`, action weights, and runtime fixed for reproducibility in paper experiments.
