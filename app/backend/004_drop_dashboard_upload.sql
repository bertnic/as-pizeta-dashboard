-- Remove legacy in-browser PDF upload storage (unused; ingestion via ETL / mart).

DROP TABLE IF EXISTS dashboard_upload;
