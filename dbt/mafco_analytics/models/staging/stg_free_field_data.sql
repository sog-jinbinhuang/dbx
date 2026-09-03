with cleaned as (

    select
        source_database,

        nullif(trim(`System-ID`), '')                                   as system_id,
        nullif(trim(`Module-ID`), '')                                   as module_id,
        nullif(trim(`Program-ID`), '')                                  as program_id,
        nullif(trim(`Free-Field-Type`), '')                             as free_field_type,
        TRY_CAST(`Sequence-1` AS DECIMAL(18,0))                              as sequence_1,
        nullif(trim(`Sequence-1CV`), '')                                as sequence_1_cv,
        nullif(trim(`Data-Key`), '')                                    as data_key,
        nullif(trim(`Data-Value`), '')                                  as data_value,
        nullif(trim(`Security-Access`), '')                             as security_access,
        nullif(trim(`User-1`), '')                                      as user_1,
        nullif(trim(`Created-by`), '')                                  as created_by,
        CAST(TRY_TO_TIMESTAMP(`Created-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)                                     as created_date,
        TRY_TO_TIMESTAMP(`Created-Date-Time`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS')                       as created_date_time,
        nullif(trim(`Update-by`), '')                                   as update_by,
        CAST(TRY_TO_TIMESTAMP(`Update-date`, 'yyyy-MM-dd HH:mm:ss.SSSSSSS') AS DATE)                                      as update_date,
        nullif(trim(`Update-time`), '')                                 as update_time
    from {{ source('bronze', 'free_field_data') }}

)

select
    *,
    case
        when program_id = 'Custfmnt'
            and source_database = 'US'
            and sequence_1 = 3
            then data_value
        when program_id = 'Custfmnt'
            and source_database != 'US'
            and sequence_1 = 1
            then data_value
    end as cust_segment,
    case
        when lower(program_id) = 'prodfmnt'
            and source_database = 'EVD'
            and sequence_1 = 10
            then data_value
        when lower(program_id) = 'prodfmnt'
            and source_database = 'US'
            and sequence_1 = 10
            then data_value
        when lower(program_id) = 'prodfmnt'
            and source_database = 'CHINA'
            and sequence_1 = 4
            then data_value
        when lower(program_id) = 'prodfmnt'
            and source_database = 'WEIFENG'
            and sequence_1 = 4
            then data_value
    end as prod_segment
from cleaned
