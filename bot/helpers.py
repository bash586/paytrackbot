from functools import reduce
import re
from typing import List
from config import *

def normalize_phone(phone: str) -> str:
    """Convert phone number to digits only(Remove all non-digits)"""
    digits = re.sub(r"\D", "", phone)
    return digits

def is_valid_phone(
    number: str,
    pattern: str = DEFAULT_PHONE_PATTERN,
    ) -> bool:
    """Return True if the number matches a local/national phone format."""
    return re.match(pattern, number.strip()) is not None

def is_valid_name(
    name: str,
    pattern: str = DEFAULT_NAME_PATTERN
) -> bool:
    """
    Return True if the name includes:
    - first and last name (required)
    - middle name (optional)
    - Maximum length: 30 characters
    """
    return re.match(pattern, name.strip()) is not None

def normalize_name(name: str) -> str:
    return name.strip().lower()

def normalize_fullname(
    name: str
) -> str:
    """return fullname"""
    name_parts = re.split(r"\s+", name)
    first, last = normalize_name(name_parts[0]), normalize_name(name_parts[-1])
    middle = ' '.join(normalize_name(p) for p in name_parts[1:-1])

    return f"{first} {middle + ' ' if len(middle)>0 else ''}{last}"

def get_args(msg_txt: str) -> List[str]:
    try:
        args_txt = msg_txt.split(" ", maxsplit=1)[1].strip('|') # discard command part
    except IndexError:
        args_txt = ""
    args = args_txt.split("|") # "|" is args delimeter
    refined_args = filter(lambda arg: len(arg) > 0 ,map(lambda item: item.strip(), args)) # remove unwanted spaces and empty arguments
    return list(refined_args)