{{ config(materialized='table') }}

{{ generate_dimension_hierarchy('Entity', 12) }}