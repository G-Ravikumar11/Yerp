/*
 * Renames the words people read - "owner" to "Master", "gang" to "contractor" - in the app's screens, and only
 * there: string literals, template text and JSX text, never identifiers, object keys or values the code
 * compares against. Uses the TypeScript parser so code is never touched.
 *
 *   node scripts/rename-words.cjs [--check]
 */
const fs = require('fs')
const path = require('path')
const ts = require('typescript')

const ROOT = path.join(__dirname, '..', 'src')
const check = process.argv.includes('--check')

function replaceWords(text) {
  return text
    .replace(/\b([Aa])n (owner|Owner)\b/g, (_, a) => `${a} Master`)
    .replace(/\bOWNERS\b/g, 'MASTERS')
    .replace(/\bOWNER\b/g, 'MASTER')
    .replace(/\b[Oo]wner(s?)('s|s')?(?![A-Za-z])/g, (_, s, poss) => `Master${s}${poss ?? ''}`)
    .replace(/\bGANGS\b/g, 'CONTRACTORS')
    .replace(/\bGANG\b/g, 'CONTRACTOR')
    .replace(/\bGang(s?)('s|s')?(?![A-Za-z])/g, (_, s, poss) => `Contractor${s}${poss ?? ''}`)
    .replace(/\bgang(s?)('s|s')?(?![A-Za-z])/g, (_, s, poss) => `contractor${s}${poss ?? ''}`)
}

// A string with no space is a value the code uses ('owner', 'gang-orders') unless it is one of these labels.
const LABELS = new Set(['Owner', 'Owners', 'Gang', 'Gangs'])

function walk(dir, out) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name)
    if (fs.statSync(p).isDirectory()) walk(p, out)
    else if (/\.(tsx?|)$/.test(name) && /\.tsx?$/.test(name)) out.push(p)
  }
  return out
}

let changed = 0
for (const file of walk(ROOT, [])) {
  const src = fs.readFileSync(file, 'utf8')
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const edits = []
  const visit = (node) => {
    let start, end
    if (ts.isJsxText(node)) {
      start = node.getStart(sf, false)
      end = node.getEnd()
    } else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || node.kind === ts.SyntaxKind.TemplateHead || node.kind === ts.SyntaxKind.TemplateMiddle || node.kind === ts.SyntaxKind.TemplateTail) {
      start = node.getStart(sf, false)
      end = node.getEnd()
      const inner = src.slice(start + 1, end - 1)
      // Import paths, keys and compared values have no space; a lone label word does not either.
      if (ts.isImportDeclaration(node.parent) || ts.isExportDeclaration(node.parent)) return
      if (!/\s/.test(inner.trim()) && !LABELS.has(inner.trim())) return
    }
    if (start !== undefined) {
      const piece = src.slice(start, end)
      const next = replaceWords(piece)
      if (next !== piece) edits.push([start, end, next])
      return
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  if (!edits.length) continue
  let out = src
  for (const [s, e, t] of edits.sort((a, b) => b[0] - a[0])) out = out.slice(0, s) + t + out.slice(e)
  changed++
  console.log(`${check ? 'would change' : 'changed'} ${path.relative(ROOT, file)} (${edits.length})`)
  if (!check) fs.writeFileSync(file, out)
}
console.log(`${changed} files`)
