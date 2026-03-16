# Multi-Portal Job Scraper & RAG Data Pipeline

A high-performance, modular tool designed to scrape job listings from major tech career portals and transform them into a standardized, **RAG-ready (Retrieval-Augmented Generation)** data format. Supports saving to **local PostgreSQL** or **Supabase** (cloud PostgreSQL).

## Supported Portals

| Portal | Key | Scraping Method |
| :--- | :--- | :--- |
| Meta | `meta` | JSON-LD parsing |
| Google | `google` | Public API |
| Amazon | `amazon` | Public API |
| NVIDIA | `nvidia` | Eightfold.ai API |
| Apple | `apple` | Global internal API |
| OpenAI | `openai` | Greenhouse API |
| Microsoft | `microsoft` | Public API |
| Netflix | `netflix` | Eightfold.ai API |

## Key Features

- **Universal RAG Schema**: Automatically transforms messy career portal data into a clean, granular `snake_case` JSON structure optimized for LLMs.
- **Data Contract Enforcement**: Uses **Pydantic** models to validate every scraped job against a strict data contract.
- **Smart Heuristics**: Auto-detects `work_mode` (Remote/Hybrid/Onsite), `travel_requirements`, and `language_requirements` from unstructured text.
- **Multi-Format Export**: Saves data in CSV, XLSX, ODS, and standardized JSON (Schema.org & RAG-Ready).
- **Database Sync**: Incremental upsert to PostgreSQL (local or Supabase) with soft-delete for closed jobs.
- **Dual Environment Support**: `--env LOCAL` for local PostgreSQL, `--env PROD` for Supabase cloud database.
- **Concurrency Control**: Asynchronous scraping with Playwright and semaphores for high throughput without getting blocked.

## Project Structure

```
job-portal-scrapper/
├── main.py              # Main CLI entry point
├── base_scraper.py      # Core logic, heuristics, and base class
├── db.py                # Database layer (local PostgreSQL + Supabase)
├── job_models.py        # Pydantic models for data contract enforcement
├── common_job_posting_contract.json # Formal JSON Schema specification
├── transform_to_rag.py  # Utility to transform existing CSVs to RAG format
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variables template
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

---

## Getting Started

### 1. Clone the Repository

```bash
git clone git@github.com:techiemmk/job-portal-scrapper.git
cd job-portal-scrapper
```

### 2. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate     # macOS/Linux
# venv\Scripts\activate      # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright Browsers

```bash
playwright install chromium
```

### 5. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your database credentials:

```env
# ── Local PostgreSQL (used with --env LOCAL or no --env flag) ──
DB_HOST=localhost
DB_PORT=5432
DB_NAME=job_scraper
DB_USER=postgres
DB_PASSWORD=postgres

# ── Supabase PostgreSQL (used with --env PROD) ──
# Get from: Supabase Dashboard → Settings → Database → Connection string (URI)
SUPABASE_DB_URL=postgresql://postgres.your-project-ref:your-password@aws-0-region.pooler.supabase.com:6543/postgres
```

---

## Usage

### Quick Start — Scrape & Save to Files Only

```bash
python main.py --portal meta --max_pages 2
```

This scrapes Meta jobs and saves them as CSV, XLSX, ODS, and RAG JSON files in the `data/` folder.

### Save to Local PostgreSQL

```bash
python main.py --portal meta --save-to-db
```

### Save to Supabase (Production)

```bash
python main.py --portal meta --env PROD
```

> **Note:** `--env PROD` automatically implies `--save-to-db`. It connects to Supabase using the `SUPABASE_DB_URL` from your `.env` file.

### Save to Database Only (Skip File Exports)

```bash
python main.py --portal meta --env PROD --db-only
```

### Scrape All Companies to Supabase

```bash
# Scrape all 8 portals and save to Supabase
python main.py --portal meta      --env PROD --db-only
python main.py --portal google    --env PROD --db-only
python main.py --portal amazon    --env PROD --db-only
python main.py --portal nvidia    --env PROD --db-only
python main.py --portal apple     --env PROD --db-only
python main.py --portal openai    --env PROD --db-only
python main.py --portal microsoft --env PROD --db-only
python main.py --portal netflix   --env PROD --db-only
```

Or with page limits for a faster run:

```bash
python main.py --portal meta      --env PROD --db-only --max_pages 3
python main.py --portal google    --env PROD --db-only --max_pages 3
python main.py --portal amazon    --env PROD --db-only --max_pages 3
python main.py --portal nvidia    --env PROD --db-only --max_pages 3
python main.py --portal apple     --env PROD --db-only --max_pages 3
python main.py --portal openai    --env PROD --db-only --max_pages 3
python main.py --portal microsoft --env PROD --db-only --max_pages 3
python main.py --portal netflix   --env PROD --db-only --max_pages 3
```

---

## CLI Reference

```
python main.py [OPTIONS]
```

| Flag | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--portal` | choice | `meta` | Portal to scrape: `meta`, `google`, `amazon`, `nvidia`, `apple`, `openai`, `microsoft`, `netflix` |
| `--max_pages` | int | all | Maximum number of pages to scrape |
| `--concurrency` | int | `5` | Number of concurrent browser pages |
| `--save-to-db` | flag | off | Save scraped jobs to PostgreSQL database |
| `--db-only` | flag | off | Save to database only, skip file exports (implies `--save-to-db`) |
| `--env` | choice | `LOCAL` | Database environment: `LOCAL` (local PostgreSQL) or `PROD` (Supabase) |

---

## Database

### Schema

The scraper creates two tables automatically on first run:

- **`jobs`** — Active job listings with full details, salary parsing, keywords, and metadata
- **`closed_jobs`** — Archived jobs that are no longer listed

### Sync Behavior

Each run performs an **incremental sync** for the given portal:

1. **New jobs** → Inserted with a UUID primary key
2. **Existing jobs** → Updated with latest content + `last_ingested_at` timestamp
3. **Missing jobs** → Soft-deleted (`is_active = false`, `closed_at = NOW()`)

Jobs are identified by `platform` + `source_job_id` (extracted from the job URL).

---

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

### Retroactive RAG Transformation

If you already have CSV data and want to generate the latest RAG-ready JSON:
```bash
python transform_to_rag.py
```

---

## Contributing

To add a new portal:
1. Create a new file in `scrapers/` (e.g., `scrapers/newportal.py`).
2. Subclass `BaseJobScraper`.
3. Implement the `run()` and `scrape_job_details()` methods.
4. Use `self.translate_to_rag_schema(job)` to ensure your data fits the contract.
5. Add the portal to `PORTAL_MAP` in `main.py`.
