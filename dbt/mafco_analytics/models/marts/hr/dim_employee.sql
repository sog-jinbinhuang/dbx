with ukg as (
    select
        e.id                                as ukg_employee_id,
        e.company_id,
        e.person_id,
        em.primary_job_id                   as job_id,
        em.primary_work_location_id         as location_id,
        em.supervisor_id                    as ukg_supervisor_id,
        em.pay_group,
        em.organization_level_1_id          as org_level_1_id,
        em.organization_level_2_id          as org_level_2_id,
        em.organization_level_3_id          as org_level_3_id,
        em.organization_level_4_id          as org_level_4_id,
        e.first_name,
        e.last_name,
        e.preferred_name,
        e.middle_name,
        CAST(e.date_of_birth AS DATE)       as date_of_birth,
        e.gender,
        e.marital_status_code,
        e.ethnic_description,
        e.email_address,
        e.address_city,
        e.address_state,
        e.address_zip_code,
        e.address_country,
        c.name                              as company_name,
        c.code                              as company_code,
        c.gl_segment                        as company_gl_segment,
        j.title                             as job_title,
        j.job_family_code,
        j.flsa_type_code,
        j.eeo_category,
        l.description                       as location_name,
        l.city                              as location_city,
        l.state                             as location_state,
        l.zip_or_postal_code                as location_zip,
        l.country_code                      as location_country,
        l.location_gl_segment               as location_gl_segment,
        o1.description                      as org_level_1_name,
        o2.description                      as org_level_2_name,
        o3.description                      as org_level_3_name,
        o4.description                      as org_level_4_name,
        o1.gl_segment                       as org_level_1_gl_segment,
        o2.gl_segment                       as org_level_2_gl_segment,
        o3.gl_segment                       as org_level_3_gl_segment,
        o4.gl_segment                       as org_level_4_gl_segment,
        em.employee_type_code,
        em.full_time_or_part_time_code,
        case
            when em.full_time_or_part_time_code = 'F' then 'Full Time'
            when em.full_time_or_part_time_code = 'P' then 'Part Time'
            else 'Unknown'
        end                                 as employment_type,
        em.salary_or_hourly,
        em.shift,
        em.shift_group,
        em.pay_period,
        em.scheduled_fte,
        em.scheduled_work_hrs,
        em.scheduled_annual_hrs,
        em.weekly_hours,
        em.ok_to_rehire,
        CAST(em.original_hire_date AS DATE) as original_hire_date,
        CAST(em.last_hire_date AS DATE)     as last_hire_date,
        CAST(em.date_in_job AS DATE)        as date_in_job,
        CAST(em.date_of_seniority AS DATE)  as date_of_seniority,
        CAST(em.date_of_termination AS DATE) as date_of_termination,
        e.is_disabled,
        e.is_multi_pay_group,
        es.status                           as employment_status,
        es.status_reason,
        es.status_reason_desc,
        CAST(es.status_start_date AS DATE)  as status_effective_date,
        case
            when em.date_of_termination is not null then false
            else true
        end                                 as is_active
    from {{ source('ukg', 'EMPLOYEE') }} e
    left join (
            select *,
                row_number() over (
                    partition by employee_id
                    order by
                        case when employee_status_code = 'A' then 0
                            when employee_status_code = 'L' then 1
                            else 2
                        end asc,
                        date_in_job desc
                ) as rn
            from {{ source('ukg', 'EMPLOYMENT') }}
            where coalesce(cast(_fivetran_deleted as boolean), false) = false
        ) em
            on e.id = em.employee_id
            and em.rn = 1
    left join {{ source('ukg', 'EMPLOYEE_STATUS') }} es
        on e.id = es.employee_id
    left join {{ source('ukg', 'COMPANY') }} c
        on e.company_id = c.id
    left join {{ source('ukg', 'JOB') }} j
        on em.primary_job_id = j.id
    left join {{ source('ukg', 'LOCATION') }} l
        on em.primary_work_location_id = l.id
    left join {{ source('ukg', 'ORGANIZATION_LEVEL') }} o1
        on em.organization_level_1_id = o1.id
        and o1.level = 1
    left join {{ source('ukg', 'ORGANIZATION_LEVEL') }} o2
        on em.organization_level_2_id = o2.id
        and o2.level = 2
    left join {{ source('ukg', 'ORGANIZATION_LEVEL') }} o3
        on em.organization_level_3_id = o3.id
        and o3.level = 3
    left join {{ source('ukg', 'ORGANIZATION_LEVEL') }} o4
        on em.organization_level_4_id = o4.id
        and o4.level = 4
    left join {{ source('ukg', 'EMPLOYEE') }} sup
        on em.supervisor_id = sup.id
        and coalesce(cast(sup._fivetran_deleted as boolean), false) = false
    where coalesce(cast(e._fivetran_deleted as boolean), false) = false
),

sf as (
    select * from {{ ref('stg_successfactors_employee') }}
)

-- population 1: UKG (domestic)
select
    'UKG'                                as employee_source,
    ukg.is_active,
    ukg.ukg_employee_id                  as employee_id,
    ukg.first_name,
    ukg.last_name,
    ukg.first_name || ' ' || ukg.last_name as full_name,
    ukg.preferred_name,
    ukg.middle_name,
    ukg.job_title,
    ukg.employee_type_code,
    ukg.employment_type,
    ukg.salary_or_hourly,
    ukg.job_family_code,
    ukg.flsa_type_code,
    ukg.eeo_category,
    ukg.company_name,
    ukg.company_code,
    ukg.company_gl_segment,
    'North America'                      as business_unit_name,
    ukg.org_level_1_name,
    ukg.org_level_2_name,
    ukg.org_level_3_name,
    ukg.org_level_4_name                 as department_name,
    ukg.org_level_1_gl_segment,
    ukg.org_level_2_gl_segment,
    ukg.org_level_3_gl_segment,
    ukg.org_level_4_gl_segment,
    ukg.location_id,
    ukg.location_name,
    ukg.location_city,
    ukg.location_state,
    ukg.location_zip,
    ukg.location_country,
    ukg.location_gl_segment,
    ukg.pay_group,
    ukg.pay_period,
    ukg.shift,
    ukg.shift_group,
    ukg.scheduled_fte,
    ukg.scheduled_work_hrs,
    ukg.scheduled_annual_hrs,
    ukg.weekly_hours,
    ukg.date_of_birth,
    ukg.gender,
    ukg.marital_status_code,
    ukg.ethnic_description,
    ukg.is_disabled,
    ukg.is_multi_pay_group,
    ukg.email_address,
    ukg.address_city,
    ukg.address_state,
    ukg.address_zip_code,
    ukg.address_country,
    ukg.original_hire_date,
    ukg.last_hire_date,
    ukg.date_in_job,
    ukg.date_of_seniority,
    ukg.date_of_termination,
    ukg.employment_status,
    ukg.status_reason,
    ukg.status_reason_desc,
    ukg.status_effective_date,
    -- sf-only fields, null on the UKG side
    null                                  as job_level_sf,
    null                                  as compensation_amount,
    null                                  as compensation_currency,
    null                                  as cost_center_name,
    null                                  as cost_center_code,
    null                                  as supervisor_name_sf

from ukg
where ukg.pay_group != 'RETIRE'

union all

-- population 2: SuccessFactors (international) -- kept as its own set of rows,
-- no attempt to match/join to UKG since no reliable shared key currently exists
-- (see stg_successfactors_employee.sql -- no email/national ID in the current export)
select
    'SUCCESSFACTORS'                     as employee_source,
    case
        when sf.date_of_termination is not null then false
        else true
    end                                   as is_active,
    sf.sf_employee_id                     as employee_id,
    sf.first_name,
    sf.last_name,
    sf.first_name || ' ' || sf.last_name  as full_name,
    null                                  as preferred_name,
    null                                  as middle_name,
    sf.job_title,
    null                                  as employee_type_code,
    sf.employment_type,
    null                                  as salary_or_hourly,
    null                                  as job_family_code,
    null                                  as flsa_type_code,
    null                                  as eeo_category,
    sf.company_name,
    sf.company_code,
    null                                  as company_gl_segment,
    sf.business_unit_name,
    null                                  as org_level_1_name,
    null                                  as org_level_2_name,
    null                                  as org_level_3_name,
    sf.department_name,
    null                                  as org_level_1_gl_segment,
    null                                  as org_level_2_gl_segment,
    null                                  as org_level_3_gl_segment,
    null                                  as org_level_4_gl_segment,
    null                                  as location_id,
    null                                  as location_name,
    null                                  as location_city,
    null                                  as location_state,
    null                                  as location_zip,
    sf.legal_entity_country               as location_country,
    null                                  as location_gl_segment,
    null                                  as pay_group,
    null                                  as pay_period,
    null                                  as shift,
    null                                  as shift_group,
    CAST(null AS DOUBLE)                  as scheduled_fte,
    CAST(null AS DOUBLE)                  as scheduled_work_hrs,
    CAST(null AS DOUBLE)                  as scheduled_annual_hrs,
    CAST(null AS DOUBLE)                  as weekly_hours,
    CAST(null AS DATE)                    as date_of_birth,
    null                                  as gender,
    null                                  as marital_status_code,
    null                                  as ethnic_description,
    CAST(null AS BOOLEAN)                 as is_disabled,
    CAST(null AS BOOLEAN)                 as is_multi_pay_group,
    null                                  as email_address,
    null                                  as address_city,
    null                                  as address_state,
    null                                  as address_zip_code,
    sf.legal_entity_country               as address_country,
    sf.original_hire_date,
    CAST(null AS DATE)                    as last_hire_date,
    CAST(null AS DATE)                    as date_in_job,
    CAST(null AS DATE)                    as date_of_seniority,
    sf.date_of_termination,
    null                                  as employment_status,
    null                                  as status_reason,
    null                                  as status_reason_desc,
    CAST(null AS DATE)                    as status_effective_date,
    -- sf-specific fields
    sf.job_level_sf,
    sf.compensation_amount,
    sf.compensation_currency,
    sf.cost_center_name,
    sf.cost_center_code,
    sf.supervisor_name                    as supervisor_name_sf

from sf