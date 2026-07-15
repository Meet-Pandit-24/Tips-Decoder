import sys
content = open('app.py', encoding='utf-8').read()

old_text = '''    text = (
        f"✅ **Tip Decoded Successfully**\\n\\n"
        f"**Symbol:** {best_match['symbol']}\\n"
        f"**Entry Price:** ₹{current_price}\\n"
        f"**Lot Size:** {best_match['lot_size']}\\n"
        f"**Match Quality:** {best_match['match_quality']}"
    )'''

new_text = '''    text = (
        f"✅ **Tip Decoded Successfully**\\n\\n"
        f"**Symbol:** {best_match['symbol']}\\n"
        f"**Entry Price:** ₹{current_price}\\n"
        f"**Lot Size:** {best_match['lot_size']}\\n"
        f"**Match Quality:** {best_match['match_quality']}\\n\\n"
        f"📝 **Raw OCR Log:**\\n"
        f"{raw_text.strip()}"
    )'''

content = content.replace(old_text, new_text)
open('app.py', 'w', encoding='utf-8').write(content)
