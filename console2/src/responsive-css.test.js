import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

describe('1024 desktop layout contract', () => {
  it('removes the legacy 1180px floor and collapses major two-column workspaces', () => {
    const styles = readFileSync('src/styles.css', 'utf8')
    const full = readFileSync('src/full.css', 'utf8')
    expect(styles).toMatch(/@media \(max-width: 1100px\)[\s\S]*body\s*\{[^}]*min-width:\s*0/)
    expect(styles).toMatch(/@media \(max-width: 1100px\)[\s\S]*\.app-shell\s*\{[^}]*min-width:\s*0/)
    expect(full).toMatch(/@media \(max-width: 1100px\)[\s\S]*\.dashboard-grid[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
    expect(full).toMatch(/@media \(max-width: 1100px\)[\s\S]*\.survey-capture-layout[\s\S]*grid-template-columns:\s*minmax\(0,\s*1fr\)/)
  })

  it('extends the login traffic flow underneath the right-side card on wide screens', () => {
    const styles = readFileSync('src/styles.css', 'utf8')
    expect(styles).toMatch(/\.login-traffic-flow\s*\{[^}]*width:\s*78vw/)
    expect(styles).not.toMatch(/\.login-traffic-flow\s*\{[^}]*width:\s*min\([^}]*920px/)
    expect(styles).toMatch(/\.login-backdrop img\s*\{[^}]*z-index:\s*0/)
    expect(styles).toMatch(/\.login-traffic-flow\s*\{[^}]*z-index:\s*1/)
    expect(styles).toMatch(/\.login-backdrop::after\s*\{[^}]*z-index:\s*2/)
  })

  it('lets standard page workspaces fill the remaining viewport height', () => {
    const styles = readFileSync('src/styles.css', 'utf8')
    const full = readFileSync('src/full.css', 'utf8')
    expect(styles).toMatch(/\.shell-main\s*\{[^}]*display:\s*flex[^}]*flex-direction:\s*column/)
    expect(styles).toMatch(/\.shell-main\s*\{[^}]*padding:\s*18px 22px;/)
    expect(full).toMatch(/\.shell-main\s*>\s*:is\([^)]*\.dashboard-grid[^)]*\.video-layout[^)]*\.rules-layout[^)]*\)\s*\{[^}]*flex-grow:\s*1/)
    expect(full).toMatch(/\.shell-main\s*>\s*\.surface-panel:last-child\s*\{[^}]*flex-grow:\s*1/)
    expect(full).toMatch(/\.map-master-panel\s*>\s*\.city-map\s*\{[^}]*height:\s*100%/)
    expect(full).not.toMatch(/\.map-master-panel\s*>\s*\.city-map\s*\{[^}]*height:\s*calc\(100%\s*-\s*48px\)/)
  })

  it('keeps the monitoring source picker readable with long source names', () => {
    const styles = readFileSync('src/styles.css', 'utf8')
    expect(styles).toMatch(/\.monitoring-source-picker\s*\{[^}]*position:\s*relative[^}]*width:\s*100%/)
    expect(styles).toMatch(/\.monitoring-source-picker select\s*\{[^}]*text-overflow:\s*ellipsis[^}]*appearance:\s*none/)
    expect(styles).toMatch(/\.monitoring-source-caret\s*\{[^}]*pointer-events:\s*none/)
  })

  it('keeps direct panels scrollable instead of shrinking and clipping their content', () => {
    const full = readFileSync('src/full.css', 'utf8')
    expect(full).toMatch(/\.shell-main\s*>\s*\.surface-panel\s*\{[^}]*flex-shrink:\s*0/)
    expect(full).toMatch(/@media \(max-width:\s*1100px\)[^}]*\.replay-camera-grid\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/)
    expect(full).toMatch(/@media \(max-width:\s*760px\)[^}]*\.replay-camera-grid\s*\{[^}]*grid-template-columns:\s*1fr/)
  })

  it('keeps replay camera frames at 16:9 with controls floating inside the feed', () => {
    const full = readFileSync('src/full.css', 'utf8')
    expect(full).toMatch(/\.replay-camera-feed\s*\{[^}]*position:\s*relative[^}]*aspect-ratio:\s*16\s*\/\s*9/)
    expect(full).not.toMatch(/\.replay-camera-feed\s*\{[^}]*height:\s*158px/)
    expect(full).toMatch(/\.replay-camera-overlay\s*\{[^}]*position:\s*absolute[^}]*inset:/)
    expect(full).toMatch(/\.replay-camera-overlay\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/)
    expect(full).toMatch(/\.replay-camera-action\s*\{[^}]*position:\s*static[^}]*grid-column:\s*2/)
  })
})
