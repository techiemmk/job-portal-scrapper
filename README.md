# Multi-Portal Job Scraper & RAG Data Pipeline

A high-performance, modular tool designed to scrape job listings from major tech career portals (Apple, Meta, Google, Amazon, NVIDIA, Microsoft, Netflix, OpenAI) and transform them into a standardized, **RAG-ready (Retrieval-Augmented Generation)** data format.

## Key Features

- **Universal RAG Schema**: Automatically transforms messy career portal data into a clean, granular `snake_case` JSON structure optimized for LLMs.
- **Data Contract Enforcement**: Uses **Pydantic** models to validate every scraped job against a strict data contract.
- **Smart Heuristics**: Auto-detects `work_mode` (Remote/Hybrid/Onsite), `travel_requirements`, and `language_requirements` from unstructured text.
- **Multi-Format Export**: Saves data in CSV, XLSX, ODS, and standardized JSON (Schema.org & RAG-Ready).
- **Concurrency Control**: Asynchronous scraping with Playwright and semaphores for high throughput without getting blocked.
- **Global Scope**: Specialized logic for global search (e.g., Apple's global internal API, Microsoft's global career API).

## Project Structure

```
job-portal-scrapper/
├── main.py              # Main CLI entry point
├── base_scraper.py      # Core logic, heuristics, and base class
├── job_models.py        # Pydantic models for data contract enforcement
├── common_job_posting_contract.json # Formal JSON Schema specification
├── transform_to_rag.py  # Utility to transform existing CSVs to RAG format
├── requirements.txt     # Python dependencies
├── scrapers/            # Portal-specific scraper modules
│   ├── apple.py         # Apple Jobs Scraper (Global API)
│   ├── meta.py          # Meta Careers Scraper (JSON-LD parsing)
│   ├── google.py        # Google Careers Scraper (Public API)
│   ├── nvidia.py        # NVIDIA Scraper (Eightfold.ai API)
│   ├── amazon.py        # Amazon Jobs Scraper (Public API)
│   ├── microsoft.py     # Microsoft Careers Scraper (Public API)
│   ├── netflix.py       # Netflix Careers Scraper (Eightfold.ai API)
│   └── openai.py        # OpenAI Careers Scraper (Greenhouse API)
└── data/                # [Ignored] Output folder for scraped files
```

## Setup

1. **Create a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

## Usage

### Scraping Jobs
Run the scraper using `main.py`. It will automatically save data in all supported formats.

```bash
# Scrape Apple Careers (Global)
python main.py --portal apple --max_pages 5 --concurrency 10

# Scrape Microsoft Careers
python main.py --portal microsoft --max_pages 3

# Scrape Netflix Careers
python main.py --portal netflix --max_pages 2

# Scrape Meta Careers
python main.py --portal meta --concurrency 15
```

### Retroactive RAG Transformation
If you already have CSV data and want to generate the latest RAG-ready JSON:
```bash
python transform_to_rag.py
```

## Data Contract (RAG Schema)

The tool enforces a strict schema for every job posting:

| Section | Description |
| :--- | :--- |
| **metadata** | IDs, Titles, Links, and standardized timestamps. |
| **logistics** | `work_mode` (Remote/Local), `job_locations` (list), and travel info. |
| **role_details** | Granular splitting of Minimum/Preferred qualifications and responsibilities. |
| **compensation** | Salary ranges and detailed benefit prose. |
| **legal** | EEO statements and company backgrounds. |

See `common_job_posting_contract.json` for the full technical specification.

## Contributing

To add a new portal:
1. Subclass `BaseJobScraper`.
2. Implement the `run()` and `scrape_job_details()` methods.
3. Use `self.translate_to_rag_schema(job)` to ensure your data fits the contract.
