select
    source_database,

        NULLIF(TRIM(`Table-Name`), '') as table_name,
        NULLIF(TRIM(`Field-Name`), '') as field_name,
        NULLIF(TRIM(`Unique-String`), '') as unique_string,
        TRY_CAST(`Old-Value` AS DECIMAL(8,0)) as old_value,
        NULLIF(TRIM(`Update-By`), '') as update_by,

        -- raw string as-is, e.g. 2005112106:57:42
        `Update-Date-Time` as update_date_time_raw,

        -- parse into proper timestamp: insert a separator between the
        -- yyyyMMdd date portion and the HH:mm:ss time portion
        TRY_TO_TIMESTAMP(
            SUBSTR(`Update-Date-Time`, 1, 8) || ' ' ||
            SUBSTR(`Update-Date-Time`, 9),
            'yyyyMMdd HH:mm:ss'
        ) as update_date_time,

        -- extract date portion only
        CAST(TRY_TO_TIMESTAMP(SUBSTR(`Update-Date-Time`, 1, 8), 'yyyyMMdd') AS DATE) as update_date
from {{ source('bronze', 'audit_order') }}
