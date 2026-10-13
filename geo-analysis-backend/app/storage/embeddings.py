import math

from app.config import EMBED_DIM


def embed(text: str) -> list[float]:
    vector = [0.0] * EMBED_DIM
    tokens = [token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if token]
    if not tokens:
        return vector
    for token in tokens:
        digest = 0
        for char in token:
            digest = (digest * 33 + ord(char)) % (2**32)
        index = digest % EMBED_DIM
        sign = 1.0 if (digest >> 8) & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
