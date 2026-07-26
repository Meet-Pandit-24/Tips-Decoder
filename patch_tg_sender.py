import sys
content = open('app.py', encoding='utf-8').read()

# 1. Update _process_telegram_text signature and success message template
old_process_sig = 'def _process_telegram_text(raw_text, chat_id, message_id, status_msg_id=None):'
new_process_sig = 'def _process_telegram_text(raw_text, chat_id, message_id, status_msg_id=None, sender_name=None, forward_info=None):'
content = content.replace(old_process_sig, new_process_sig)

old_text_template = '''    text = (
        f"✅ **Tip Decoded Successfully**\\n\\n"
        f"**Symbol:** {best_match['symbol']}\\n"
        f"**Entry Price:** ₹{current_price}\\n"
        f"**Lot Size:** {best_match['lot_size']}\\n"
        f"**Match Quality:** {best_match['match_quality']}\\n\\n"
        f"📝 **Raw OCR Log:**\\n"
        f"{raw_text.strip()}"
    )'''

new_text_template = '''    meta_str = ""
    if sender_name:
        meta_str += f"👤 **Shared By:** {sender_name}\\n"
    if forward_info:
        meta_str += f"📢 **Source:** {forward_info}\\n"
    if meta_str:
        meta_str += "\\n"

    text = (
        f"✅ **Tip Decoded Successfully**\\n\\n"
        f"{meta_str}"
        f"**Symbol:** {best_match['symbol']}\\n"
        f"**Entry Price:** ₹{current_price}\\n"
        f"**Lot Size:** {best_match['lot_size']}\\n"
        f"**Match Quality:** {best_match['match_quality']}\\n\\n"
        f"📝 **Raw OCR Log:**\\n"
        f"{raw_text.strip()}"
    )'''

content = content.replace(old_text_template, new_text_template)

# 2. Update handle_photo to extract sender_name & forward_info
old_process_call = '_process_telegram_text(raw_text, chat_id, msg_id, status_msg.message_id)'
new_process_call = '''# Extract sender details
            sender = message.from_user
            sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip()
            if sender.username:
                sender_name += f" (@{sender.username})"
            
            # Extract forward source details if forwarded
            forward_info = None
            if message.forward_from_chat:
                chat = message.forward_from_chat
                forward_info = f"{chat.title or ''}"
                if chat.username:
                    forward_info += f" (@{chat.username})"
            elif message.forward_from:
                usr = message.forward_from
                usr_name = f"{usr.first_name or ''} {usr.last_name or ''}".strip()
                if usr.username:
                    usr_name += f" (@{usr.username})"
                forward_info = usr_name

            _process_telegram_text(raw_text, chat_id, msg_id, status_msg.message_id, sender_name, forward_info)'''

content = content.replace(old_process_call, new_process_call)

# 3. Update handle_trade_callback to save to Database
old_callback_body = '''            orderId = obj.placeOrder(orderparams)
            
            bot.answer_callback_query(call.id, "✅ Trade Executed!")
            bot.edit_message_text(
                f"{call.message.text}\\n\\n✅ **Trade Executed! (Order ID: {orderId})**", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )'''

new_callback_body = '''            orderId = obj.placeOrder(orderparams)
            
            # Save the executed trade to the Database tracker
            try:
                with app.app_context():
                    # Parse Entry Price from message text
                    import re
                    price_match = re.search(r'Entry Price:\\s*₹?(\\d+\\.\\d+|\\d+)', call.message.text)
                    entry_price = float(price_match.group(1)) if price_match else 0.0
                    
                    # Parse Shared By details
                    shared_match = re.search(r'Shared By:\\s*([^\\n]+)', call.message.text)
                    shared_by = shared_match.group(1).strip() if shared_match else "Telegram User"
                    
                    tip = Tip(
                        symbol=real_symbol,
                        token=token,
                        underlying=opt_info.iloc[0]["name"],
                        strike=float(opt_info.iloc[0]["strike"]),
                        expiry=opt_info.iloc[0]["expiry"],
                        opt_type=opt_info.iloc[0]["opt_type"],
                        lot_size=int(qty),
                        instrument_type=inst_type,
                        entry_price=entry_price,
                        entry_ltp=float(opt_info.iloc[0].get("ltp", entry_price)),
                        mode="TRADED",
                        status="OPEN",
                        notes=f"Executed via Telegram by {call.from_user.first_name or 'User'}. Shared by: {shared_by}"
                    )
                    db.session.add(tip)
                    db.session.commit()
            except Exception as db_err:
                print(f"[WARN] Failed to auto-save Telegram trade to database: {db_err}")

            bot.answer_callback_query(call.id, "✅ Trade Executed!")
            bot.edit_message_text(
                f"{call.message.text}\\n\\n✅ **Trade Executed! (Order ID: {orderId})**", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id,
                parse_mode="Markdown"
            )'''

content = content.replace(old_callback_body, new_callback_body)

open('app.py', 'w', encoding='utf-8').write(content)
