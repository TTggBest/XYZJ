"""The strategy YAML accepts both standard Markdown fenced-code markers."""
import re


def strategy_yaml_block(text):
    return re.search(r'^(?P<fence>```|~~~)(?:yaml|yml)[ \t]*\r?\n(?P<body>.*?)^(?P=fence)[ \t]*\r?$',
                     text,re.MULTILINE|re.DOTALL|re.IGNORECASE)
