select
    source_database,

        NULLIF(TRIM(`System-ID`), '')                                   as system_id,
        NULLIF(TRIM(`FROM-CURRENCY`), '')                               as from_currency,
        NULLIF(TRIM(`TO-CURRENCY`), '')                                 as to_currency,
        CAST(TRY_TO_TIMESTAMP(`DATE-EFFECTIVE`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)                                   as date_effective,
        TRY_CAST(`EXCHANGE-RATE` AS DECIMAL(18,8))                           as exchange_rate,
        NULLIF(TRIM(`EFFECTIVE-TIME`), '')                              as effective_time,
        IF(UPPER(TRIM(`Active`)) = 'TRUE', TRUE,
            IF(UPPER(TRIM(`Active`)) = 'FALSE', FALSE, NULL))          as active,
        NULLIF(TRIM(`Security-Access`), '')                             as security_access,
        NULLIF(TRIM(`User-1`), '')                                      as user_1,
        NULLIF(TRIM(`Update-by`), '')                                   as update_by,
        CAST(TRY_TO_TIMESTAMP(`Update-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)                                      as update_date,
        NULLIF(TRIM(`Update-time`), '')                                 as update_time,
        NULLIF(TRIM(`Created-by`), '')                                  as created_by,
        CAST(TRY_TO_TIMESTAMP(`Created-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)                                     as created_date,
        TRY_TO_TIMESTAMP(`Created-Date-Time`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS')                       as created_date_time
from {{ source('bronze', 'gl_exch_rate') }}
