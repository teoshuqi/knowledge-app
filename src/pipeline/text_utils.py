"""Simhash for near-duplicate title detection (repost dedup, §10.3). Self-contained:
stdlib hashlib only, no dependency for ~20 lines of bit manipulation.
"""

import hashlib


def simhash(text: str, shingle_size: int = 3) -> int:
    words = text.lower().split()
    shingles = [
        " ".join(words[i : i + shingle_size])
        for i in range(max(len(words) - shingle_size + 1, 1))
    ]
    if not shingles:
        shingles = [text.lower()]

    bit_weights = [0] * 64
    for shingle in shingles:
        h = int(hashlib.blake2b(shingle.encode(), digest_size=8).hexdigest(), 16)
        for bit in range(64):
            bit_weights[bit] += 1 if (h >> bit) & 1 else -1

    fingerprint = 0
    for bit in range(64):
        if bit_weights[bit] > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def title_simhash(title: str, body_fallback: str = "") -> int:
    """Falls back to the first ~100 chars of body when the title itself is
    too short to shingle meaningfully (§10.3) — "Update" or "New Release"
    carries no signal on its own.
    """
    text = title if len(title.split()) >= 3 else f"{title} {body_fallback[:100]}"
    return simhash(text)
