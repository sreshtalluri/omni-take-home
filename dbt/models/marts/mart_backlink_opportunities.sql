with coverage as (select * from {{ ref('int_competitor_coverage') }}),
authority as (select * from {{ ref('int_domain_authority') }}),
scored as (
    select
        c.source_domain,
        c.links_sigma, c.links_hex, c.links_mode, c.links_lightdash, c.links_omni,
        c.links_sigma + c.links_hex + c.links_mode + c.links_lightdash
            as competitor_count,
        c.present_in_both,
        c.releases_seen,
        coalesce(a.authority_percentile, 0) as authority_percentile,
        {{ var('weight_gap_breadth') }}
            * (c.links_sigma + c.links_hex + c.links_mode + c.links_lightdash) / 4.0
        + {{ var('weight_authority') }} * coalesce(a.authority_percentile, 0)
        + {{ var('weight_persistence') }} * c.present_in_both
            as opportunity_score
    from coverage c
    left join authority a using (source_domain)
),
categorized as (
    select s.*,
        -- NOTE: regexp_matches(...), not `similar to '%(...)%'` as in the
        -- brief -- see task-7-report.md "Deviations". In the installed
        -- DuckDB (1.5.5), SIMILAR TO treats `%`/`_` as literal characters
        -- rather than wildcards (verified empirically: 'ab' similar to '%'
        -- is false), so the brief's patterns would never match. regexp_matches
        -- does the same unanchored "contains one of these alternatives"
        -- check the brief intends.
        coalesce(o.category,
            case
                when regexp_matches(s.source_domain, '(top10|best|review|vs|compare|toplist)')
                    then 'listicle/review'
                when regexp_matches(s.source_domain, '(learn|course|academy|tutorial|univ|school|edu)')
                    or s.source_domain like '%.edu' then 'community/education'
                when regexp_matches(s.source_domain, '(dev|docs|github|stack|engineer|data|analytics)')
                    then 'dev-tooling/data-content'
                when regexp_matches(s.source_domain, '(news|daily|weekly|times|post|magazine|media)')
                    then 'news/media'
                when regexp_matches(s.source_domain, '(directory|list|tools|apps|software|saas)')
                    then 'directory'
                else 'other'
            end) as category
    from scored s
    left join {{ ref('category_overrides') }} o using (source_domain)
)
select * from categorized
where links_omni = 0
  and competitor_count >= {{ var('min_competitor_count') }}
order by opportunity_score desc
