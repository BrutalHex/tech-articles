import { defineConfig } from 'vitepress'
import { getSidebar } from './utils/posts.mts'

export default defineConfig({
  title: 'BrutalHex Tech Articles',
  description: 'Technical articles and engineering notes',

  base: '/',

  cleanUrls: true,

  themeConfig: {
    nav: [
      { text: 'Home', link: '/' },
      { text: 'Articles', link: '/posts/' }
    ],

    sidebar: {
      '/posts/': getSidebar()
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/BrutalHex/tech-articles' }
    ],

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2026 BrutalHex'
    }
  }
})