with source as (
    select * from {{ ref('teams_focus') }}
),

deduped as (
    select distinct
        lower(trim(regexp_replace(cust_group, '["\\t]', ''))) as cust_group,
        team,
        focus
    from source
)

select * from deduped
