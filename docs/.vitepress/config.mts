import { defineConfig } from 'vitepress'
import { getSidebar } from './utils/posts.mts'

export default defineConfig({
  title: 'Tech Articles',
  description: 'Technical articles and engineering notes',

  base: '/',

  cleanUrls: true,

  head: [
    ['link', { rel: 'icon', href: '/favicon.ico', sizes: 'any' }],
    ['link', { rel: 'icon', type: 'image/png', href: '/favicon.png' }],
    ['link', { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' }]
  ],

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
      copyright: 'Copyright © 2026'
    }
  }
})