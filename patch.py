import sys
content = open('app.py', encoding='utf-8').read()
insert_idx = content.find('@app.route("/api/tip/update", methods=["POST"])')

handlers = '''
# --- TELEGRAM BOT WEBHOOKS & HANDLERS ---

@app.route("/api/telegram-setup", methods=["GET"])
def telegram_setup():
    if not bot:
        return jsonify({"error": "TELEGRAM_BOT_TOKEN not set"}), 400
    host_url = request.url_root.replace("http://", "https://") 
    webhook_url = f"{host_url}api/telegram-webhook"
    bot.remove_webhook()
    success = bot.set_webhook(url=webhook_url)
    return jsonify({"status": "Webhook set", "success": success, "url": webhook_url})

@app.route("/api/telegram-webhook", methods=["POST"])
def telegram_webhook():
    if bot:
        update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
        bot.process_new_updates([update])
    return "!", 200

def _process_telegram_text(raw_text, chat_id, message_id):
    import re
    matches = re.search(r'(\d+\.\d+|\d+)\s+([+-]\d+\.\d+|[+-]\d+)', raw_text)
    if not matches:
        bot.send_message(chat_id, f"❌ Could not parse Price and Change from text.", reply_to_message_id=message_id)
        return
        
    try:
        current_price = float(matches.group(1))
        change = float(matches.group(2))
    except ValueError:
        bot.send_message(chat_id, "❌ Failed to parse matched numbers", reply_to_message_id=message_id)
        return
        
    lot_size = 0
    qty_match = re.search(r'(?:qty|lot|size|quantity)\D*(\d+)', raw_text, re.IGNORECASE)
    if qty_match:
        lot_size = int(qty_match.group(1))
        
    option_type = "BOTH"
    if re.search(r'\\bCE\\b|\\bCALL\\b', raw_text, re.IGNORECASE):
        option_type = "CE"
    elif re.search(r'\\bPE\\b|\\bPUT\\b', raw_text, re.IGNORECASE):
        option_type = "PE"

    try:
        decoded = decode_tip(
            current_price=current_price,
            abs_change=change,
            pct_change=None,
            lot_size=lot_size,
            option_type=option_type,
            expiry_scope="nearest",
            tolerance_pct=1.0
        )
    except Exception as e:
        bot.send_message(chat_id, f"❌ Decode error: {str(e)}", reply_to_message_id=message_id)
        return

    if "error" in decoded:
        bot.send_message(chat_id, f"❌ {decoded['error']}", reply_to_message_id=message_id)
        return
        
    matches_list = decoded.get("matches", [])
    if not matches_list:
        bot.send_message(chat_id, "❌ No matching options found.", reply_to_message_id=message_id)
        return
        
    best_match = matches_list[0]
    
    text = (
        f"✅ **Tip Decoded Successfully**\\n\\n"
        f"**Symbol:** {best_match['symbol']}\\n"
        f"**Entry Price:** ₹{current_price}\\n"
        f"**Lot Size:** {best_match['lot_size']}\\n"
        f"**Match Quality:** {best_match['match_quality']}"
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    cb_data = f"trade_{best_match['symbol']}_{best_match['token']}_{best_match['lot_size']}"
    if len(cb_data) > 64:
        cb_data = f"trade_short_{best_match['token']}_{best_match['lot_size']}" 
        
    btn = telebot.types.InlineKeyboardButton("⚡ Execute Trade", callback_data=cb_data)
    markup.add(btn)
    
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_to_message_id=message_id, reply_markup=markup)

if bot:
    @bot.message_handler(content_types=['photo'])
    def handle_photo(message):
        chat_id = message.chat.id
        msg_id = message.message_id
        bot.send_chat_action(chat_id, 'typing')
        
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
            
            ocr_api_key = os.getenv("OCR_SPACE_API_KEY", "helloworld")
            r = requests.post("https://api.ocr.space/parse/image", data={'apikey': ocr_api_key, 'url': file_url, 'isOverlayRequired': False})
            ocr_result = r.json()
            
            if ocr_result.get("IsErroredOnProcessing"):
                bot.send_message(chat_id, f"❌ OCR API Error: {ocr_result.get('ErrorMessage')}", reply_to_message_id=msg_id)
                return
                
            parsed_text = ocr_result.get("ParsedResults", [{}])[0].get("ParsedText", "")
            
            caption = message.caption or ""
            raw_text = caption + " " + parsed_text
            
            _process_telegram_text(raw_text, chat_id, msg_id)
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Bot Error processing image: {str(e)}", reply_to_message_id=msg_id)
            
    @bot.callback_query_handler(func=lambda call: call.data.startswith('trade_'))
    def handle_trade_callback(call):
        try:
            parts = call.data.split('_')
            if parts[1] == "short":
                token = parts[2]
                qty = parts[3]
                symbol = "Unknown"
            else:
                symbol = parts[1]
                token = parts[2]
                qty = parts[3]
                
            obj = get_session()
            df = get_instrument_df()
            opt_info = df[df["token"] == token]
            if opt_info.empty:
                 bot.answer_callback_query(call.id, "❌ Error: Could not find instrument in memory.")
                 return
                 
            real_symbol = opt_info.iloc[0]["symbol"]
            inst_type = opt_info.iloc[0]["instrumenttype"]
            
            orderparams = {
                "variety": "NORMAL",
                "tradingsymbol": real_symbol,
                "symboltoken": token,
                "transactiontype": "BUY",
                "exchange": inst_type == "OPTIDX" and "NFO" or "BFO",
                "ordertype": "MARKET",
                "producttype": "CARRYFORWARD",
                "duration": "DAY",
                "quantity": str(qty)
            }
            
            orderId = obj.placeOrder(orderparams)
            
            bot.answer_callback_query(call.id, "✅ Trade Executed!")
            bot.edit_message_text(
                f"{call.message.text}\\n\\n✅ **Trade Executed! (Order ID: {orderId})**", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )
            
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Execution Failed: {str(e)}", show_alert=True)

'''
new_content = content[:insert_idx] + handlers + content[insert_idx:]
open('app.py', 'w', encoding='utf-8').write(new_content)
