"""
Example: Use a completely custom schema to scrape anything.

This example shows how to define your own extraction fields
without using any predefined schema.

Usage:
    python examples/custom_schema.py
"""

from ai_scraper import AIScraper

API_KEY = "YOUR_OPENROUTER_API_KEY"


def main():
    # Define your own schema — just a dict of field_name: description
    my_schema = {
        "university_name": "Name of the university",
        "ranking": "Global or national ranking position",
        "country": "Country where the university is located",
        "tuition_fee": "Annual tuition fee with currency",
        "notable_programs": "Top 3 programs or departments",
        "website": "University website URL",
    }

    with AIScraper(
        provider="openrouter",
        api_key=API_KEY,
        model="google/gemini-2.5-flash",
    ) as scraper:
        results = scraper.scrape(
            url="https://www.topuniversities.com/university-rankings/world-university-rankings/2025",
            schema=my_schema,
            instructions="Extract the top 20 universities from the ranking table.",
        )

        print(f"\n🎓 Found {len(results)} universities\n")
        for uni in results:
            print(f"  #{uni.get('ranking', '?')} {uni.get('university_name', 'N/A')}")
            print(
                f"     📍 {uni.get('country', 'N/A')} | 💰 {uni.get('tuition_fee', 'N/A')}"
            )
            print(f"     🏆 {uni.get('notable_programs', 'N/A')}")
            print()

        scraper.save_json(results, "output/universities.json")


if __name__ == "__main__":
    main()
