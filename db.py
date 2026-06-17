import os
import uuid
import hashlib
import re
import psycopg2
from datetime import datetime, date

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Module-level env mode — set via set_env_mode() before any DB calls
_env_mode = "LOCAL"


def set_env_mode(mode):
    """Set the environment mode: 'LOCAL' or 'PROD'."""
    global _env_mode
    _env_mode = mode.upper()
    print(f"Database mode set to: {_env_mode}")


def get_connection():
    """Create a PostgreSQL connection.
    - LOCAL: uses DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD env vars
    - PROD:  uses SUPABASE_DB_URL connection string (Supabase PostgreSQL)
    """
    if _env_mode == "PROD":
        db_url = os.environ.get("SUPABASE_DB_URL")
        if not db_url:
            raise ValueError(
                "SUPABASE_DB_URL environment variable is required in PROD mode.\n"
                "Get it from: Supabase Dashboard → Settings → Database → Connection string (URI)"
            )
        print(f"Connecting to Supabase PostgreSQL...") if not hasattr(get_connection, '_logged') else None
        get_connection._logged = True
        return psycopg2.connect(db_url)
    else:
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "job_scraper"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres")
        )


def init_db():
    """Create the jobs and closed_jobs tables if they don't exist."""
    conn = get_connection()
    cur = conn.cursor()

    # Try to enable pgvector (optional)
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        conn.commit()
    except Exception:
        conn.rollback()

    # Check if vector type is available
    cur.execute("SELECT EXISTS(SELECT 1 FROM pg_type WHERE typname = 'vector');")
    has_vector = cur.fetchone()[0]

    embedding_col = ",\n            embedding vector(1536)" if has_vector else ""

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS jobs (
            id                   text PRIMARY KEY,
            title                text NOT NULL,
            company              text NOT NULL,
            location             text NOT NULL,
            description          text NOT NULL,
            requirements         text[],
            salary               text,
            salary_min           integer,
            salary_max           integer,
            posted_at            timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
            source_url           text,
            keywords             text[],
            apply_url            text,
            source_job_id        text,
            platform             text,
            department           text,
            responsibilities     text,
            min_qualifications   text,
            pref_qualifications  text,
            about_company        text,
            compensation_details text,
            eeo_statement        text,
            additional_links     text[],
            salary_range_display text,
            salary_period        text DEFAULT 'year' NOT NULL,
            salary_has_bonus     boolean DEFAULT false NOT NULL,
            salary_has_equity    boolean DEFAULT false NOT NULL,
            salary_has_benefits  boolean DEFAULT false NOT NULL,
            compensation_summary text,
            is_active            boolean DEFAULT true NOT NULL,
            last_ingested_at     timestamp,
            closed_at            timestamp{embedding_col}
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS closed_jobs (
            id                   text PRIMARY KEY,
            original_id          text,
            title                text NOT NULL,
            company              text NOT NULL,
            location             text NOT NULL,
            description          text NOT NULL,
            requirements         text[],
            salary               text,
            salary_min           integer,
            salary_max           integer,
            posted_at            timestamp NOT NULL,
            closed_at            timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
            source_url           text,
            department           text,
            responsibilities     text,
            min_qualifications   text,
            pref_qualifications  text,
            about_company        text,
            compensation_details text,
            eeo_statement        text,
            additional_links     text[],
            keywords             text[],
            apply_url            text,
            source_job_id        text,
            platform             text,
            salary_range_display text,
            salary_period        text DEFAULT 'year' NOT NULL,
            salary_has_bonus     boolean DEFAULT false NOT NULL,
            salary_has_equity    boolean DEFAULT false NOT NULL,
            salary_has_benefits  boolean DEFAULT false NOT NULL,
            compensation_summary text
        );
    """)

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_closed_at ON jobs (closed_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_jobs_platform_last_ingested ON jobs (platform, last_ingested_at);")
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_platform_source_job_id
        ON jobs (platform, source_job_id);
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("Database tables initialized.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_source_job_id(platform, job_link):
    """Extract a portal-specific job ID from the job URL."""
    if not job_link:
        return None

    try:
        patterns = {
            "meta":      r'/job_details/(\d+)',
            "google":    r'/jobs/results/([^/]+)',
            "amazon":    r'/jobs/(\d+)',
            "apple":     r'/details/(\d+)',
            "nvidia":    r'/careers/job/(\d+)',
            "openai":    r'/openai/([^/?]+)',
            "microsoft": r'/job/(\d+)',
            "netflix":   r'/careers/job/(\d+)',
            "kumaran":   r'/jobs/Careers/(\d+)',
        }

        pattern = patterns.get(platform)
        if pattern:
            match = re.search(pattern, job_link)
            if match:
                return match.group(1)

        # Generic fallback: last path segment
        return job_link.rstrip("/").split("/")[-1].split("?")[0]
    except Exception:
        return job_link


def parse_salary(salary_str):
    """Parse a salary string into structured fields."""
    result = {
        "salary": salary_str or "",
        "salary_min": None,
        "salary_max": None,
        "salary_range_display": "",
        "salary_has_bonus": False,
        "salary_has_equity": False,
        "salary_has_benefits": False,
        "compensation_summary": salary_str or "",
    }

    if not salary_str:
        return result

    lower = salary_str.lower()
    result["salary_has_bonus"] = "bonus" in lower
    result["salary_has_equity"] = "equity" in lower
    result["salary_has_benefits"] = "benefits" in lower or "benefit" in lower

    # Extract dollar amounts: $130,000 or 130000 or 130,000
    amounts = re.findall(r'\$?([\d,]+)', salary_str)
    if amounts:
        cleaned = [int(a.replace(",", "")) for a in amounts if int(a.replace(",", "")) > 1000]
        if len(cleaned) >= 2:
            result["salary_min"] = min(cleaned[0], cleaned[1])
            result["salary_max"] = max(cleaned[0], cleaned[1])
            result["salary_range_display"] = f"${result['salary_min']:,} - ${result['salary_max']:,}"
        elif len(cleaned) == 1:
            result["salary_min"] = cleaned[0]
            result["salary_max"] = cleaned[0]
            result["salary_range_display"] = f"${cleaned[0]:,}"

    return result


def extract_keywords(job):
    """Extract basic keywords from job title and department."""
    stop_words = {
        "and", "or", "the", "a", "an", "in", "on", "at", "for", "to", "of",
        "with", "is", "are", "was", "were", "be", "been", "being", "this",
        "that", "it", "its", "not", "but", "if", "can", "will", "may", "our",
        "all", "each", "every", "both", "few", "more", "most", "other",
    }
    keywords = set()

    for text in [job.get("job_name", ""), job.get("job_department", "")]:
        if text:
            words = re.split(r"[\s,/&\-\u2013\u2014()+]+", text)
            for w in words:
                w = w.strip().lower()
                if w and len(w) > 2 and w not in stop_words:
                    keywords.add(w)

    return sorted(keywords)


def compute_content_hash(job):
    """Compute a SHA-256 hash of key job fields to detect content changes."""
    key_fields = "|".join([
        job.get("job_name", ""),
        job.get("job_location", ""),
        job.get("job_department", ""),
        job.get("job_description", ""),
        job.get("job_responsibilities", ""),
        job.get("minimum_qualifications", ""),
        job.get("preferred_qualifications", ""),
        job.get("salary", ""),
    ])
    return hashlib.sha256(key_fields.encode("utf-8")).hexdigest()


def _to_text_array(value):
    """Convert a value to a PostgreSQL text[] compatible list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


# ---------------------------------------------------------------------------
# Core sync logic
# ---------------------------------------------------------------------------

def sync_jobs(platform, company, scraped_jobs):
    """
    Synchronize scraped jobs with the database for a given platform.

    1. Upsert each scraped job (insert if new, update if content changed).
       Commits every BATCH_COMMIT_SIZE jobs to avoid losing progress on crash.
    2. Soft-delete jobs in DB that are NOT in the scraped set (is_active=false, closed_at=NOW).

    Returns a summary dict with counts.
    """
    if not scraped_jobs:
        print(f"No new jobs to process for {platform}. Checking for expired jobs...")

    conn = get_connection()
    cur = conn.cursor()

    now = datetime.now()
    BATCH_COMMIT_SIZE = 50

    inserted = 0
    updated = 0
    unchanged = 0

    scraped_source_ids = set()

    for idx, job in enumerate(scraped_jobs, 1):
        try:
            job_link = job.get("job_link", "")
            if not job_link:
                continue

            source_job_id = extract_source_job_id(platform, job_link)
            if not source_job_id:
                continue

            scraped_source_ids.add(source_job_id)
            salary_data = parse_salary(job.get("salary", ""))
            keywords = extract_keywords(job)
            additional_links = _to_text_array(job.get("additional_links", ""))

            # Check if job already exists
            cur.execute(
                "SELECT id FROM jobs WHERE platform = %s AND source_job_id = %s",
                (platform, source_job_id)
            )
            existing = cur.fetchone()

            if existing is None:
                # INSERT new job
                job_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO jobs (
                        id, title, company, location, description,
                        requirements, salary, salary_min, salary_max,
                        posted_at, source_url, keywords, apply_url,
                        source_job_id, platform, department, responsibilities,
                        min_qualifications, pref_qualifications, about_company,
                        compensation_details, eeo_statement, additional_links,
                        salary_range_display, salary_period,
                        salary_has_bonus, salary_has_equity, salary_has_benefits,
                        compensation_summary, is_active, last_ingested_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                """, (
                    job_id,
                    job.get("job_name", ""),
                    company,
                    job.get("job_location", ""),
                    job.get("job_description", ""),
                    _to_text_array(job.get("requirements", [])),
                    salary_data["salary"],
                    salary_data["salary_min"],
                    salary_data["salary_max"],
                    job.get("posted_date", now),
                    job_link,
                    keywords,
                    job.get("apply_url", job_link),
                    source_job_id,
                    platform,
                    job.get("job_department", ""),
                    job.get("job_responsibilities", ""),
                    job.get("minimum_qualifications", ""),
                    job.get("preferred_qualifications", ""),
                    job.get("about_company", ""),
                    job.get("compensation_details", ""),
                    job.get("eeo", ""),
                    additional_links,
                    salary_data["salary_range_display"],
                    "year",
                    salary_data["salary_has_bonus"],
                    salary_data["salary_has_equity"],
                    salary_data["salary_has_benefits"],
                    salary_data["compensation_summary"],
                    True,
                    now,
                ))
                inserted += 1

            else:
                existing_id = existing[0]

                # Always update content fields + last_ingested_at.
                # If the job was previously closed, reactivate it.
                cur.execute("""
                    UPDATE jobs SET
                        title = %s, company = %s, location = %s, description = %s,
                        requirements = %s, salary = %s, salary_min = %s, salary_max = %s,
                        source_url = %s, keywords = %s, apply_url = %s,
                        department = %s, responsibilities = %s,
                        min_qualifications = %s, pref_qualifications = %s, about_company = %s,
                        compensation_details = %s, eeo_statement = %s, additional_links = %s,
                        salary_range_display = %s,
                        salary_has_bonus = %s, salary_has_equity = %s, salary_has_benefits = %s,
                        compensation_summary = %s,
                        is_active = true, closed_at = NULL, last_ingested_at = %s
                    WHERE id = %s
                """, (
                    job.get("job_name", ""),
                    company,
                    job.get("job_location", ""),
                    job.get("job_description", ""),
                    _to_text_array(job.get("requirements", [])),
                    salary_data["salary"],
                    salary_data["salary_min"],
                    salary_data["salary_max"],
                    job_link,
                    keywords,
                    job.get("apply_url", job_link),
                    job.get("job_department", ""),
                    job.get("job_responsibilities", ""),
                    job.get("minimum_qualifications", ""),
                    job.get("preferred_qualifications", ""),
                    job.get("about_company", ""),
                    job.get("compensation_details", ""),
                    job.get("eeo", ""),
                    additional_links,
                    salary_data["salary_range_display"],
                    salary_data["salary_has_bonus"],
                    salary_data["salary_has_equity"],
                    salary_data["salary_has_benefits"],
                    salary_data["compensation_summary"],
                    now,
                    existing_id,
                ))
                updated += 1

            # Batch commit every BATCH_COMMIT_SIZE jobs
            if idx % BATCH_COMMIT_SIZE == 0:
                conn.commit()
                print(f"  💾 DB batch commit: {idx}/{len(scraped_jobs)} jobs processed ({inserted} new, {updated} updated)")

        except Exception as e:
            print(f"  ⚠ Error processing job {idx} ({job.get('job_link', 'unknown')}): {e}")
            conn.rollback()
            continue

    # Commit any remaining jobs from the last partial batch
    conn.commit()
    print(f"  💾 DB final commit: {len(scraped_jobs)}/{len(scraped_jobs)} jobs processed")

    # Soft-delete: mark active jobs NOT in scraped set as closed
    cur.execute(
        "SELECT id, source_job_id FROM jobs WHERE platform = %s AND is_active = true",
        (platform,)
    )
    all_active = cur.fetchall()

    closed = 0
    for db_id, db_source_id in all_active:
        if db_source_id not in scraped_source_ids:
            cur.execute(
                "UPDATE jobs SET is_active = false, closed_at = %s WHERE id = %s",
                (now, db_id)
            )
            closed += 1

    conn.commit()
    cur.close()
    conn.close()

    summary = {
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "closed": closed,
    }

    print(f"\n{'='*50}")
    print(f"DB Sync Summary for [{platform}]")
    print(f"  New jobs inserted  : {inserted}")
    print(f"  Jobs updated       : {updated}")
    print(f"  Jobs soft-deleted  : {closed}")
    print(f"{'='*50}\n")

    return summary

