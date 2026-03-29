"""
JSON repair for malformed LLM responses.
Local patch (martindecz/PageIndex) — not submitted upstream.

Handles common LLM JSON issues:
- Unescaped double quotes inside string values
- Extra data after valid JSON object/array
- Trailing commas before closing brackets/braces
- Truncated JSON (unclosed strings, arrays, objects)
"""

import json
import re
import logging


def repair_json(text):
    """Attempt to repair malformed JSON from LLM output.

    Returns parsed Python object on success, None on failure.
    """
    if not text or not text.strip():
        return None

    # 1) Try raw_decode — handles "extra data" after valid JSON
    try:
        decoder = json.JSONDecoder()
        result, _ = decoder.raw_decode(text.strip())
        return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 2) Fix invalid unicode escapes (\uXXXX with non-hex chars) and trailing commas
    cleaned = re.sub(r'\\u(?![0-9a-fA-F]{4})[^"]{0,4}', '', text)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    # 3) Fix unescaped quotes inside JSON string values
    repaired = _fix_unescaped_quotes(cleaned)
    if repaired != cleaned:
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            pass

    # 4) Try to close truncated JSON (unclosed strings/brackets)
    closed = _close_truncated(cleaned)
    if closed != cleaned:
        try:
            return json.loads(closed)
        except (json.JSONDecodeError, ValueError):
            pass
        # Also try with unescaped quote fix
        repaired2 = _fix_unescaped_quotes(closed)
        try:
            return json.loads(repaired2)
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _fix_unescaped_quotes(text):
    """Fix unescaped double quotes inside JSON string values.

    Strategy: walk through the string tracking whether we are inside
    a JSON string.  When inside a string, a '"' that is NOT preceded
    by '\\' and is NOT followed by  a structural char ( , : } ] or
    whitespace before one of those) is likely an embedded quote that
    should be escaped.
    """
    # Structural characters that normally follow a closing quote
    struct_after_quote = set(',:}]')

    result = []
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]

        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue

        # Inside a string
        if ch == '\\':
            # Escaped character — keep as-is
            result.append(ch)
            if i + 1 < len(text):
                i += 1
                result.append(text[i])
            i += 1
            continue

        if ch == '"':
            # Is this the real closing quote or an unescaped embed?
            rest = text[i + 1:].lstrip()
            if not rest or rest[0] in struct_after_quote:
                # Legit closing quote
                result.append(ch)
                in_string = False
            else:
                # Embedded quote — escape it
                result.append('\\"')
            i += 1
            continue

        result.append(ch)
        i += 1

    return ''.join(result)


def _close_truncated(text):
    """Try to close truncated JSON by appending missing brackets."""
    text = text.rstrip()

    # Close unclosed string
    quote_count = 0
    escaped = False
    for ch in text:
        if escaped:
            escaped = False
            continue
        if ch == '\\':
            escaped = True
            continue
        if ch == '"':
            quote_count += 1
    if quote_count % 2 != 0:
        text += '"'

    # Close unclosed brackets/braces
    stack = []
    in_str = False
    esc = False
    for ch in text:
        if esc:
            esc = False
            continue
        if ch == '\\' and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in '{[':
            stack.append('}' if ch == '{' else ']')
        elif ch in '}]' and stack:
            stack.pop()

    if stack:
        text += ''.join(reversed(stack))

    return text
