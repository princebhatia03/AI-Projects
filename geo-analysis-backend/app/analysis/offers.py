"""Load the static preventive / upsell offer menu for at-risk pincodes."""

from __future__ import annotations

import csv
from pathlib import Path

from app import config


def offers_path() -> Path:
    path = Path(config.OFFERS_PATH)
    if not path.is_absolute():
        path = config.ROOT / path
    return path


def load_offers() -> list[dict]:
    path = offers_path()
    if not path.exists():
        raise FileNotFoundError(f"Offers file not found: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    offers = []
    for row in rows:
        tags = [part.strip() for part in (row.get("addresses_patterns") or "").split("|") if part.strip()]
        offers.append({
            "offer_id": row["offer_id"].strip(),
            "name": row["name"].strip(),
            "description": (row.get("description") or "").strip(),
            "addresses_patterns": tags,
            "channel": (row.get("channel") or "").strip(),
            "priority": int(row.get("priority") or 99),
        })
    return offers


def offer_ids(offers: list[dict] | None = None) -> set[str]:
    return {item["offer_id"] for item in (offers or load_offers())}


def _score_offer(offer: dict, needles: set[str]) -> tuple[int, int, list[str]]:
    """Return (match_score, sort_rank, matched_pattern_labels)."""
    tags = {tag.lower() for tag in offer.get("addresses_patterns") or []}
    exact_hits = needles & tags
    exact = len(exact_hits)
    fuzzy_hits: list[str] = []
    fuzzy = 0
    if exact == 0:
        for needle in needles:
            for tag in tags:
                if needle in tag or tag in needle:
                    fuzzy += 1
                    fuzzy_hits.append(needle)
                    break
    score = exact * 2 + fuzzy
    sort_rank = score * 100 - int(offer.get("priority") or 99)
    matched = sorted(exact_hits) if exact_hits else sorted(set(fuzzy_hits))
    return score, sort_rank, matched


def match_offers(
    pattern_ids: list[str],
    metric_names: list[str],
    offers: list[dict] | None = None,
) -> list[dict]:
    """All menu offers that match any needle, best match first.

    Each item is the offer dict plus ``match_score`` and ``matched_patterns``.
    """
    menu = offers or load_offers()
    needles = {str(value).lower() for value in pattern_ids + metric_names if value}
    if not needles:
        return []
    scored: list[tuple[int, dict]] = []
    for offer in menu:
        score, sort_rank, matched = _score_offer(offer, needles)
        if score == 0:
            continue
        scored.append((sort_rank, {
            **offer,
            "match_score": score,
            "matched_patterns": matched,
        }))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored]


def match_offer(pattern_ids: list[str], metric_names: list[str], offers: list[dict] | None = None) -> dict | None:
    matches = match_offers(pattern_ids, metric_names, offers=offers)
    if not matches:
        return None
    best = dict(matches[0])
    best.pop("match_score", None)
    best.pop("matched_patterns", None)
    return best


def fallback_offer(profile: dict | None = None, offers: list[dict] | None = None) -> dict | None:
    """Always return a preventive offer when tag matching fails."""
    menu = offers or load_offers()
    if not menu:
        return None
    by_id = {item["offer_id"]: item for item in menu}
    risk = (profile or {}).get("risk_rate")
    risk_mean = (profile or {}).get("risk_score_mean")
    if isinstance(risk, (int, float)) and risk >= 0.25 and "OFF_PREVENT" in by_id:
        return by_id["OFF_PREVENT"]
    if isinstance(risk_mean, (int, float)) and risk_mean >= config.HIGH_RISK_SCORE and "OFF_PREVENT" in by_id:
        return by_id["OFF_PREVENT"]
    for preferred in ("OFF_PREVENT", "OFF_PRICE", "OFF_CONTRACT", "OFF_SUPPORT", "OFF_UNLIM"):
        if preferred in by_id:
            return by_id[preferred]
    return sorted(menu, key=lambda item: int(item.get("priority") or 99))[0]
