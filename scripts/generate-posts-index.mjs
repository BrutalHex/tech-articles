import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const postsDir = path.resolve(__dirname, '../docs/posts')
const outputPath = path.join(postsDir, 'index.md')

function parseFrontmatter(content) {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---/)
  if (!match) return {}

  const frontmatter = {}
  for (const line of match[1].split('\n')) {
    const separator = line.indexOf(':')
    if (separator === -1) continue
    const key = line.slice(0, separator).trim()
    const value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, '')
    frontmatter[key] = value
  }

  return frontmatter
}

function getPosts() {
  return fs
    .readdirSync(postsDir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => {
      const indexPath = path.join(postsDir, entry.name, 'index.md')
      if (!fs.existsSync(indexPath)) return null

      const content = fs.readFileSync(indexPath, 'utf-8')
      const frontmatter = parseFrontmatter(content)

      return {
        slug: entry.name,
        title: frontmatter.title ?? entry.name,
        category: frontmatter.category ?? 'Uncategorized',
        date: frontmatter.date ?? entry.name.slice(0, 10),
        description: frontmatter.description ?? ''
      }
    })
    .filter(Boolean)
    .sort((a, b) => b.date.localeCompare(a.date))
}

function groupByCategory(posts) {
  const categories = new Map()

  for (const post of posts) {
    const items = categories.get(post.category) ?? []
    items.push(post)
    categories.set(post.category, items)
  }

  return [...categories.entries()].sort(([a], [b]) => a.localeCompare(b))
}

const posts = getPosts()
const grouped = groupByCategory(posts)

const lines = [
  '# Articles',
  '',
  'Browse technical articles grouped by category.',
  ''
]

for (const [category, items] of grouped) {
  lines.push(`## ${category}`, '')

  for (const post of items) {
    lines.push(`- [${post.title}](/posts/${post.slug}/) — ${post.date}`)
    if (post.description) {
      lines.push(`  ${post.description}`)
    }
  }

  lines.push('')
}

fs.writeFileSync(outputPath, `${lines.join('\n').trimEnd()}\n`)
console.log(`Generated ${outputPath} with ${posts.length} article(s) in ${grouped.length} category(ies).`)