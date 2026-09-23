with arcash as (

    select * from {{ ref('stg_arcash') }}

),

cust as (

    select * from {{ ref('stg_cust') }}

),

joined as (

    select
        a.source_database                    as database,
        c.cust_name,
        c.cust_code,
        -- posting_year / posting_period is the authoritative GL period the
        -- discount actually posted to -- used as "year/month applied"
        -- instead of payment_date, which can be null (e.g. cancelled or
        -- still-open items) even when a discount amount is present.
        a.posting_year,
        a.posting_period,
        a.year_period,
        a.discount_amt,
        a.ref_num,
        a.ref_type,
        a.payment_method,
        a.due_date,
        a.payment_date,
        a.gl_acct_ptr,
        a.journal_number,
        a.created_by,
        a.created_date

    from arcash a
    left join cust c
        on  a.source_database = c.source_database
        and a.system_id       = c.system_id
        and a.cust_key        = c.cust_key
    -- only rows where a discount was actually applied
    where a.discount_amt is not null
      and a.discount_amt <> 0

)

select * from joined
