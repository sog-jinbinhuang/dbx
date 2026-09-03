with unioned_data as (
    select * from {{ ref('fct_global_sales') }}
    union all
    select * from {{ ref('fct_global_orders') }}
),

final as (
    select
        u.*,
        case
        when cast(u.month as int) > month(u.invoice_date)
            then date_trunc('month', to_date(concat(u.year,'-',lpad(u.month,2,'0'),'-01'),'yyyy-MM-dd'))
        when cast(u.month as int) < month(u.invoice_date)
            then last_day(to_date(concat(u.year,'-',lpad(u.month,2,'0'),'-01'),'yyyy-MM-dd'))
        else u.invoice_date
        end as year_month_date,
        -- reporting_segment
        case
            when u.division = 'CHINA' and lower(u.cust_group) in ('b.a.t.','jti')                                   then 'TOBACCO'
            when u.division = 'CHINA' and lower(u.cust_group) = 'commer asia' and lower(u.product_code) = 'fl3134' then 'TOBACCO'
            when u.division = 'CHINA' and lower(u.cust_group) = 'r&b food'                                          then 'TOBACCO'
            when lower(u.product_code) in ('mg0023','mg0026','mg0143','mg0152','mg0097')                              then 'PURE DERIVATIVES'
            else u.segment
        end as reporting_segment,
        -- from unified_product_mapping
        p.unified_product_name,
        p.unified_product_code,
        p.new_unified_code,
        p.product_categories,
        -- from product_category
        c.category_type,
        -- from teams_focus
        t.team,
        t.focus
    from unioned_data u
    left join {{ ref('unified_product_mapping') }} as p
        on u.database      = p.database
        and lower(u.product_code) = lower(p.product_code)
    left join {{ ref('product_category') }} as c
        on lower(p.product_categories) = lower(c.product_categories)
    left join {{ ref('stg_teams_focus') }} as t
        on lower(trim(regexp_replace(u.cust_group, '["\\t]', ''))) = t.cust_group
    where not (
        u.database in ('CHINA','WEIFENG')
        and u.order_num in (
            '1908','1924','1917','1918','1919','1920','1921','1922','1923','1925',
            '8986','9009','9010','9011','9654','9763',
            '2172','2175','2176','2177','2179','2180','2181','2182',
            '9934','9946','9947',
            '2487','2503','2504','2505','2506','2507','2508','2509','2510',
            '2802','2805','2806','2807','2808','2809',
            '2987','3001','3002','3026','3003','3027','3004','3005','3006',
            '3120','3007','3208'
        )
    ) and u.year >= year(current_date) - 5
)

select * from final
