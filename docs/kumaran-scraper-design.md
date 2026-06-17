# Kumaran Scraper Design Specification

**Date:** 2026-06-18  
**Status:** Approved  
**Approach:** Full Playwright DOM Scraping

---

## 1. Overview

Design and implement a scraper for Kumaran Systems careers portal (`https://careers.kumaran.com/jobs/Careers`) using Playwright to collect and transform job listings into RAG-ready format compatible with the existing job-portal-scrapper infrastructure.

---

## 2. Portal Analysis

### 2.1 Listing Page
- **URL:** `https://careers.kumaran.com/jobs/Careers`
- **Behavior:** All 47 jobs load on first page (no pagination)
- **Filter:** Job Type filter shows breakdown: Contract (1), Full time (46)
- **Job Links:** Each job is clickable and navigates to detail page

### 2.2 Job Detail Page
- **URL Format:** `https://careers.kumaran.com/jobs/Careers/{JOB_ID}/{JOB_SLUG}`
- **Example:** `https://careers.kumaran.com/jobs/Careers/31840000016758226/Java-Backend-Developer?source=CareerSite`
- **Structure:** Single-page layout with header, sidebar metadata, and main content sections
- **Platform:** Zoho Recruit (no JSON-LD structured data available)

### 2.3 Page Sections
1. **Header:** Title, Company, Location, Job Type, Posted Date
2. **Sidebar:** Department, Work Experience, City, State, Country, Postal Code
3. **Main Content:**
   - About Us (company description)
   - Why Kumaran? (company culture)
   - Job Description
   - Requirements (bullet list)
   - Responsibilities (bullet list)
   - Must-Have Skills (categorized: Java, Spring, RESTful, SQL, Microservices)
   - Soft Skills (Problem-Solving, Communication, etc.)
   - Hard Skills (technical skills)
   - EEO Statement

---

## 3. Architecture

### 3.1 Class Structure
```
scrapers/kumaran.py
└── KumaranScraper(BaseJobScraper)
    ├── __init__(concurrency=5)
    ├── run(max_pages=None, start_time=None)
    ├── get_all_job_links(context, max_pages)
    └── scrape_job_details(page, url)
```

### 3.2 Inheritance & Reuse
- **Subclass:** `BaseJobScraper` (from `base_scraper.py`)
- **Inherited Methods:**
  - `scrape_single_job()` - Retry logic, page lifecycle management
  - `translate_to_rag_schema()` - Transform to RAG contract
  - `save_to_formats()` - Export to CSV/XLSX/ODS
  - `save_to_rag_json()` - Export to RAG JSON
  - `save_to_db()` - Database sync
  - Heuristic methods: `detect_work_mode()`, `detect_travel()`, `detect_languages()`
  - Utility methods: `clean_html_field()`, `extract_links_from_field()`

### 3.3 Data Flow
```
1. Initialize KumaranScraper with concurrency=5
2. Open Playwright browser context
3. Collect all job URLs from listing page
4. For each job URL:
   a. Navigate to detail page
   b. Extract data using CSS selectors
   c. Structure into internal job dict
5. Translate to RAG schema (via BaseJobScraper)
6. Save to formats (CSV, XLSX, ODS, RAG JSON)
7. Sync to database (if --save-to-db flag)
8. Close browser
```

---

## 4. Data Extraction & Mapping

### 4.1 Listing Page Extraction
**Method:** `get_all_job_links(context, max_pages)`

Extract job URLs from listing page:
- Use Playwright to navigate to `https://careers.kumaran.com/jobs/Careers`
- Wait for job listings to render
- Use JavaScript `document.querySelectorAll()` to extract all job links
- Return list of job URLs

**CSS Selector Pattern:** TBD (requires inspection of actual DOM)  
**Expected Format:** List of full URLs like `/jobs/Careers/{JOB_ID}/{JOB_SLUG}`

### 4.2 Job Detail Page Extraction
**Method:** `scrape_job_details(page, url)`

Extract fields using CSS selectors or JavaScript evaluation:

| Source Field | DOM Location | Extraction Method | Target Column |
|---|---|---|---|
| Job Title | Header h1 | Text content | `job_name` |
| Company | Header text | Static: "Kumaran Systems" | `about_company` |
| Location | Header + Sidebar | Combine city/state/country | `job_location` |
| Job Type | Header | Text: "Full time" or "Contract" | `job_type` |
| Posted Date | Header text "Posted on DD/MM/YYYY" | Regex extract | `posted_date` |
| Department Name | Sidebar | Text content | `job_department` |
| Work Experience | Sidebar "Work Experience" | Text: "4-5 years" | Part of `min_qualifications` |
| City, State, Country, Postal Code | Sidebar fields | Extract individually | Build `job_location` |
| Job Description | Main content h2 "Job Description" | Following paragraph text | `job_description` |
| Requirements | Bulleted list under "Requirements" | Extract all bullets | Append to `requirements` |
| Responsibilities | Bulleted list under "Responsibilities" | Extract all bullets | `job_responsibilities` |
| Must-Have Skills | Bulleted list under "Must-Have Skills" | Extract all bullets | Append to `requirements` |
| Hard Skills | Bulleted list under "Hard Skills" | Extract all bullets | Part of `requirements` |
| Soft Skills | Bulleted list under "Soft Skills" | Extract all bullets | Append to `min_qualifications` |
| About Company | Section "About Us" | Paragraph text | `about_company` |
| EEO Statement | Bottom section | Full text block | `eeo` |
| Job Link | URL parameter | Current page URL | `job_link` |
| Job ID | URL path | Extract: `/jobs/Careers/{JOB_ID}/` | `job_id` |

### 4.3 Data Consolidation
Combine related fields into database columns:

**`requirements`:**
```
Requirements:
• Bachelor's degree in Computer Science...
• 3-5 years of experience...
[all bullet points]

Must-Have Skills:
• Java Programming: Deep knowledge...
• Spring Framework: Proficient...
[all technical skills]

Hard Skills:
• [hard skills content]
```

**`min_qualifications`:**
```
Experience: 4-5 years

Soft Skills:
• Problem-Solving: Ability to analyze...
• Communication: Ability to clearly...
[all soft skills]
```

**`job_responsibilities`:**
```
• Design, develop, and maintain backend services...
• Collaborate with front-end developers...
[all responsibility bullets]
```

---

## 5. Implementation Details

### 5.1 CSS Selectors
CSS selectors will be determined during implementation by inspecting the actual HTML. Expected patterns:
- Header container: `.cw-job-details-header` or similar
- Sidebar: `.job-info-sidebar`, `.job-metadata`
- Section headings: `h2`, `h3` with specific text
- Bullet lists: `ul > li`, `.requirements-list > li`

### 5.2 Error Handling
- **Retry Logic:** Use inherited `scrape_single_job()` with max_retries=2, exponential backoff
- **Missing Fields:** Graceful fallback to empty strings (BaseJobScraper default)
- **Pagination:** Not needed (all jobs on first page)
- **Batch Processing:** Use inherited `scrape_jobs_in_batches()` with save_interval=50

### 5.3 Concurrency Control
- **Semaphore:** Control concurrent page loads (default: 5)
- **Batch Delays:** Stagger requests to avoid blocking
- **Cooldown:** Extended cooldown every 100 batches (inherited behavior)

### 5.4 Integration with Main CLI
Add to `main.py`:
```python
from scrapers.kumaran import KumaranScraper

PORTAL_MAP = {
    ...
    "kumaran": ("Kumaran Systems", KumaranScraper),
}
```

Usage:
```bash
python main.py --portal kumaran --env PROD --db-only
```

---

## 6. Database Sync

### 6.1 Source Job ID Extraction
Pattern for Kumaran URLs:
```
URL: https://careers.kumaran.com/jobs/Careers/31840000016758226/Java-Backend-Developer
Extract: 31840000016758226
Regex: r'/jobs/Careers/(\d+)'
```

Add to `db.py` `extract_source_job_id()` function:
```python
patterns = {
    ...
    "kumaran": r'/jobs/Careers/(\d+)',
    ...
}
```

### 6.2 Sync Behavior
- **Incremental upsert:** Insert new, update changed, soft-delete missing
- **Unique key:** `(platform='kumaran', source_job_id)`
- **Batch commits:** Every 50 jobs (inherited)

---

## 7. Testing Strategy

### 7.1 Unit Testing
- Test CSS selector accuracy on sample pages
- Test data extraction for all fields
- Test data consolidation (requirements, min_qualifications combining)
- Test RAG schema translation

### 7.2 Integration Testing
- Full scrape of listing page → detail pages → database
- Verify all 47 jobs scraped successfully
- Verify database records created/updated correctly
- Check RAG JSON output format

### 7.3 Edge Cases
- Jobs with missing optional fields (e.g., no posted date)
- Skill sections with varying formats
- Special characters in job descriptions
- Very long requirement lists

---

## 8. Success Criteria

✅ All 47 Kumaran jobs successfully scraped  
✅ All required fields extracted and mapped correctly  
✅ Data stored in database with correct platform + source_job_id  
✅ RAG JSON output validates against Pydantic schema  
✅ CSV/XLSX/ODS exports contain expected data  
✅ Integration with `--env PROD` and database sync works  
✅ No blocking or rate limiting issues  

---

## 9. Comparison with Existing Scrapers

| Aspect | Meta | Kumaran |
|---|---|---|
| **Method** | JSON-LD parsing | DOM selectors |
| **Listing Page** | Paginated | Single page, all jobs at once |
| **Detail Pages** | Yes | Yes |
| **Concurrency** | Semaphore-based | Semaphore-based (inherited) |
| **Data Format** | Schema.org + custom | Custom HTML structure |
| **Retry Logic** | 2 retries with backoff | 2 retries with backoff (inherited) |
| **API** | No | No (Zoho Recruit, HTML only) |

---

## 10. File Locations

```
job-portal-scrapper/
├── scrapers/
│   └── kumaran.py                    # New scraper implementation
├── db.py                              # Update extract_source_job_id()
├── main.py                            # Update PORTAL_MAP
└── docs/
    └── kumaran-scraper-design.md     # This file
```

---

## 11. Dependencies

- **playwright** - Already in requirements.txt
- **psycopg2-binary** - Already in requirements.txt for database
- **pydantic** - Already in requirements.txt for schema validation
- No new dependencies needed

---

## 12. Notes

- The Kumaran portal is powered by Zoho Recruit, which doesn't expose JSON-LD structured data
- All 47 jobs are available without pagination (efficient scraping)
- Job URLs follow predictable pattern enabling reliable extraction
- No salary information visible on detail pages (field will be empty)
- No travel requirement information visible (will use heuristic detection or mark as "Not specified")
