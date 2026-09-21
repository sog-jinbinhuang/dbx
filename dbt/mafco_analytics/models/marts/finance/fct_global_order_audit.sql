with base_data as (
    select 
        order_hdr.source_database as oh_database,
        order_trl.source_database as ot_database,
        cust.source_database as cu_database,
        product.source_database as pr_database,
        packaging.source_database as pa_database,
        country.source_database as co_database,
        whs_prod_pkg.source_database as wh_database,
        abs(order_hdr.order_num) as order_num,
        order_hdr.created_by,
        order_hdr.created_date,
        order_hdr.default_ship_from_warehouse,
        cust.group_id,
        cust.cust_division,
        cust.cust_name,
        order_hdr.customer_po_num,
        product.product_division,
        product.product_class,
        order_trl.product_code,
        order_trl.prod_pkg_code,
        product.product_name,
        order_hdr.order_open_amount,
        order_trl.sale_um,
        order_trl.quantity_ordered,
        order_trl.quantity_open,
        order_trl.quantity_shipped,
        order_trl.qty_um,
        order_trl.delivery_date,
        order_trl.sale_measure,
        order_hdr.ship_date,
        cust.cust_code,
        product.um_conversion_percentage,
        order_trl.gross_price,
        order_trl.price_um,
        order_trl.net_price,
        order_hdr.order_currency,
        order_hdr.order_date,
        packaging.unit_of_meas as pkg_um,
        packaging.measure as pkg_measure,
        cust.territory,
        cust.industry_code,
        country.country_name,
        whs_prod_pkg.average_cost,
        whs_prod_pkg.standard_cost,
        order_hdr.sales_agent_id as sa_id,
        country.system_id,
        cust.active as active_customer,
        cust.default_sales_agent as sales_agent,
        cust.default_sales_agent_2 as sales_agent2,
        cust.customer_class,
        order_hdr.shipto_state,
        order_hdr.shipto_country,
        order_hdr.shipto_zip,
        order_hdr.shipto_address_1,
        order_hdr.shipto_address_2,
        order_hdr.shipto_address_3,
        order_hdr.shipto_city,
        order_hdr.fob_remark,
        order_hdr.ship_mode,
        order_hdr.freight_terms,
        order_hdr.freight_cost,
        order_hdr.shipper_id
    from {{ ref('stg_country') }} as country
    join {{ ref('stg_cust') }} as cust
        on cust.source_database = country.source_database
        and cust.country = country.country_code
        and cust.system_id = country.system_id
    join {{ ref('stg_order_hdr') }} as order_hdr
        on order_hdr.source_database = cust.source_database
        and order_hdr.cust_key = cust.cust_key
        and order_hdr.system_id = cust.system_id
    join {{ ref('stg_order_trl') }} as order_trl
        on order_trl.source_database = order_hdr.source_database
        and order_trl.system_id = order_hdr.system_id
        and order_trl.order_num = order_hdr.order_num
    join {{ ref('stg_product') }} as product
        on product.source_database = order_trl.source_database
        and product.system_id = order_trl.system_id
        and product.product_key = order_trl.product_key
    join {{ ref('stg_packaging') }} as packaging
        on packaging.source_database = order_trl.source_database
        and packaging.packaging_code = order_trl.packaging_code
        and packaging.system_id = order_trl.system_id
    join {{ ref('stg_whs_prod_pkg') }} as whs_prod_pkg
        on whs_prod_pkg.source_database = order_trl.source_database
        and whs_prod_pkg.system_id = order_trl.system_id
        and whs_prod_pkg.packaging_key = order_trl.packaging_key
        and whs_prod_pkg.product_key = order_trl.product_key
        and whs_prod_pkg.facility = order_trl.ship_from_warehouse
    where order_hdr.created_date >= dateadd(day, -7, current_date())
      -- dateadd(unit, value, expr) is supported as-is in Databricks SQL
      -- (Databricks Runtime 10.4+, same syntax as Snowflake) -- no
      -- conversion needed here.
      and order_trl.cancelled = false
      and order_trl.closed = false
),

---------------------------------------------------------
-- step 2: kg & forex
---------------------------------------------------------
step_02 as (
    select
        b.*,
        'SYSTEM_ID2' as system_id2,
        b.order_open_amount as order_open_amount3,
        b.pr_database as database,
        b.freight_cost as freight_cost_extended,
        -- open_qty_in_kg: E-case uses pkg_um (w1); non-E uses price_um (w2)
        case
            when upper(b.qty_um) in ('E', '', null)
            then b.quantity_open * b.pkg_measure / nullif(w1.conversion, 0)
            else b.quantity_open / nullif(w2.conversion, 0)
        end as open_qty_in_kg,
        -- usd_sales_x_rate: latest available period rate (max period join)
        case
            when b.pr_database = 'WEIFENG' then 1
            when b.pr_database = 'CHINA'   then exch_china.rate
            when b.pr_database = 'EVD'     then exch_euro.rate
            when b.pr_database = 'US' and upper(b.order_currency) = 'USD'  then 1
            when b.pr_database = 'US' and upper(b.order_currency) <> 'USD' then 1 / nullif(exch_euro.rate, 0)
        end as usd_sales_x_rate,
        -- price_per_kg: E-case uses pkg_um (w1); non-E uses price_um (w2)
        case
            when upper(b.price_um) = 'E'
            then (b.gross_price / nullif(b.pkg_measure, 0)) * w1.conversion
            else b.gross_price * w2.conversion
        end as price_per_kg,
        -- cost_per_kg: US/EVD standard cost via pkg_um (w1); CHINA/WEIFENG average cost via price_um (w2)
        case
            when b.pr_database in ('US', 'EVD') then b.standard_cost * w1.conversion
            else                                      b.average_cost  * w2.conversion
        end as cost_per_kg
    from base_data b
    left join {{ ref('weight_conversion') }} as w1
        on upper(b.pkg_um) = upper(w1.weight)
    left join {{ ref('weight_conversion') }} as w2
        on upper(b.price_um) = upper(w2.weight)
    left join {{ ref('exch_rate_china') }} as exch_china
        on b.pr_database = 'CHINA'
        and exch_china.period = (select max(period) from {{ ref('exch_rate_china') }})
    left join {{ ref('exch_rate_euro') }} as exch_euro
        on b.pr_database = 'EVD'
        and exch_euro.period = (select max(period) from {{ ref('exch_rate_euro') }})
    where year(b.order_date) > 2007
),

---------------------------------------------------------
-- step 3: financials
---------------------------------------------------------
financials as (
    select
        s2.*,
        -- price_per_kg_local_currency: WEIFENG/US always multiply by rate;
        -- CHINA/EVD only multiply when order currency is USD; otherwise pass through raw
        case
            when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
            when s2.pr_database in ('CHINA', 'EVD') and upper(s2.order_currency) = 'USD' then s2.price_per_kg * s2.usd_sales_x_rate
            else s2.price_per_kg
        end as price_per_kg_local_currency,
        -- cost_per_kg_local_currency: no rate applied — warehouse cost is already in local currency
        s2.cost_per_kg as cost_per_kg_local_currency,
        (
            case
                when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                when s2.pr_database in ('CHINA', 'EVD') and upper(s2.order_currency) = 'USD' then s2.price_per_kg * s2.usd_sales_x_rate
                else s2.price_per_kg
            end
            - s2.cost_per_kg
        ) as profit_per_kg_local_currency,
        (
            case
                when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                when s2.pr_database in ('CHINA', 'EVD') and upper(s2.order_currency) = 'USD' then s2.price_per_kg * s2.usd_sales_x_rate
                else s2.price_per_kg
            end
            * s2.open_qty_in_kg
        ) as ext_price_local_currency,
        (s2.cost_per_kg * s2.open_qty_in_kg) as ext_cost_local_currency,
        (
            (
                case
                    when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                    when s2.pr_database in ('CHINA', 'EVD') and upper(s2.order_currency) = 'USD' then s2.price_per_kg * s2.usd_sales_x_rate
                    else s2.price_per_kg
                end
                * s2.open_qty_in_kg
            )
            - (s2.cost_per_kg * s2.open_qty_in_kg)
        ) as ext_profit_local_currency,
        -- price_per_kg_in_usd: WEIFENG/US multiply rate; CHINA/EVD divide local price by rate
        case
            when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
            when s2.pr_database in ('CHINA', 'EVD')  then
                case
                    when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                    when upper(s2.order_currency) = 'USD'    then s2.price_per_kg * s2.usd_sales_x_rate
                    else s2.price_per_kg
                end / nullif(s2.usd_sales_x_rate, 0)
        end as price_per_kg_in_usd,
        -- cost_per_kg_in_usd: WEIFENG/US use local cost as-is; CHINA/EVD divide by rate
        case
            when s2.pr_database in ('WEIFENG', 'US') then s2.cost_per_kg
            when s2.pr_database in ('CHINA', 'EVD')  then s2.cost_per_kg / nullif(s2.usd_sales_x_rate, 0)
        end as cost_per_kg_in_usd,
        (
            case
                when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                when s2.pr_database in ('CHINA', 'EVD')  then
                    case
                        when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                        when upper(s2.order_currency) = 'USD'    then s2.price_per_kg * s2.usd_sales_x_rate
                        else s2.price_per_kg
                    end / nullif(s2.usd_sales_x_rate, 0)
            end
            -
            case
                when s2.pr_database in ('WEIFENG', 'US') then s2.cost_per_kg
                when s2.pr_database in ('CHINA', 'EVD')  then s2.cost_per_kg / nullif(s2.usd_sales_x_rate, 0)
            end
        ) as profit_per_kg_in_usd,
        (
            case
                when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                when s2.pr_database in ('CHINA', 'EVD')  then
                    case
                        when s2.pr_database in ('WEIFENG', 'US') then s2.price_per_kg * s2.usd_sales_x_rate
                        when upper(s2.order_currency) = 'USD'    then s2.price_per_kg * s2.usd_sales_x_rate
                        else s2.price_per_kg
                    end / nullif(s2.usd_sales_x_rate, 0)
            end
            * s2.open_qty_in_kg
        ) as ext_price_in_usd,
        (
            case
                when s2.pr_database in ('WEIFENG', 'US') then s2.cost_per_kg
                when s2.pr_database in ('CHINA', 'EVD')  then s2.cost_per_kg / nullif(s2.usd_sales_x_rate, 0)
            end
            * s2.open_qty_in_kg
        ) as ext_cost_in_usd
    from step_02 s2
),

---------------------------------------------------------
-- step 4: dates & division
---------------------------------------------------------
dates_enriched as (
    select
        f.*,
        (f.ext_price_in_usd - f.ext_cost_in_usd) as ext_profit_in_usd,
        year(f.ship_date) as year,
        coalesce(
            case
                when f.pr_database in ('CHINA', 'WEIFENG') then month(f.ship_date)
                when f.ship_date > (select max(period_end_date) from {{ ref('period_2016') }}) then month(f.ship_date)
                else p.month_number
            end,
            month(f.ship_date)
        ) as month,
        f.open_qty_in_kg * f.um_conversion_percentage / 100 as qty_in_drykg,
        date_part('week', f.ship_date) as week,
        f.open_qty_in_kg as qty_in_kg,
        -- iff() is Snowflake-specific -- Databricks uses if(), same argument order
        if(f.group_id is null or f.group_id = '', f.cust_name, f.group_id) as cust_group,
        case
            when upper(f.database) in ('WEIFENG', 'CHINA') and year(f.ship_date) > 0 then 'CHINA'
            when upper(f.database) = 'EVD'                 and year(f.ship_date) > 0 then 'FRANCE'
            when upper(f.database) = 'US'                  and year(f.ship_date) > 0 then 'USA'
            else '?????'
        end as division
    from financials as f
    left join {{ ref('period_2016') }} as p
        on f.ship_date between p.period_begin_date and p.period_end_date
        and f.ship_date <= (select max(period_end_date) from {{ ref('period_2016') }})
),

---------------------------------------------------------
-- step 5: segmentation
---------------------------------------------------------
segmentation as (
    select
        d.*,
        concat(d.cust_group, d.product_code) as group_product_n,
        concat(d.cust_name, d.product_name)  as cust_product_n,
        case
            when d.month >= 10 then concat(d.year, d.month)
            else concat(d.year, '0', d.month)
        end as year_period,
        case
            when d.month < 4                   then 'Q1'
            when d.month >= 4 and d.month < 7  then 'Q2'
            when d.month >= 7 and d.month < 10 then 'Q3'
            else                                    'Q4'
        end as quarter,
        'ORDER' as sales_or_order,
        case
            when d.division in ('FRANCE', 'USA')
                 and upper(d.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(d.product_class) in ('GP FIN GDS')
            then 'GARDEN PRODUCTS'
            when (upper(d.database) = 'US'  and d.cust_code in ('1505','1581','3011','3111','3059','3203','3204'))
              or (upper(d.database) = 'EVD' and d.cust_code in ('15003') and upper(d.product_code) in ('FL5019'))
              or (upper(d.database) = 'US'  and d.cust_code in ('2122')  and upper(d.product_code) in ('FL5019'))
            then 'INDUSTRIAL'
            when (d.database = 'WEIFENG' and d.cust_code in ('54', '56'))
              or (d.database = 'US'      and d.cust_code in ('1663'))
            then 'MAGNASWEET'
            when d.division = 'CHINA'
                 and upper(d.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(d.product_class) in ('CWE','GP FIN GDS','INTERM-CGA','LIC FIN GDS','LIC OTHER RM','LIC RESALE','MAG OTHER RM','MAG RESALE','MAG-BYPROD','MAG-REF-CMAG','MAG-REFINED','MAGSW FIN GD','NAT PROD RM','NATP RM-IMPT','NATPRDFINGDS','NATPRDRESALE','REMELTS','RM-OTHER','ROOT')
            then 'PURE DERIVATIVES'
            when d.division in ('FRANCE', 'USA')
                 and upper(d.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(d.product_class) in ('INTERM-CGA','MAG OTHER RM','MAG RESALE','MAG-BYPROD','MAG-REF-CMAG','MAG-REFINED','MAGSW FIN GD')
            then 'MAGNASWEET'
            when d.division in ('FRANCE', 'USA')
                 and upper(d.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(d.product_class) in ('CWE','LIC FIN GDS','LIC OTHER RM','LIC RESALE','NAT PROD RM','NATP RM-IMPT','NATPRDFINGDS','NATPRDRESALE','REMELTS','RM-OTHER','ROOT')
                 and upper(d.industry_code) not in ('TOBACCO')
            then 'CONFECTION'
            when d.division in ('FRANCE', 'USA')
                 and upper(d.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(d.product_class) in ('CWE','LIC FIN GDS','LIC OTHER RM','LIC RESALE','NAT PROD RM','NATP RM-IMPT','NATPRDFINGDS','NATPRDRESALE','REMELTS','RM-OTHER','ROOT')
                 and upper(d.industry_code) = 'TOBACCO'
            then 'TOBACCO'
            -- no ELSE: NULL segment is intentional for unmatched rows, matching VW_ORDERS exactly
        end as segment
    from dates_enriched d
),

---------------------------------------------------------
-- step 6: pre-union prep
---------------------------------------------------------
final_prep as (
    select
        s.*,
        concat(s.customer_class, s.segment, s.cust_group, s.product_name) as region_segment_group_product_n,
        concat(s.customer_class, s.segment, s.cust_name,  s.product_name) as region_segment_cust_product_n,
        concat(s.customer_class, s.segment)                               as region_segment,
        concat(s.customer_class, s.segment, s.cust_group)                 as region_segment_group
    from segmentation s
)

---------------------------------------------------------
-- output select
---------------------------------------------------------
select
    o.database,
    o.created_by,
    o.created_date,
    o.cust_name,
    o.order_num,
    o.ext_price_in_usd as revenue,
    o.qty_in_kg
from final_prep as o
where upper(o.cust_division) in ('EVD', 'THIRD PARTY')
  and upper(o.product_class) in (
      'INTERM-CGA', 'LIC FIN GDS', 'MAG-BYPROD', 'MAG-REF-CMAG',
      'MAG-REFINED', 'MAGSW FIN GD', 'NAT PROD RM', 'NATPRDFINGDS',
      'REMELTS'
  )