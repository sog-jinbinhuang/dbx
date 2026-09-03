with parsed as (

    select
        source_database,
        order_num,
        created_date_time,
        fob_remark,
        -- Parse the whole "YYYYMMDD:HH:mm:ss" string in one shot rather than
        -- slicing by fixed character offsets — the source has colons
        -- separating date/hour/minute/second, so raw substr() math is fragile
        -- and breaks silently if the layout shifts. TRY_TO_TIMESTAMP returns
        -- NULL on a bad parse (same safety as Snowflake's TRY_TO_DATE) instead
        -- of failing the whole model.
        try_to_timestamp(created_date_time, 'yyyyMMdd:HH:mm:ss') as created_ts
    from {{ ref('stg_order_hdr') }}

),

order_hdr as (

    select
        source_database,
        order_num,
        created_date_time,
        fob_remark,
        cast(created_ts as date) as created_date,
        -- Databricks SQL has no TIME type, so time-of-day is represented as
        -- seconds-since-midnight (int) for comparison purposes. hour()/
        -- minute()/second() all return NULL automatically if created_ts is NULL.
        hour(created_ts)   * 3600
        + minute(created_ts) * 60
        + second(created_ts)          as created_time_secs
    from parsed

),

recent as (

    select *
    from order_hdr
    where
        -- Databricks SQL warehouses default their session timezone to UTC,
        -- while this pipeline ran in America/New_York on Snowflake. Using
        -- plain current_date()/current_timestamp() shifts results by a day
        -- (and near month-end, by a whole month bucket) whenever UTC has
        -- already rolled over past midnight local time. Converting the UTC
        -- instant to America/New_York explicitly makes this correct
        -- regardless of the session/warehouse's default timezone setting.
        --
        -- same day: any time is within 24h
        (created_date = cast(from_utc_timestamp(current_timestamp(), 'America/New_York') as date))
        or
        -- yesterday: only if time is after (current_time - used as cutoff)
        (
            created_date = date_sub(cast(from_utc_timestamp(current_timestamp(), 'America/New_York') as date), 1)
            and created_time_secs >= (
                hour(from_utc_timestamp(current_timestamp(), 'America/New_York')) * 3600
                + minute(from_utc_timestamp(current_timestamp(), 'America/New_York')) * 60
                + second(from_utc_timestamp(current_timestamp(), 'America/New_York'))
            )
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
        h.created_date,
        h.created_time_secs,
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