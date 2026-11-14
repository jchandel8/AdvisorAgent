-- Step 7a: cache of news searches made by the Market MCP server (Tavily). Searches never contain client
-- data (the server refuses such queries before calling out), so the cache holds only public news.
-- Entries are reused for 6 hours: fewer paid calls, and repeatable demos.
CREATE TABLE market_news_cache (
    key         text PRIMARY KEY,            -- sha256 of the normalized query and options
    query       text NOT NULL,
    response    jsonb NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX market_news_cache_fetched_idx ON market_news_cache (fetched_at);
