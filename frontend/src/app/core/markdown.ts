import DOMPurify from 'dompurify';
import { marked } from 'marked';

/** Markdown from the model -> sanitized HTML. DOMPurify removes scripts, handlers and unsafe URLs. */
export function renderMarkdown(text: string): string {
  const html = marked.parse(text, { async: false, gfm: true, breaks: false }) as string;
  return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}
