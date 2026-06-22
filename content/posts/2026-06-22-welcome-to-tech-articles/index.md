+++
 title = "Welcome to Tech Articles"
 date = 2026-06-22
 draft = false
 tags = ["welcome", "hugo", "github-actions", "documentation"]
 categories = ["Meta"]
 summary = "This is the first article in the tech-articles repository. It demonstrates how articles and sample code are organized."
+++

# Welcome to Tech Articles

This repository is my personal collection of **technical articles**, engineering notes, and **real code samples**.

Everything is written in clean Markdown and automatically published as a beautiful website using **Hugo** + **GitHub Actions** + **GitHub Pages**.

## Why This Setup?

- Articles stay in version-controlled Markdown (easy to edit, search, and maintain)
- Sample code lives right next to the article that explains it
- The site looks professional with great code highlighting
- Full history and collaboration via GitHub
- Free hosting on your own subdomain

## How Articles + Code Work Together

This article uses a **Hugo page bundle**. That means the article folder contains:

- `index.md` (this file)
- `code/` folder with real runnable examples
- (optionally) `images/` for diagrams

### Example: Running the sample code

```bash
python code/hello.py
```

You should see:

```
Hello from the tech-articles repository!
```

## Next Steps

1. Read the [README.md](../..) for full setup instructions
2. Add your own articles in `content/posts/`
3. Push to `main` → site updates automatically

Thank you for visiting!

---

*This site is powered by GitHub Actions and deployed to GitHub Pages.*