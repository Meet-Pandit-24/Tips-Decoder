import sys
content = open('app.py', encoding='utf-8').read()

# Replace _process_telegram_text signature and bot.send_message calls
old_proc_sig = '''def _process_telegram_text(raw_text, chat_id, message_id):'''
new_proc_sig = '''def _process_telegram_text(raw_text, chat_id, message_id, status_msg_id=None):
    def send_or_edit(text, markup=None):
        if status_msg_id:
            bot.edit_message_text(text, chat_id=chat_id, message_id=status_msg_id, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, text, reply_to_message_id=message_id, reply_markup=markup, parse_mode="Markdown")
'''
content = content.replace(old_proc_sig, new_proc_sig)

# Replace all bot.send_message inside _process_telegram_text
import re
content = re.sub(r'bot\.send_message\(chat_id,\s*(.*?),\s*reply_to_message_id=message_id\)', r'send_or_edit(\1)', content)
content = re.sub(r'bot\.send_message\(chat_id,\s*(.*?),\s*parse_mode="Markdown",\s*reply_to_message_id=message_id,\s*reply_markup=markup\)', r'send_or_edit(\1, markup=markup)', content)

# Replace handle_photo
old_handle = '''    @bot.message_handler(content_types=['photo'])
    def handle_photo(message):
        chat_id = message.chat.id
        msg_id = message.message_id
        bot.send_chat_action(chat_id, 'typing')
        
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
            
            # Download the image from Telegram first to ensure OCR Space doesn't fail on URL fetching
            img_response = requests.get(file_url)
            if img_response.status_code != 200:
                bot.send_message(chat_id, "❌ Error downloading image from Telegram.", reply_to_message_id=msg_id)
                return
            
            ocr_api_key = os.getenv("OCR_SPACE_API_KEY", "helloworld")
            r = requests.post(
                "https://api.ocr.space/parse/image", 
                data={'apikey': ocr_api_key, 'isOverlayRequired': False},
                files={'file': ('image.jpg', img_response.content, 'image/jpeg')}
            )
            ocr_result = r.json()
            
            if ocr_result.get("IsErroredOnProcessing"):
                bot.send_message(chat_id, f"❌ OCR API Error: {ocr_result.get('ErrorMessage')}", reply_to_message_id=msg_id)
                return
                
            parsed_text = ocr_result.get("ParsedResults", [{}])[0].get("ParsedText", "")
            
            caption = message.caption or ""
            raw_text = caption + " " + parsed_text
            
            _process_telegram_text(raw_text, chat_id, msg_id)
            
        except Exception as e:
            bot.send_message(chat_id, f"❌ Bot Error processing image: {str(e)}", reply_to_message_id=msg_id)'''

new_handle = '''    @bot.message_handler(content_types=['photo'])
    def handle_photo(message):
        chat_id = message.chat.id
        msg_id = message.message_id
        
        status_msg = bot.send_message(chat_id, "⏳ **Downloading image...**", parse_mode="Markdown", reply_to_message_id=msg_id)
        
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_info.file_path}"
            
            img_response = requests.get(file_url)
            if img_response.status_code != 200:
                bot.edit_message_text("❌ Error downloading image from Telegram.", chat_id=chat_id, message_id=status_msg.message_id)
                return
            
            bot.edit_message_text("🔍 **Extracting text (OCR)...**", chat_id=chat_id, message_id=status_msg.message_id, parse_mode="Markdown")
            
            ocr_api_key = os.getenv("OCR_SPACE_API_KEY", "helloworld")
            r = requests.post(
                "https://api.ocr.space/parse/image", 
                data={'apikey': ocr_api_key, 'isOverlayRequired': False},
                files={'file': ('image.jpg', img_response.content, 'image/jpeg')}
            )
            ocr_result = r.json()
            
            if ocr_result.get("IsErroredOnProcessing"):
                bot.edit_message_text(f"❌ OCR API Error: {ocr_result.get('ErrorMessage')}", chat_id=chat_id, message_id=status_msg.message_id)
                return
                
            parsed_text = ocr_result.get("ParsedResults", [{}])[0].get("ParsedText", "")
            
            bot.edit_message_text("🧠 **Decoding options and finding match...**", chat_id=chat_id, message_id=status_msg.message_id, parse_mode="Markdown")
            
            caption = message.caption or ""
            raw_text = caption + " " + parsed_text
            
            _process_telegram_text(raw_text, chat_id, msg_id, status_msg.message_id)
            
        except Exception as e:
            bot.edit_message_text(f"❌ Bot Error processing image: {str(e)}", chat_id=chat_id, message_id=status_msg.message_id)'''

content = content.replace(old_handle, new_handle)
open('app.py', 'w', encoding='utf-8').write(content)
