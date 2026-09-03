-- Staging: OneStream hierarchy export (Account, CostCenter, DataType, District, Entity, Flow, Scenario)
--
-- NOTE ON DimID: several dimension_types in the raw export are split across two DimID values
-- (e.g. Account = DimID 8 and 9, CostCenter = 1 and 2, District = 3 and 4, Scenario = 10 and 11).
-- These are NOT alternate/competing hierarchies: no child_id appears under more than one DimID,
-- and no child_id has more than one distinct parent_id anywhere in the export. They are
-- complementary slices of a single tree (verified against the 2026M2 facts extract -- walking the
-- combined, un-filtered edge set balances Assets = Liabilities + Equity exactly, for every entity).
-- Downstream models therefore ignore dim_id and use the full edge set per dimension_type.
--
-- SNAPSHOT FILTERING: the hierarchy is a full-tree export each time (not additive), so
-- this model only keeps rows from the most recently ingested file -- older snapshots
-- stay in the bronze table (for audit/history) but are excluded here.

with source as (

    select * from {{ source('bronze', 'onestream_hierarchy') }}

),

latest_load as (

    select max(_ingested_at) as max_ingested_at from source

),

renamed as (

    select
        s.DimensionType                          as dimension_type,
        cast(s.DimID as integer)                  as dim_id,
        cast(s.ParentID as bigint)                as parent_id,
        nullif(trim(s.ParentName), '')            as parent_name,
        nullif(trim(s.ParentDescription), '')     as parent_description,
        cast(s.ChildID as bigint)                 as child_id,
        s.ChildName                                as child_name,
        nullif(trim(s.ChildDescription), '')      as child_description,
        cast(s.SiblingSortOrder as bigint)        as sibling_sort_order,
        cast(s.Aggregation as integer)            as aggregation,        -- +1 add, -1 subtract, 0 no rollup
        to_timestamp(s.UpdateTime, 'M/d/yyyy h:mm:ss a')  as update_time,  -- OneStream exports as M/D/YYYY h:mm:ss AM/PM
        -- DuckDB equivalent, if you ever run this locally instead of on Databricks:
        -- strptime(s.UpdateTime, '%m/%d/%Y %I:%M:%S %p')
        s._source_file,
        s._ingested_at
    from source s
    inner join latest_load l on s._ingested_at = l.max_ingested_at

)

select * from renamed
