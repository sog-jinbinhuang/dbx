-- int_facts_usd: stg_onestream__facts with an added amount_usd column.
--
-- USD-denominated facts pass through unchanged (amount_usd = amount). Non-USD
-- facts are translated using fxrates' AverageRate_Fcst -- the only rate type
-- available for 2026 periods (see stg_onestream__fxrates.sql for the full
-- background). Two accepted, documented limitations, per explicit decision:
--
--   1. FORECAST, NOT ACTUAL: 2026 periods only have AverageRate_Fcst and
--      BudgetRate in this export -- no realized/actual rate. Verified against
--      real data: this produces a ~12.5% variance from OneStream's own actual
--      translated figure for a sample Argentina account (raw ARS amount
--      converted via this rate: $214.48; OneStream's own actual translation,
--      reverse-engineered from facts.csv's embedded FX_BS_EOM flow: $245.12).
--
--   2. WRONG RATE TYPE FOR BALANCE SHEET: conventionally, BS accounts should
--      translate at a period-end/closing rate, not an average rate -- but no
--      closing rate exists for 2026 in this export at all. AverageRate_Fcst is
--      used for BOTH statements here as the best available option, not because
--      it's the methodologically correct choice for BS.
--
-- Revisit both once OneStream publishes an actual rate type for 2026.
--
-- fx_conversion_missing flags any non-USD fact where no matching rate was
-- found at all (currency/period combo absent from fxrates) -- amount_usd is
-- null in that case rather than silently falling back to the raw local amount.

with facts as (

    select * from {{ ref('stg_onestream__facts') }}

),

rates as (

    select time_period, source_currency, rate
    from {{ ref('stg_onestream__fxrates') }}
    where rate_type = 'AverageRate_Fcst'
      and destination_currency = 'USD'

)

select
    f.*,
    case
        when f.currency = 'USD' then f.amount
        when r.rate is not null then f.amount * r.rate
        else null
    end as amount_usd,
    (f.currency <> 'USD' and r.rate is null) as fx_conversion_missing
from facts f
left join rates r
    on r.source_currency = f.currency
   and r.time_period = f.time_period
