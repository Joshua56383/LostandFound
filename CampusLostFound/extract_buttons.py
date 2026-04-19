import os
import re
from html.parser import HTMLParser

class ButtonParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_button = False
        self.buttons = set()
        self.current_data = []

    def handle_starttag(self, tag, attrs):
        if tag == 'button':
            self.in_button = True
            self.current_data = []
        elif tag == 'a':
            # check if class contains 'btn'
            for attr in attrs:
                if attr[0] == 'class' and 'btn' in attr[1]:
                    self.in_button = True
                    self.current_data = []
                    break

    def handle_endtag(self, tag):
        if self.in_button and tag in ['button', 'a']:
            self.in_button = False
            text = ' '.join(self.current_data).strip()
            clean_text = re.sub(r'[^a-zA-Z0-9\s]', '', text).strip()
            if clean_text:
                self.buttons.add(clean_text)

    def handle_data(self, data):
        if self.in_button:
            self.current_data.append(data)

template_dir = r"c:\Users\AnaLian\Desktop\LostAndFoundProject\CampusLostFound\templates"
parser = ButtonParser()

for root, _, files in os.walk(template_dir):
    for file in files:
        if file.endswith(".html"):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                parser.feed(f.read())

with open('button_names.txt', 'w') as out:
    for name in sorted(list(parser.buttons)):
        out.write(name + '\n')
