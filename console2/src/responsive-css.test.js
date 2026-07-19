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
})
