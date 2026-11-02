"""Registration-number normalisation, validation and fuzzy comparison."""
import re

# Characters OCR engines commonly confuse. Folding both sides to the same
# canonical symbol lets "MH12AB1234" match "MH12A81234".
_CONFUSION = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7"})


def normalize_plate(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
    return cleaned or None


def is_valid_plate(plate: str | None, min_len: int = 4, max_len: int = 12, regex: str = "") -> bool:
    if not plate:
        return False
    if not (min_len <= len(plate) <= max_len):
        return False
    if not (any(c.isdigit() for c in plate) and any(c.isalpha() for c in plate)):
        return False
    if regex:
        try:
            return re.fullmatch(regex, plate) is not None
        except re.error:
            return True
    return True


def fold(plate: str) -> str:
    return plate.translate(_CONFUSION)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def plate_distance(a: str, b: str) -> int:
    """Edit distance after folding OCR-confusable characters."""
    return levenshtein(fold(a), fold(b))
