import sys
content = open('app.py', encoding='utf-8').read()

# Add imports and predict_option_target_sl helper before decode()
predict_code = '''
def predict_option_target_sl(symbol_info, entry_price):
    \"\"\"
    Given a decoded symbol dict and the buy entry price,
    dynamically look up the underlying spot price, calculate support/resistance,
    estimate the Option Delta, and predict the Option Target and Stop Loss.
    Also returns option risk warning checklist.
    \"\"\"
    underlying = symbol_info.get("underlying")
    strike = symbol_info.get("strike")
    opt_type = symbol_info.get("opt_type")
    expiry_str = symbol_info.get("expiry")
    lot_size = symbol_info.get("lot_size", 1)
    
    # 1. Resolve Underlying Spot Token
    index_map = {
        "NIFTY": ("NSE", "99926000", "Nifty 50"),
        "BANKNIFTY": ("NSE", "99926009", "Nifty Bank"),
        "FINNIFTY": ("NSE", "99926037", "Nifty Fin Service"),
        "MIDCPNIFTY": ("NSE", "99926014", "Nifty Midcap 50"),
        "SENSEX": ("BSE", "99919000", "SENSEX"),
    }
    
    obj = get_session()
    
    exch = "NSE"
    spot_token = None
    spot_symbol = ""
    
    if underlying in index_map:
        exch, spot_token, spot_symbol = index_map[underlying]
    else:
        try:
            search_res = obj.searchScrip(exchange="NSE", searchscrip=underlying)
            if search_res and search_res.get("status") and search_res.get("data"):
                for item in search_res["data"]:
                    symbol = item.get("tradingsymbol", "")
                    if symbol == f"{underlying}-EQ" or symbol == underlying:
                        spot_token = item.get("symboltoken")
                        spot_symbol = symbol
                        break
                if not spot_token:
                    spot_token = search_res["data"][0].get("symboltoken")
                    spot_symbol = search_res["data"][0].get("tradingsymbol")
        except Exception as e:
            print(f"[WARN] Failed to search scrip for {underlying}: {e}")
            
    # Default fallback if spot cannot be found
    if not spot_token:
        return {
            "spot_price": None,
            "spot_support": None,
            "spot_resistance": None,
            "option_target": round(entry_price * 1.4, 2),
            "option_sl": round(entry_price * 0.7, 2),
            "rr_ratio": 1.33,
            "lot_profit": round((entry_price * 0.4) * lot_size, 2),
            "lot_loss": round((entry_price * 0.3) * lot_size, 2),
            "warnings": ["⚠️ Could not fetch spot candles. Using standard 40% Target / 30% SL rule."],
            "logic_target": "Using default 40% option target",
            "logic_sl": "Using default 30% option stop loss"
        }
        
    # 2. Get Live Spot LTP and historical candles
    spot_price = None
    support = None
    resistance = None
    atr = None
    
    try:
        # Get live spot price
        increment_api_call()
        mkt_res = obj.getMarketData("LTP", {exch: [spot_token]})
        if mkt_res and mkt_res.get("status") and mkt_res.get("data", {}).get("fetched"):
            spot_price = float(mkt_res["data"]["fetched"][0].get("ltp", 0))
            
        # Get 7 daily candles
        today = date.today()
        from_date = (today - timedelta(days=12)).strftime('%Y-%m-%d 09:15')
        to_date = today.strftime('%Y-%m-%d 15:30')
        
        increment_api_call()
        candle_res = obj.getCandleData({
            "exchange": exch,
            "symboltoken": spot_token,
            "interval": "ONE_DAY",
            "fromdate": from_date,
            "todate": to_date
        })
        
        if candle_res and candle_res.get("status") and candle_res.get("data"):
            candles = candle_res["data"]
            if len(candles) >= 3:
                support = min(float(c[3]) for c in candles[-3:])
                resistance = max(float(c[2]) for c in candles[-3:])
                atr_vals = [float(c[2]) - float(c[3]) for c in candles[-5:]]
                atr = sum(atr_vals) / len(atr_vals)
    except Exception as e:
        print(f"[WARN] Failed to fetch spot technicals: {e}")
        
    if not spot_price or not support or not resistance:
        return {
            "spot_price": None,
            "spot_support": None,
            "spot_resistance": None,
            "option_target": round(entry_price * 1.4, 2),
            "option_sl": round(entry_price * 0.7, 2),
            "rr_ratio": 1.33,
            "lot_profit": round((entry_price * 0.4) * lot_size, 2),
            "lot_loss": round((entry_price * 0.3) * lot_size, 2),
            "warnings": ["⚠️ Could not fetch spot candles. Using standard 40% Target / 30% SL rule."],
            "logic_target": "Using default 40% option target",
            "logic_sl": "Using default 30% option stop loss"
        }
        
    if not atr:
        atr = spot_price * 0.015
        
    diff_pct = ((spot_price - strike) / strike) * 100
    
    delta = 0.5
    moneyness = "ATM"
    
    if opt_type == "CE":
        if diff_pct >= 2.0:
            delta = 0.75
            moneyness = "ITM"
        elif diff_pct <= -2.0:
            delta = 0.25
            moneyness = "OTM"
    else:
        if diff_pct <= -2.0:
            delta = 0.75
            moneyness = "ITM"
        elif diff_pct >= 2.0:
            delta = 0.25
            moneyness = "OTM"
            
    warnings = []
    
    try:
        expiry_dt = datetime.strptime(expiry_str, "%d%b%Y").date()
        days_to_expiry = (expiry_dt - date.today()).days
        if days_to_expiry <= 2:
            warnings.append(f"⚠️ **High Time Decay:** Only {days_to_expiry} days to expiry. Scalp only.")
        else:
            warnings.append(f"✅ **Safe Expiry:** {days_to_expiry} days left.")
    except:
        days_to_expiry = 5
        
    if moneyness == "OTM":
        warnings.append("⚠️ **Out-of-the-Money:** Option has lower probability of expiring ITM. Targets depend on strong price momentum.")
        
    target_price = None
    sl_price = None
    
    logic_target = ""
    logic_sl = ""
    
    if opt_type == "CE":
        spot_target_dist = resistance - spot_price
        if spot_target_dist <= 0:
            spot_target_dist = atr * 1.5
            logic_target = "Spot is at resistance. Target set at spot price + 1.5x ATR."
        else:
            logic_target = f"Derived from Spot Resistance level: ₹{resistance:,.2f}"
            
        opt_gain = spot_target_dist * delta
        target_price = entry_price + opt_gain
        
        spot_sl_dist = spot_price - support
        if spot_sl_dist <= 0:
            spot_sl_dist = atr
            logic_sl = "Spot is at support. SL set at spot price - 1x ATR."
        else:
            logic_sl = f"Derived from Spot Support level: ₹{support:,.2f}"
            
        opt_loss = spot_sl_dist * delta
        sl_price = entry_price - opt_loss
        
    else:
        spot_target_dist = spot_price - support
        if spot_target_dist <= 0:
            spot_target_dist = atr * 1.5
            logic_target = "Spot is at support. Target set at spot price - 1.5x ATR."
        else:
            logic_target = f"Derived from Spot Support level: ₹{support:,.2f}"
            
        opt_gain = spot_target_dist * delta
        target_price = entry_price + opt_gain
        
        spot_sl_dist = resistance - spot_price
        if spot_sl_dist <= 0:
            spot_sl_dist = atr
            logic_sl = "Spot is at resistance. SL set at spot price + 1x ATR."
        else:
            logic_sl = f"Derived from Spot Resistance level: ₹{resistance:,.2f}"
            
        opt_loss = spot_sl_dist * delta
        sl_price = entry_price - opt_loss

    if days_to_expiry <= 2:
        target_price = entry_price + (target_price - entry_price) * 0.8
        logic_target += " (Reduced 20% due to close expiry)"

    max_sl = entry_price * 0.65
    min_sl = entry_price * 0.85
    if sl_price < max_sl:
        sl_price = max_sl
        logic_sl += " (Capped at standard max 35% SL)"
    elif sl_price > min_sl:
        sl_price = min_sl
        logic_sl += " (Adjusted to standard min 15% SL)"
        
    target_price = round(max(target_price, entry_price * 1.15), 2)
    sl_price = round(max(sl_price, 0.05), 2)
    
    opt_gain = target_price - entry_price
    opt_loss = entry_price - sl_price
    rr = round(opt_gain / opt_loss, 2) if opt_loss > 0 else 1.0
    
    return {
        "spot_price": round(spot_price, 2),
        "spot_support": round(support, 2),
        "spot_resistance": round(resistance, 2),
        "option_target": target_price,
        "option_sl": sl_price,
        "rr_ratio": rr,
        "lot_profit": round(opt_gain * lot_size, 2),
        "lot_loss": round(opt_loss * lot_size, 2),
        "warnings": warnings,
        "logic_target": logic_target,
        "logic_sl": logic_sl
    }

'''

insert_idx = content.find('def decode():')
content = content[:insert_idx] + predict_code + content[insert_idx:]

open('app.py', 'w', encoding='utf-8').write(content)
