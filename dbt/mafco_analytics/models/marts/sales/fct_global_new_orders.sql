with parsed as (

    select
        source_database,
        order_num,
        created_date_time,
        fob_remark,
        -- Parse the whole "yyyyMMddHH:mm:ss" string in one shot rather than
        -- slicing by fixed character offsets -- the source has NO colon
        -- between date and hour (only before minutes/seconds), so raw
        -- substr() math is fragile and breaks silently if the layout
        -- shifts. TRY_TO_TIMESTAMP returns NULL on a bad parse (same safety
        -- as Snowflake's TRY_TO_DATE) instead of failing the whole model.
        try_to_timestamp(created_date_time, 'yyyyMMddHH:mm:ss') as created_ts
    from {{ ref('stg_order_hdr') }}

),

recent as (

    select
        source_database,
        order_num,
        created_date_time,
        fob_remark,
        created_ts
    from parsed
    where
        -- Straight rolling 24-hour window on the actual timestamp, instead
        -- of the old two-branch (today OR yesterday-with-a-time-of-day-
        -- cutoff) approach. That approach re-derives the same 24h window
        -- indirectly via date + time-of-day comparisons, which is harder to
        -- reason about and shrinks/shifts in confusing ways as the clock
        -- moves -- this is just "anything created in the last 24 hours,"
        -- stated directly.
        --
        -- created_ts has no timezone info (parsed from a naive
        -- "yyyyMMdd:HH:mm:ss" source string), so it represents whatever
        -- local timezone the source system writes in -- America/New_York,
        -- same as the original Snowflake pipeline. Databricks SQL warehouses
        -- default current_timestamp() to UTC regardless of session
        -- settings, so "now" is converted to America/New_York once here to
        -- compare on the same footing as created_ts, then shifted back 24h
        -- for the cutoff.
        created_ts >= (
            from_utc_timestamp(current_timestamp(), 'America/New_York') - interval 24 hours
        )

),

order_lines as (

    select
        `database`,
        order_num,
        sales_rep,
        cust_code,
        cust_name,
        product_code,
        product_name,
        order_date,
        ship_date,
        revenue,
        qty_in_kg
    from {{ ref('fct_global_orders') }}

),

joined as (

    select
        h.source_database                       as `database`,
        h.order_num,
        cast(h.created_ts as date)               as created_date,
        h.created_ts,
        h.fob_remark,
        s.sales_rep,
        s.cust_code,
        s.cust_name,
        s.product_code,
        s.product_name,
        s.order_date,
        s.ship_date,
        s.revenue,
        s.qty_in_kg

    from recent           h
    join order_lines      s
        on  s.`database` = h.source_database
        and s.order_num  = h.order_num

)

select * from joined