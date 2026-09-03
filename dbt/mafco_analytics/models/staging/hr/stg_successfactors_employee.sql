select
    `Employee_Id`                                                          as sf_employee_id,
    `First_Name-Personal_Information`                                      as first_name,
    `Last_Name-Personal_Information`                                       as last_name,
    `Name-Business_Unit`                                                   as business_unit_name,
    `Code-Business_Unit`                                                   as business_unit_code,
    `Name-Legal_Entity`                                                    as company_name,
    `Code-Legal_Entity`                                                    as company_code,
    `Country_of_Registration-Legal_Entity`                                 as legal_entity_country,
    `Name-Department`                                                      as department_name,
    `Code-Department`                                                      as department_code,
    `Name-Cost_Center`                                                     as cost_center_name,
    `Code-Cost_Center`                                                     as cost_center_code,
    `District-FOCorporateAddressDEFLT`                                     as address_district,
    `Country/Region-FOCorporateAddressDEFLT`                               as address_country_region,
    CAST(TRY_TO_TIMESTAMP(`Latest_Termination_Date-PersonEmpTerminationInfo`, 'MM/dd/yyyy') AS DATE)
                                                                            as date_of_termination,
    CAST(TRY_TO_TIMESTAMP(`Hire_Date-Employment_Details`, 'MM/dd/yyyy') AS DATE)
                                                                            as original_hire_date,
    `Job_Level-Position`                                                   as job_level_sf,
    `Job_Title-Position`                                                   as job_title,
    `label-PicklistLabel`                                                  as employment_type,
    `Supervisor-Job_Information`                                           as supervisor_name,
    TRY_CAST(`amount-EmpCompensationGroupSumCalculated` AS DECIMAL(18,2))  as compensation_amount,
    `Currency_Code-EmpCompensationGroupSumCalculated`                      as compensation_currency,
    CAST(TRY_TO_TIMESTAMP(`Date_of_Salary_Last_Adjustment-Compensation_Information`, "yyyy-MM-dd'T'HH:mm:ss'Z'") AS DATE)
                                                                            as last_salary_adjustment_date,
    `label-PicklistLabel.1`                                                as employment_status_label

from {{ source('hr_raw', 'dim_emp') }}
