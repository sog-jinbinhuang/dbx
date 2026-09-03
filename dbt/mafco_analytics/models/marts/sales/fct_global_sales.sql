with base_data as (
    select
        invoice_hdr.source_database as ih_database,
        invoice_trl.source_database as it_database,
        cust.source_database as cu_database,
        product.source_database as pr_database,
        packaging.source_database as pa_database,
        country.source_database as co_database,
        order_hdr.source_database as oh_database,
        invoice_hdr.ref_type,
        abs(invoice_hdr.invoice_num) as invoice_num,
        abs(invoice_hdr.order_num) as order_num,
        invoice_hdr.year_period,
        invoice_hdr.invoice_date,
        order_hdr.order_date,
        invoice_hdr.default_ship_from_warehouse,
        cust.cust_division,
        country.country_name,
        cust.cust_code,
        invoice_hdr.sales_agent_id,
        cust.cust_name,
        order_hdr.customer_po_num,
        product.product_division,
        product.product_class,
        product.product_code,
        invoice_trl.prod_pkg_code,
        product.product_name,
        product.um_conversion_percentage,
        invoice_trl.gross_price,
        invoice_trl.price_um,
        invoice_trl.cost,
        invoice_trl.cogs,
        invoice_trl.quantity_shipped,
        invoice_trl.qty_um,
        invoice_hdr.invoice_amount,
        invoice_hdr.invoice_currency_conversion_rate,
        invoice_hdr.invoice_currency,
        invoice_hdr.cogs_currency_conversion_rate,
        invoice_hdr.invoice_currency_conversion_date,
        invoice_hdr.journal_number,
        invoice_hdr.cogs_journal_number,
        packaging.unit_of_meas as package_um,
        packaging.measure as package_measure,
        cust.group_id,
        invoice_trl.return_warehouse,
        invoice_trl.cm_dm_type,
        cust.territory,
        cust.industry_code,
        cust.active as active_customer,
        cust.default_sales_agent as sales_agent,
        cust.default_sales_agent_2 as sales_agent2,
        cust.customer_class,
        invoice_hdr.shipto_state,
        invoice_hdr.shipto_country,
        invoice_hdr.shipto_zip,
        invoice_hdr.shipto_address_1,
        invoice_hdr.shipto_address_2,
        invoice_hdr.shipto_address_3,
        invoice_hdr.shipto_city,
        order_hdr.ship_mode,
        order_hdr.freight_terms,
        order_hdr.fob_remark,
        invoice_trl.freight_cost,
        invoice_trl.extended_freight_cost,
        order_hdr.shipper_id
    from {{ ref('stg_invoice_hdr') }} as invoice_hdr
    join {{ ref('stg_invoice_trl') }} as invoice_trl
      on invoice_hdr.source_database = invoice_trl.source_database
      and invoice_hdr.invoice_num = invoice_trl.invoice_num
      and invoice_hdr.system_id = invoice_trl.system_id
    join {{ ref('stg_cust') }} as cust
      on cust.source_database = invoice_hdr.source_database
      and cust.cust_key = invoice_hdr.cust_key
      and cust.system_id = invoice_hdr.system_id
    join {{ ref('stg_product') }} as product
      on product.source_database = invoice_trl.source_database
      and product.product_key = invoice_trl.product_key
      and product.system_id = invoice_trl.system_id
    join {{ ref('stg_country') }} as country
      on country.source_database = invoice_hdr.source_database
      and country.country_code = invoice_hdr.shipto_country
      and country.system_id = invoice_hdr.system_id
    join {{ ref('stg_packaging') }} as packaging
      on packaging.source_database = invoice_trl.source_database
      and packaging.packaging_code = invoice_trl.packaging_code
      and packaging.system_id = invoice_trl.system_id
    join {{ ref('stg_order_hdr') }} as order_hdr
      on order_hdr.source_database = invoice_hdr.source_database
      and order_hdr.order_num = invoice_hdr.order_num
      and order_hdr.system_id = invoice_hdr.system_id
    where invoice_hdr.cancelled = false
      and invoice_hdr.year_period >= 200801
),

---------------------------------------------------------
-- step 2: kg & forex
---------------------------------------------------------
step_02 as (
    select
        b.*,
        b.pr_database as database,
        -- FIX: added cast to decimal(38,18) matching VW_SALES exactly
        case
            when b.qty_um is null or trim(b.qty_um) = '' or upper(b.qty_um) = 'E'
            then cast((b.quantity_shipped * b.package_measure) / nullif(w1.conversion, 0) as decimal(38,18))
            else cast(b.quantity_shipped / nullif(w2.conversion, 0) as decimal(38,18))
        end as shipped_qty_in_kg,
        -- FIX: added cast to decimal(18,6) matching VW_SALES exactly
        cast(case
            when b.pr_database = 'CHINA' and upper(b.invoice_currency) = 'RMB' then exch_c.rate
            when b.pr_database = 'EVD'   and upper(b.invoice_currency) <> 'USD' then exch_e.rate
            when b.pr_database in ('WEIFENG', 'US') then b.invoice_currency_conversion_rate
            else 1
        end as decimal(18,6)) as usd_sales_x_rate,
        -- FIX: added cast to decimal(18,6) matching VW_SALES exactly
        cast(case
            when upper(b.price_um) = 'E'
            then (b.gross_price / nullif(b.package_measure, 0)) * w1.conversion
            else b.gross_price * w3.conversion
        end as decimal(18,6)) as price_per_kg
    from base_data b
    left join {{ ref('weight_conversion') }} as w1 on upper(b.package_um) = upper(w1.weight)
    left join {{ ref('weight_conversion') }} as w2 on upper(b.qty_um)     = upper(w2.weight)
    left join {{ ref('weight_conversion') }} as w3 on upper(b.price_um)   = upper(w3.weight)
    left join {{ ref('exch_rate_china') }} as exch_c
        on b.pr_database = 'CHINA'
        and b.year_period = exch_c.period
    left join {{ ref('exch_rate_euro') }} as exch_e
        on b.pr_database = 'EVD'
        and b.year_period = exch_e.period
),

---------------------------------------------------------
-- step 3: financials
---------------------------------------------------------
financials as (
    select
        s2.*,
        coalesce(s2.cogs / nullif(s2.shipped_qty_in_kg, 0), 0) as cost_per_kg,
        (s2.price_per_kg * s2.invoice_currency_conversion_rate) as price_per_kg_local_currency,
        (coalesce(s2.cogs / nullif(s2.shipped_qty_in_kg, 0), 0) * s2.cogs_currency_conversion_rate) as cost_per_kg_local_currency,
        case
            when s2.database = 'US' then s2.price_per_kg * s2.usd_sales_x_rate
            else s2.price_per_kg / nullif(s2.usd_sales_x_rate, 0)
        end as price_per_kg_in_usd,
        case
            when s2.database = 'US' then (coalesce(s2.cogs / nullif(s2.shipped_qty_in_kg, 0), 0) * s2.usd_sales_x_rate)
            else (coalesce(s2.cogs / nullif(s2.shipped_qty_in_kg, 0), 0) / nullif(s2.usd_sales_x_rate, 0))
        end as cost_per_kg_in_usd
    from step_02 s2
),

---------------------------------------------------------
-- step 4: enrichment
---------------------------------------------------------
enriched as (
    select
        f.*,
        (f.price_per_kg_local_currency - f.cost_per_kg_local_currency) * IF(upper(f.ref_type) = 'CM', -1, 1) as profit_kg_local_currency,
        (f.price_per_kg_local_currency * f.shipped_qty_in_kg) as ext_price_local_currency,
        (f.cost_per_kg_local_currency * f.shipped_qty_in_kg) as ext_cost_local_currency,
        (f.price_per_kg_in_usd * f.shipped_qty_in_kg) as ext_price_in_usd,
        (f.cost_per_kg_in_usd * f.shipped_qty_in_kg) as ext_cost_in_usd,
        (f.shipped_qty_in_kg * f.um_conversion_percentage / 100) as qty_in_drykg,
        substr(f.year_period, 1, 4) as year,
        substr(f.year_period, -2) as month,
        date_part('week', f.invoice_date) as week,
        IF(upper(f.cm_dm_type) = 'PRICE', 0, f.shipped_qty_in_kg) as qty_in_kg,
        coalesce(nullif(f.group_id, ''), f.cust_name) as cust_group,
        case
            when f.database in ('WEIFENG', 'CHINA') then 'CHINA'
            when f.database = 'EVD'                 then 'FRANCE'
            when f.database = 'US'                  then 'USA'
        end as division
    from financials f
),

---------------------------------------------------------
-- step 5: segmentation
---------------------------------------------------------
segmented as (
    select
        e.*,
        (e.ext_price_in_usd - e.ext_cost_in_usd) as ext_profit_in_usd,
        -- FIX: 'Q4' uppercase to match VW_SALES (was 'q4')
        case
            when try_cast(e.month as int) < 4  then 'Q1'
            when try_cast(e.month as int) < 7  then 'Q2'
            when try_cast(e.month as int) < 10 then 'Q3'
            else                              'Q4'
        end as quarter,
        'SALES' as sales_or_order,
        concat(e.cust_group, e.product_code) as group_product_n,
        concat(e.cust_name,  e.product_name) as cust_product_n,
        case
            when e.division in ('FRANCE', 'USA')
                 and upper(e.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(e.product_class) in ('GP FIN GDS')
            then 'GARDEN PRODUCTS'
            when (upper(e.database) = 'US'  and e.cust_code in ('1505','1581','3011','3111','3059','3203','3204'))
              or (upper(e.database) = 'EVD' and e.cust_code in ('15003') and upper(e.product_code) in ('FL5019'))
              or (upper(e.database) = 'US'  and e.cust_code in ('2122')  and upper(e.product_code) in ('FL5019'))
            then 'INDUSTRIAL'
            when e.database = 'WEIFENG' and e.cust_code in ('54', '56') then 'MAGNASWEET'
            when e.database = 'US'      and e.cust_code in ('1663')     then 'MAGNASWEET'
            when e.division = 'CHINA'
                 and upper(e.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(e.product_class) in ('CWE','GP FIN GDS','INTERM-CGA','LIC FIN GDS','LIC OTHER RM','LIC RESALE','MAG OTHER RM','MAG RESALE','MAG-BYPROD','MAG-REF-CMAG','MAG-REFINED','MAGSW FIN GD','NAT PROD RM','NATP RM-IMPT','NATPRDFINGDS','NATPRDRESALE','REMELTS','RM-OTHER','ROOT')
            then 'PURE DERIVATIVES'
            when e.division in ('FRANCE', 'USA')
                 and upper(e.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(e.product_class) in ('INTERM-CGA','MAG OTHER RM','MAG RESALE','MAG-BYPROD','MAG-REF-CMAG','MAG-REFINED','MAGSW FIN GD')
            then 'MAGNASWEET'
            when e.division in ('FRANCE', 'USA')
                 and upper(e.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(e.product_class) in ('CWE','LIC FIN GDS','LIC OTHER RM','LIC RESALE','NAT PROD RM','NATP RM-IMPT','NATPRDFINGDS','NATPRDRESALE','REMELTS','RM-OTHER','ROOT')
                 and upper(e.industry_code) not in ('TOBACCO')
            then 'CONFECTION'
            when e.division in ('FRANCE', 'USA')
                 and upper(e.cust_division) in ('THIRD PARTY', 'EVD')
                 and upper(e.product_class) in ('CWE','LIC FIN GDS','LIC OTHER RM','LIC RESALE','NAT PROD RM','NATP RM-IMPT','NATPRDFINGDS','NATPRDRESALE','REMELTS','RM-OTHER','ROOT')
                 and upper(e.industry_code) = 'TOBACCO'
            then 'TOBACCO'
            -- FIX: 'OTHER' uppercase to match VW_SALES (was 'other')
            else 'OTHER'
        end as segment
    from enriched e
)

---------------------------------------------------------
-- final select
---------------------------------------------------------
select
    s.invoice_num,
    s.order_num,
    s.year_period,
    to_date(s.invoice_date)  as invoice_date,
    to_date(s.order_date)    as order_date,
    '0'                      as delivery_date,
    s.default_ship_from_warehouse,
    s.cust_division,
    s.country_name,
    s.cust_name,
    s.customer_po_num,
    s.product_code,
    s.cust_code,
    s.product_division,
    s.product_class,
    s.prod_pkg_code,
    s.product_name,
    s.um_conversion_percentage,
    s.gross_price,
    s.price_um,
    s.cost,
    s.cogs                   as old_cogs,
    s.quantity_shipped,
    s.qty_um,
    s.invoice_amount,
    s.invoice_currency_conversion_rate,
    s.invoice_currency,
    s.cogs_currency_conversion_rate,
    s.invoice_currency_conversion_date,
    s.journal_number,
    s.cogs_journal_number,
    s.package_um,
    s.package_measure,
    s.group_id,
    s.ref_type,
    s.return_warehouse,
    s.cm_dm_type,
    s.territory,
    s.industry_code,
    s.active_customer,
    s.sales_agent_id,
    s.sales_agent,
    s.sales_agent2           as sales_rep,
    s.customer_class         as region,
    s.shipped_qty_in_kg,
    s.usd_sales_x_rate,
    s.price_per_kg,
    s.cost_per_kg,
    s.price_per_kg_local_currency,
    s.cost_per_kg_local_currency,
    s.profit_kg_local_currency as profit_per_kg_local_currency,
    s.ext_price_local_currency,
    s.ext_cost_local_currency,
    (s.ext_price_local_currency - s.ext_cost_local_currency) as ext_profit_local_currency,
    s.price_per_kg_in_usd,
    s.cost_per_kg_in_usd,
    (s.price_per_kg_in_usd - s.cost_per_kg_in_usd) as profit_per_kg_in_usd,
    s.ext_price_in_usd       as revenue,
    s.ext_cost_in_usd        as cogs,
    s.ext_profit_in_usd      as profit,
    trim(s.year)             as year,
    cast(s.month as int)     as month,
    s.qty_in_drykg,
    s.database,
    s.shipto_state,
    s.shipto_country,
    s.shipto_zip,
    s.shipto_address_1,
    s.shipto_address_2,
    s.shipto_address_3,
    s.shipto_city,
    s.ship_mode,
    s.freight_terms,
    s.fob_remark,
    s.extended_freight_cost,
    s.shipper_id,
    s.week,
    s.qty_in_kg,
    s.cust_group,
    s.division,
    s.quarter,
    s.sales_or_order,
    s.group_product_n,
    s.cust_product_n,
    s.segment,
    concat(s.customer_class, s.segment, s.cust_group, s.product_name) as region_segment_group_product_n,
    concat(s.customer_class, s.segment, s.cust_name,  s.product_name) as region_segment_cust_product_n,
    concat(s.customer_class, s.segment)                               as region_segment,
    concat(s.customer_class, s.segment, s.cust_group)                 as region_segment_group
from segmented s
where upper(s.cust_division) in ('EVD', 'THIRD PARTY')
  and upper(s.product_class) in (
      'INTERM-CGA', 'LIC FIN GDS', 'MAG-BYPROD', 'MAG-REF-CMAG',
      'MAG-REFINED', 'MAGSW FIN GD', 'NAT PROD RM', 'NATPRDFINGDS',
      'REMELTS'
  )