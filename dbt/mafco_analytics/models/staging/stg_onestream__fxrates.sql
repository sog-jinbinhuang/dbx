-- Staging: OneStream FX rates export.
--
-- NOTE ON SCOPE -- read before using this for currency translation:
-- This table does NOT have an "actual" rate for 2026 periods. Checked directly:
-- every period from 2022M1 through 2025M9 has a `ConstantRate` type that looks
-- like the realized/actual rate for that period; from 2026M1 onward, only
-- `AverageRate_Fcst` (forecast) and `BudgetRate` exist -- no actual. Verified
-- this doesn't match either: for ARS/2026M2, both 2026 rate types imply
-- ~1,587.30, but the rate actually embedded in facts_2026M2.csv (via the
-- FX_BS_EOM flow, reverse-engineered from real entity data) is ~1,388.89.
-- Whatever rate OneStream actually used for current-period consolidation isn't
-- exposed in this export. Useful for budget-vs-actual variance analysis and for
-- historical-period actuals (pre-2026); NOT a fix for translating current-period
-- local-currency entities -- that gap (see dim_entity_segment /
-- financial_statement_report.py) is still open.
--
-- Unlike hierarchy, this file already contains its full period range (60
-- distinct periods) in one export rather than being period-specific like facts
-- -- so, like hierarchy, only the most recently ingested load is kept here
-- (a fresh export supersedes the whole table, it isn't accumulated period by
-- period the way facts is).

with source as (

    select * from {{ source('bronze', 'onestream_fxrates') }}

),

latest_load as (

    select max(_ingested_at) as max_ingested_at from source

),

renamed as (

    select
        s.TimePeriod                                     as time_period,
        s.RateType                                        as rate_type,
        s.SourceCurrency                                  as source_currency,
        s.DestinationCurrency                             as destination_currency,
        cast(s.Rate as double)                            as rate,
        to_timestamp(s.UpdateTime, 'M/d/yyyy h:mm:ss a')   as update_time,  -- OneStream exports as M/D/YYYY h:mm:ss AM/PM
        -- DuckDB equivalent, if you ever run this locally instead of on Databricks:
        -- strptime(s.UpdateTime, '%m/%d/%Y %I:%M:%S %p')
        s._source_file,
        s._ingested_at
    from source s
    inner join latest_load l on s._ingested_at = l.max_ingested_at

)

select * from renamed
