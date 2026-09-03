{{ config(materialized='table') }}

{{ generate_dimension_hierarchy('Account', 14) }}