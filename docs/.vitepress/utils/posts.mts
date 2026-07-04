import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const postsDir = path.resolve(__dirname, '../../posts')

export interface PostMeta {
  slug: string
  title: string
  category: string
  date: string
}

function parseFrontmatter(content: string): Record<string, string> {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---/)
  if (!match) return {}

  const frontmatter: Record<string, string> = {}
  for (const line of match[1].split('\n')) {
    const separator = line.indexOf(':')
    if (separator === -1) continue
    const key = line.slice(0, separator).trim()
    const value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, '')
    frontmatter[key] = value
  }

  return frontmatter
}

export function getPosts(): PostMeta[] {
  if (!fs.existsSync(postsDir)) return []

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
        date: frontmatter.date ?? entry.name.slice(0, 10)
      }
    })
    .filter((post): post is PostMeta => post !== null)
    .sort((a, b) => b.date.localeCompare(a.date))
}

export function getSidebar() {
  const categories = new Map<string, PostMeta[]>()

  for (const post of getPosts()) {
    const items = categories.get(post.category) ?? []
    items.push(post)
    categories.set(post.category, items)
  }

  return [...categories.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, items]) => ({
      text: category,
      collapsed: false,
      items: items.map((post) => ({
        text: post.title,
        link: `/posts/${post.slug}/`
      }))
    }))
}