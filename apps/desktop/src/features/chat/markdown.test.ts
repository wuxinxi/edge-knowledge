// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { renderAnswer } from './markdown'
function render(content: string, count = 2) {
  const root = document.createElement('div')
  root.innerHTML = renderAnswer(content, count, 'Copy code', 'View source')
  return root
}
describe('safe answer rendering', () => {
  it('renders lists, inline code, fenced code and tables without exposing Markdown delimiters', () => {
    const root = render(
      '# Summary\n\n- **One**\n- `local-only`\n\n```ts\nconst value = "<safe>"\n```\n\n| Name | Status |\n| --- | --- |\n| Notes | Ready |',
    )
    expect(root.querySelector('h1')?.textContent).toBe('Summary')
    expect(root.querySelectorAll('li')).toHaveLength(2)
    expect(root.querySelector('pre code')?.textContent).toContain('"<safe>"')
    expect(root.querySelector('button[data-copy-code]')?.textContent).toBe('Copy code')
    expect(root.querySelector('table td')?.textContent).toBe('Notes')
  })
  it('makes only valid evidence numbers clickable and leaves citations inside code untouched', () => {
    const root = render(
      'Evidence [1][2] [99] and `[1]`.\n\n```text\n[2]\n```\n\n[1](https://example.com)',
    )
    expect(
      [...root.querySelectorAll('button[data-source-index]')].map((e) =>
        e.getAttribute('data-source-index'),
      ),
    ).toEqual(['0', '1'])
    expect(root.querySelector('pre')?.textContent).toContain('[2]')
    expect(root.querySelector('a button')).toBeNull()
    expect(render('[1]', 0).querySelector('button')).toBeNull()
  })
  it('rejects scripts, event handlers, remote images and unsafe links from model output', () => {
    const root = render(
      '<script>alert(1)</script><img src="https://example.com/track" onerror="alert(1)">\n\n![track](https://example.com/track)\n\n[bad](javascript:alert%281%29) [file](file:///etc/passwd) [data](data:text/html,x)\n\n```html\n<img src=x onerror=alert(1)>\n```',
    )
    expect(root.querySelector('script,img,iframe,svg,style')).toBeNull()
    expect(root.querySelector('[onerror],[onclick],[style]')).toBeNull()
    expect(
      [...root.querySelectorAll('a')].every((a) => !/^(javascript|file|data):/i.test(a.href)),
    ).toBe(true)
    expect(root.querySelector('code')?.textContent).toContain('<img')
  })
})
