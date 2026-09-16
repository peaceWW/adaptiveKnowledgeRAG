import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import katex from 'katex';
import 'katex/dist/katex.min.css';
const md = new MarkdownIt({ html: false, linkify: true, breaks: true });
md.inline.ruler.before('escape', 'math', (state, silent) => {
  const source = state.src.slice(state.pos);
  const match = /^(?:\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$)/.exec(source);
  if (!match) return false;
  if (!silent) {
    const token = state.push('math', '', 0);
    token.content = match[1] ?? match[2] ?? match[3] ?? match[4];
    token.meta = { display: match[1] !== undefined || match[3] !== undefined };
  }
  state.pos += match[0].length;
  return true;
});
md.renderer.rules.math = (tokens, idx) => katex.renderToString(tokens[idx].content, {
  displayMode: Boolean(tokens[idx].meta?.display), throwOnError: false, trust: false, output: 'html',
});
export function renderAnswer(text: string) {
  return DOMPurify.sanitize(md.render(text || ''));
}
