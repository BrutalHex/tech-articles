import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const errors = []

if (fs.existsSync(path.join(root, 'CNAME'))) {
  errors.push(
    'Root CNAME must not exist. GitHub uses it for branch-based Jekyll deploy, which serves README.md instead of the VitePress site. Keep the domain only in docs/public/CNAME.'
  )
}

if (!fs.existsSync(path.join(root, '.nojekyll'))) {
  errors.push(
    'Root .nojekyll is required to prevent GitHub from serving README.md via Jekyll when branch deploy is accidentally enabled.'
  )
}

if (fs.existsSync(path.join(root, '.vitepress'))) {
  errors.push(
    'Root .vitepress/ must not exist. VitePress config lives in docs/.vitepress/ only.'
  )
}

const publicCnamePath = path.join(root, 'docs/public/CNAME')
if (!fs.existsSync(publicCnamePath)) {
  errors.push(
    'docs/public/CNAME is required — do not delete it. It configures tech.mohammadabbasi.com for the VitePress deploy. Only a root /CNAME file (repo root) must be avoided.'
  )
} else {
  const cname = fs.readFileSync(publicCnamePath, 'utf-8').trim()
  if (!cname) {
    errors.push('docs/public/CNAME must contain the custom domain.')
  }
}

if (!fs.existsSync(path.join(root, 'docs/public/.nojekyll'))) {
  errors.push('docs/public/.nojekyll is required to disable Jekyll in the deployed artifact.')
}

const config = fs.readFileSync(path.join(root, 'docs/.vitepress/config.mts'), 'utf-8')
if (!config.includes("base: '/'") && !config.includes('base: "/"')) {
  errors.push("docs/.vitepress/config.mts must use base: '/' for the custom domain root.")
}

if (errors.length > 0) {
  for (const error of errors) {
    console.error(`ERROR: ${error}`)
  }
  process.exit(1)
}

console.log('Pages setup verification passed.')