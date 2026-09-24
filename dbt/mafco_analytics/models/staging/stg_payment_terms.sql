select
    source_database,
    NULLIF(TRIM(`System-ID`), '') as system_id,
    NULLIF(TRIM(`Internal-terms-key`), '') as internal_terms_key,
    NULLIF(TRIM(`Terms-code`), '') as terms_code,
    IF(UPPER(TRIM(`Active`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Active`)) = 'FALSE', FALSE, NULL)) as active,
    NULLIF(TRIM(`Description`), '') as description,
    NULLIF(TRIM(`Term-type`), '') as term_type,
    NULLIF(TRIM(`Term-typeCV`), '') as term_type_cv,
    TRY_CAST(`Initial-Payment-Percent` AS DECIMAL(18,4)) as initial_payment_percent,
    TRY_CAST(`Balance-Due-Days` AS DECIMAL(18,0)) as balance_due_days,
    TRY_CAST(`Day-of-month` AS DECIMAL(18,0)) as day_of_month,

    -- Days@1 .. Days@20
    {% for i in range(1, 21) %}
    TRY_CAST(`Days@{{ i }}` AS DECIMAL(18,0)) as days_{{ i }},
    {% endfor %}

    -- Percent@1 .. Percent@20
    {% for i in range(1, 21) %}
    TRY_CAST(`Percent@{{ i }}` AS DECIMAL(18,4)) as percent_{{ i }},
    {% endfor %}

    IF(UPPER(TRIM(`Add-finance-charge`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Add-finance-charge`)) = 'FALSE', FALSE, NULL)) as add_finance_charge,
    TRY_CAST(`Finance-charge-monthly-percent` AS DECIMAL(18,4)) as finance_charge_monthly_percent,
    TRY_CAST(`Discount-percentage` AS DECIMAL(18,4)) as discount_percentage,
    TRY_CAST(`Discount-Days` AS DECIMAL(18,0)) as discount_days,
    NULLIF(TRIM(`Update-by`), '') as update_by,
    CAST(TRY_TO_TIMESTAMP(`Update-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE) as update_date,
    NULLIF(TRIM(`Update-time`), '') as update_time,
    NULLIF(TRIM(`Created-by`), '') as created_by,
    CAST(TRY_TO_TIMESTAMP(`Created-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE) as created_date,
    NULLIF(TRIM(`Security-Access`), '') as security_access,
    NULLIF(TRIM(`User-1`), '') as user_1,
    TRY_CAST(`Prox-Day` AS DECIMAL(18,0)) as prox_day,
    CAST(TRY_TO_TIMESTAMP(`Prox-Discount-Date@1`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE) as prox_discount_date_1,
    CAST(TRY_TO_TIMESTAMP(`Prox-Discount-Date@2`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE) as prox_discount_date_2,
    TRY_CAST(`Prox-Discount-Percent@1` AS DECIMAL(18,4)) as prox_discount_percent_1,
    TRY_CAST(`Prox-Discount-Percent@2` AS DECIMAL(18,4)) as prox_discount_percent_2,
    CAST(TRY_TO_TIMESTAMP(`Prox-Due-Date@1`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE) as prox_due_date_1,
    CAST(TRY_TO_TIMESTAMP(`Prox-Due-Date@2`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE) as prox_due_date_2,
    IF(UPPER(TRIM(`Prox-Use-Net-Days@1`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Prox-Use-Net-Days@1`)) = 'FALSE', FALSE, NULL)) as prox_use_net_days_1,
    IF(UPPER(TRIM(`Prox-Use-Net-Days@2`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Prox-Use-Net-Days@2`)) = 'FALSE', FALSE, NULL)) as prox_use_net_days_2,
    TRY_TO_TIMESTAMP(`Created-Date-Time`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') as created_date_time,
    IF(UPPER(TRIM(`Exclude-Credit-Hold`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Exclude-Credit-Hold`)) = 'FALSE', FALSE, NULL)) as exclude_credit_hold,
    IF(UPPER(TRIM(`AR-Disc-On-Merch`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`AR-Disc-On-Merch`)) = 'FALSE', FALSE, NULL)) as ar_disc_on_merch,
    NULLIF(TRIM(`Multiple-Payment-Type`), '') as multiple_payment_type,

    -- Multiple-Payment-Month@1 .. @20
    {% for i in range(1, 21) %}
    TRY_CAST(`Multiple-Payment-Month@{{ i }}` AS DECIMAL(18,0)) as multiple_payment_month_{{ i }},
    {% endfor %}

    -- Multiple-Payment-Day@1 .. @20
    {% for i in range(1, 21) %}
    TRY_CAST(`Multiple-Payment-Day@{{ i }}` AS DECIMAL(18,0)) as multiple_payment_day_{{ i }},
    {% endfor %}

    IF(UPPER(TRIM(`Commission-Hold@1`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Commission-Hold@1`)) = 'FALSE', FALSE, NULL)) as commission_hold_1,
    IF(UPPER(TRIM(`Commission-Hold@2`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Commission-Hold@2`)) = 'FALSE', FALSE, NULL)) as commission_hold_2,
    TRY_CAST(`Commission-Split@1` AS DECIMAL(18,4)) as commission_split_1,
    TRY_CAST(`Commission-Split@2` AS DECIMAL(18,4)) as commission_split_2,
    NULLIF(TRIM(`Commission-Suffix@1`), '') as commission_suffix_1,
    NULLIF(TRIM(`Commission-Suffix@2`), '') as commission_suffix_2,
    IF(UPPER(TRIM(`Require-Auth-Only-Trans`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Require-Auth-Only-Trans`)) = 'FALSE', FALSE, NULL)) as require_auth_only_trans,
    NULLIF(TRIM(`Spare-Char-1`), '') as spare_char_1,
    IF(UPPER(TRIM(`Auto-Charge-Credit-Card`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Auto-Charge-Credit-Card`)) = 'FALSE', FALSE, NULL)) as auto_charge_credit_card,
    TRY_CAST(`Charge-Card-XDays-After` AS DECIMAL(18,0)) as charge_card_xdays_after,
    NULLIF(TRIM(`Charge-Card-Based-Upon`), '') as charge_card_based_upon,
    IF(UPPER(TRIM(`Collect-Payment-Now`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Collect-Payment-Now`)) = 'FALSE', FALSE, NULL)) as collect_payment_now,
    IF(UPPER(TRIM(`Exclude-From-Automated-Print`)) = 'TRUE', TRUE,
    IF(UPPER(TRIM(`Exclude-From-Automated-Print`)) = 'FALSE', FALSE, NULL)) as exclude_from_automated_print

from {{ source('bronze', 'payment_terms') }}
