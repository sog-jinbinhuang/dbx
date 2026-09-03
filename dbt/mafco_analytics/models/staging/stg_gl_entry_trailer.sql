select
    source_database,

        NULLIF(TRIM(`System-ID`), '')                            as system_id,
        NULLIF(TRIM(`Origin`), '')                               as origin,
        NULLIF(TRIM(`Journal-Number`), '')                       as journal_number,
        NULLIF(TRIM(`Seq-Number`), '')                           as seq_number,
        NULLIF(TRIM(`GL-Acct-Ptr`), '')                          as gl_acct_ptr,
        TRY_CAST(`Posting-Year` AS DECIMAL(18,0))                     as posting_year,
        NULLIF(TRIM(`Credit-Debit`), '')                         as credit_debit,
        TRY_CAST(`Amount` AS DECIMAL(18,2))                           as amount,
        CASE
            WHEN TRIM(UPPER(`Credit-Debit`)) = 'DR' THEN  TRY_CAST(`Amount` AS DECIMAL(18,2))
            WHEN TRIM(UPPER(`Credit-Debit`)) = 'CR' THEN -TRY_CAST(`Amount` AS DECIMAL(18,2))
        END                                                      as signed_amount,
        NULLIF(TRIM(`Proj-num`), '')                             as proj_num,
        NULLIF(TRIM(`Distrib-Acct-Num-Ptr`), '')                 as distrib_acct_num_ptr,
        NULLIF(TRIM(`Update-by`), '')                            as update_by,
        CAST(TRY_TO_TIMESTAMP(`Update-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)                               as update_date,
        NULLIF(TRIM(`Update-time`), '')                          as update_time,
        NULLIF(TRIM(`Created-by`), '')                           as created_by,
        CAST(TRY_TO_TIMESTAMP(`Created-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)                              as created_date,
        NULLIF(TRIM(`Security-Access`), '')                      as security_access,
        NULLIF(TRIM(`User-1`), '')                               as user_1,
        NULLIF(TRIM(`remark`), '')                               as remark,
        NULLIF(TRIM(`Product-Key`), '')                          as product_key,
        NULLIF(TRIM(`Packaging-Key`), '')                        as packaging_key,
        NULLIF(TRIM(`Equipment-key`), '')                        as equipment_key,
        NULLIF(TRIM(`Safety-Code`), '')                          as safety_code,
        NULLIF(TRIM(`Quality-Code`), '')                         as quality_code,
        TRY_TO_TIMESTAMP(`Created-Date-Time`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS')                as created_date_time,
        TRY_CAST(`Account-Currency-Amount` AS DECIMAL(18,2))          as account_currency_amount,
        NULLIF(TRIM(`Account-Currency`), '')                     as account_currency,
        CAST(TRY_TO_TIMESTAMP(`Account-Currency-Conversion-Date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)          as account_currency_conversion_date,
        TRY_CAST(`Account-Currency-Conversion-Rate` AS DECIMAL(18,6)) as account_currency_conversion_rate,
        NULLIF(TRIM(`Related-Info`), '')                         as related_info,
        NULLIF(TRIM(`Posting-Year-Period`), '')                   as posting_year_period
from {{ source('bronze', 'gl_entry_trailer') }}
