select
    source_database,
    TRY_CAST(`System-ID` AS STRING) as system_id,
    TRY_CAST(`GL-Acct-Ptr` AS STRING) as gl_acct_ptr,
    TRY_CAST(`GL-Year` AS INT) as fiscal_year,
    COALESCE(TRY_CAST(`Debit-Fwd` AS DECIMAL(18,2)), 0)  - COALESCE(TRY_CAST(`Credit-Fwd` AS DECIMAL(18,2)), 0)  as per_0,
    COALESCE(TRY_CAST(`Debits@1` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@1` AS DECIMAL(18,2)), 0)   as per_1,
    COALESCE(TRY_CAST(`Debits@2` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@2` AS DECIMAL(18,2)), 0)   as per_2,
    COALESCE(TRY_CAST(`Debits@3` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@3` AS DECIMAL(18,2)), 0)   as per_3,
    COALESCE(TRY_CAST(`Debits@4` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@4` AS DECIMAL(18,2)), 0)   as per_4,
    COALESCE(TRY_CAST(`Debits@5` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@5` AS DECIMAL(18,2)), 0)   as per_5,
    COALESCE(TRY_CAST(`Debits@6` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@6` AS DECIMAL(18,2)), 0)   as per_6,
    COALESCE(TRY_CAST(`Debits@7` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@7` AS DECIMAL(18,2)), 0)   as per_7,
    COALESCE(TRY_CAST(`Debits@8` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@8` AS DECIMAL(18,2)), 0)   as per_8,
    COALESCE(TRY_CAST(`Debits@9` AS DECIMAL(18,2)), 0)   - COALESCE(TRY_CAST(`Credits@9` AS DECIMAL(18,2)), 0)   as per_9,
    COALESCE(TRY_CAST(`Debits@10` AS DECIMAL(18,2)), 0)  - COALESCE(TRY_CAST(`Credits@10` AS DECIMAL(18,2)), 0)  as per_10,
    COALESCE(TRY_CAST(`Debits@11` AS DECIMAL(18,2)), 0)  - COALESCE(TRY_CAST(`Credits@11` AS DECIMAL(18,2)), 0)  as per_11,
    COALESCE(TRY_CAST(`Debits@12` AS DECIMAL(18,2)), 0)  - COALESCE(TRY_CAST(`Credits@12` AS DECIMAL(18,2)), 0)  as per_12,
    COALESCE(TRY_CAST(`Debits@13` AS DECIMAL(18,2)), 0)  - COALESCE(TRY_CAST(`Credits@13` AS DECIMAL(18,2)), 0)  as per_13
from {{ source('bronze', 'gl_data') }}
where TRY_CAST(`GL-Year` AS INT) > 2021
