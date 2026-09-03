with base as (
    select
        lot.source_database              as lot_database,
        prod.source_database             as prod_database,
        pkg.source_database              as pkg_database,
        prod.product_code,
        lot.prod_pkg_code,
        prod.product_name,
        prod.product_class,
        prod.product_division,
        prod.product_type,
        lot.inv_amount_10                as inv_amount_fifo,
        lot.inv_amount_1                 as inv_amount_wpl,
        pkg.inv_amount                   as inv_amount_wp,
        lot.unit_of_meas,
        -- cost basis
        lot2.average_cost                as avg_cost_lot,   -- lot-grain (varies by lot)
        pkg.average_cost                 as avg_cost_wp,     -- warehouse-product pool average
        lot.last_cost                    as last_cost_wpl,
        pkg.standard_cost                as std_cost_wp,
        lot.weight_um,
        lot.weight,
        prod.use_fifo,
        prod.lot_controlled,
        lot.facility,
        lot.active,
        lot.lot_code,
        lot.created_date                 as lot_date,
        prod.um_conversion_percentage, 
        lot2.description                 as lot_description,
        lot2.long_description,
        lot2.created_date                as lot_created_date,
        lot2.expiration_date             as lot_expiration_date,
        lot2.supplier_lot_code           as lot_supplier_lot_code,
        lot2.internal_key                as lot_internal_key,
        rem.remark_data,
        sup.supplier_name,
        sup.supplier_code,
        lot.source_database              as database,
        pp.average_cost as avg_cost_pp
    from {{ ref('stg_prod_pkg_whs_lot') }} as lot
    join {{ ref('stg_product') }} as prod
        on prod.source_database = lot.source_database
        and prod.product_key    = lot.product_key
        and prod.system_id      = lot.system_id
    join {{ ref('stg_lot') }} as lot2
        on prod.source_database = lot2.source_database
        and lot.lot_code        = lot2.lot_code
        and lot.product_key     = lot2.product_key
        and lot.packaging_key   = lot2.packaging_key
    join {{ ref('stg_whs_prod_pkg') }} as pkg
        on pkg.source_database  = lot.source_database
        and pkg.system_id       = lot.system_id
        and pkg.packaging_key   = lot.packaging_key
        and pkg.product_key     = lot.product_key
        and pkg.facility        = lot.facility
        and pkg.source_database = prod.source_database
        and pkg.product_key     = prod.product_key
        and pkg.system_id       = prod.system_id
    left join {{ ref('stg_remarks') }} as rem
        on lot2.internal_key    = rem.remark_key
        and lot2.source_database = rem.source_database
        and lower(rem.remark_type) = 'lot'
    left join {{ ref('stg_suppname') }} as sup
        on lot2.supplier_id     = sup.supplier_code
        and lot2.source_database = sup.source_database
    join {{ ref('stg_prod_pkg') }} as pp
        on pp.source_database = lot.source_database
        and pp.product_key    = lot.product_key
        and pp.packaging_key  = lot.packaging_key
    where pkg.active = 'TRUE'
        and pkg.facility not like 'TBD_WHS'
),

calc1 as (
    select
        b.*,
        case b.database
            when 'US'  then 'USA'
            when 'EVD' then 'FRANCE'
            else 'CHINA'
        end as division,
        case
            when lower(b.unit_of_meas) = 'e'
                then (b.inv_amount_wpl * b.weight) / coalesce(uom_w.conversion, 1)
            else b.inv_amount_wpl / coalesce(uom.conversion, 1)
        end as qty_in_kg,
        -- per-kg cost: lot actual drives valuation; WP average kept as reference
        b.avg_cost_lot * coalesce(uom.conversion, 1) as cost_kg,
        b.avg_cost_wp  * coalesce(uom.conversion, 1) as cost_kg_wp,
        b.avg_cost_pp  * coalesce(uom.conversion, 1) as cost_kg_pp,
        b.um_conversion_percentage / 100             as dry_percent
    from base b
    left join {{ ref('weight_conversion') }} as uom_w
        on lower(b.weight_um)    = lower(uom_w.weight)
    left join {{ ref('weight_conversion') }} as uom
        on lower(b.unit_of_meas) = lower(uom.weight)
),

calc2 as (
    select
        c.*,
        c.qty_in_kg * c.cost_kg    as extension,        -- valued at the lot's own cost
        c.qty_in_kg * c.cost_kg_wp as extension_wp,     -- valued at warehouse-product pool average
        c.qty_in_kg * c.cost_kg_pp as extension_pp,
        case
            when c.dry_percent = 0 then c.qty_in_kg
            else c.qty_in_kg * c.dry_percent
        end as qty_in_dkg,
        case
            when c.dry_percent = 0 then c.cost_kg
            else c.cost_kg / nullif(c.dry_percent, 0)
        end as cost_dkg,
        case
            when c.dry_percent = 0 then c.cost_kg_wp
            else c.cost_kg_wp / nullif(c.dry_percent, 0)
        end as cost_dkg_wp,
        case
            when c.dry_percent = 0 then c.cost_kg_pp
            else c.cost_kg_pp / nullif(c.dry_percent, 0)
        end as cost_dkg_pp
    from calc1 c
),

final_calcs as (
    select
        u.*,
        case
            when u.database = 'EVD'   then u.cost_kg / nullif(er_eu.rate, 0)
            when u.database = 'CHINA' then u.cost_kg / nullif(er_ch.rate, 0)
            else u.cost_kg
        end as cost_kg_usd,
        case
            when u.database = 'EVD'   then u.cost_kg_wp / nullif(er_eu.rate, 0)
            when u.database = 'CHINA' then u.cost_kg_wp / nullif(er_ch.rate, 0)
            else u.cost_kg_wp
        end as cost_kg_wp_usd,
        case
            when u.database = 'EVD'   then u.cost_kg_pp / nullif(er_eu.rate, 0)   -- ← new
            when u.database = 'CHINA' then u.cost_kg_pp / nullif(er_ch.rate, 0)
            else u.cost_kg_pp
        end as cost_kg_pp_usd,
        case
            when u.database = 'EVD'   then u.extension / nullif(er_eu.rate, 0)
            when u.database = 'CHINA' then u.extension / nullif(er_ch.rate, 0)
            else u.extension
        end as extension_usd,
        case
            when u.database = 'EVD'   then u.extension_wp / nullif(er_eu.rate, 0)
            when u.database = 'CHINA' then u.extension_wp / nullif(er_ch.rate, 0)
            else u.extension_wp
        end as extension_wp_usd,
        case
            when u.database = 'EVD'   then u.extension_pp / nullif(er_eu.rate, 0)   -- ← new
            when u.database = 'CHINA' then u.extension_pp / nullif(er_ch.rate, 0)
            else u.extension_pp
        end as extension_pp_usd,
        case
            when u.database = 'EVD'   then u.cost_dkg / nullif(er_eu.rate, 0)
            when u.database = 'CHINA' then u.cost_dkg / nullif(er_ch.rate, 0)
            else u.cost_dkg
        end as cost_dkg_usd,
        case
            when u.database = 'EVD'   then u.cost_dkg_wp / nullif(er_eu.rate, 0)
            when u.database = 'CHINA' then u.cost_dkg_wp / nullif(er_ch.rate, 0)
            else u.cost_dkg_wp
        end as cost_dkg_wp_usd,
        case
            when u.database = 'EVD'   then u.cost_dkg_pp / nullif(er_eu.rate, 0)
            when u.database = 'CHINA' then u.cost_dkg_pp / nullif(er_ch.rate, 0)
            else u.cost_dkg_pp
        end as cost_dkg_pp_usd,
        datediff(current_date, u.lot_created_date) as days_old
    from calc2 u
    
    left join {{ ref('exch_rate_euro') }} as er_eu
        on er_eu.period = cast(date_format(current_date, 'yyyyMM') as integer)
    left join {{ ref('exch_rate_china') }} as er_ch
        on er_ch.period = cast(date_format(current_date, 'yyyyMM') as integer)
),

final as (
    select
        f.*,
        case
            when f.days_old <= 30  then '0-30 Days'
            when f.days_old <= 90  then '31-90 Days'
            when f.days_old <= 180 then '91-180 Days'
            else 'Over 180 Days'
        end as aging_bucket,
        case
            when upper(f.product_class) in ('INTERM-CGA', 'INTERM-CGAFG') then 'CRUDE DERIVATIVES'
            when upper(f.product_class) in ('MAG-BYPROD')                  then 'DERIVATIVES BYPRODUCTS'
            when upper(f.product_class) in ('MAGSW FIN GD')                then 'MAGNASWEET'
            when upper(f.product_class) in ('REMELTS')                     then 'REMELTS'
        end as product_category
    from final_calcs f
)

select * from final