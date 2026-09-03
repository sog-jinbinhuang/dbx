with ytd as (
    select
        cast(date_format(date_trunc('year', current_date), 'yyyyMM') as integer) as start_period,
        cast(date_format(current_date, 'yyyyMM') as integer)                      as end_period
),

-- one class per (source_database, product_key) so the join can't fan out the
-- transaction rows (which would inflate the summed kg). Dry % is a product-
-- level attribute (um_conversion_percentage), so it rides along on the same
-- join — mirrors how FCT_GLOBAL_INVENTORY derives dry_percent from
-- prod.um_conversion_percentage / 100.
product_lookup as (
    select source_database, product_key, product_class, product_name, dry_percent
    from (
        select
            source_database,
            product_key,
            product_class,
            product_name,
            um_conversion_percentage / 100 as dry_percent,
            row_number() over (
                partition by source_database, product_key
                order by product_class
            ) as rn
        from {{ ref('stg_product') }}
    )
    where rn = 1
),

transactions as (
    select
        t.source_database,
        t.prod_pkg_code,
        prod.product_class,
        prod.product_name,
        case upper(t.module_id)
            when 'M/G' then 'Production'
            when 'P/O' then 'Purchase'
            when 'I/C' then 'Warehouse Transfer'
            when 'O/E' then 'Sales'
            else            'Other'
        end as transaction_category,

        case
            when lower(t.unit_of_meas) = 'e'
                then (t.amount * coalesce(try_cast(t.measure as decimal(18,4)), 1)) / coalesce(uom_w.conversion, 1)
            else
                t.amount / coalesce(uom.conversion, 1)
        end * t.inv_mult_1                      as amount_kg,

        -- dry-kg equivalent — same fallback rule as FCT_GLOBAL_INVENTORY's
        -- qty_in_dkg: no dry % on file means treat the row as fully dry
        case
            when coalesce(prod.dry_percent, 0) = 0
                then
                    case
                        when lower(t.unit_of_meas) = 'e'
                            then (t.amount * coalesce(try_cast(t.measure as decimal(18,4)), 1)) / coalesce(uom_w.conversion, 1)
                        else
                            t.amount / coalesce(uom.conversion, 1)
                    end * t.inv_mult_1
            else
                case
                    when lower(t.unit_of_meas) = 'e'
                        then (t.amount * coalesce(try_cast(t.measure as decimal(18,4)), 1)) / coalesce(uom_w.conversion, 1)
                    else
                        t.amount / coalesce(uom.conversion, 1)
                end * t.inv_mult_1 * prod.dry_percent
        end                                      as amount_dkg

    from {{ ref('stg_inv_transact') }} t
    left join product_lookup as prod
        on prod.source_database = t.source_database
        and prod.product_key    = t.product_key
    left join {{ ref('weight_conversion') }} as uom_w
        on lower(t.cost_um)      = lower(uom_w.weight)
    left join {{ ref('weight_conversion') }} as uom
        on lower(t.unit_of_meas) = lower(uom.weight)
        and lower(t.unit_of_meas) != 'e'
    cross join ytd
    where t.year_period between ytd.start_period
                            and ytd.end_period
      and t.inv_mult_1  != 0
      and t.posting_year >= year(current_date) - 2
),

aggregated as (
    select
        source_database,
        prod_pkg_code,
        product_class,
        product_name,
        sum(case when transaction_category = 'Production'
            then amount_kg else 0 end)          as production_kg,
        sum(case when transaction_category = 'Production'
            then amount_dkg else 0 end)         as production_dkg,
        sum(case when transaction_category = 'Purchase'
            then amount_kg else 0 end)          as purchase_kg,
        sum(case when transaction_category = 'Sales'
            then amount_kg else 0 end)          as sales_kg,
        sum(case when transaction_category = 'Warehouse Transfer'
            then amount_kg else 0 end)          as warehouse_transfer_kg,
        sum(case when transaction_category = 'Other'
            then amount_kg else 0 end)          as other_kg,
        sum(amount_kg)                          as total_net_kg
    from transactions
    group by 1, 2, 3, 4
)

select
    a.*,
    y.start_period,
    y.end_period
from aggregated a
cross join ytd y