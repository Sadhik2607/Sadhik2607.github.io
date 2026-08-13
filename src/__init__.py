"""MigrateForge — client data migration toolkit.

Pipeline stages:
    ingest   (Python/pandas)  -> clean + profile raw client data
    mapping  (Python)         -> resolve source columns to target CRM fields
    transform(Node.js)        -> reshape records into the target schema
    validate (Python)         -> enforce required fields / types / uniqueness
    report   (Python)         -> human + machine readable migration report
"""

__version__ = "1.0.0"
