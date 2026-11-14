import { describe, expect, it } from 'vitest';
import { AgentStep } from '../../core/models';
import { summary } from './agent-runs';

function step(kind: AgentStep['kind'], request: unknown, response: unknown, name = 'x'): AgentStep {
  return {
    seq: 1,
    kind,
    name,
    started_at: '2026-11-14T00:00:00Z',
    duration_ms: 5,
    request,
    response,
    truncated: false,
    is_error: false,
    stop_reason: null,
    input_tokens: null,
    output_tokens: null,
    cache_read_tokens: null,
    cache_write_tokens: null,
  };
}

describe('agent run step summaries', () => {
  it('shows the tool calls a model asked for, with their arguments', () => {
    const s = step(
      'model',
      {},
      {
        content: [{ type: 'tool_use', name: 'get_accounts', input: { client_id: 201 } }],
      },
    );
    expect(summary(s)).toBe('Asked for a tool: get_accounts(client_id=201)');
  });

  it('shows the start of what a model wrote', () => {
    const s = step('model', {}, { content: [{ type: 'text', text: 'C1 has account X.' }] });
    expect(summary(s)).toBe('Wrote: C1 has account X.');
  });

  it('shows a tool call and whether it failed', () => {
    const ok = step('tool', { input: { query: 'college' } }, { results: [] }, 'search_documents');
    const bad = step('tool', { input: { account_id: 9 } }, { error: 'not found' }, 'get_holdings');
    expect(summary(ok)).toBe('search_documents(query="college") → ok');
    expect(summary(bad)).toBe('get_holdings(account_id=9) → error: not found');
  });

  it('shows the scope check verdict', () => {
    const s = step('scope_check', {}, { category: 'out_of_scope', reason: 'general knowledge' });
    expect(summary(s)).toBe('out_of_scope: general knowledge');
  });
});
