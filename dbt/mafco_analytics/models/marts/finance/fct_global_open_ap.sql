
with ap_base as (
    select
        a.source_database as database,
        case
            when a.source_database in ('CHINA', 'WEIFENG') then 'CHINA'
            else a.source_database
        end as division,
        case
            when a.source_database = 'CHINA' and substr(cast(g.gl_acct as string), 1, 2) in ('72') then 'ZFTZ'
            when a.source_database = 'CHINA' and substr(cast(g.gl_acct as string), 1, 2) in ('78') then 'SHMF'
            when a.source_database = 'WEIFENG' then 'WFHK'
            when a.source_database = 'MAFCO' then 'MAFWW'
            else a.source_database
        end as company,
        case
            when a.voucher_type = 'DM' then -a.amount
            else a.amount
        end as amt,
        case
            when a.voucher_type = 'DM' then -a.open_amount
            else a.open_amount
        end as op_amt,
        a.voucher_type,
        a.voucher_number,
        a.reference_number,
        cast(a.invoice_date as date) as invoice_date,
        cast(a.due_date as date) as due_date,
        datediff(cast(a.due_date as date), current_date()) as open_days,
        a.entered_currency,
        a.convert_to_currency as local_currency,
        a.ent_currency_conversion_rate,
        a.po_number,
        a.inv_status,
        s.supplier_code,
        s.supplier_name,
        g.gl_acct
    from {{ ref('stg_apinvhdr') }} as a
    inner join {{ ref('stg_suppname') }} as s
        on a.supplier_key = s.supplier_key
        and a.source_database = s.source_database
        and a.system_id = s.system_id
    inner join {{ ref('stg_gl_accts') }} as g
        on a.ap_gl_acct_ptr = g.gl_acct_ptr
        and a.source_database = g.source_database
        and a.system_id = g.system_id
    where a.open_amount <> 0
        and a.closed = false
        and a.inv_status <> 'VOIDED'
        and not (a.source_database = 'US'   and s.supplier_code in ('3767','5539','5235','4624','6189','6087','6445','5539'))
        and not (a.source_database = 'CHINA' and s.supplier_code in ('579', '6', '576'))
        and not (a.source_database = 'EVD'    and s.supplier_code in ('367', '368', '574'))
        and not (a.source_database = 'WEIFENG'    and s.supplier_code in ('88', '7', '4'))
),

latest_rates as (
    select
        1.0 / nullif(max(case when b.period = (select max(period) from {{ ref('exch_spot_rate_china') }}) then b.rate end), 0) as rmb_usd,
        1.0 / nullif(max(case when e.period = (select max(period) from {{ ref('exch_spot_rate_euro') }})  then e.rate end), 0) as eur_usd,
        1.0 / nullif(max(case when c.period = (select max(period) from {{ ref('exch_spot_rate_chile') }}) then c.rate end), 0) as clp_usd
    from {{ ref('exch_spot_rate_china') }} as b
    full outer join {{ ref('exch_spot_rate_euro') }}  as e on b.period = e.period
    full outer join {{ ref('exch_spot_rate_chile') }} as c on b.period = c.period
),

calculated_xrate as (
    select
        b.*,
        case
            when b.open_days > 30                       then 'DUE IN > 30 DAYS'
            when b.open_days >= 0                         then 'DUE IN <= 30 DAYS'
            when -b.open_days between 1  and 30         then 'PAST DUE 0 TO 30 DAYS'
            when -b.open_days between 31 and 60         then 'PAST DUE 31 TO 60 DAYS'
            when -b.open_days between 61 and 90         then 'PAST DUE 61 TO 90 DAYS'
            when -b.open_days > 90                      then 'PAST DUE > 90 DAYS'
        end as open_group,
        b.amt    * b.ent_currency_conversion_rate       as amount_local_currency,
        b.op_amt * b.ent_currency_conversion_rate       as open_amount_local_currency,
        case
            when b.entered_currency = 'RMB'  then lr.rmb_usd
            when b.entered_currency = 'EURO' then lr.eur_usd
            when b.entered_currency = 'CLP'  then lr.clp_usd
            else 1
        end as latest_x_rate
    from ap_base as b
    cross join latest_rates as lr
),

final as (
    select
        *,
        latest_x_rate * amt    as amount_in_usd,
        latest_x_rate * op_amt as open_amount_in_usd
    from calculated_xrate
)

select * from final