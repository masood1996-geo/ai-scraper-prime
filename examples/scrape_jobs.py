"""
Example: Scrape job listings from any job board.

Usage:
    python examples/scrape_jobs.py
"""

from ai_scraper import AIScraper, Schema

API_KEY = "YOUR_OPENROUTER_API_KEY"


def main():
    with AIScraper(
        provider="openrouter",
        api_key=API_KEY,
        model="google/gemini-2.5-flash",
    ) as scraper:
        results = scraper.scrape(
            url="https://www.indeed.com/jobs?q=python+developer&l=remote",
            schema=Schema.JOB_LISTINGS,
            instructions="Extract only actual job postings, not sponsored ads.",
        )

        print(f"\n💼 Found {len(results)} job listings\n")
        for job in results:
            print(f"  📌 {job.get('title', 'N/A')}")
            print(
                f"     🏢 {job.get('company', 'N/A')} | "
                f"📍 {job.get('location', 'N/A')} | "
                f"💰 {job.get('salary', 'N/A')}"
            )
            print()

        scraper.save_csv(results, "output/jobs.csv")


if __name__ == "__main__":
    main()
