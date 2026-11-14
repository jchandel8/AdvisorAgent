"""search_documents: full-text search over the documents of accounts the advisor can access.

Same access rule as every other tool: only documents on visible accounts (open, with the advisor's
account_access row, and the selected client's accounts when one is selected). Deleted documents are never
found. Ranking and snippets are done by Postgres (ts_rank_cd, ts_headline), not by the model.
"""

from __future__ import annotations

from wealth.access import NOT_FOUND, VISIBLE, ToolContext, scoped_account_ids
from wealth.tools.schemas import DocumentSearchInput

HEADLINE_OPTIONS = 'MaxFragments=2, MinWords=6, MaxWords=28, FragmentDelimiter=" … ", StartSel=«, StopSel=»'


def search_documents(ctx: ToolContext, params: DocumentSearchInput) -> dict:
    ids = None
    if params.account_id is not None or params.client_id is not None:
        ids = scoped_account_ids(ctx, account_id=params.account_id, client_id=params.client_id)
        if not ids:
            return NOT_FOUND
    rows = ctx.conn.execute(
        f"""WITH {VISIBLE},
        q AS (SELECT websearch_to_tsquery('english', %(query)s) AS tsq)
        SELECT d.id AS document_id,
               d.title,
               d.doc_type,
               a.id AS account_id,
               a.account_name,
               coalesce(d.uploaded_at::date, d.created_date) AS document_date,
               round(ts_rank_cd(d.search_tsv, q.tsq)::numeric, 4) AS rank,
               ts_headline('english', coalesce(d.text, d.extracted_text, d.note, d.title), q.tsq,
                           %(headline)s) AS snippet
        FROM visible v
        JOIN accounts a ON a.id = v.account_id
        JOIN documents d ON d.account_id = v.account_id AND d.deleted_at IS NULL
        CROSS JOIN q
        WHERE d.search_tsv @@ q.tsq
          AND (%(ids)s::int[] IS NULL OR v.account_id = ANY(%(ids)s::int[]))
        ORDER BY rank DESC, document_date DESC, d.id DESC
        LIMIT %(limit)s""",
        {
            **ctx.viewer_params(),
            "query": params.query,
            "headline": HEADLINE_OPTIONS,
            "ids": ids,
            "limit": params.limit,
        },
    ).fetchall()
    return {
        "query": params.query,
        "result_count": len(rows),
        "results": rows,
        "note": "Snippets mark matching words with « ». Full documents are in the advisor's Documents page.",
    }
