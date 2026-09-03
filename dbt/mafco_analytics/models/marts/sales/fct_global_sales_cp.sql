select
    coalesce(team,                 'Unassigned') as team,
    coalesce(sales_rep,            'Unassigned') as sales_rep,
    coalesce(cust_group,           'Unassigned') as cust_group,
    coalesce(cust_name,            'Unassigned') as cust_name,
    coalesce(unified_product_code, 'Unassigned') as unified_product_code,
    coalesce(max(unified_product_name), 'Unassigned') as unified_product_name,
    coalesce(max(category_type),        'Unassigned') as category_type,
    coalesce(max(product_categories),   'Unassigned') as product_categories,

    -- =================== group 1: revenue by order_date ===================
    sum(case when year(order_date) = year(current_date) - 3 then revenue else 0 end) as rev_od_year_minus_3,
    sum(case when year(order_date) = year(current_date) - 2 then revenue else 0 end) as rev_od_year_minus_2,
    sum(case when year(order_date) = year(current_date) - 1 then revenue else 0 end) as rev_od_year_minus_1,
    sum(case when order_date >= dateadd(month,-24,current_date) and order_date < dateadd(month,-12,current_date) then revenue else 0 end) as rev_od_l12mya,
    sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then revenue else 0 end) as rev_od_l12m,
    sum(case when order_date >= dateadd(day,-730,current_date) and order_date < dateadd(day,-365,current_date) then revenue else 0 end) as rev_od_l365dya,
    sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then revenue else 0 end) as rev_od_l365d,
    sum(case when year(order_date) = year(current_date) then revenue else 0 end) as rev_od_year_current,
    sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then revenue else 0 end) -
    sum(case when year(order_date) = year(current_date) - 1 then revenue else 0 end) as rev_od_l12mxpy,
    sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then revenue else 0 end) -
    sum(case when year(order_date) = year(current_date) - 1 then revenue else 0 end) as rev_od_l365dxpy,
    sum(case when order_date >= date_trunc('month',dateadd(month,-3,current_date)) and order_date < date_trunc('month',current_date) then revenue else 0 end) as rev_od_l3m,
    sum(case when order_date >= date_trunc('month',current_date) and order_date < current_date then revenue else 0 end) as rev_od_mtd,
    sum(case when order_date > current_date and invoice_date <= current_date then revenue else 0 end) as rev_od_backlog,

    -- =================== group 2: shipped_qty_in_kg by order_date ===================
    sum(case when year(order_date) = year(current_date) - 3 then shipped_qty_in_kg else 0 end) as kg_od_year_minus_3,
    sum(case when year(order_date) = year(current_date) - 2 then shipped_qty_in_kg else 0 end) as kg_od_year_minus_2,
    sum(case when year(order_date) = year(current_date) - 1 then shipped_qty_in_kg else 0 end) as kg_od_year_minus_1,
    sum(case when order_date >= dateadd(month,-24,current_date) and order_date < dateadd(month,-12,current_date) then shipped_qty_in_kg else 0 end) as kg_od_l12mya,
    sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then shipped_qty_in_kg else 0 end) as kg_od_l12m,
    sum(case when order_date >= dateadd(day,-730,current_date) and order_date < dateadd(day,-365,current_date) then shipped_qty_in_kg else 0 end) as kg_od_l365dya,
    sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then shipped_qty_in_kg else 0 end) as kg_od_l365d,
    sum(case when year(order_date) = year(current_date) then shipped_qty_in_kg else 0 end) as kg_od_year_current,
    sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then shipped_qty_in_kg else 0 end) -
    sum(case when year(order_date) = year(current_date) - 1 then shipped_qty_in_kg else 0 end) as kg_od_l12mxpy,
    sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then shipped_qty_in_kg else 0 end) -
    sum(case when year(order_date) = year(current_date) - 1 then shipped_qty_in_kg else 0 end) as kg_od_l365dxpy,
    sum(case when order_date >= date_trunc('month',dateadd(month,-3,current_date)) and order_date < date_trunc('month',current_date) then shipped_qty_in_kg else 0 end) as kg_od_l3m,
    sum(case when order_date >= date_trunc('month',current_date) and order_date < current_date then shipped_qty_in_kg else 0 end) as kg_od_mtd,
    sum(case when order_date > current_date and invoice_date <= current_date then shipped_qty_in_kg else 0 end) as kg_od_backlog,

    -- =================== group 3: revenue by invoice_date ===================
    sum(case when year(invoice_date) = year(current_date) - 3 then revenue else 0 end) as rev_id_year_minus_3,
    sum(case when year(invoice_date) = year(current_date) - 2 then revenue else 0 end) as rev_id_year_minus_2,
    sum(case when year(invoice_date) = year(current_date) - 1 then revenue else 0 end) as rev_id_year_minus_1,
    sum(case when invoice_date >= dateadd(month,-24,current_date) and invoice_date < dateadd(month,-12,current_date) then revenue else 0 end) as rev_id_l12mya,
    sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then revenue else 0 end) as rev_id_l12m,
    sum(case when invoice_date >= dateadd(day,-730,current_date) and invoice_date < dateadd(day,-365,current_date) then revenue else 0 end) as rev_id_l365dya,
    sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then revenue else 0 end) as rev_id_l365d,
    sum(case when year(invoice_date) = year(current_date) then revenue else 0 end) as rev_id_year_current,
    sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then revenue else 0 end) -
    sum(case when year(invoice_date) = year(current_date) - 1 then revenue else 0 end) as rev_id_l12mxpy,
    sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then revenue else 0 end) -
    sum(case when year(invoice_date) = year(current_date) - 1 then revenue else 0 end) as rev_id_l365dxpy,
    sum(case when invoice_date >= date_trunc('month',dateadd(month,-3,current_date)) and invoice_date < date_trunc('month',current_date) then revenue else 0 end) as rev_id_l3m,
    sum(case when invoice_date >= date_trunc('month',current_date) and invoice_date < current_date then revenue else 0 end) as rev_id_mtd,
    sum(case when order_date > current_date and invoice_date <= current_date then revenue else 0 end) as rev_id_backlog,

    -- =================== group 4: shipped_qty_in_kg by invoice_date ===================
    sum(case when year(invoice_date) = year(current_date) - 3 then shipped_qty_in_kg else 0 end) as kg_id_year_minus_3,
    sum(case when year(invoice_date) = year(current_date) - 2 then shipped_qty_in_kg else 0 end) as kg_id_year_minus_2,
    sum(case when year(invoice_date) = year(current_date) - 1 then shipped_qty_in_kg else 0 end) as kg_id_year_minus_1,
    sum(case when invoice_date >= dateadd(month,-24,current_date) and invoice_date < dateadd(month,-12,current_date) then shipped_qty_in_kg else 0 end) as kg_id_l12mya,
    sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then shipped_qty_in_kg else 0 end) as kg_id_l12m,
    sum(case when invoice_date >= dateadd(day,-730,current_date) and invoice_date < dateadd(day,-365,current_date) then shipped_qty_in_kg else 0 end) as kg_id_l365dya,
    sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then shipped_qty_in_kg else 0 end) as kg_id_l365d,
    sum(case when year(invoice_date) = year(current_date) then shipped_qty_in_kg else 0 end) as kg_id_year_current,
    sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then shipped_qty_in_kg else 0 end) -
    sum(case when year(invoice_date) = year(current_date) - 1 then shipped_qty_in_kg else 0 end) as kg_id_l12mxpy,
    sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then shipped_qty_in_kg else 0 end) -
    sum(case when year(invoice_date) = year(current_date) - 1 then shipped_qty_in_kg else 0 end) as kg_id_l365dxpy,
    sum(case when invoice_date >= date_trunc('month',dateadd(month,-3,current_date)) and invoice_date < date_trunc('month',current_date) then shipped_qty_in_kg else 0 end) as kg_id_l3m,
    sum(case when invoice_date >= date_trunc('month',current_date) and invoice_date < current_date then shipped_qty_in_kg else 0 end) as kg_id_mtd,
    sum(case when order_date > current_date and invoice_date <= current_date then shipped_qty_in_kg else 0 end) as kg_id_backlog,

    -- =================== group 5: profit by invoice_date ===================
    sum(case when year(invoice_date) = year(current_date) - 3 then profit else 0 end) as profit_id_year_minus_3,
    sum(case when year(invoice_date) = year(current_date) - 2 then profit else 0 end) as profit_id_year_minus_2,
    sum(case when year(invoice_date) = year(current_date) - 1 then profit else 0 end) as profit_id_year_minus_1,
    sum(case when invoice_date >= dateadd(month,-24,current_date) and invoice_date < dateadd(month,-12,current_date) then profit else 0 end) as profit_id_l12mya,
    sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then profit else 0 end) as profit_id_l12m,
    sum(case when invoice_date >= dateadd(day,-730,current_date) and invoice_date < dateadd(day,-365,current_date) then profit else 0 end) as profit_id_l365dya,
    sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then profit else 0 end) as profit_id_l365d,
    sum(case when year(invoice_date) = year(current_date) then profit else 0 end) as profit_id_year_current,
    sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then profit else 0 end) -
    sum(case when year(invoice_date) = year(current_date) - 1 then profit else 0 end) as profit_id_l12mxpy,
    sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then profit else 0 end) -
    sum(case when year(invoice_date) = year(current_date) - 1 then profit else 0 end) as profit_id_l365dxpy,
    sum(case when invoice_date >= date_trunc('month',dateadd(month,-3,current_date)) and invoice_date < date_trunc('month',current_date) then profit else 0 end) as profit_id_l3m,
    sum(case when invoice_date >= date_trunc('month',current_date) and invoice_date < current_date then profit else 0 end) as profit_id_mtd,
    sum(case when order_date > current_date and invoice_date <= current_date then profit else 0 end) as profit_id_backlog,

    -- =================== group 6: margin (profit/revenue) by invoice_date ===================
    coalesce(sum(case when year(invoice_date) = year(current_date) - 3 then profit else 0 end) / nullif(sum(case when year(invoice_date) = year(current_date) - 3 then revenue else 0 end), 0), 0) as margin_id_year_minus_3,
    coalesce(sum(case when year(invoice_date) = year(current_date) - 2 then profit else 0 end) / nullif(sum(case when year(invoice_date) = year(current_date) - 2 then revenue else 0 end), 0), 0) as margin_id_year_minus_2,
    coalesce(sum(case when year(invoice_date) = year(current_date) - 1 then profit else 0 end) / nullif(sum(case when year(invoice_date) = year(current_date) - 1 then revenue else 0 end), 0), 0) as margin_id_year_minus_1,
    coalesce(sum(case when invoice_date >= dateadd(month,-24,current_date) and invoice_date < dateadd(month,-12,current_date) then profit else 0 end) / nullif(sum(case when invoice_date >= dateadd(month,-24,current_date) and invoice_date < dateadd(month,-12,current_date) then revenue else 0 end), 0), 0) as margin_id_l12mya,
    coalesce(sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then profit else 0 end) / nullif(sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then revenue else 0 end), 0), 0) as margin_id_l12m,
    coalesce(sum(case when invoice_date >= dateadd(day,-730,current_date) and invoice_date < dateadd(day,-365,current_date) then profit else 0 end) / nullif(sum(case when invoice_date >= dateadd(day,-730,current_date) and invoice_date < dateadd(day,-365,current_date) then revenue else 0 end), 0), 0) as margin_id_l365dya,
    coalesce(sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then profit else 0 end) / nullif(sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then revenue else 0 end), 0), 0) as margin_id_l365d,
    coalesce(sum(case when year(invoice_date) = year(current_date) then profit else 0 end) / nullif(sum(case when year(invoice_date) = year(current_date) then revenue else 0 end), 0), 0) as margin_id_year_current,
    coalesce(sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then profit else 0 end) - sum(case when year(invoice_date) = year(current_date) - 1 then profit else 0 end) / nullif(sum(case when invoice_date >= dateadd(month,-12,current_date) and invoice_date < current_date then revenue else 0 end) - sum(case when year(invoice_date) = year(current_date) - 1 then revenue else 0 end), 0), 0) as margin_id_l12mxpy,
    coalesce(sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then profit else 0 end) - sum(case when year(invoice_date) = year(current_date) - 1 then profit else 0 end) / nullif(sum(case when invoice_date >= dateadd(day,-365,current_date) and invoice_date < current_date then revenue else 0 end) - sum(case when year(invoice_date) = year(current_date) - 1 then revenue else 0 end), 0), 0) as margin_id_l365dxpy,
    coalesce(sum(case when invoice_date >= date_trunc('month',dateadd(month,-3,current_date)) and invoice_date < date_trunc('month',current_date) then profit else 0 end) / nullif(sum(case when invoice_date >= date_trunc('month',dateadd(month,-3,current_date)) and invoice_date < date_trunc('month',current_date) then revenue else 0 end), 0), 0) as margin_id_l3m,
    coalesce(sum(case when invoice_date >= date_trunc('month',current_date) and invoice_date < current_date then profit else 0 end) / nullif(sum(case when invoice_date >= date_trunc('month',current_date) and invoice_date < current_date then revenue else 0 end), 0), 0) as margin_id_mtd,
    coalesce(sum(case when order_date > current_date and invoice_date <= current_date then profit else 0 end) / nullif(sum(case when order_date > current_date and invoice_date <= current_date then revenue else 0 end), 0), 0) as margin_id_backlog,

    -- =================== group 7: profit by order_date ===================
    sum(case when year(order_date) = year(current_date) - 3 then profit else 0 end) as profit_od_year_minus_3,
    sum(case when year(order_date) = year(current_date) - 2 then profit else 0 end) as profit_od_year_minus_2,
    sum(case when year(order_date) = year(current_date) - 1 then profit else 0 end) as profit_od_year_minus_1,
    sum(case when order_date >= dateadd(month,-24,current_date) and order_date < dateadd(month,-12,current_date) then profit else 0 end) as profit_od_l12mya,
    sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then profit else 0 end) as profit_od_l12m,
    sum(case when order_date >= dateadd(day,-730,current_date) and order_date < dateadd(day,-365,current_date) then profit else 0 end) as profit_od_l365dya,
    sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then profit else 0 end) as profit_od_l365d,
    sum(case when year(order_date) = year(current_date) then profit else 0 end) as profit_od_year_current,
    sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then profit else 0 end) -
    sum(case when year(order_date) = year(current_date) - 1 then profit else 0 end) as profit_od_l12mxpy,
    sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then profit else 0 end) -
    sum(case when year(order_date) = year(current_date) - 1 then profit else 0 end) as profit_od_l365dxpy,
    sum(case when order_date >= date_trunc('month',dateadd(month,-3,current_date)) and order_date < date_trunc('month',current_date) then profit else 0 end) as profit_od_l3m,
    sum(case when order_date >= date_trunc('month',current_date) and order_date < current_date then profit else 0 end) as profit_od_mtd,
    sum(case when order_date > current_date and invoice_date <= current_date then profit else 0 end) as profit_od_backlog,

    -- =================== group 8: margin (profit/revenue) by order_date ===================
    coalesce(sum(case when year(order_date) = year(current_date) - 3 then profit else 0 end) / nullif(sum(case when year(order_date) = year(current_date) - 3 then revenue else 0 end), 0), 0) as margin_od_year_minus_3,
    coalesce(sum(case when year(order_date) = year(current_date) - 2 then profit else 0 end) / nullif(sum(case when year(order_date) = year(current_date) - 2 then revenue else 0 end), 0), 0) as margin_od_year_minus_2,
    coalesce(sum(case when year(order_date) = year(current_date) - 1 then profit else 0 end) / nullif(sum(case when year(order_date) = year(current_date) - 1 then revenue else 0 end), 0), 0) as margin_od_year_minus_1,
    coalesce(sum(case when order_date >= dateadd(month,-24,current_date) and order_date < dateadd(month,-12,current_date) then profit else 0 end) / nullif(sum(case when order_date >= dateadd(month,-24,current_date) and order_date < dateadd(month,-12,current_date) then revenue else 0 end), 0), 0) as margin_od_l12mya,
    coalesce(sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then profit else 0 end) / nullif(sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then revenue else 0 end), 0), 0) as margin_od_l12m,
    coalesce(sum(case when order_date >= dateadd(day,-730,current_date) and order_date < dateadd(day,-365,current_date) then profit else 0 end) / nullif(sum(case when order_date >= dateadd(day,-730,current_date) and order_date < dateadd(day,-365,current_date) then revenue else 0 end), 0), 0) as margin_od_l365dya,
    coalesce(sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then profit else 0 end) / nullif(sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then revenue else 0 end), 0), 0) as margin_od_l365d,
    coalesce(sum(case when year(order_date) = year(current_date) then profit else 0 end) / nullif(sum(case when year(order_date) = year(current_date) then revenue else 0 end), 0), 0) as margin_od_year_current,
    coalesce(sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then profit else 0 end) - sum(case when year(order_date) = year(current_date) - 1 then profit else 0 end) / nullif(sum(case when order_date >= dateadd(month,-12,current_date) and order_date < current_date then revenue else 0 end) - sum(case when year(order_date) = year(current_date) - 1 then revenue else 0 end), 0), 0) as margin_od_l12mxpy,
    coalesce(sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then profit else 0 end) - sum(case when year(order_date) = year(current_date) - 1 then profit else 0 end) / nullif(sum(case when order_date >= dateadd(day,-365,current_date) and order_date < current_date then revenue else 0 end) - sum(case when year(order_date) = year(current_date) - 1 then revenue else 0 end), 0), 0) as margin_od_l365dxpy,
    coalesce(sum(case when order_date >= date_trunc('month',dateadd(month,-3,current_date)) and order_date < date_trunc('month',current_date) then profit else 0 end) / nullif(sum(case when order_date >= date_trunc('month',dateadd(month,-3,current_date)) and order_date < date_trunc('month',current_date) then revenue else 0 end), 0), 0) as margin_od_l3m,
    coalesce(sum(case when order_date >= date_trunc('month',current_date) and order_date < current_date then profit else 0 end) / nullif(sum(case when order_date >= date_trunc('month',current_date) and order_date < current_date then revenue else 0 end), 0), 0) as margin_od_mtd,
    coalesce(sum(case when order_date > current_date and invoice_date <= current_date then profit else 0 end) / nullif(sum(case when order_date > current_date and invoice_date <= current_date then revenue else 0 end), 0), 0) as margin_od_backlog,
    coalesce(product_segment, 'Unassigned') as product_segment

from {{ ref('fct_global_sales_orders_2') }}
group by
    coalesce(team,                 'Unassigned'),
    coalesce(sales_rep,            'Unassigned'),
    coalesce(cust_group,           'Unassigned'),
    coalesce(cust_name,            'Unassigned'),
    coalesce(unified_product_code, 'Unassigned'),
    coalesce(product_segment,      'Unassigned')
    