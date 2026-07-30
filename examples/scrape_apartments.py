"""
Example: Scrape apartment listings from any website.

Usage:
    python examples/scrape_apartments.py
"""

from ai_scraper import AIScraper, Schema

# Configure your API key
API_KEY = "YOUR_OPENROUTER_API_KEY"

# URLs to scrape (works with ANY real estate website)
URLS = [
    "https://www.immowelt.de/liste/berlin/wohnungen/mieten",
    # "https://www.rightmove.co.uk/property-to-rent/find.html?searchLocation=London",
    # "https://www.idealista.com/en/alquiler-viviendas/madrid-madrid/",
]


def main():
    with AIScraper(
        provider="openrouter",
        api_key=API_KEY,
        model="google/gemini-2.5-flash",
        headless=True,
    ) as scraper:
        for url in URLS:
            print(f"\n🏠 Scraping: {url}")
            print("=" * 60)

            results = scraper.scrape(
                url=url,
                schema=Schema.APARTMENTS,
                instructions="Focus on actual apartment listings only. "
                "Ignore navigation items, ads, and corporate content.",
            )

            for apt in results:
                print(f"  📍 {apt.get('title', 'N/A')}")
                print(
                    f"     💰 {apt.get('price', 'N/A')} | "
                    f"🏠 {apt.get('rooms', '?')} rooms | "
                    f"📐 {apt.get('size', 'N/A')}"
                )
                print(f"     🔗 {apt.get('url', 'N/A')}")
                print()

            # Save results
            scraper.save_json(results, f"output/apartments_{len(results)}.json")


if __name__ == "__main__":
    main()
