"""Canonical data model and API request/response schemas.

The canonical model is deliberately flexible: every field is optional. An uploaded
file is mapped onto these fields by the user (with suggestions from
``ingest.suggest_mapping``); anything left unmapped is preserved as an extra column.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Canonical fields
# ---------------------------------------------------------------------------
# kind controls how cleaning.py parses the source column:
#   text      -> trimmed string
#   list      -> comma/pipe/semicolon separated, trimmed, title-cased list
#   rating    -> numeric rating, "4.1/5" style strings supported, scale metadata kept
#   count     -> non-negative number (review counts / votes)
#   money     -> non-negative number, "1,200" / "Rs. 450" style strings supported
#   bool      -> Yes/No style values, unknown stays null
#   float     -> plain number (coordinates)
#   date      -> parsed date, invalid stays null
CANONICAL_FIELDS: dict[str, dict] = {
    "restaurant_name": {"kind": "text", "label": "Restaurant name",
                        "synonyms": ["name", "restaurant_name", "restaurant", "res_name", "business_name", "title", "outlet_name", "restaurant_title"]},
    "address": {"kind": "text", "label": "Address",
                "synonyms": ["address", "full_address", "street_address", "addr", "street"]},
    "locality": {"kind": "text", "label": "Locality / neighborhood",
                 "synonyms": ["location", "locality", "neighborhood", "neighbourhood", "area", "suburb", "locality_verbose", "listed_in_city", "zone", "district"]},
    "city": {"kind": "text", "label": "City",
             "synonyms": ["city", "town", "municipality"]},
    "region": {"kind": "text", "label": "Region / state",
               "synonyms": ["state", "region", "province", "county"]},
    "country": {"kind": "text", "label": "Country",
                "synonyms": ["country", "country_name", "nation"]},
    "cuisines": {"kind": "list", "label": "Cuisines",
                 "synonyms": ["cuisines", "cuisine", "cuisine_type", "food_type", "cuisine_types"]},
    "restaurant_type": {"kind": "list", "label": "Restaurant type / category",
                        "synonyms": ["rest_type", "restaurant_type", "type", "category", "categories", "establishment", "establishment_type", "listed_in_type"]},
    "rating": {"kind": "rating", "label": "Rating",
               "synonyms": ["rate", "rating", "ratings", "aggregate_rating", "stars", "star_rating", "score", "avg_rating", "average_rating", "user_rating"]},
    "review_count": {"kind": "count", "label": "Review count / votes",
                     "synonyms": ["votes", "vote_count", "review_count", "reviews_count", "num_reviews", "number_of_reviews", "rating_count", "total_reviews", "user_ratings_total"]},
    "cost": {"kind": "money", "label": "Cost / price",
             "synonyms": ["approx_cost_for_two_people", "average_cost_for_two", "cost_for_two", "cost", "price", "avg_cost", "average_cost", "cost_for_one", "price_for_two", "approx_cost"]},
    "currency": {"kind": "text", "label": "Currency",
                 "synonyms": ["currency", "currency_code", "curr"]},
    "online_order": {"kind": "bool", "label": "Online ordering / delivery",
                     "synonyms": ["online_order", "has_online_delivery", "online_delivery", "delivery", "offers_delivery", "is_delivering_now", "online_ordering"]},
    "table_booking": {"kind": "bool", "label": "Table booking / reservations",
                      "synonyms": ["book_table", "has_table_booking", "table_booking", "reservations", "reservation", "takes_reservations"]},
    "latitude": {"kind": "float", "label": "Latitude", "synonyms": ["latitude", "lat"]},
    "longitude": {"kind": "float", "label": "Longitude", "synonyms": ["longitude", "lng", "lon", "long"]},
    "review_text": {"kind": "text", "label": "Review text",
                    "synonyms": ["reviews_list", "review_text", "review", "reviews", "text", "comment"]},
    "menu_items": {"kind": "text", "label": "Menu items",
                   "synonyms": ["menu_item", "menu_items", "menu", "dish_liked", "dishes"]},
    "opening_hours": {"kind": "text", "label": "Opening hours",
                      "synonyms": ["opening_hours", "hours", "timings", "open_hours", "working_hours"]},
    "source_date": {"kind": "date", "label": "Listing / source date",
                    "synonyms": ["date", "listing_date", "scraped_at", "source_date", "date_added", "created_at"]},
}

# Fields that must not be compared without a matching unit/currency context.
PRICE_UNITS = ["for_two", "per_person", "menu_item", "price_tier", "unknown"]


class MappingEntry(BaseModel):
    source_column: str
    canonical_field: Optional[str] = None  # None = leave unmapped (column is preserved)


class ImportSettings(BaseModel):
    """User-confirmed settings that make an import reproducible."""
    mapping: list[MappingEntry]
    dataset_name: Optional[str] = None
    rating_scale_max: Optional[float] = Field(default=None, gt=0, description="Source rating scale maximum (e.g. 5, 10, 100). None = auto-detect.")
    rating_scale_min: float = 0.0
    currency: Optional[str] = Field(default=None, description="Dataset-level currency when no currency column is mapped.")
    price_unit: Literal["for_two", "per_person", "menu_item", "price_tier", "unknown"] = "unknown"


class ActiveDatasetRequest(BaseModel):
    dataset_id: str


class SettingsUpdate(BaseModel):
    min_group_n: Optional[int] = Field(default=None, ge=2, le=1000)
    opportunity_min_n: Optional[int] = Field(default=None, ge=2, le=1000)
    bayes_m_override: Optional[float] = Field(default=None, ge=0)
    clear_bayes_m_override: bool = False


class SqlRequest(BaseModel):
    sql: str = Field(max_length=20000)
    dataset_id: Optional[str] = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    dataset_id: Optional[str] = None
    location: Optional[str] = None


class CompareRequest(BaseModel):
    dataset_id: Optional[str] = None
    kind: Literal["restaurant", "cuisine", "location"]
    items: list[str] = Field(min_length=2, max_length=4)


class ReportRequest(BaseModel):
    dataset_id: Optional[str] = None
    report_type: Literal["market_overview", "cuisine", "location", "comparison"] = "market_overview"
    length: Literal["executive", "detailed"] = "executive"
    use_filters: bool = False
    filters: dict = Field(default_factory=dict)
    focus: Optional[str] = None  # cuisine or location name for focused reports
    compare_kind: Optional[Literal["restaurant", "cuisine", "location"]] = None
    compare_items: list[str] = Field(default_factory=list)
