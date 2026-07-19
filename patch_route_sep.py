import sys
content = open('app.py', encoding='utf-8').read()

# 1. Remove prediction logic from /api/decode route
old_decode_pred = '''        # Dynamically predict targets, SL, and check risks for each matching option
        if "matches" in result:
            for match in result["matches"]:
                try:
                    match["predictions"] = predict_option_target_sl(match, current_price)
                except Exception as ex:
                    print(f"[WARN] Target/SL prediction failed: {ex}")'''
content = content.replace(old_decode_pred, '')

# 2. Add new /api/predict endpoint
predict_route = '''
@app.route("/api/predict", methods=["POST"])
@login_required
def get_prediction():
    """
    Separate API to fetch targets and SL asynchronously so it doesn't slow down the main decode action.
    """
    body = request.get_json(force=True)
    try:
        symbol_info = body.get("match")
        entry_price = float(body.get("entry_price", 0))
        
        if not symbol_info or entry_price <= 0:
            return jsonify({"error": "Invalid request parameters"}), 400
            
        predictions = predict_option_target_sl(symbol_info, entry_price)
        return jsonify(predictions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
'''

# Place the route after decode()
insert_idx = content.find('@app.route("/api/auto-trade"')
content = content[:insert_idx] + predict_route + '\n' + content[insert_idx:]

open('app.py', 'w', encoding='utf-8').write(content)
