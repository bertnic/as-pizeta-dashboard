import { copyFileSync, existsSync, mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

// app/frontend/scripts -> mono root
const monoRoot = resolve(__dirname, "../../../../..")
const source = resolve(monoRoot, "packages/ui/img/logo.svg")
const target = resolve(__dirname, "../src/assets/logo.svg")

mkdirSync(dirname(target), { recursive: true })

if (existsSync(source)) {
  copyFileSync(source, target)
  console.log(`[sync-logo] copied ${source} -> ${target}`)
} else if (existsSync(target)) {
  console.log(`[sync-logo] source missing (${source}); using local ${target}`)
} else {
  throw new Error(
    `[sync-logo] missing both source (${source}) and fallback (${target})`
  )
}
