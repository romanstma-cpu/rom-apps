/* Detect e2e assertion drift: literal UI strings that no longer exist in src/.
 *
 * The paper-activity suite failed for four releases because it waited on text
 * the app stopped rendering. This extracts quoted strings from Playwright
 * locators in every spec and reports any that appear nowhere in the source,
 * so drift is caught by inspection rather than by a 30-second timeout.
 */
import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const specs = fs.readdirSync(path.join(root, 'e2e')).filter((f) => f.endsWith('.mjs'));

// Every string the renderer could produce.
const srcFiles = [];
const walk = (dir) => {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (/\.(tsx?|css|html)$/.test(entry.name)) srcFiles.push(full);
  }
};
for (const dir of ['src', 'shared', 'electron']) walk(path.join(root, dir));
const haystack = srcFiles.map((f) => fs.readFileSync(f, 'utf8')).join('\n');

// Playwright text locators that carry a literal expectation.
const PATTERNS = [
  /getByText\(\s*'([^']{4,})'/g,
  /getByText\(\s*"([^"]{4,})"/g,
  /getByRole\([^)]*?name:\s*'([^']{4,})'/g,
  /getByRole\([^)]*?name:\s*"([^"]{4,})"/g,
  /getByLabel\(\s*'([^']{4,})'/g,
  /getByPlaceholder\(\s*'([^']{4,})'/g,
];

let missing = 0;
let checked = 0;
let skipped = 0;
for (const spec of specs) {
  const text = fs.readFileSync(path.join(root, 'e2e', spec), 'utf8');
  const seen = new Set();
  for (const pattern of PATTERNS) {
    for (const match of text.matchAll(pattern)) {
      const literal = match[1];
      if (seen.has(literal)) continue;
      seen.add(literal);

      // A spec may inject its own fixture text through a stubbed IPC handler,
      // and may assert that a string is ABSENT. Neither is drift.
      const injected = text.includes(`'${literal}'`) &&
        new RegExp(`ipcMain\\.handle[\\s\\S]{0,2000}?${literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)
          .test(text);
      const line = text.slice(text.lastIndexOf('\n', match.index) + 1,
                             text.indexOf('\n', match.index));
      const negated = /count\(\)\s*,\s*0|toHaveCount\(0\)|\.count\(\)\s*===\s*0/.test(line);
      if (injected || negated) { skipped += 1; continue; }

      checked += 1;
      // JSX composes text from expressions, so a rendered line like
      // "Ready: Risk limits saved" exists in source only as its parts.
      // Compare on the longest static fragment rather than the whole string.
      const fragments = literal
        .split(/\s*[·—]\s*|^(?:Ready|Needed|Main strategy):\s*/)
        .filter(Boolean)
        .sort((a, b) => b.length - a.length);
      const probe = (fragments[0] || literal).trim();
      if (probe.length >= 4 && !haystack.includes(probe)) {
        console.log(`DRIFT  ${spec}: ${JSON.stringify(literal)}`);
        missing += 1;
      }
    }
  }
}

console.log(`\nChecked ${checked} literal locators across ${specs.length} specs ` +
            `(${skipped} skipped as fixtures or absence assertions).`);
if (missing) {
  console.log(`${missing} string(s) not found in src/ — verify before trusting the suite.`);
  process.exit(1);
}
console.log('No drift: every asserted string still exists in the source.');
