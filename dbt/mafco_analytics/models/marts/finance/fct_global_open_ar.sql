with ar_base as (
    select
        ar.source_database as database,
        case
            when ar.source_database in ('CHINA', 'WEIFENG') then 'CHINA'
            else ar.source_database
        end as division,
        case
            when ar.source_database = 'CHINA' and substr(cast(gl.gl_acct as string), 1, 2) = '72' then 'ZFTZ'
            when ar.source_database = 'CHINA' and substr(cast(gl.gl_acct as string), 1, 2) = '78' then 'SHMF'
            when ar.source_database = 'WEIFENG' then 'WFHK'
            when ar.source_database = 'MAFCO'  then 'MAFWW'
            when ar.source_database = 'EVD'    then 'EVD'
            else ar.source_database
        end as company,
        case
            when ar.source_database = 'CHINA'   then 'RMB'
            when ar.source_database = 'EVD'     then 'EURO'
            when ar.source_database = 'MAFCO'   then 'USD'
            when ar.source_database = 'WEIFENG' then 'USD'
            else ar.entered_currency
        end as local_currency_label,
        case
            when ar.ref_type in ('CM', 'CA') then -ar.amount
            else ar.amount
        end as amt,
        case
            when ar.ref_type in ('CM', 'CA') then -ar.open_amt
            else ar.open_amt
        end as op_amt,
        ar.ref_type,
        ar.ref_num,
        cast(ar.ref_date as date)   as ref_date,
        cast(iv.due_date as date)   as due_date,
        datediff(current_date(), cast(iv.due_date as date)) as days_overdue,
        ar.entered_currency,
        ar.ent_currency_conversion_rate,
        cu.cust_code,
        cu.cust_name,
        cu.default_sales_agent_2,
        gl.gl_acct
    from {{ ref('stg_aropen') }} as ar
    left join {{ ref('stg_invoice_hdr') }} as iv
        on cast(ar.ref_num as string) = cast(iv.invoice_num as string)
        and ar.ref_type        = iv.ref_type
        and ar.source_database = iv.source_database
    inner join {{ ref('stg_cust') }} as cu
        on ar.cust_key         = cu.cust_key
        and ar.source_database = cu.source_database
    inner join {{ ref('stg_gl_accts') }} as gl
        on ar.gl_acct_ptr      = gl.gl_acct_ptr
        and ar.source_database = gl.source_database
    where ar.open_amt <> 0
        and ar.posting_year > 2013
        and not (ar.source_database = 'EVD'   and cu.cust_code in ('41000', '58000', '54000'))
        and not (ar.source_database = 'CHINA' and cu.cust_code in ('5', '3', '213'))
        and not (ar.source_database = 'US'    and cu.cust_code in ('1128', '2063', '2108'))
        and not (ar.source_database = 'WEIFENG'    and cu.cust_code in ('15', '11', '12'))
),

latest_exch as (
    select
        1.0 / nullif(max(case when b.period = (select max(period) from {{ ref('exch_spot_rate_china') }}) then b.rate end), 0) as china_rmb_usd,
        1.0 / nullif(max(case when e.period = (select max(period) from {{ ref('exch_spot_rate_euro') }}) then e.rate end), 0)   as evd_eur_usd
    from {{ ref('exch_spot_rate_china') }} as b
    full outer join {{ ref('exch_spot_rate_euro') }} as e
        on b.period = e.period
),

calculated_addons as (
    select
        b.*,
        case
            when b.days_overdue < -30                        then 'Due > 30 D'
            when b.days_overdue < 0 and b.days_overdue >= -30 then 'Due < 30 D'
            when b.days_overdue between 0  and 30            then 'PD 0 to 30 D'
            when b.days_overdue between 31 and 60            then 'PD 31 to 60 D'
            when b.days_overdue between 61 and 90            then 'PD 61 to 90 D'
            when b.days_overdue > 90                         then 'PD > 90 D'
        end as open_group,
        b.amt    * b.ent_currency_conversion_rate as amount_local_currency,
        b.op_amt * b.ent_currency_conversion_rate as open_amount_local_currency,
        case
            when b.database = 'EVD'   and b.entered_currency = 'EURO' then cross_r.evd_eur_usd
            when b.database = 'CHINA' and b.entered_currency = 'RMB'  then cross_r.china_rmb_usd
            else 1
        end as latest_x_rate
    from ar_base as b
    cross join latest_exch as cross_r
),

final as (
    select
        *,
        latest_x_rate * amt    as amount_in_usd,
        latest_x_rate * op_amt as open_amount_in_usd
    from calculated_addons
)

select * from final