import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const errors = []
const domain = 'tech.mohammadabbasi.com'

if (fs.existsSync(path.join(root, 'docs/public/CNAME'))) {
  errors.push(
    'docs/public/CNAME must not exist. It conflicts with the custom domain in GitHub Settings and causes a 404 loop. Use the root CNAME file and Settings → Pages → Custom domain instead.'
  )
}

if (!fs.existsSync(path.join(root, 'CNAME'))) {
  errors.push(
    `Root CNAME is required with "${domain}". Set the custom domain in GitHub Settings → Pages; GitHub uses the root CNAME file for domain routing.`
  )
} else {
  const cname = fs.readFileSync(path.join(root, 'CNAME'), 'utf-8').trim()
  if (cname !== domain) {
    errors.push(`Root CNAME must be "${domain}", found "${cname}".`)
  }
}

if (fs.existsSync(path.join(root, '.vitepress'))) {
  errors.push(
    'Root .vitepress/ must not exist. VitePress config lives in docs/.vitepress/ only.'
  )
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