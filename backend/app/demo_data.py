"""Deterministic synthetic demo dataset (Sample data — illustrative only).

The generator produces a *raw*, Zomato-style messy CSV (ratings like "4.1/5",
costs like "1,200", Yes/No flags) so the cleaning pipeline has real work to do:
~8% unrated rows, ~3% duplicate listings and a handful of invalid values.

All names are fictional. Bangalore locations are used ONLY for this demo and are
never assumed for uploaded datasets.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd

SEED = 42
N_BASE = 780  # unique listings before duplicates are injected (~800 rows total)

LOCATIONS = {
    "Koramangala 5th Block": 10, "Indiranagar": 10, "HSR": 9, "BTM": 9, "Whitefield": 8,
    "Jayanagar": 8, "Marathahalli": 7, "Electronic City": 6, "Bellandur": 7, "JP Nagar": 7,
    "Church Street": 6, "MG Road": 6, "Brigade Road": 6, "Malleshwaram": 5, "Banashankari": 5,
    "Koramangala 6th Block": 7, "Sarjapur Road": 6, "Residency Road": 4, "Basavanagudi": 4,
    "Frazer Town": 4, "Ulsoor": 4, "Rajajinagar": 4, "Kalyan Nagar": 4, "Yelahanka": 3,
    "Hebbal": 4, "New BEL Road": 3,
}
PREMIUM_LOCATIONS = {"Indiranagar", "Koramangala 5th Block", "Koramangala 6th Block", "Church Street", "MG Road"}

CUISINES = {
    "North Indian": 14, "South Indian": 10, "Chinese": 11, "Biryani": 8, "Fast Food": 8, "Cafe": 7,
    "Italian": 5, "Continental": 6, "Desserts": 7, "Beverages": 7, "Street Food": 4, "Andhra": 4,
    "Kerala": 3, "Mughlai": 4, "Pizza": 4, "Burger": 4, "Asian": 3, "Thai": 2, "Mexican": 2,
    "Healthy Food": 2, "Bakery": 3, "Seafood": 3, "Arabian": 2, "Japanese": 1,
}

# (weight, cost range for two in INR, rating shift)
REST_TYPES = {
    "Quick Bites": (30, (150, 400), -0.10),
    "Casual Dining": (26, (400, 1200), 0.00),
    "Cafe": (10, (300, 800), 0.05),
    "Delivery": (9, (200, 500), -0.15),
    "Dessert Parlor": (5, (150, 450), 0.10),
    "Bar": (4, (700, 1800), 0.05),
    "Pub": (4, (800, 1800), 0.10),
    "Takeaway": (5, (150, 400), -0.10),
    "Bakery": (4, (150, 500), 0.00),
    "Fine Dining": (3, (1500, 3500), 0.20),
}

NAME_FIRST = ["Spice", "Saffron", "Copper", "Masala", "Tandoor", "Coastal", "Green", "Urban", "Royal",
              "Little", "Golden", "Banyan", "Monsoon", "Curry", "Bamboo", "Olive", "Pepper", "Cardamom",
              "Tamarind", "Lotus", "Clove", "Mango", "Ember", "Jasmine", "Nilgiri", "Cinnamon"]
NAME_SECOND = ["Kitchen", "House", "Table", "Bistro", "Cafe", "Diner", "Grill", "Corner", "Junction",
               "Garden", "Bowl", "Oven", "Express", "Eatery", "Pantry", "Courtyard", "Social", "Tiffins"]
STREETS = ["1st Main", "2nd Cross", "80 Feet Road", "100 Feet Road", "4th Cross", "Service Road",
           "12th Main", "Outer Ring Road", "17th Cross", "5th Main", "Double Road", "Park Street"]
DISHES = ["Paneer Tikka", "Masala Dosa", "Hakka Noodles", "Chicken Biryani", "Cold Coffee", "Momos",
          "Filter Coffee", "Butter Chicken", "Pasta", "Brownie", "Fish Curry", "Falafel Wrap"]


def _weighted_choice(rng: np.random.Generator, options: dict, size: int | None = None):
    keys = list(options)
    weights = np.array([v[0] if isinstance(v, tuple) else v for v in options.values()], dtype=float)
    return rng.choice(keys, size=size, p=weights / weights.sum())


def _fmt_cost(value: float) -> str:
    return f"{int(value):,}"


def generate_demo_dataframe() -> pd.DataFrame:
    """Return the raw demo dataframe. Same seed -> identical output every time."""
    rng = np.random.default_rng(SEED)
    rows = []
    cuisine_keys = list(CUISINES)
    cuisine_p = np.array(list(CUISINES.values()), dtype=float)
    cuisine_p /= cuisine_p.sum()

    for _ in range(N_BASE):
        loc = str(_weighted_choice(rng, LOCATIONS))
        rtype = str(_weighted_choice(rng, REST_TYPES))
        _, (lo, hi), shift = REST_TYPES[rtype]
        cost = rng.uniform(lo, hi)
        if loc in PREMIUM_LOCATIONS:
            cost *= rng.uniform(1.20, 1.30)
        cost = round(cost / 50) * 50

        n_cuisines = int(rng.choice([1, 2, 3], p=[0.35, 0.40, 0.25]))
        cuisines = list(dict.fromkeys(rng.choice(cuisine_keys, size=n_cuisines, p=cuisine_p)))

        votes = int(np.round(rng.lognormal(mean=3.6, sigma=1.55)))
        rating = rng.normal(3.88 + shift, 0.32) + 0.06 * np.log10(votes + 1)
        rating = float(np.clip(np.round(rating, 1), 2.8, 4.8))

        online = rng.random() < (0.72 if rtype in {"Quick Bites", "Delivery", "Cafe", "Takeaway"} else 0.45)
        booking = rng.random() < (0.65 if rtype in {"Casual Dining", "Fine Dining", "Bar", "Pub"} else 0.04)

        name = f"{rng.choice(NAME_FIRST)} {rng.choice(NAME_SECOND)}"
        address = f"{int(rng.integers(1, 400))}, {rng.choice(STREETS)}, {loc}, Bangalore"

        rate_str = f"{rating}/5"
        unrated = rng.random() < 0.08
        if unrated:
            rate_str = str(rng.choice(["NEW", "-", ""], p=[0.6, 0.25, 0.15]))
            votes = int(rng.integers(0, 4))

        rows.append({
            "name": name,
            "address": address,
            "location": loc,
            "rest_type": rtype,
            "cuisines": ", ".join(cuisines),
            "rate": rate_str,
            "votes": str(votes),
            "approx_cost(for two people)": "" if rng.random() < 0.02 else _fmt_cost(cost),
            "online_order": "" if rng.random() < 0.01 else ("Yes" if online else "No"),
            "book_table": "" if rng.random() < 0.01 else ("Yes" if booking else "No"),
            "dish_liked": ", ".join(rng.choice(DISHES, size=2, replace=False)),
        })

    # A few invalid values to exercise rule 6 (out-of-range rating, negative votes/cost).
    for idx, field, value in [(37, "rate", "6.2/5"), (151, "rate", "-1/5"), (233, "votes", "-12"),
                              (402, "approx_cost(for two people)", "-300"), (515, "votes", "-5"),
                              (688, "rate", "7.5/5")]:
        rows[idx][field] = value

    # A cost outlier the IQR rule should flag but not delete.
    rows[90]["approx_cost(for two people)"] = "9,500"

    # ~3% duplicates: re-listings with case/whitespace noise and fewer votes.
    dup_sources = rng.choice(N_BASE, size=24, replace=False)
    dups = []
    for src in sorted(int(s) for s in dup_sources):
        d = dict(rows[src])
        d["name"] = f"  {d['name'].upper()} " if src % 2 else d["name"].lower()
        try:
            d["votes"] = str(max(0, int(d["votes"]) // 2))
        except ValueError:
            pass
        dups.append(d)
    positions = rng.choice(N_BASE, size=len(dups), replace=False)
    for pos, d in sorted(zip(positions, dups), key=lambda t: -int(t[0])):
        rows.insert(int(pos), d)

    return pd.DataFrame(rows)


def demo_csv_bytes() -> bytes:
    buf = io.StringIO()
    generate_demo_dataframe().to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


DEMO_MAPPING = {
    "name": "restaurant_name",
    "address": "address",
    "location": "locality",
    "rest_type": "restaurant_type",
    "cuisines": "cuisines",
    "rate": "rating",
    "votes": "review_count",
    "approx_cost(for two people)": "cost",
    "online_order": "online_order",
    "book_table": "table_booking",
    "dish_liked": "menu_items",
}
