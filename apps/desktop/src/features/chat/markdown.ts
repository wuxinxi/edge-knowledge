import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

export function renderAnswer(
  content: string,
  sourceCount: number,
  copyLabel: string,
  sourceLabel: string,
): string {
  const md = new MarkdownIt({ html: false, linkify: false, breaks: true, typographer: false })
  md.disable('image')
  md.inline.ruler.before('link', 'citation', (state, silent) => {
    if (state.src[state.pos] !== '[' || state.linkLevel > 0) return false
    const match = state.src.slice(state.pos).match(/^\[(\d{1,3})\](?![(:])/)
    if (!match) return false
    const index = Number(match[1])
    if (index < 1 || index > sourceCount) return false
    if (!silent) {
      const token = state.push('html_inline', '', 0)
      token.content = `<button type="button" class="answer-citation" data-source-index="${index - 1}" aria-label="${md.utils.escapeHtml(sourceLabel)} ${index}">${index}</button>`
    }
    state.pos += match[0].length
    return true
  })
  md.renderer.rules.fence = (tokens, index) => {
    const token = tokens[index]!
    const language = token.info.trim().split(/\s+/)[0] || 'text'
    return `<div class="answer-code"><div class="answer-code-heading"><span>${md.utils.escapeHtml(language)}</span><button type="button" data-copy-code="true">${md.utils.escapeHtml(copyLabel)}</button></div><pre><code>${md.utils.escapeHtml(token.content)}</code></pre></div>`
  }
  md.renderer.rules.link_open = (tokens, index, options, _env, renderer) => {
    const token = tokens[index]!
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
    return renderer.renderToken(tokens, index, options)
  }
  return DOMPurify.sanitize(md.render(content), {
    ALLOWED_TAGS: [
      'p',
      'br',
      'strong',
      'em',
      's',
      'ul',
      'ol',
      'li',
      'h1',
      'h2',
      'h3',
      'h4',
      'h5',
      'h6',
      'blockquote',
      'pre',
      'code',
      'table',
      'thead',
      'tbody',
      'tr',
      'th',
      'td',
      'hr',
      'a',
      'div',
      'span',
      'button',
    ],
    ALLOWED_ATTR: [
      'class',
      'href',
      'title',
      'target',
      'rel',
      'type',
      'aria-label',
      'data-source-index',
      'data-copy-code',
      'start',
      'align',
    ],
    ALLOW_DATA_ATTR: false,
  })
}
