// Generate src/types/artsoc.ts from the JSON Schema `make types` dumps out of pydantic.
//
// Types are GENERATED, never hand-written. A hand-maintained copy of RunRecord drifts from
// the schema the moment a field moves, and the drift shows up as a blank panel rather than
// as a compile error — the page still renders, so nobody notices.
//
// Run via `npm run gen:types`, which `make types` calls after dumping the schema.

import { readdir, readFile, writeFile, mkdir } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { compile } from 'json-schema-to-typescript'

const here = dirname(fileURLToPath(import.meta.url))
const schemaDir = join(here, '..', 'schema')
const outFile = join(here, '..', 'src', 'types', 'artsoc.ts')

const header = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Produced by \`make types\`, which dumps JSON Schema from the pydantic models in
 * src/artsoc/{schema,views,session,metrics}.py and compiles it here. Edit the Python
 * models and re-run \`make types\`; editing this file makes the two disagree silently.
 */

/* eslint-disable */
`

const files = (await readdir(schemaDir)).filter((f) => f.endsWith('.json')).sort()
if (files.length === 0) {
  console.error(`no schema files in ${schemaDir}; run \`make types\` from the repo root`)
  process.exit(1)
}

// Pydantic titles every property ("summary" becomes title "Summary"), and
// json-schema-to-typescript turns each title into a named exported type. That yields
// hundreds of aliases like `Text` and `N` whose names collide across models. Stripping
// property titles — but not the root's, which names the interface, nor a $defs entry's,
// which names a nested model — leaves the field types inline where they belong.
function stripPropertyTitles(node) {
  if (Array.isArray(node)) return node.forEach(stripPropertyTitles)
  if (!node || typeof node !== 'object') return
  for (const [key, value] of Object.entries(node)) {
    if (key === 'properties' && value && typeof value === 'object') {
      for (const property of Object.values(value)) {
        if (property && typeof property === 'object') delete property.title
        stripPropertyTitles(property)
      }
      continue
    }
    stripPropertyTitles(value)
  }
}

const parts = []
for (const file of files) {
  const schema = JSON.parse(await readFile(join(schemaDir, file), 'utf8'))
  stripPropertyTitles(schema)
  const ts = await compile(schema, schema.title ?? file.replace(/\.json$/, ''), {
    bannerComment: '',
    additionalProperties: false,
    unknownAny: false,
    style: { singleQuote: true, semi: false },
  })
  parts.push(ts.trim())
}

// Every schema carries its own copy of shared $defs, so identical interfaces are emitted
// more than once. Keep the first of each declaration and drop the repeats.
const seen = new Set()
const kept = []
for (const block of parts.join('\n\n').split(/\n(?=export (?:interface|type) )/)) {
  const name = block.match(/^export (?:interface|type) (\w+)/)?.[1]
  if (name && seen.has(name)) continue
  if (name) seen.add(name)
  kept.push(block.trim())
}

await mkdir(dirname(outFile), { recursive: true })
await writeFile(outFile, `${header}\n${kept.join('\n\n')}\n`, 'utf8')
console.log(`wrote ${seen.size} types to src/types/artsoc.ts`)
