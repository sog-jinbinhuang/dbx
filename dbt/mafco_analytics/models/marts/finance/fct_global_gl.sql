with header as (
    select * from {{ ref('stg_gl_entry_header') }}
),

trailer as (
    select * from {{ ref('stg_gl_entry_trailer') }}
),

mapping as (
    select * from {{ ref('onestream_account_mapping') }}
),

cc_mapping as (
    select * from {{ ref('onestream_cc_mapping') }}
),

cc_hierarchy as (
    select * from {{ ref('dim_cc_hierarchy') }}
),

account_hierarchy as (
    select * from {{ ref('dim_account_hierarchy') }}
),

gl_accts_cleaned as (
    select
        *,
        case
            when source_database = 'EVD'
                then substr(gl_acct, 1, 2)  || '-' ||
                     substr(gl_acct, 3, 2)  || '-' ||
                     substr(gl_acct, 5, 8)  || '-' ||
                     substr(gl_acct, 13, 4)
            when source_database = 'CHINA'
                then substr(gl_acct, 1, 2)  || '-' ||
                     substr(gl_acct, 3, 2)  || '-' ||
                     substr(gl_acct, 5, 5)  || '-' ||
                     substr(gl_acct, 10, 4)
            when source_database = 'US'
                then substr(gl_acct, 1, 2)  || '-' ||
                     substr(gl_acct, 3, 2)  || '-' ||
                     substr(gl_acct, 5, 4)  || '-' ||
                     substr(gl_acct, 9, 4)
            when source_database = 'WEIFENG'
                then substr(gl_acct, 1, 2)  || '-' ||
                     substr(gl_acct, 3, 2)  || '-' ||
                     substr(gl_acct, 5, 5)  || '-' ||
                     substr(gl_acct, 10, 4)
            when source_database = 'CHILE'
                then substr(gl_acct, 1, 2)  || '-' ||
                     substr(gl_acct, 3, 2)  || '-' ||
                     substr(gl_acct, 5, 4)  || '-' ||
                     substr(gl_acct, 9, 4)           
            else gl_acct
        end as chempax_account_num
    from {{ ref('stg_gl_accts') }}
),

sales as (
    select
        i.source_database,
        cast(cast(i.invoice_num as integer) as string)   as invoice_num,
        i.journal_number,
        c.cust_name,
        c.cust_group
    from {{ ref('stg_invoice_hdr') }} i
    left join {{ ref('stg_cust') }} c
        on  i.source_database   = c.source_database
        and i.cust_key          = c.cust_key
    group by i.source_database, i.invoice_num, i.journal_number, c.cust_name, c.cust_group
),

ap as (
    select
        a.source_database,
        a.journal_number,
        s.supplier_name,
        s.supplier_code
    from {{ ref('stg_apinvhdr') }} a
    left join {{ ref('stg_suppname') }} s
        on  a.source_database   = s.source_database
        and a.supplier_key      = s.supplier_key
),

joined as (
    select
        -- =================== keys ===================
        t.source_database,
        t.system_id,
        t.origin,
        t.journal_number,
        t.seq_number,
        t.gl_acct_ptr,
        t.posting_year,
        t.posting_year_period,

        -- =================== journal header context ===================
        h.source                        as journal_source,
        h.posting_period,
        h.remark                        as journal_remark,
        h.detailed_remark,
        h.transaction_date,
        h.entered_by,
        h.entered_date,
        h.posted_by,
        h.posted_date,
        h.approved,
        h.approved_by,
        h.approved_date,
        h.reversible,
        h.reversed_by,
        h.reversed_date,
        h.reversed_to_period,
        h.reversed_to_year,
        h.entered_currency,
        h.on_hold,
        h.batch_number,

        -- =================== line amounts ===================
        t.credit_debit,
        t.amount                        as raw_amount,
        t.signed_amount,
        t.remark                        as line_remark,
        t.proj_num,
        t.product_key,
        t.packaging_key,

        -- =================== period dates ===================
        to_date(
            CAST(t.posting_year AS STRING) || '-' || lpad(CAST(h.posting_period AS STRING), 2, '0') || '-01',
            'yyyy-MM-dd'
        ) as period_start_date,
        last_day(to_date(
            CAST(t.posting_year AS STRING) || '-' || lpad(CAST(h.posting_period AS STRING), 2, '0') || '-01',
            'yyyy-MM-dd'
        )) as period_end_date,

        -- =================== quarter & half ===================
        case
            when h.posting_period between 1  and 3  then 'Q1'
            when h.posting_period between 4  and 6  then 'Q2'
            when h.posting_period between 7  and 9  then 'Q3'
            when h.posting_period between 10 and 12 then 'Q4'
        end as fiscal_quarter,
        case
            when h.posting_period between 1 and 6  then 'H1'
            when h.posting_period between 7 and 12 then 'H2'
        end as fiscal_half,

        -- =================== region ===================
        case
            when t.source_database in ('CHINA', 'WEIFENG') then 'China'
            when t.source_database = 'EVD'                 then 'France'
            when t.source_database = 'US'                  then 'USA'
            when t.source_database = 'CHILE'               then 'Chile'
        end as region,

        -- =================== local currency ===================
        case
            when t.source_database = 'US'      then 'USD'
            when t.source_database = 'WEIFENG' then 'USD'
            when t.source_database = 'CHINA'   then 'RMB'
            when t.source_database = 'EVD'     then 'EUR'
            when t.source_database = 'CHILE'   then 'CLP'
        end as local_currency,

        -- =================== account details ===================
        d.chempax_account_num,
        d.full_description                  as chempax_account_description,
        d.full_description                  as chempax_account_description_en,
        d.account_category                  as chempax_account_category,
        d.typical_balance                   as chempax_balance_type,
        d.bs_account_type                   as chempax_account_type,
        d.actnumseg1,
        d.actnumseg2,
        d.actnumseg3,
        d.actnumseg4,
        d.other_tracking_num                as cap_var,

        -- =================== exchange rate ===================
        case
            when t.source_database = 'US'      then 1
            when t.source_database = 'WEIFENG' then 1
            when t.source_database = 'CHINA'   then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_china.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_china.rate, 0)
                    else 1 / nullif(exch_china.rate, 0)
                end
            when t.source_database = 'EVD'     then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_euro.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_euro.rate, 0)
                    else 1 / nullif(exch_euro.rate, 0)
                end
            when t.source_database = 'CHILE'   then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_chile.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_chile.rate, 0)
                    else 1 / nullif(exch_chile.rate, 0)
                end
            else 1
        end as usd_x_rate,

        -- =================== usd amounts ===================
        t.signed_amount * case
            when t.source_database = 'US'      then 1
            when t.source_database = 'WEIFENG' then 1
            when t.source_database = 'CHINA'   then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_china.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_china.rate, 0)
                    else 1 / nullif(exch_china.rate, 0)
                end
            when t.source_database = 'EVD'     then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_euro.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_euro.rate, 0)
                    else 1 / nullif(exch_euro.rate, 0)
                end
            when t.source_database = 'CHILE'   then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_chile.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_chile.rate, 0)
                    else 1 / nullif(exch_chile.rate, 0)
                end
            else 1
        end as signed_amount_usd,

        abs(
            t.signed_amount * case
            when t.source_database = 'US'      then 1
            when t.source_database = 'WEIFENG' then 1
            when t.source_database = 'CHINA'   then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_china.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_china.rate, 0)
                    else 1 / nullif(exch_china.rate, 0)
                end
            when t.source_database = 'EVD'     then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_euro.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_euro.rate, 0)
                    else 1 / nullif(exch_euro.rate, 0)
                end
            when t.source_database = 'CHILE'   then
                case
                    when d.bs_account_type in ('EX', 'IC') then 1 / nullif(exch_chile.rate, 0)
                    when d.bs_account_type in ('AS', 'LI', 'EQ') then 1 / nullif(exch_spot_chile.rate, 0)
                    else 1 / nullif(exch_chile.rate, 0)
                end
            else 1
            end 
        )                                   as amount_usd,

        -- =================== onestream account mapping ===================
        map.description                     as onestream_account_description,
        map.outputvalue                     as onestream_account_num,

        -- =================== onestream cc mapping (with account-based fallback) ===================
        cc.description                      as onestream_cc_description,
        coalesce(
            cc.outputvalue,
            case substr(map.outputvalue, 1, 1)
                when '1' then 'CC_BalSheet'
                when '2' then 'CC_BalSheet'
                when '3' then 'CC_BalSheet'
                when '4' then 'CC_SalesandDedAccts'
                when '5' then 'CC_StdCOGSAccts'
                when '8' then 'CC_NonOpAccts'
                when '6' then
                    case
                        when substr(map.outputvalue, 1, 2) = '69' then 'CC_OthOpExAccts'
                        else 'CC_Missing'
                    end
                else 'CC_Missing'
            end
        )                                   as onestream_cc,

        -- =================== vendor extraction ===================
        case
            -- Supplier pattern: "Supplier <name>" (ends at end of string)
            when h.remark ilike '%Supplier %'
                then trim(regexp_extract(h.remark, 'Supplier\\s+(.+)$', 1))

            -- Customer colon pattern: "Customer: <name>,"
            when h.remark ilike '%Customer:%'
                then trim(regexp_extract(h.remark, 'Customer:\\s*(.+?),', 1))

            -- Cust Name pattern: "Cust Name <name>, Cust ID"
            when h.remark ilike '%Cust Name %'
                then trim(regexp_extract(h.remark, 'Cust Name\\s+(.+?),\\s*Cust ID', 1))

            -- Payment Dt pattern: "Reference # <anything>, <VENDOR NAME>, Payment Dt"
            when h.remark ilike '%Payment Dt%'
                then trim(regexp_extract(h.remark, ',\\s*([^,]+),\\s*Payment Dt', 1))

            -- Reversed entry A/P voucher
            when h.remark ilike '%Reversed Entry%' and h.remark ilike '%Voucher #%'
                then trim(regexp_extract(h.remark, '\\d{2}/\\d{2}/\\d{4},\\s*(.+?),\\s*Reference\\s+#', 1))

            -- Standard A/P voucher: "DATE, VENDOR NAME, Reference #"
            when h.remark ilike '%Voucher #%'
                then trim(regexp_extract(h.remark, '\\d{2}/\\d{2}/\\d{4},\\s*(.+?),\\s*Reference\\s+#', 1))

            else null
        end                                 as vendor_name,

        case
            when h.remark ilike '%Customer:%'   then 'Customer'
            when h.remark ilike '%Cust Name %'  then 'Customer'
            when h.remark ilike '%Supplier %'   then 'Supplier'
            when h.remark ilike '%Voucher #%'   then 'Vendor'
            when h.remark ilike '%Payment Dt%'  then 'Vendor'
            else null
        end                                 as vendor_type,


        -- =================== sales order ===================
        s.invoice_num,
        s.cust_name,
        s.cust_group,


        -- =================== ap supplier ===================
        ap.supplier_name,
        ap.supplier_code,
        -- =================== account hierarchy ===================
        acct_hier.level_9                   as account_bs_pl,
        acct_hier.level_9_desc              as account_bs_pl_description,
        acct_hier.level_10                  as account_category_l1,
        acct_hier.level_10_desc             as account_category_l1_description,
        acct_hier.level_11                  as account_category_l2,
        acct_hier.level_11_desc             as account_category_l2_description,
        acct_hier.level_12                  as account_category_l3,
        acct_hier.level_12_desc             as account_category_l3_description,
        acct_hier.level_13                  as account_category_l4,
        acct_hier.level_13_desc             as account_category_l4_description,
        acct_hier.leaf_desc                 as account_leaf_description,

        -- =================== cost center hierarchy ===================
        cc_hier.level_3                     as cc_level_1,
        cc_hier.level_3_desc                as cc_level_1_description,
        cc_hier.level_4                     as cc_level_2,
        cc_hier.level_4_desc                as cc_level_2_description,
        cc_hier.level_5                     as cc_level_3,
        cc_hier.level_5_desc                as cc_level_3_description,
        cc_hier.leaf_desc                   as cc_leaf_description

    from trailer t
    left join header h
        on  t.source_database = h.source_database
        and t.system_id       = h.system_id
        and t.origin          = h.origin
        and t.journal_number  = h.journal_number
        and t.posting_year    = h.posting_year
        and h.posting_period  between 1 and 12
    left join gl_accts_cleaned as d
        on  t.source_database = d.source_database
        and t.system_id       = d.system_id
        and t.gl_acct_ptr     = d.gl_acct_ptr
    -- Translation dependency removed for now -- using d.full_description directly
    -- above instead of joining to dim_gl_account_description_translated.
    left join {{ ref('exch_rate_china') }} as exch_china
        on  t.source_database = 'CHINA'
        and exch_china.period = cast(
                CAST(t.posting_year AS STRING) || lpad(CAST(h.posting_period AS STRING), 2, '0')
            as integer)
    left join {{ ref('exch_rate_euro') }} as exch_euro
        on  t.source_database = 'EVD'
        and exch_euro.period = cast(
                CAST(t.posting_year AS STRING) || lpad(CAST(h.posting_period AS STRING), 2, '0')
            as integer)
    left join {{ ref('exch_rate_chile') }} as exch_chile
        on  t.source_database = 'CHILE'
        and exch_chile.period = cast(
                CAST(t.posting_year AS STRING) || lpad(CAST(h.posting_period AS STRING), 2, '0')
            as integer)
    left join {{ ref('exch_spot_rate_china') }} as exch_spot_china
        on  t.source_database = 'CHINA'
        and exch_spot_china.period = cast(
                CAST(t.posting_year AS STRING) || lpad(CAST(h.posting_period AS STRING), 2, '0')
            as integer)
    left join {{ ref('exch_spot_rate_euro') }} as exch_spot_euro
        on  t.source_database = 'EVD'
        and exch_spot_euro.period = cast(
                CAST(t.posting_year AS STRING) || lpad(CAST(h.posting_period AS STRING), 2, '0')
            as integer)
    left join {{ ref('exch_spot_rate_chile') }} as exch_spot_chile
        on  t.source_database = 'CHILE'
        and exch_spot_chile.period = cast(
                CAST(t.posting_year AS STRING) || lpad(CAST(h.posting_period AS STRING), 2, '0')
            as integer)
    left join sales as s
        on  t.source_database   = s.source_database
        and h.journal_number    = s.journal_number
        and t.origin            = 'I/N'
    left join ap
        on  t.source_database   = ap.source_database
        and h.journal_number    = ap.journal_number
        and t.origin            = 'A/P'
    left join mapping as map
        on  t.source_database                           = map.database
        and replace(d.chempax_account_num, '-', '')     = replace(map.name, '-', '')
    left join cc_mapping as cc
        on  t.source_database                           = cc.database
        and replace(d.chempax_account_num, '-', '')     = replace(cc.name, '-', '')
    left join account_hierarchy as acct_hier
        on  map.outputvalue                             = acct_hier.leaf
    left join cc_hierarchy as cc_hier
        on  coalesce(
                cc.outputvalue,
                case substr(map.outputvalue, 1, 1)
                    when '1' then 'CC_BalSheet'
                    when '2' then 'CC_BalSheet'
                    when '3' then 'CC_BalSheet'
                    when '4' then 'CC_SalesandDedAccts'
                    when '5' then 'CC_StdCOGSAccts'
                    when '8' then 'CC_NonOpAccts'
                    when '6' then
                        case
                            when substr(map.outputvalue, 1, 2) = '69' then 'CC_OthOpExAccts'
                            else 'CC_Missing'
                        end
                    else 'CC_Missing'
                end
            )                                           = cc_hier.leaf

    where d.bs_account_type <> 'ST' and t.posting_year_period >= date_format(dateadd(month, -12, current_date()), 'yyyyMM')
)

select * from joined