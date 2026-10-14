"""Reuse explicit filename metadata without guessing a publication venue."""
import re
from pathlib import PureWindowsPath

PUBLISHERS = {'ieee', 'iet', 'elsevier', 'springer', 'wiley', 'acm', '非期刊', 'unknown'}


def filename_metadata(paths):
    year = None
    venue = ''
    for path in paths:
        tokens = re.findall(r'\[([^\[\]]+)\]', PureWindowsPath(path).name)
        for index, token in enumerate(tokens):
            token = token.strip()
            if re.fullmatch(r'(?:19|20)\d{2}', token):
                if year is None:
                    year = int(token)
                if index + 1 < len(tokens):
                    candidate = tokens[index + 1].strip()
                    if candidate.casefold() not in PUBLISHERS and not re.fullmatch(r'\d{4}', candidate):
                        venue = venue or candidate.upper()
    if not venue:
        for path in paths:
            leading = re.match(r'^\[([^\[\]]+)\]', PureWindowsPath(path).name)
            if leading and not re.fullmatch(r'\d{4}', leading[1]) and leading[1].casefold() not in PUBLISHERS:
                venue = leading[1].upper()
                break
    return {'year': year, 'venue': venue}
