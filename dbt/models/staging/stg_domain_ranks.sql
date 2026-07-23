select
    r.release,
    lower(array_to_string(list_reverse(string_split(r.source_rev_domain, '.')), '.'))
        as source_domain,
    r.hc_pos,
    s.nodes_total,
    -- harmonic centrality position 1 = best; convert to 0..1 percentile
    1.0 - (r.hc_pos - 1.0) / s.nodes_total as authority_percentile
from {{ source('raw', 'raw_domain_ranks') }} r
join {{ source('raw', 'raw_graph_stats') }} s using (release)
