select * from {{ ref('mart_backlink_opportunities') }}
where competitor_count < 2 or competitor_count > 4
