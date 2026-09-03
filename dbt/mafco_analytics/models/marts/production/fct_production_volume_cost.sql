with params as (
    select
        year(current_date())     as cy,
        year(current_date()) - 1 as py,
        month(current_date())    as cur_month,
        quarter(current_date())  as cur_qtr
),

brq_source as (
    select
        source_database,
        batch_warehouse,
        receipt_num,
        batch_num,
        cust_id,
        product_code,
        packaging_code,
        prod_pkg_code,
        posted_journal_number,
        posted_gl_acct_ptr,
        quantity_manufactured,
        drum_off_manufactured,
        qty_manufactured_um,
        posting_year,
        posting_period,
        average_cost,
        standard_cost,
        last_cost
    from {{ ref('stg_batch_rec_hdr') }}
),

brq_gl_accts as (
    select * from {{ ref('stg_gl_accts') }}
),

brq_packaging as (
    select * from {{ ref('stg_packaging') }}
),

brq_product as (
    select * from {{ ref('stg_product') }}
),

brq_absorption_category as (
    select
        source_database,
        journal_number,
        sum(signed_amount_usd)      as signed_amount_usd,
        max(case chempax_account_num
            -- EVD categories
            when '55-00-71350000-2025' then 'SPRAY DRY'
            when '55-00-71350000-2030' then 'BLOCK'
            when '55-00-71350000-2035' then 'REPROCESS'
            when '55-00-71350000-2040' then 'DRY BLEND'
            when '55-00-71350000-2048' then 'SEMI-FLUID'
            -- China categories
            when '72-70-50321-2321' then 'FD-GA-CA'
            when '72-70-50321-2314' then 'AG-CAKE'
            when '72-70-50321-2320' then 'FD-DPG/TSG/DSG/GA'
            when '72-70-50321-2332' then 'AG-MM300'
            when '72-70-50321-2315' then 'CMAG-CGA'
            when '72-70-50321-2317' then 'DPG/TSG/DSG/GA-CGA'
            when '72-70-50321-2318' then 'DPG/TSG/DSG/GA-CMAG'
            when '72-70-50321-2325' then 'DRY MIX'
            when '72-70-50321-2324' then 'WET MIX'
            when '72-70-50321-2316' then 'MAG-CMAG'
            when '72-70-50321-2329' then 'MIXING-MAG/DPG/TSG/DSG/GA'
            when '72-70-50321-2322' then 'MAGNASWEET-MAG/DPG/TSG/DSG/GA'
            -- US categories
            when '30-10-5910-2106' then 'REMELT BLEND'
            when '30-10-5910-2128' then 'FINISHED GOODS'
            when '30-20-5910-2626' then 'OTHERS'
        end)                        as absorption_category
    from {{ ref('fct_global_gl') }}
    where chempax_account_num in (
        -- EVD
        '55-00-71350000-2025','55-00-71350000-2030','55-00-71350000-2035',
        '55-00-71350000-2040','55-00-71350000-2048',
        -- China
        '72-70-50321-2321','72-70-50321-2314','72-70-50321-2320',
        '72-70-50321-2332','72-70-50321-2315','72-70-50321-2317',
        '72-70-50321-2318','72-70-50321-2325','72-70-50321-2324','72-70-50321-2316',
        '72-70-50321-2329','72-70-50321-2322',
        -- US
        '30-10-5910-2106','30-10-5910-2128','30-14-5935-2109',
        '30-14-5920-2109','30-20-5910-2626'
    )
    group by
        source_database,
        journal_number
),

brq_with_gl as (
    select
        s.*,
        g.gl_acct,
        g.full_description,
        p.measure                           as package_measure,
        p.unit_of_meas                      as package_um,
        pr.um_conversion_percentage,
        case
            when pr.um_conversion_percentage = 0 then 1
            else pr.um_conversion_percentage / 100
        end                                 as dry_percent
    from brq_source s
    left join brq_gl_accts g
        on  s.source_database    = g.source_database
        and s.posted_gl_acct_ptr = g.gl_acct_ptr
    left join brq_packaging p
        on  s.source_database    = p.source_database
        and s.packaging_code     = p.packaging_code
    left join brq_product pr
        on  s.source_database    = pr.source_database
        and s.product_code       = pr.product_code
),

brq_with_conversions as (
    select
        w.*,
        wc.conversion               as weight_conversion,
        wp.conversion               as pkg_conversion
    from brq_with_gl w
    left join {{ ref('weight_conversion') }} wc
        on lower(w.qty_manufactured_um) = lower(wc.weight)
    left join {{ ref('weight_conversion') }} wp
        on lower(w.package_um) = lower(wp.weight)
),

brq_with_category as (
    select
        w.*,

        -- quantity in KG
        cast(
            case
                when lower(w.qty_manufactured_um) = 'e'
                then (w.quantity_manufactured * w.package_measure) / coalesce(w.pkg_conversion, 1)
                else w.quantity_manufactured / coalesce(w.weight_conversion, 1)
            end
        as decimal(18, 6))                   as quantity_manufactured_kg,

        -- quantity in dry KG
        cast(
            case
                when w.dry_percent = 0
                then
                    case
                        when lower(w.qty_manufactured_um) = 'e'
                        then (w.quantity_manufactured * w.package_measure) / coalesce(w.pkg_conversion, 1)
                        else w.quantity_manufactured / coalesce(w.weight_conversion, 1)
                    end
                else
                    case
                        when lower(w.qty_manufactured_um) = 'e'
                        then (w.quantity_manufactured * w.package_measure) / coalesce(w.pkg_conversion, 1)
                        else w.quantity_manufactured / coalesce(w.weight_conversion, 1)
                    end
                    * w.dry_percent
            end
        as decimal(18, 6))                   as quantity_manufactured_dkg,

        ac.absorption_category,
        ac.signed_amount_usd                as absorption_variance_usd

    from brq_with_conversions w
    inner join brq_absorption_category ac
        on  w.source_database        = ac.source_database
        and w.posted_journal_number  = ac.journal_number
),

brq_final as (
    select
        *,
        cast(
            absorption_variance_usd / nullif(quantity_manufactured_kg, 0)
        as decimal(18, 6))                   as absorption_variance_per_kg,
        cast(
            absorption_variance_usd / nullif(quantity_manufactured_dkg, 0)
        as decimal(18, 6))                   as absorption_variance_per_dkg
    from brq_with_category
),

source as (
    select
        source_database                         as entity,
        absorption_category,
        product_code,
        packaging_code,
        prod_pkg_code,
        posting_year,
        posting_period,
        quantity_manufactured_kg,
        quantity_manufactured_dkg,
        absorption_variance_usd,
        average_cost                            as avg_cost_kg,
        standard_cost                           as std_cost_kg
    from brq_final
    where absorption_category is not null
),

with_names as (
    select
        s.*,
        pr.product_name,
        pr.product_segment
    from source s
    left join {{ ref('stg_product') }} pr
        on  s.entity       = pr.source_database
        and s.product_code = pr.product_code
),

pivoted as (
    select
        w.entity,
        w.absorption_category,
        w.product_code,
        w.product_name,
        w.product_segment,
        w.packaging_code,
        w.prod_pkg_code,
        p.cy,
        p.py,
        p.cur_month,
        p.cur_qtr,

        -- =================== volume KG ===================
        sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month                                     then w.quantity_manufactured_kg  end) as cy_vol_kg_cur_month,
        sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month                                     then w.quantity_manufactured_kg  end) as cy_vol_kg_ytd,
        sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3         then w.quantity_manufactured_kg  end) as cy_vol_kg_cur_qtr,
        sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month                                     then w.quantity_manufactured_kg  end) as py_vol_kg_cur_month,
        sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month                                     then w.quantity_manufactured_kg  end) as py_vol_kg_ytd,
        sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3         then w.quantity_manufactured_kg  end) as py_vol_kg_cur_qtr,

        -- =================== volume KG monthly ===================
        sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.quantity_manufactured_kg end) as cy_vol_kg_m01,
        sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.quantity_manufactured_kg end) as cy_vol_kg_m02,
        sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.quantity_manufactured_kg end) as cy_vol_kg_m03,
        sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.quantity_manufactured_kg end) as cy_vol_kg_m04,
        sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.quantity_manufactured_kg end) as cy_vol_kg_m05,
        sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.quantity_manufactured_kg end) as cy_vol_kg_m06,
        sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.quantity_manufactured_kg end) as cy_vol_kg_m07,
        sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.quantity_manufactured_kg end) as cy_vol_kg_m08,
        sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.quantity_manufactured_kg end) as cy_vol_kg_m09,
        sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.quantity_manufactured_kg end) as cy_vol_kg_m10,
        sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.quantity_manufactured_kg end) as cy_vol_kg_m11,
        sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.quantity_manufactured_kg end) as cy_vol_kg_m12,

        -- =================== volume DKG ===================
        sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month                                     then w.quantity_manufactured_dkg end) as cy_vol_dkg_cur_month,
        sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month                                     then w.quantity_manufactured_dkg end) as cy_vol_dkg_ytd,
        sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3         then w.quantity_manufactured_dkg end) as cy_vol_dkg_cur_qtr,
        sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month                                     then w.quantity_manufactured_dkg end) as py_vol_dkg_cur_month,
        sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month                                     then w.quantity_manufactured_dkg end) as py_vol_dkg_ytd,
        sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3         then w.quantity_manufactured_dkg end) as py_vol_dkg_cur_qtr,

        -- =================== volume DKG monthly ===================
        sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m01,
        sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m02,
        sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m03,
        sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m04,
        sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m05,
        sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m06,
        sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m07,
        sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m08,
        sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m09,
        sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m10,
        sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m11,
        sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.quantity_manufactured_dkg end) as cy_vol_dkg_m12,

        -- =================== absorption variance USD ===================
        sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month                                     then w.absorption_variance_usd   end) as cy_var_usd_cur_month,
        sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month                                     then w.absorption_variance_usd   end) as cy_var_usd_ytd,
        sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3         then w.absorption_variance_usd   end) as cy_var_usd_cur_qtr,
        sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month                                     then w.absorption_variance_usd   end) as py_var_usd_cur_month,
        sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month                                     then w.absorption_variance_usd   end) as py_var_usd_ytd,
        sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3         then w.absorption_variance_usd   end) as py_var_usd_cur_qtr,

        -- =================== absorption variance USD monthly ===================
        sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.absorption_variance_usd end) as cy_var_usd_m01,
        sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.absorption_variance_usd end) as cy_var_usd_m02,
        sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.absorption_variance_usd end) as cy_var_usd_m03,
        sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.absorption_variance_usd end) as cy_var_usd_m04,
        sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.absorption_variance_usd end) as cy_var_usd_m05,
        sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.absorption_variance_usd end) as cy_var_usd_m06,
        sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.absorption_variance_usd end) as cy_var_usd_m07,
        sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.absorption_variance_usd end) as cy_var_usd_m08,
        sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.absorption_variance_usd end) as cy_var_usd_m09,
        sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.absorption_variance_usd end) as cy_var_usd_m10,
        sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.absorption_variance_usd end) as cy_var_usd_m11,
        sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.absorption_variance_usd end) as cy_var_usd_m12,

        -- =================== avg cost / KG ===================
        sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month             then w.avg_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month      then w.quantity_manufactured_kg end), 0)              as cy_avg_cost_kg_cur_month,
        sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month             then w.avg_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month      then w.quantity_manufactured_kg end), 0)              as cy_avg_cost_kg_ytd,
        sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.avg_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_cur_qtr,
        sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month             then w.avg_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month      then w.quantity_manufactured_kg end), 0)              as py_avg_cost_kg_cur_month,
        sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month             then w.avg_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month      then w.quantity_manufactured_kg end), 0)              as py_avg_cost_kg_ytd,
        sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.avg_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_kg end), 0) as py_avg_cost_kg_cur_qtr,

        -- =================== avg cost / KG monthly ===================
        sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m01,
        sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m02,
        sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m03,
        sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m04,
        sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m05,
        sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m06,
        sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m07,
        sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m08,
        sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m09,
        sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m10,
        sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m11,
        sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.avg_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.quantity_manufactured_kg end), 0) as cy_avg_cost_kg_m12,

        -- =================== std cost / KG ===================
        sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month             then w.std_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month      then w.quantity_manufactured_kg end), 0)              as cy_std_cost_kg_cur_month,
        sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month             then w.std_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month      then w.quantity_manufactured_kg end), 0)              as cy_std_cost_kg_ytd,
        sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.std_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_cur_qtr,
        sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month             then w.std_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month      then w.quantity_manufactured_kg end), 0)              as py_std_cost_kg_cur_month,
        sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month             then w.std_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month      then w.quantity_manufactured_kg end), 0)              as py_std_cost_kg_ytd,
        sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.std_cost_kg * w.quantity_manufactured_kg end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_kg end), 0) as py_std_cost_kg_cur_qtr,

        -- =================== std cost / KG monthly ===================
        sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m01,
        sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m02,
        sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m03,
        sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m04,
        sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m05,
        sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m06,
        sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m07,
        sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m08,
        sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m09,
        sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m10,
        sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m11,
        sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.std_cost_kg * w.quantity_manufactured_kg end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.quantity_manufactured_kg end), 0) as cy_std_cost_kg_m12,

        -- =================== variance per KG ===================
        sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month      then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_cur_month,
        sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month      then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_ytd,
        sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_cur_qtr,
        sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month      then w.quantity_manufactured_kg end), 0) as py_var_per_kg_cur_month,
        sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month      then w.quantity_manufactured_kg end), 0) as py_var_per_kg_ytd,
        sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_kg end), 0) as py_var_per_kg_cur_qtr,

        -- =================== variance per KG monthly ===================
        sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m01,
        sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m02,
        sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m03,
        sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m04,
        sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m05,
        sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m06,
        sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m07,
        sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m08,
        sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m09,
        sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m10,
        sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m11,
        sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.quantity_manufactured_kg end), 0) as cy_var_per_kg_m12,

        -- =================== variance per DKG ===================
        sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period  = p.cur_month      then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_cur_month,
        sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period <= p.cur_month      then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_ytd,
        sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.cy and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_cur_qtr,
        sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period  = p.cur_month      then w.quantity_manufactured_dkg end), 0) as py_var_per_dkg_cur_month,
        sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month             then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period <= p.cur_month      then w.quantity_manufactured_dkg end), 0) as py_var_per_dkg_ytd,
        sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.absorption_variance_usd end) /
        nullif(sum(case when w.posting_year = p.py and w.posting_period between (p.cur_qtr-1)*3+1 and p.cur_qtr*3 then w.quantity_manufactured_dkg end), 0) as py_var_per_dkg_cur_qtr,

        -- =================== variance per DKG monthly ===================
        sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  1 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m01,
        sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  2 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m02,
        sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  3 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m03,
        sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  4 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m04,
        sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  5 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m05,
        sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  6 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m06,
        sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  7 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m07,
        sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  8 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m08,
        sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period =  9 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m09,
        sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 10 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m10,
        sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 11 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m11,
        sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.absorption_variance_usd end) / nullif(sum(case when w.posting_year = p.cy and w.posting_period = 12 then w.quantity_manufactured_dkg end), 0) as cy_var_per_dkg_m12

    from with_names w
    cross join params p
    group by
        w.entity,
        w.absorption_category,
        w.product_code,
        w.product_name,
        w.product_segment,
        w.packaging_code,
        w.prod_pkg_code,
        p.cy,
        p.py,
        p.cur_month,
        p.cur_qtr
)

select * from pivoted
order by
    entity,
    absorption_category,
    product_code,
    packaging_code