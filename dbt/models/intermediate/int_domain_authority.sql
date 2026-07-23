-- best (max) percentile across releases; a domain's authority shouldn't
-- drop just because one release ranked it slightly lower
select source_domain, max(authority_percentile) as authority_percentile
from {{ ref('stg_domain_ranks') }}
group by 1
