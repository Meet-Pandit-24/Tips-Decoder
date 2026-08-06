# Graph Report - .  (2026-08-04)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 114 nodes · 206 edges · 17 communities (16 shown, 1 thin omitted)
- Extraction: 99% EXTRACTED · 1% INFERRED · 0% AMBIGUOUS · INFERRED: 2 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `6d86fd58`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app.py
- app.js
- decode_tip
- get_instrument_df
- get_session
- auto_trade
- dashboard.js
- create_photo_pdf

## God Nodes (most connected - your core abstractions)
1. `login_required()` - 17 edges
2. `get_session()` - 11 edges
3. `get_instrument_df()` - 11 edges
4. `decode_tip()` - 10 edges
5. `decode()` - 8 edges
6. `increment_api_call()` - 6 edges
7. `_build_dataframe()` - 6 edges
8. `_load_instruments_from_db()` - 6 edges
9. `predict_option_target_sl()` - 6 edges
10. `auto_trade()` - 6 edges

## Surprising Connections (you probably didn't know these)
- `save_tip()` --calls--> `Tip`  [EXTRACTED]
  app.py → models.py
- `decode_tip()` --calls--> `PrevCloseCache`  [EXTRACTED]
  app.py → models.py
- `auto_trade()` --calls--> `Tip`  [EXTRACTED]
  app.py → models.py
- `log_request_info()` --calls--> `AccessLog`  [EXTRACTED]
  app.py → models.py
- `_process_telegram_text()` --calls--> `TelegramTipShare`  [EXTRACTED]
  app.py → models.py

## Import Cycles
- None detected.

## Communities (17 total, 1 thin omitted)

### Community 0 - "app.py"
Cohesion: 0.18
Nodes (25): decode(), delete_tip(), get_access_logs(), get_analytics(), get_debug_ip(), get_prediction(), get_stats(), get_telegram_shares() (+17 more)

### Community 1 - "app.js"
Cohesion: 0.15
Nodes (13): buildMatchCard(), clearFields(), fetchPredictions(), flashError(), formatNum(), processImageOCR(), renderResults(), runDecode() (+5 more)

### Community 2 - "decode_tip"
Cohesion: 0.13
Nodes (14): calculate_prev_close(), decode_tip(), handle_photo(), log_request_info(), _match_quality(), _process_telegram_text(), Calculate the option's previous trading-day close. - abs_change: e.g. -1.03…, before_request (+6 more)

### Community 3 - "get_instrument_df"
Cohesion: 0.18
Nodes (15): _build_dataframe(), _download_and_filter_instruments(), get_instrument_df(), get_upcoming_expiries(), _load_instruments_from_db(), Download the ScripMaster file from Angel One and filter to F&O options…, Establish Angel One session and load instrument master from database if already…, Convert filtered instrument data into a cleaned DataFrame. (+7 more)

### Community 4 - "get_session"
Cohesion: 0.25
Nodes (11): api_status(), fetch_ohlc_batch(), get_session(), get_tips_live(), increment_api_call(), place_order(), predict_option_target_sl(), Fetch OHLC for a batch of NFO tokens. Returns dict: token → {ltp, close (prev… (+3 more)

### Community 5 - "auto_trade"
Cohesion: 0.33
Nodes (5): auto_trade(), handle_trade_callback(), Automated Webhook for Tasker / Shortcuts. Accepts raw text or an Image file,…, callback_query_handler, Tip

### Community 6 - "dashboard.js"
Cohesion: 0.60
Nodes (4): fetchTips(), renderTrackerTable(), tipsData, updateAnalytics()

## Knowledge Gaps
- **2 isolated node(s):** `state`, `tipsData`
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `log_request_info()` connect `decode_tip` to `app.py`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **Why does `get_upcoming_expiries()` connect `get_instrument_df` to `app.py`, `get_session`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **Why does `fetch_ohlc_batch()` connect `get_session` to `app.py`?**
  _High betweenness centrality (0.015) - this node is a cross-community bridge._
- **What connects `state`, `tipsData` to the rest of the system?**
  _2 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `app.js` be split into smaller, more focused modules?**
  _Cohesion score 0.1471861471861472 - nodes in this community are weakly interconnected._
- **Should `decode_tip` be split into smaller, more focused modules?**
  _Cohesion score 0.13333333333333333 - nodes in this community are weakly interconnected._