-- Mētis catalogue pack: PostgreSQL. Read only. Connect to {{DB}}; {{SCHEMA_FILTER}} is the schema filter.
-- ID: CATALOG-TABLES
SELECT t.table_catalog, t.table_schema, t.table_name, t.table_type,
       c.reltuples::bigint AS row_count, obj_description(c.oid, 'pg_class') AS comment
FROM information_schema.tables t
LEFT JOIN pg_namespace n ON n.nspname = t.table_schema
LEFT JOIN pg_class c ON c.relname = t.table_name AND c.relnamespace = n.oid
WHERE t.table_schema NOT IN ('pg_catalog', 'information_schema') {{SCHEMA_FILTER:t.table_schema}}
ORDER BY t.table_schema, t.table_name;
-- ID: CATALOG-COLUMNS
SELECT c.table_catalog, c.table_schema, c.table_name, c.column_name, c.ordinal_position, c.data_type, c.is_nullable,
       col_description(format('%I.%I', c.table_schema, c.table_name)::regclass, c.ordinal_position) AS comment
FROM information_schema.columns c
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema') {{SCHEMA_FILTER:c.table_schema}}
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
-- ID: CATALOG-FKEYS
SELECT kcu.table_schema AS fk_schema_name, kcu.table_name AS fk_table_name, kcu.column_name AS fk_column_name,
       ccu.table_schema AS pk_schema_name, ccu.table_name AS pk_table_name, ccu.column_name AS pk_column_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.constraint_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' {{SCHEMA_FILTER:kcu.table_schema}}
ORDER BY 1, 2, 3;
