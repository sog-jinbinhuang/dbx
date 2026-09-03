select
    source_database,
    NULLIF(TRIM(`System-ID`), '')                                   as system_id,
    NULLIF(TRIM(`GL-Acct`), '')                                     as gl_acct,
    NULLIF(TRIM(`GL-Acct-Ptr`), '')                                 as gl_acct_ptr,

    IF(UPPER(TRIM(`Active`)) = 'TRUE', TRUE, FALSE)                 as active,
    NULLIF(TRIM(`Report-Label`), '')                                as report_label,
    NULLIF(TRIM(`Description`), '')                                 as description,
    NULLIF(TRIM(`Description`), '')                                 as full_description,
    NULLIF(TRIM(`Account-Type`), '')                                as account_type,
    NULLIF(TRIM(`Account-Type`), '')                                as bs_account_type,
    NULLIF(TRIM(`Category`), '')                                    as category,
    NULLIF(TRIM(`Category`), '')                                    as account_category,
    NULLIF(TRIM(`Default-Currency`), '')                            as default_currency,
    NULLIF(TRIM(`Currency`), '')                                    as currency,
    NULLIF(TRIM(`Company-Name`), '')                                as company_name,

    IF(UPPER(TRIM(`Require-Journal-Comment`)) = 'TRUE', TRUE, FALSE) as require_journal_comment,
    NULLIF(TRIM(`Defaults-to-Cred-Deb`), '')                        as defaults_to_cred_deb,
    NULLIF(TRIM(`Defaults-to-Cred-Deb`), '')                        as typical_balance,
    IF(UPPER(TRIM(`Journal-Entry-Allowed`)) = 'TRUE', TRUE, FALSE) as journal_entry_allowed,
    NULLIF(TRIM(`Allow-Manual-Posting`), '')                        as allow_manual_posting,
    IF(UPPER(TRIM(`DisablePosting`)) = 'TRUE', TRUE, FALSE)        as disable_posting,
    TRY_CAST(`Write-Off-Limit` AS DECIMAL(38,2))                    as write_off_limit,

    NULLIF(TRIM(`Capital-Proj-#`), '')                               as capital_proj_num,
    NULLIF(TRIM(`Other-tracking-num`), '')                          as other_tracking_num,
    NULLIF(TRIM(`Statistical-UM`), '')                              as statistical_um,
    NULLIF(TRIM(`auth-users`), '')                                  as auth_users,
    NULLIF(TRIM(`auth-user-id`), '')                                as auth_user_id,
    IF(UPPER(TRIM(`stat-acct-carry-fwd`)) = 'TRUE', TRUE, FALSE)   as stat_acct_carry_fwd,
    IF(UPPER(TRIM(`Req-Prod-Code`)) = 'TRUE', TRUE, FALSE)         as req_prod_code,
    IF(UPPER(TRIM(`Req-Equip-Code`)) = 'TRUE', TRUE, FALSE)        as req_equip_code,
    IF(UPPER(TRIM(`Req-Safety-Code`)) = 'TRUE', TRUE, FALSE)       as req_safety_code,
    IF(UPPER(TRIM(`Req-Quality-Code`)) = 'TRUE', TRUE, FALSE)      as req_quality_code,

    NULLIF(TRIM(`Immediate-Origin-Name`), '')                       as immediate_origin_name,
    NULLIF(TRIM(`Immediate-Destination`), '')                       as immediate_destination,
    NULLIF(TRIM(`Immediate-Origin`), '')                            as immediate_origin,
    NULLIF(TRIM(`Bank-Account-Number`), '')                         as bank_account_number,
    NULLIF(TRIM(`Immediate-Destination-Name`), '')                  as immediate_destination_name,
    NULLIF(TRIM(`Originating-DFI`), '')                             as originating_dfi,
    NULLIF(TRIM(`Company-ID`), '')                                  as company_id,
    NULLIF(TRIM(`ISA-Sender-ID-Qualifier`), '')                     as isa_sender_id_qualifier,
    NULLIF(TRIM(`ISA-Sender-ID`), '')                               as isa_sender_id,
    IF(UPPER(TRIM(`Send-Balanced-ACH-CTX-File`)) = 'TRUE', TRUE, FALSE) as send_balanced_ach_ctx_file,
    IF(UPPER(TRIM(`Always-Use-Blocking`)) = 'TRUE', TRUE, FALSE)   as always_use_blocking,
    NULLIF(TRIM(`ACH-TXP-File-Header`), '')                         as ach_txp_file_header,
    NULLIF(TRIM(`Send-Addenda-for-CCD-PPD`), '')                    as send_addenda_for_ccd_ppd,
    NULLIF(TRIM(`ACH-File-Format`), '')                             as ach_file_format,
    IF(UPPER(TRIM(`ACH-Increment-Segment-Per-Pmt-ID`)) = 'TRUE', TRUE, FALSE) as ach_increment_segment_per_pmt_id,
    IF(UPPER(TRIM(`ACH-Details-Verified`)) = 'TRUE', TRUE, FALSE)  as ach_details_verified,

    NULLIF(TRIM(`ePayment-Processor`), '')                          as epayment_processor,
    NULLIF(TRIM(`ePayment-Credentials`), '')                        as epayment_credentials,
    NULLIF(TRIM(`ePayment-URL`), '')                                as epayment_url,
    NULLIF(TRIM(`Credit-Card-Transaction-Key`), '')                 as credit_card_transaction_key,
    NULLIF(TRIM(`CardConnect-Merchant-ID`), '')                     as cardconnect_merchant_id,
    NULLIF(TRIM(`CardConnect-User-ID`), '')                         as cardconnect_user_id,
    NULLIF(TRIM(`CardConnect-Password`), '')                       as cardconnect_password,
    IF(UPPER(TRIM(`Include-RMR05-Value`)) = 'TRUE', TRUE, FALSE)   as include_rmr05_value,
    NULLIF(TRIM(`CardConnect-Enabled`), '')                         as cardconnect_enabled,
    NULLIF(TRIM(`Credit-Card-Processor`), '')                       as credit_card_processor,
    NULLIF(TRIM(`Credit-Card-Device-ID`), '')                       as credit_card_device_id,
    NULLIF(TRIM(`ePayments-Enabled`), '')                           as epayments_enabled,

    -- NOTE: inlined NULLIF(TRIM(`GL-Acct`),'') here directly instead of referencing
    -- the `gl_acct` alias -- Databricks doesn't reliably support lateral column
    -- aliases the way Snowflake does.
    CASE
        WHEN source_database in ('EVD', 'CHINA', 'CHILE', 'US', 'WEIFENG')
            THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 1, 2)
    END as actnumseg1,

    CASE
        WHEN source_database in ('EVD', 'CHINA', 'CHILE', 'US', 'WEIFENG')
            THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 3, 2)
    END as actnumseg2,

    CASE
        WHEN source_database = 'EVD'                          THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 5, 8)
        WHEN source_database in ('CHINA', 'WEIFENG')          THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 5, 5)
        WHEN source_database in ('US', 'CHILE')               THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 5, 4)
    END as actnumseg3,

    CASE
        WHEN source_database = 'EVD'                          THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 13, 4)
        WHEN source_database in ('CHINA', 'WEIFENG')          THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 10, 4)
        WHEN source_database in ('US', 'CHILE')               THEN SUBSTR(NULLIF(TRIM(`GL-Acct`), ''), 9, 4)
    END as actnumseg4,

    NULLIF(TRIM(`Update-by`), '')                                   as update_by,
    CAST(TRY_TO_TIMESTAMP(`Update-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)     as update_date,
    NULLIF(TRIM(`Update-time`), '')                                 as update_time,
    NULLIF(TRIM(`Created-by`), '')                                  as created_by,
    CAST(TRY_TO_TIMESTAMP(`Created-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)    as created_date,
    TRY_TO_TIMESTAMP(`Created-Date-Time`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS')    as created_date_time,
    NULLIF(TRIM(`Security-Access`), '')                             as security_access,
    CAST(TRY_TO_TIMESTAMP(`last-fin-charge-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE) as last_fin_charge_date,
    CAST(TRY_TO_TIMESTAMP(`Spare-Date-1`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)    as spare_date_1,
    TRY_CAST(`Spare-Decimal-1` AS DECIMAL(38,10))                   as spare_decimal_1,
    TRY_CAST(`Spare-Integer-1` AS DECIMAL(18,0))                    as spare_integer_1,
    IF(UPPER(TRIM(`Spare-Logical-2`)) = 'TRUE', TRUE, FALSE)       as spare_logical_2,
    IF(UPPER(TRIM(`Spare-Logical-3`)) = 'TRUE', TRUE, FALSE)       as spare_logical_3,
    IF(UPPER(TRIM(`Spare-Logical-4`)) = 'TRUE', TRUE, FALSE)       as spare_logical_4,
    IF(UPPER(TRIM(`Spare-Logical-5`)) = 'TRUE', TRUE, FALSE)       as spare_logical_5,
    IF(UPPER(TRIM(`Spare-Logical-6`)) = 'TRUE', TRUE, FALSE)       as spare_logical_6,
    IF(UPPER(TRIM(`Spare-Logical-7`)) = 'TRUE', TRUE, FALSE)       as spare_logical_7,
    NULLIF(TRIM(`Spare-Char-7`), '')                                as spare_char_7,
    NULLIF(TRIM(`Spare-Char-8`), '')                                as spare_char_8,
    NULLIF(TRIM(`Spare-Char-9`), '')                                as spare_char_9,
    NULLIF(TRIM(`Spare-Char-10`), '')                               as spare_char_10,
    NULLIF(TRIM(`Spare-Char-11`), '')                               as spare_char_11,
    NULLIF(TRIM(`Spare-Char-12`), '')                               as spare_char_12

from {{ source('bronze', 'gl_accts') }}
-- filter out template/temp accounts
where LEFT(NULLIF(TRIM(`GL-Acct`), ''), 1) != '%'
