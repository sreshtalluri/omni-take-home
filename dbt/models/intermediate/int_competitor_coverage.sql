select
    source_domain,
    max(case when target_domain = 'omni.co' then 1 else 0 end)            as links_omni,
    max(case when target_domain = 'sigmacomputing.com' then 1 else 0 end) as links_sigma,
    max(case when target_domain = 'hex.tech' then 1 else 0 end)           as links_hex,
    max(case when target_domain = 'mode.com' then 1 else 0 end)           as links_mode,
    max(case when target_domain = 'lightdash.com' then 1 else 0 end)      as links_lightdash,
    count(distinct release)                                               as releases_seen,
    (count(distinct release) = 2)::int                                    as present_in_both
from {{ ref('stg_backlink_edges') }}
group by 1
