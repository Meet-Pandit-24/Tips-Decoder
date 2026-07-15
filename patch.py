import sys
content = open('app.py', encoding='utf-8').read()

# Fix /api/order
content = content.replace(
    '\"exchange\": body.get(\"exchange\", \"NFO\"),',
    '\"exchange\": opt_info.iloc[0][\"exch_seg\"] if not opt_info.empty else body.get(\"exchange\", \"NFO\"),'
)

# Fix telegram trade execution callback
content = content.replace(
    '\"exchange\": inst_type == \"OPTIDX\" and \"NFO\" or \"BFO\",',
    '\"exchange\": opt_info.iloc[0][\"exch_seg\"],'
)

# Fix telegram error handling for orderId = None
old_exec = '''            orderId = obj.placeOrder(orderparams)
            
            # Record in DB'''

new_exec = '''            orderId = obj.placeOrder(orderparams)
            if not orderId:
                bot.answer_callback_query(call.id, "❌ Order failed in Angel One. Check API credentials or funds.", show_alert=True)
                return
            
            # Record in DB'''
content = content.replace(old_exec, new_exec)

# Fix auto-trade webhook
old_auto = '''            "exchange": best_match["instrumenttype"] == "OPTIDX" and "NFO" or "BFO",'''
new_auto = '''            "exchange": best_match.get("exch_seg", "NFO"),'''
content = content.replace(old_auto, new_auto)

# Add exch_seg to matches in decode_tip
old_match = '''                  "instrumenttype":      row["instrumenttype"],'''
new_match = '''                  "instrumenttype":      row["instrumenttype"],
                  "exch_seg":            row["exch_seg"],'''
content = content.replace(old_match, new_match)


open('app.py', 'w', encoding='utf-8').write(content)
