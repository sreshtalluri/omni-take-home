-- un-reverse source domains once, dedup defensively; one row per
-- (release, source_domain, target_domain)
with edges as (
    select
        release,
        lower(array_to_string(list_reverse(string_split(source_rev_domain, '.')), '.'))
            as source_domain,
        lower(target_domain) as target_domain
    from {{ source('raw', 'raw_backlink_edges') }}
)
select distinct release, source_domain, target_domain
from edges
where source_domain <> target_domain
