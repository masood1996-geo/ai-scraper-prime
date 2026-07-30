"""
Predefined extraction schemas for common use cases.

Each schema defines the fields the LLM should extract from a webpage.
Users can also define custom schemas as plain dictionaries.
"""

from typing import Any, Dict


class Schema:
    """Predefined extraction schema templates."""

    # ─── Real Estate ──────────────────────────────────────────────────

    APARTMENTS = {
        "title": "Listing title / headline",
        "price": "Monthly rent price with currency",
        "rooms": "Number of rooms",
        "size": "Apartment size in m² or sqft",
        "address": "Full address or neighborhood",
        "url": "Direct link to the listing",
        "image_url": "Main image URL",
        "available_from": "Move-in date if mentioned",
    }

    REAL_ESTATE_AGENTS = {
        "name": "Agent or agency name",
        "phone": "Phone number",
        "email": "Email address",
        "website": "Website URL",
        "address": "Office address",
        "working_hours": "Office hours or availability",
        "specialty": "Area of expertise (e.g., rental, commercial, luxury)",
    }

    # ─── Jobs ─────────────────────────────────────────────────────────

    JOB_LISTINGS = {
        "title": "Job title",
        "company": "Company name",
        "location": "Job location",
        "salary": "Salary range if listed",
        "type": "Full-time, part-time, contract, remote",
        "url": "Link to job posting",
        "posted_date": "When the job was posted",
        "description_summary": "Brief 1-2 sentence summary of the role",
    }

    # ─── E-Commerce ──────────────────────────────────────────────────

    PRODUCTS = {
        "name": "Product name",
        "price": "Current price with currency",
        "original_price": "Original price before discount (if any)",
        "rating": "Star rating (e.g., 4.5/5)",
        "reviews_count": "Number of reviews",
        "url": "Link to the product page",
        "image_url": "Product image URL",
        "in_stock": "Whether the item is in stock (true/false)",
    }

    # ─── News & Articles ─────────────────────────────────────────────

    ARTICLES = {
        "headline": "Article headline",
        "author": "Author name",
        "published_date": "Publication date",
        "summary": "Brief 2-3 sentence summary",
        "url": "Link to the full article",
        "category": "Topic category (politics, tech, sports, etc.)",
    }

    # ─── Social / People ─────────────────────────────────────────────

    PROFILES = {
        "name": "Person's name",
        "title": "Professional title or role",
        "company": "Current company or affiliation",
        "location": "City or country",
        "bio": "Brief bio or description",
        "url": "Profile URL",
    }

    # ─── Events ───────────────────────────────────────────────────────

    EVENTS = {
        "name": "Event name",
        "date": "Event date and time",
        "location": "Venue or address",
        "price": "Ticket price or 'Free'",
        "url": "Event page URL",
        "description": "Brief event description",
    }

    # ─── Restaurant / Reviews ─────────────────────────────────────────

    RESTAURANTS = {
        "name": "Restaurant name",
        "cuisine": "Type of cuisine",
        "rating": "Rating (e.g., 4.5/5)",
        "price_range": "Price level (€, €€, €€€)",
        "address": "Restaurant address",
        "phone": "Phone number",
        "url": "Restaurant page URL",
    }

    # ─── Generic / Custom ────────────────────────────────────────────

    LINKS = {
        "text": "Link text",
        "url": "Link URL",
        "context": "Surrounding text or description",
    }

    CONTACTS = {
        "name": "Person or business name",
        "phone": "Phone number",
        "email": "Email address",
        "address": "Physical address",
        "website": "Website URL",
    }

    @classmethod
    def list_all(cls) -> Dict[str, Dict[str, Any]]:
        """Return all available schema names and their fields."""
        schemas = {}
        for attr_name in dir(cls):
            if (
                attr_name.startswith("_")
                or attr_name == "list_all"
                or callable(getattr(cls, attr_name))
            ):
                continue
            val = getattr(cls, attr_name)
            if isinstance(val, dict):
                schemas[attr_name] = val
        return schemas

    @classmethod
    def get(cls, name: str) -> Dict[str, Any]:
        """Get a schema by name (case-insensitive)."""
        name_upper = name.upper().replace("-", "_").replace(" ", "_")
        schema = getattr(cls, name_upper, None)
        if schema is None:
            available = ", ".join(cls.list_all().keys())
            raise ValueError(f"Unknown schema '{name}'. Available: {available}")
        return schema
