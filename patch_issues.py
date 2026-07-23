import sys
content = open('app.py', encoding='utf-8').read()

# 1. Update refresh_instrument_cache with async DB save
old_refresh = '''def refresh_instrument_cache():
    \"\"\"Download ScripMaster, filter to F&O, save to DB, and update in-memory cache.
    Called by the scheduler at 9:15 AM IST on weekdays and as a fallback on first request.\"\"\"
    global _instrument_df, _instrument_cache_date
    today = date.today()
    
    try:
        filtered_data = _download_and_filter_instruments()
        
        # Save to database (replace old data)
        with app.app_context():
            # Delete all old cached rows
            InstrumentCache.query.delete()
            
            # Insert new rows in batches for efficiency
            batch = []
            for item in filtered_data:
                batch.append(InstrumentCache(
                    cache_date=today,
                    token=item.get("token", ""),
                    symbol=item.get("symbol", ""),
                    name=item.get("name", ""),
                    expiry=item.get("expiry", ""),
                    strike=str(item.get("strike", "0")),
                    lotsize=str(item.get("lotsize", "0")),
                    instrumenttype=item.get("instrumenttype", ""),
                    exch_seg=item.get("exch_seg", ""),
                    tick_size=str(item.get("tick_size", ""))
                ))
                if len(batch) >= 1000:
                    db.session.bulk_save_objects(batch)
                    batch = []
            
            if batch:
                db.session.bulk_save_objects(batch)
            
            db.session.commit()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Saved {len(filtered_data):,} instruments to database (date: {today})")
        
        # Update in-memory cache
        with _instrument_lock:
            _instrument_df = _build_dataframe(filtered_data)
            _instrument_cache_date = today
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ In-memory cache updated")
            
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Failed to refresh instrument cache: {e}")'''

new_refresh = '''def _save_instruments_to_db_async(app_context_data, filtered_data, today):
    app, db_uri = app_context_data
    with app.app_context():
        try:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Async DB save started...")
            
            mappings = []
            for item in filtered_data:
                mappings.append({
                    "cache_date": today,
                    "token": item.get("token", ""),
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "expiry": item.get("expiry", ""),
                    "strike": str(item.get("strike", "0")),
                    "lotsize": str(item.get("lotsize", "0")),
                    "instrumenttype": item.get("instrumenttype", ""),
                    "exch_seg": item.get("exch_seg", ""),
                    "tick_size": str(item.get("tick_size", ""))
                })
            
            InstrumentCache.query.delete()
            db.session.bulk_insert_mappings(InstrumentCache, mappings)
            db.session.commit()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Async DB save complete: {len(mappings):,} rows saved.")
        except Exception as e:
            db.session.rollback()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Async DB save failed: {e}")

def refresh_instrument_cache():
    \"\"\"Download ScripMaster, filter to F&O, save to DB, and update in-memory cache.
    Called by the scheduler at 9:15 AM IST on weekdays and as a fallback on first request.\"\"\"
    global _instrument_df, _instrument_cache_date
    today = date.today()
    
    try:
        filtered_data = _download_and_filter_instruments()
        
        # 1. Update in-memory cache immediately so the current request finishes fast
        with _instrument_lock:
            _instrument_df = _build_dataframe(filtered_data)
            _instrument_cache_date = today
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ In-memory cache updated immediately")
            
        # 2. Trigger asynchronous DB write so it doesn't block the request
        thr = threading.Thread(
            target=_save_instruments_to_db_async, 
            args=((app, app.config['SQLALCHEMY_DATABASE_URI']), filtered_data, today)
        )
        thr.daemon = True
        thr.start()
            
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Failed to refresh instrument cache: {e}")'''

content = content.replace(old_refresh, new_refresh)

# 2. Replace lot size regex in auto_trade() and handle_photo()
old_regex = '''    lot_size = 0
    qty_match = re.search(r'(?:qty|lot|size|quantity)\\D*(\\d+)', raw_text, re.IGNORECASE)
    if qty_match:
        lot_size = int(qty_match.group(1))'''

new_regex = '''    lot_size = 0
    qty_match = re.search(r'(\\d+)\\s*(?:qty|lot|size|quantity)\\b', raw_text, re.IGNORECASE)
    if qty_match:
        lot_size = int(qty_match.group(1))
    else:
        qty_match = re.search(r'(?:qty|lot|size|quantity)\\s*[:=-]?\\s*(\\d+)', raw_text, re.IGNORECASE)
        if qty_match:
            lot_size = int(qty_match.group(1))'''

content = content.replace(old_regex, new_regex)

open('app.py', 'w', encoding='utf-8').write(content)
