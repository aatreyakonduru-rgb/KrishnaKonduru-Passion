# Jaffle Shop dbt models

## Model dependencies

staging model `stg_customers` reads `raw_customers`. [E: jaffle-shop/models/staging/stg_customers.sql:5 "raw_customers"]

staging model `stg_locations` reads `raw_stores`. [E: jaffle-shop/models/staging/stg_locations.sql:5 "raw_stores"]

staging model `stg_order_items` reads `raw_items`. [E: jaffle-shop/models/staging/stg_order_items.sql:5 "raw_items"]

staging model `stg_orders` reads `raw_orders`. [E: jaffle-shop/models/staging/stg_orders.sql:5 "raw_orders"]

staging model `stg_products` reads `raw_products`. [E: jaffle-shop/models/staging/stg_products.sql:5 "raw_products"]

staging model `stg_supplies` reads `raw_supplies`. [E: jaffle-shop/models/staging/stg_supplies.sql:5 "raw_supplies"]

marts model `customers` reads `stg_customers`. [E: jaffle-shop/models/marts/customers.sql:5 "stg_customers"]

marts model `customers` reads `orders`. [E: jaffle-shop/models/marts/customers.sql:11 "orders"]

marts model `locations` reads `stg_locations`. [E: jaffle-shop/models/marts/locations.sql:5 "stg_locations"]

marts model `order_items` reads `stg_order_items`. [E: jaffle-shop/models/marts/order_items.sql:5 "stg_order_items"]

marts model `order_items` reads `stg_orders`. [E: jaffle-shop/models/marts/order_items.sql:12 "stg_orders"]

marts model `order_items` reads `stg_products`. [E: jaffle-shop/models/marts/order_items.sql:18 "stg_products"]

marts model `order_items` reads `stg_supplies`. [E: jaffle-shop/models/marts/order_items.sql:24 "stg_supplies"]

marts model `orders` reads `stg_orders`. [E: jaffle-shop/models/marts/orders.sql:5 "stg_orders"]

marts model `orders` reads `order_items`. [E: jaffle-shop/models/marts/orders.sql:11 "order_items"]

marts model `products` reads `stg_products`. [E: jaffle-shop/models/marts/products.sql:5 "stg_products"]

marts model `supplies` reads `stg_supplies`. [E: jaffle-shop/models/marts/supplies.sql:5 "stg_supplies"]

## Materialization

Staging models are built as views. [E: jaffle-shop/dbt_project.yml:33 "+materialized: view"]

Marts models are built as tables. [E: jaffle-shop/dbt_project.yml:35 "+materialized: table"]

## Open questions

Who owns the raw schema that feeds the source tables? [?: Q-0002]
