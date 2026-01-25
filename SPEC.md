# Job Data Specification (RAG Data Contract)

This document defines the standard data contract used by the Multi-Portal Job Scraper. Every job listing scraped must conform to this schema to ensure compatibility with downstream RAG (Retrieval-Augmented Generation) clusters and LLM pipelines.

## 1. Schema Overview

The schema is divided into five logical namespaces to allow for targeted retrieval.

### metadata
| Field | Type | Description |
| :--- | :--- | :--- |
| `job_id` | String | Unique identifier from the career portal. |
| `job_title` | String | The official title of the role. |
| `organization_name`| String | The hiring entity (e.g., "Apple Inc."). |
| `job_department` | String | Department or Org unit (e.g., "Siri", "Cloud Env"). |
| `job_link` | URI | Permalink to the job posting. |
| `posted_date` | ISO Date | Extracted or current date (YYYY-MM-DD). |

### logistics
| Field | Type | Description |
| :--- | :--- | :--- |
| `job_locations` | List<Str> | Multi-city support. Standardized as a list. |
| `work_mode` | Enum | One of: `remote`, `hybrid`, `onsite`. |
| `travel_requirement`| String | Extracted travel intensity (e.g., "Up to 25%"). |
| `job_type` | String | e.g., "Full-time", "Internship", "Contract". |

### role_details
| Field | Type | Description |
| :--- | :--- | :--- |
| `job_description` | Text | High-level overview of the role. |
| `job_responsibilities`| Text | Bulleted list of day-to-day tasks. |
| `minimum_qualifications`| Text | Hard requirements for the role. |
| `preferred_qualifications`| Text | "Bonus" qualifications or preferred experience. |
| `language_requirements`| List<Str> | Detected languages required for the role. |

### compensation
| Field | Type | Description |
| :--- | :--- | :--- |
| `salary_range` | String | Base pay range (extracted from text or API). |
| `compensation_details`| Text | Details on Bonus, RSU, Equity, and refreshers. |
| `benefits_and_perks` | Text | Health, Wellness, and 401(k) specifics. |

### legal_and_company
| Field | Type | Description |
| :--- | :--- | :--- |
| `about_company` | Text | Standard company boilerplate (marketing text). |
| `equal_employment_opportunity` | Text | Full EEO and diversity statements. |
| `additional_links`| List<URI> | URLs found within the job text for further context. |

## 2. Validation

All data is validated at runtime using the `job_models.py` Pydantic models. Any data that fails to meet the `required` fields or `enum` constraints will trigger a warning and fallback during the scraping process.

## 3. Heuristics

The `BaseJobScraper` includes the following heuristics to populate missing data:
- **Work Mode Detection**: Scans for "remote", "wfh", "hybrid", "office" in text.
- **Travel Extraction**: Uses regex to find percentage-based travel requirements.
- **Language Detection**: Identifies non-English language requirements mentioned in descriptors.
