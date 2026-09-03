{% macro generate_dimension_hierarchy(dimension_type, max_depth=15) %}
-- Recursively walks the parent/child edges for one OneStream dimension_type and returns,
-- for every member: its depth, a full id/name ancestor path, a lexically-sortable path
-- (so `order by sort_path` reproduces the tree's depth-first display order), an is_leaf
-- flag, and a breadcrumb of level_0_id/level_0_name .. level_{{ max_depth - 1 }}_id/_name
-- giving the ancestor at each fixed depth (null if the member's path is shallower).
--
-- Requires WITH RECURSIVE support (DuckDB and Databricks Runtime 11.3+ both support this).

with recursive edges as (

    select
        parent_id,
        child_id,
        child_name,
        child_description,
        sibling_sort_order,
        aggregation
    from {{ ref('stg_onestream__hierarchy') }}
    where dimension_type = '{{ dimension_type }}'

),

tree as (

    -- anchor: top-level members of the tree (parent_id = -2)
    select
        child_id                                              as member_id,
        child_name                                             as member_name,
        child_description                                      as member_description,
        aggregation,
        0                                                       as depth,
        cast(child_id as string)                              as ancestor_id_path,
        cast(child_name as string)                            as ancestor_name_path,
        lpad(cast(sibling_sort_order as string), 20, '0')     as sort_path,
        {% for i in range(max_depth) %}
        {% if i == 0 %}child_id{% else %}cast(null as bigint){% endif %}    as level_{{ i }}_id,
        {% if i == 0 %}child_name{% else %}cast(null as string){% endif %} as level_{{ i }}_name{{ "," if not loop.last }}
        {% endfor %}
    from edges
    where parent_id = -2

    union all

    -- recursive step: join each edge onto the parent already resolved one level up
    select
        e.child_id,
        e.child_name,
        e.child_description,
        e.aggregation,
        t.depth + 1,
        t.ancestor_id_path || '>' || cast(e.child_id as string),
        t.ancestor_name_path || ' > ' || e.child_name,
        t.sort_path || '~' || lpad(cast(e.sibling_sort_order as string), 20, '0'),
        {% for i in range(max_depth) %}
        case when t.depth + 1 = {{ i }} then e.child_id else t.level_{{ i }}_id end as level_{{ i }}_id,
        case when t.depth + 1 = {{ i }} then e.child_name else t.level_{{ i }}_name end as level_{{ i }}_name{{ "," if not loop.last }}
        {% endfor %}
    from edges e
    inner join tree t on e.parent_id = t.member_id

)

select
    t.*,
    not exists (select 1 from edges e2 where e2.parent_id = t.member_id) as is_leaf
from tree t

{% endmacro %}
