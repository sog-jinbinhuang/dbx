with stg_cust_prod_price as (
    select * from {{ ref('stg_cust_prod_price') }}
),

stg_cust as (
    select * from {{ ref('stg_cust') }}
),

stg_product as (
    select * from {{ ref('stg_product') }}
),

-- from_date/to_date are already real DATE columns coming out of stg_cust_prod_price,
-- so no re-parsing is needed here (unlike the original Snowflake version, which
-- received them as strings). Kept as their own CTE for structural parity.
price_cleaned as (
    select
        *,
        from_date                                               as from_date_clean,
        to_date                                                  as to_date_clean
    from stg_cust_prod_price
),

-- filter to current active prices only
current_prices as (
    select *
    from price_cleaned
    where to_date_clean is null
       or to_date_clean >= current_date()
),

final as (
    select
        -- keys
        cp.source_database,
        cp.cust_id,
        c.cust_name,
        cp.product_code,
        p.product_name,
        cp.prod_pkg_code,
        cp.currency,
        cp.from_date_clean                                      as price_from_date,
        cp.to_date_clean                                        as price_to_date,
        cp.sale_measure,
        cp.sale_um,

        -- original contracted price as-is
        cp.breaks_price_1                                       as price,

        -- price converted to per kg
        cast(
            case
                when upper(cp.sale_um) = 'E'
                then (cp.breaks_price_1 / nullif(cp.sale_measure, 0)) * w.conversion
                else cp.breaks_price_1 * w.conversion
            end
        as decimal(18, 6))                                       as price_per_kg,

        -- price per kg in USD at fixed budget rates
        cast(
            case
                when upper(cp.sale_um) = 'E'
                then (cp.breaks_price_1 / nullif(cp.sale_measure, 0)) * w.conversion
                else cp.breaks_price_1 * w.conversion
            end /
            case
                when upper(cp.currency) = 'EURO' then 0.8547
                when upper(cp.currency) = 'RMB'  then 7.1429
                when upper(cp.currency) = 'GBP' then 0.7874 
                else 1
            end
        as decimal(18, 6))                                       as price_per_kg_usd

    from current_prices cp
    left join stg_cust c
        on  cp.source_database = c.source_database
        and cp.cust_id         = c.cust_code
    left join stg_product p
        on  cp.source_database = p.source_database
        and cp.product_code    = p.product_code
    left join {{ ref('weight_conversion') }} as w
        on upper(cp.sale_um)   = upper(w.weight)
)

select * from final