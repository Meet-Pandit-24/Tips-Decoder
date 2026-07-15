import sys
content = open('app.py', encoding='utf-8').read()

# Add exch_seg to matches in decode_tip
old_match = '''                  "instrumenttype":      row["instrumenttype"],'''
new_match = '''                  "instrumenttype":      row["instrumenttype"],
                  "exch_seg":            row["exch_seg"],'''
content = content.replace(old_match, new_match)

open('app.py', 'w', encoding='utf-8').write(content)
