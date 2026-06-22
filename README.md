# Tech Articles

Technical articles, engineering notes, and high-quality code samples.

Published automatically to a custom subdomain using **Hugo** + **GitHub Actions** + **GitHub Pages**.

## 🚀 Features

- Clean Markdown source of truth
- Beautiful code highlighting
- Sample code lives right next to the articles that use it (using Hugo page bundles)
- Automatic deployment on every push
- Custom subdomain support (e.g. `articles.yourdomain.com`)
- Tags, categories, reading time, RSS feed
- Full version history and easy collaboration via Pull Requests

## 📁 Repository Structure

```
tech-articles/
├── .github/workflows/
│   └── deploy.yml          # GitHub Actions → Hugo build + deploy to Pages
├── content/
│   └── posts/
│       └── YYYY-MM-DD-article-slug/
│           ├── index.md           # The article (frontmatter + Markdown)
│           ├── code/              # Sample code files for this article
│           └── images/            # Diagrams & screenshots
├── hugo.toml                 # Hugo configuration
├── static/                     # Global assets (favicon, etc.)
└── README.md
```

## ✍️ How to Write a New Article

1. Create a new folder:
   ```bash
   hugo new posts/2026-06-25-my-new-article/index.md
   ```
2. Edit `index.md` with YAML/TOML frontmatter + Markdown.
3. Add sample code in the `code/` folder inside the article directory.
4. (Optional) Add images in `images/`.
5. Commit and push → site updates automatically.

### Example Frontmatter

```toml
+++
 title = "My Technical Article Title"
 date = 2026-06-25
 draft = false
 tags = ["github", "hugo", "devops"]
 categories = ["Engineering"]
 summary = "Short description for listings and SEO."
+++
```

## 🚀 Local Development

```bash
# 1. Install Hugo (extended version recommended)
# https://gohugo.io/installation/

# 2. Clone this repo
git clone https://github.com/BrutalHex/tech-articles.git
cd tech-articles

# 3. (Recommended) Add PaperMod theme
git submodule add https://github.com/adityatelange/hugo-PaperMod.git themes/PaperMod

# 4. Update hugo.toml: set theme = "PaperMod"

# 5. Run local server
hugo server -D
```

Open http://localhost:1313

## 🌐 Publishing to Your Subdomain

This repo is configured to deploy to **GitHub Pages**.

### Steps:
1. Push to `main` branch (workflow runs automatically).
2. Go to repo **Settings → Pages**
3. Set **Source** to "GitHub Actions"
4. Add your custom domain (e.g. `articles.yourdomain.com`)
5. In your DNS provider, create a CNAME record:
   - Name/Host: `articles`
   - Value: `BrutalHex.github.io`
6. Wait a few minutes → your site will be live at `https://articles.yourdomain.com`

GitHub automatically provides HTTPS.

## 📄 Sample Article

See the first article in:
`content/posts/2026-06-22-welcome-to-tech-articles/`

It demonstrates page bundles (article + code folder) and code samples.

## 🔄 GitHub Actions Workflow

The workflow (`.github/workflows/deploy.yml`) does the following on every push:
- Checks out the repo (with submodules)
- Installs latest Hugo extended
- Builds the site with `--minify`
- Deploys to GitHub Pages using official actions

You can also trigger it manually from the Actions tab.

## 👍 Contributing

Pull Requests are very welcome!
Feel free to improve articles, add new ones, or enhance the setup.

## 🔗 Links

- Live site: (will be your subdomain)
- Issues: https://github.com/BrutalHex/tech-articles/issues

---

Made with ❤️ using Markdown, Hugo, and GitHub Actions.