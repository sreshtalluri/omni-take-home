-- present_in_both compares against the number of releases actually loaded,
-- not a hardcoded 2: when a third release lands in this recurring pipeline,
-- the flag keeps meaning "seen in every release" instead of silently
-- inverting for domains seen in all three. The column name reflects the
-- current two-release deliverable; it is a domain-level signal (the domain
-- linked to some competitor in every release), not a per-edge one.
with loaded_releases as (
    select count(distinct release) as n_releases
    from {{ ref('stg_backlink_edges') }}
)

select
    source_domain,
    max(case when target_domain = 'omni.co' then 1 else 0 end)            as links_omni,
    max(case when target_domain = 'sigmacomputing.com' then 1 else 0 end) as links_sigma,
    max(case when target_domain = 'hex.tech' then 1 else 0 end)           as links_hex,
    max(case when target_domain = 'mode.com' then 1 else 0 end)           as links_mode,
    max(case when target_domain = 'lightdash.com' then 1 else 0 end)      as links_lightdash,
    count(distinct release)                                               as releases_seen,
    (count(distinct release) = (select n_releases from loaded_releases))::int
                                                                           as present_in_both
from {{ ref('stg_backlink_edges') }}
group by 1
