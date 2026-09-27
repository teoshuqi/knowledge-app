-- Phase 1 I-06: Seed gold.source_registry with ingestion sources
-- All sources from Phase 1 connectors: RSS pool, Reddit, GitHub Trending

INSERT INTO
  gold.source_registry (id, domain_or_handle, source_type, category, badge)
VALUES
  (
    'netflix_blog',
    'netflixtechblog.com',
    'rss',
    'AI Engineering',
    'Primary source'
  ),
  ('jay_alammar', 'jalammar.github.io', 'rss', 'AI Engineering', 'Subject matter expert'),
  (
    'spotify_eng',
    'engineering.atspotify.com',
    'rss',
    'AI Engineering',
    'Primary source'
  ),
  (
    'seattle_data_guy',
    'seattledataguy.com',
    'rss',
    'AI Engineering',
    'Subject matter expert'
  ),
  ('arxiv_llm', 'arxiv.org (cs.CL)', 'rss', 'AI Engineering', 'Peer-reviewed'),
  ('arxiv_ai', 'arxiv.org (cs.AI)', 'rss', 'AI Engineering', 'Peer-reviewed'),
  ('arxiv_ml', 'arxiv.org (stat.ML)', 'rss', 'AI Engineering', 'Peer-reviewed'),
  (
    'r_MachineLearning',
    'r/MachineLearning',
    'reddit',
    'AI Engineering',
    'Community'
  ),
  ('r_LocalLLaMA', 'r/LocalLLaMA', 'reddit', 'AI Engineering', 'Community'),
  ('r_mlops', 'r/mlops', 'reddit', 'AI Engineering', 'Community'),
  (
    'github_trending',
    'GitHub Trending',
    'github_trending',
    'AI Engineering',
    'Primary source'
  )
ON CONFLICT (id) DO NOTHING;
