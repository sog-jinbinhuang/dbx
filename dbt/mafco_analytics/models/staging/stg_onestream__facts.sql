-- Staging: OneStream facts export (Fin_Rptg cube, leaf-level trial balance grain)
--
-- Unlike hierarchy, facts ARE additive across loads -- every period that's landed via
-- COPY INTO stays in this model (grain already includes time_period/scenario_id
-- downstream, so multiple periods just work). _source_file/_ingested_at are passed
-- through for lineage/debugging (e.g. "which extract did this row come from").

with source as (

    select * from {{ source('bronze', 'onestream_facts') }}

),

renamed as (

    select
        CubeName                                as cube_name,
        cast(EntityID as bigint)                as entity_id,
        EntityName                               as entity_name,
        EntityDescription                        as entity_description,
        Currency                                 as currency,
        cast(ScenarioID as bigint)               as scenario_id,
        ScenarioName                              as scenario_name,
        cast(TimePeriod as string)               as time_period,
        cast(AccountID as bigint)                 as account_id,
        AccountName                                as account_name,
        AccountDescription                         as account_description,
        cast(FlowID as bigint)                     as flow_id,
        FlowName                                    as flow_name,
        FlowDescription                             as flow_description,
        Origin                                      as origin,
        case when trim(IC) in ('', 'None') then null else trim(IC) end as ic,  -- intercompany trading-partner entity code; joins back to entity_id
        cast(DataTypeID as bigint)                   as data_type_id,
        DataTypeName                                 as data_type_name,
        cast(DistrictID as bigint)                    as district_id,
        DistrictName                                   as district_name,
        cast(CostCenterID as bigint)                    as cost_center_id,
        CostCenterName                                   as cost_center_name,
        cast(Amount as double)                            as amount,
        to_timestamp(UpdateTime, 'M/d/yyyy h:mm:ss a')    as update_time,  -- OneStream exports as M/D/YYYY h:mm:ss AM/PM
        -- DuckDB equivalent, if you ever run this locally instead of on Databricks:
        -- strptime(UpdateTime, '%m/%d/%Y %I:%M:%S %p')
        _source_file,
        _ingested_at
    from source

)

select * from renamed
