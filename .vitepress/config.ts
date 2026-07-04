import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'Tech Articles',
  description: 'Technical articles and engineering notes',

  // This is important for GitHub Pages deployment
  base: '/tech-articles/',

  cleanUrls: true,

  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Articles', link: '/posts/' }
    ],

    sidebar: [
      {
        text: 'Articles',
        items: [
          {
            text: 'The AI-powered Agentic Chain',
            link: '/posts/2026-06-22-agentic-chain/'
          }
        ]
      }
    ],

    socialLinks: [
      { icon: 'github', link: 'https://github.com/BrutalHex/tech-articles' }
    ],

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026'
    }
  }
})